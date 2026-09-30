"""Deterministic-first Evidence → Graph extraction boundary."""

def __getattr__(name):
    if name == "EvidenceGraphPipeline":
        from memesis.extraction.pipeline import EvidenceGraphPipeline
        return EvidenceGraphPipeline
    raise AttributeError(name)

__all__ = ["EvidenceGraphPipeline"]
