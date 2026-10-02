"""Research starting points, not validated customer conclusions."""
from memesis.investigations.contracts import InvestigationConfig

QUESTIONS = (
    ("Battery recycling economics", "Do reported recycling cost improvements apply across battery chemistries, or only particular pilots?", "battery recycling"),
    ("Agriculture and water", "When does precision irrigation reduce water use without lowering crop yield, and what contradicts that?", "irrigation"),
    ("Industrial heat", "What evidence supports heat-pump adoption for industrial process heat, and which temperature requirements remain unmet?", "heat pump"),
    ("Next opportunity: evidence gaps", "What's the next big thing? Which explanations are supported, which disagree, and what is still missing?", None),
)


def templates():
    return [InvestigationConfig(name=name, question=question,
        scope={"market_id": None, "graph_hops": 3, "include_adjacent_markets": True},
        sources=[{"source": "hackernews", "query": query}, {"source": "openalex", "query": query}] if query else [],
        enabled=False, initial_lookback_days=365, processing_version="memory-worker-v2").model_dump(mode="json")
        for name, question, query in QUESTIONS]
