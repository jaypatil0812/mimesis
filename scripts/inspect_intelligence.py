from memesis.config import settings
from memesis.db.session import make_engine, make_session_factory
from memesis.graph.sql_repository import SqlGraphRepository
from memesis.domain.schemas import NodeType, EdgeType

engine = make_engine(settings.database_url)
repo = SqlGraphRepository(make_session_factory(engine))

print("Total nodes:", len(repo.list_nodes()))
print("Total edges:", len(repo.list_edges()))
print("Total evidence:", len(repo.list_evidence()))

perceptions = repo.list_perceptions()
print("Total perceptions recorded:", len(perceptions))
for p in perceptions[:10]:
    print(f"  [{p.dimension.value}:{p.stance.value}] (target={p.target_entity_id}) snippet: {p.statement[:80]}")

print("\nSample beliefs:")
beliefs = [n for n in repo.list_nodes() if n.node_type == NodeType.BELIEF]
for b in beliefs[:10]:
    print(f"  - {b.name}")

print("\nSample persons:")
persons = [n for n in repo.list_nodes() if n.node_type == NodeType.PERSON]
for p in persons[:15]:
    print(f"  - {p.name}")

print("\nSample companies:")
companies = [n for n in repo.list_nodes() if n.node_type == NodeType.COMPANY]
for c in companies:
    print(f"  - {c.name}")
