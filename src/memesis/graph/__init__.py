"""Replaceable graph storage boundary."""

from memesis.graph.repository import GraphRepository
from memesis.graph.sql_repository import SqlGraphRepository

__all__ = ["GraphRepository", "SqlGraphRepository"]
