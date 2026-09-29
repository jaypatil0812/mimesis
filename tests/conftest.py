from collections.abc import Iterator

import pytest

from memesis.db.session import initialize_schema, make_engine, make_session_factory
from memesis.graph.sql_repository import SqlGraphRepository


@pytest.fixture
def repository() -> Iterator[SqlGraphRepository]:
    engine = make_engine("sqlite://")
    initialize_schema(engine)
    yield SqlGraphRepository(make_session_factory(engine))
    engine.dispose()
