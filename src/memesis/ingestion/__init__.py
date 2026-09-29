"""Deterministic evidence collection; this layer never invokes an LLM."""

from memesis.ingestion.service import IngestionService

__all__ = ["IngestionService"]
