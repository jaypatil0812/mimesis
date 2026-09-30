export interface MarketSummary {
  id: string;
  name: string;
  node_count: number;
  evidence_count: number;
}

export interface PersonItem {
  id: string;
  name: string;
  lead_score: number;
  influence_score: number;
}

export interface BeliefItem {
  id: string;
  name: string;
  velocity: number;
  diversity: number;
}

export interface CompanyItem {
  id: string;
  name: string;
  relationships: string[];
}

export interface TimelineItem {
  id: string;
  published_at: string | null;
  source_type: string;
  source_url: string;
  text: string;
}

export interface GraphNode {
  id: string;
  name: string;
  type: string;
}

export interface GraphEdge {
  id: string;
  from: string;
  to: string;
  type: string;
}

export interface MarketWorkspaceData {
  market: {
    id: string;
    name: string;
    recorded_at: string | null;
  };
  overview: {
    node_count: number;
    edge_count: number;
    people_count: number;
    beliefs_count: number;
    companies_count: number;
    evidence_count: number;
    adjacent_markets: Array<{ id: string; name: string }>;
  };
  people: PersonItem[];
  beliefs: BeliefItem[];
  companies: CompanyItem[];
  timeline: TimelineItem[];
  graph: {
    nodes: GraphNode[];
    edges: GraphEdge[];
  };
}

export interface Claim {
  reasoning?: string | null;
  observation_ids?: string[];
  text: string;
  evidence_ids: string[];
  status: "OBSERVED" | "INFERRED" | "SPECULATIVE";
}

export interface CitedEvidence {
  id: string;
  text: string;
  source_url: string;
  published_at: string | null;
}

export interface HistoricalAnalogue {
  analogue: string;
  time_lag_observed: string;
  similarity_confidence: number;
  similarities: string[];
  differences: string[];
}

export interface AskResponse {
  fallback_status?: string | null;
  reasoning_execution?: { status: string; usage_source?: string };
  question: string;
  summary: string;
  confidence: number;
  observed_claims: Claim[];
  inferred_claims: Claim[];
  speculative_claims: Claim[];
  who_matters: string[];
  what_they_believe: string[];
  what_changed: string[];
  historical_analogues: HistoricalAnalogue[];
  possible_implications: string[];
  unknown_or_missing: string[];
  contradictory_evidence: string[];
  evidence: CitedEvidence[];
  metrics: {
    latency_ms: number;
    total_tokens: number;
    cheap_tokens: number;
    expensive_tokens: number;
    estimated_cost_usd: number;
    deep_reasoning_invoked: boolean;
    jev_decisions: number;
    nodes_considered: number;
    nodes_retained: number;
  };
}
