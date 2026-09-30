"""Durable scheduling with a single fenced worker and append-only snapshots/reviews."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from memesis.db.models import InvestigationRow, InvestigationRunRow, InvestigationSnapshotRow, PatternReviewRow, WorkerLeaseRow
from memesis.investigations.contracts import InvestigationConfig
from memesis.retrieval.scope import utc

LEASE = "market-memory-worker"

class InvestigationStore:
    def __init__(self, sessions):
        self.sessions = sessions

    @staticmethod
    def record(row):
        return {"id": row.id, "config": row.config_json, "revision": row.revision, "state": row.state_json,
                "next_due_at": utc(row.next_due_at).isoformat(), "running_run_id": row.running_run_id,
                "created_at": utc(row.created_at).isoformat(), "updated_at": utc(row.updated_at).isoformat()}

    def get(self, investigation_id):
        with self.sessions() as session:
            row = session.get(InvestigationRow, str(investigation_id))
            return self.record(row) if row else None

    def invalidate_evidence(self, evidence_ids, rebuild_id):
        """Queue analysis where tracked evidence or retained snapshots changed."""
        changed = set(map(str, evidence_ids))
        affected = []
        with self.sessions.begin() as session:
            for row in session.scalars(select(InvestigationRow)):
                state = dict(row.state_json)
                tracked = set(state.get("tracked_evidence_ids", []))
                snapshots = session.scalars(select(InvestigationSnapshotRow).where(
                    InvestigationSnapshotRow.investigation_id == row.id)).all()
                # Snapshot JSON layouts are versioned; UUID membership in the
                # serialized immutable snapshot conservatively includes paths.
                import json
                snapshot_text = json.dumps([s.payload_json for s in snapshots], default=str)
                if not (tracked & changed or any(eid in snapshot_text for eid in changed)):
                    continue
                state.pop("last_fingerprint", None)
                state["memory_rebuild_pending"] = {"rebuild_id": str(rebuild_id),
                                                 "evidence_ids": sorted(tracked & changed)}
                row.state_json = state
                row.next_due_at = datetime.now(UTC)
                row.updated_at = datetime.now(UTC)
                affected.append(row.id)
        return affected

    def list(self):
        with self.sessions() as session:
            return [self.record(row) for row in session.scalars(select(InvestigationRow).order_by(InvestigationRow.created_at))]

    def create(self, config: InvestigationConfig):
        now, key = datetime.now(UTC), str(uuid4())
        with self.sessions.begin() as session:
            row = InvestigationRow(id=key, config_json=config.model_dump(mode="json"), state_json={}, revision=1,
                enabled=config.enabled, next_due_at=now, created_at=now, updated_at=now)
            session.add(row)
            session.flush()
            return self.record(row)

    def configure(self, key, config, revision):
        with self.sessions.begin() as session:
            row = session.get(InvestigationRow, str(key))
            if row is None:
                raise KeyError(key)
            lease = session.get(WorkerLeaseRow, LEASE)
            if row.running_run_id and lease and utc(lease.expires_at) > datetime.now(UTC):
                raise ValueError("Investigation is running; retry configuration after this bounded job finishes")
            if row.revision != revision:
                raise ValueError("Configuration revision conflict")
            state = dict(row.state_json)
            if row.config_json.get("processing_version") != config.processing_version:
                state["pending_evidence_ids"] = state.get("tracked_evidence_ids", [])
                state["projection_review_required"] = True
                state["dead_letters"] = {}
                state["extraction_attempts"] = {}
            state.pop("last_fingerprint", None)
            changed = session.execute(update(InvestigationRow).where(InvestigationRow.id == str(key), InvestigationRow.revision == revision)
                .values(config_json=config.model_dump(mode="json"), state_json=state, revision=revision + 1,
                        enabled=config.enabled, next_due_at=datetime.now(UTC), updated_at=datetime.now(UTC)))
            if changed.rowcount != 1:
                raise ValueError("Configuration revision conflict")
        return self.get(key)

    def request_run(self, key):
        with self.sessions.begin() as session:
            row = session.get(InvestigationRow, str(key))
            if row is None:
                raise KeyError(key)
            lease = session.get(WorkerLeaseRow, LEASE)
            if row.running_run_id and lease and utc(lease.expires_at) > datetime.now(UTC):
                raise ValueError("Investigation is running; retry after its bounded job finishes")
            state = dict(row.state_json)
            state["manual_requested"] = True
            row.state_json, row.next_due_at = state, datetime.now(UTC)

    def acquire(self, owner, now=None, seconds=300):
        now = now or datetime.now(UTC)
        try:
            with self.sessions.begin() as session:
                row = session.get(WorkerLeaseRow, LEASE)
                if row is None:
                    session.add(WorkerLeaseRow(name=LEASE, owner=owner, expires_at=now + timedelta(seconds=seconds), heartbeat_at=now))
                    return True
                result = session.execute(update(WorkerLeaseRow).where(WorkerLeaseRow.name == LEASE,
                    WorkerLeaseRow.expires_at <= now).values(owner=owner, expires_at=now + timedelta(seconds=seconds), heartbeat_at=now).execution_options(synchronize_session=False))
                return result.rowcount == 1
        except IntegrityError:
            return False

    def renew(self, owner, now=None, seconds=300):
        now = now or datetime.now(UTC)
        with self.sessions.begin() as session:
            changed = session.execute(update(WorkerLeaseRow).where(WorkerLeaseRow.name == LEASE,
                WorkerLeaseRow.owner == owner, WorkerLeaseRow.expires_at > now)
                .values(expires_at=now + timedelta(seconds=seconds), heartbeat_at=now).execution_options(synchronize_session=False))
            return changed.rowcount == 1

    def release(self, owner):
        with self.sessions.begin() as session:
            session.execute(update(WorkerLeaseRow).where(WorkerLeaseRow.name == LEASE, WorkerLeaseRow.owner == owner)
                .values(expires_at=datetime.now(UTC)).execution_options(synchronize_session=False))

    def health(self):
        with self.sessions() as session:
            row = session.get(WorkerLeaseRow, LEASE)
            heartbeat_age = (datetime.now(UTC) - utc(row.heartbeat_at)).total_seconds() if row else None
            return {"running": bool(row and utc(row.expires_at) > datetime.now(UTC)),
                    "heartbeat_age_seconds": heartbeat_age,
                    "last_seen_recently": heartbeat_age is not None and heartbeat_age < 90,
                    "heartbeat_at": utc(row.heartbeat_at).isoformat() if row else None,
                    "lease_expires_at": utc(row.expires_at).isoformat() if row else None,
                    "serving_api_starts_collection": False}

    @staticmethod
    def fenced(session, owner):
        # Conditional write takes a row lock on PostgreSQL and a writer lock on SQLite.
        now = datetime.now(UTC)
        changed = session.execute(update(WorkerLeaseRow).where(WorkerLeaseRow.name == LEASE,
            WorkerLeaseRow.owner == owner, WorkerLeaseRow.expires_at > now).values(heartbeat_at=now).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise RuntimeError("Worker lease lost; stale worker cannot publish")

    def claim(self, owner, key):
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            self.fenced(session, owner)
            row = session.get(InvestigationRow, key)
            if row is None or (not row.enabled and not row.state_json.get("manual_requested")) or utc(row.next_due_at) > now:
                return None
            if row.running_run_id:
                old = session.get(InvestigationRunRow, row.running_run_id)
                if old and old.status == "running":
                    old.status, old.completed_at = "abandoned", now
                    old.receipt_json = {"error": "Previous worker interrupted; durable pages and versioned extraction will resume"}
            run_id = str(uuid4())
            row.running_run_id = run_id
            session.add(InvestigationRunRow(id=run_id, investigation_id=key, revision=row.revision,
                status="running", started_at=now, receipt_json={}))
            session.flush()
            return self.record(row)

    def complete(self, owner, watch, state, receipt, snapshot, delay):
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            self.fenced(session, owner)
            row = session.get(InvestigationRow, watch["id"])
            if row.running_run_id != watch["running_run_id"] or row.revision != watch["revision"]:
                raise RuntimeError("Investigation changed; stale run cannot publish")
            run = session.get(InvestigationRunRow, watch["running_run_id"])
            run.status, run.completed_at, run.receipt_json = receipt["status"], now, receipt
            if snapshot is not None:
                session.add(InvestigationSnapshotRow(id=str(uuid4()), investigation_id=row.id, run_id=run.id,
                    fingerprint=snapshot["fingerprint"], payload_json=snapshot, created_at=now))
            row.state_json, row.running_run_id = state, None
            row.next_due_at, row.updated_at = now + timedelta(seconds=delay), now

    def history(self, key, limit=20):
        with self.sessions() as session:
            rows = session.scalars(select(InvestigationSnapshotRow).where(InvestigationSnapshotRow.investigation_id == str(key))
                .order_by(InvestigationSnapshotRow.created_at.desc()).limit(limit))
            return [{"id": r.id, "run_id": r.run_id, "created_at": utc(r.created_at).isoformat(), **r.payload_json} for r in rows]

    def runs(self, key, limit=20):
        with self.sessions() as session:
            return [{"id": r.id, "status": r.status, "revision": r.revision,
                     "started_at": utc(r.started_at).isoformat(), "completed_at": utc(r.completed_at).isoformat() if r.completed_at else None,
                     "receipt": r.receipt_json} for r in session.scalars(select(InvestigationRunRow)
                    .where(InvestigationRunRow.investigation_id == str(key)).order_by(InvestigationRunRow.started_at.desc()).limit(limit))]

    def review(self, key, pattern_id, state, reviewer, note):
        with self.sessions.begin() as session:
            snapshots = session.scalars(select(InvestigationSnapshotRow).where(InvestigationSnapshotRow.investigation_id == str(key)))
            if not any(any(p["id"] == pattern_id for p in row.payload_json.get("patterns", [])) for row in snapshots):
                raise KeyError("Unknown pattern")
            session.add(PatternReviewRow(id=str(uuid4()), investigation_id=str(key), pattern_id=pattern_id,
                state=state, reviewer=reviewer, note=note, created_at=datetime.now(UTC)))

    def reviews(self, key):
        with self.sessions() as session:
            return [{"id": r.id, "pattern_id": r.pattern_id, "state": r.state, "reviewer": r.reviewer,
                     "note": r.note, "created_at": utc(r.created_at).isoformat()}
                    for r in session.scalars(select(PatternReviewRow).where(PatternReviewRow.investigation_id == str(key))
                        .order_by(PatternReviewRow.created_at))]
