# Schema migrations

Run `memesis db upgrade` (or `alembic upgrade head`) against the configured database. Migration `0001_foundation` creates the Phase 1 ledger, provenance, and graph tables. SQLite is supported only as an explicit local/demo/test backend; configured deployments should use PostgreSQL.
