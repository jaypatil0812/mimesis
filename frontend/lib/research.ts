const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";
export type SourceWatch = { source: "hackernews" | "bluesky" | "openalex" | "github" | "rss" | "web"; query: string; feed_url?: string; page_url?: string };
export type WatchConfig = { name: string; question: string; scope: { market_id: string | null; start_at?: string | null; time_basis: string; graph_hops: number; include_adjacent_markets: boolean }; sources: SourceWatch[]; enabled: boolean; interval_seconds: number; processing_version?: string; [key: string]: unknown };
export type Observation = { id: string; statement: string; observation_type: string; review_state: string; published_at?: string; source_url?: string; attribution?: string; context?: Record<string, unknown>; source_family?: { id: string; basis: string }; evidence_ids: string[]; source_spans?: { id: string; start: number; end: number; text: string }[]; reviews?: { reviewer: string; state: string; note: string }[] };
export type Pattern = { id: string; category: string; explanation: string; alternative_explanations: string[]; missing_information: string[]; evidence_ids: string[]; contradictory_evidence_ids: string[]; related_opposing_evidence_ids?: string[]; connecting_paths: string[][]; supporting_observations: Observation[]; next_investigation?: { question: string; rationale: string }; review_state: string };
export type Snapshot = { id: string; created_at: string; patterns: Pattern[]; observations: Observation[]; connecting_relationships: { id: string; from: string; to: string; type: string; evidence_ids: string[] }[]; missing_information: string[]; reasoning_execution: { status: string }; coverage: Record<string, unknown>; change: { added_evidence_ids: string[]; removed_from_scope_ids: string[]; comparison_baseline_present: boolean } };
export type Watch = { id: string; config: WatchConfig; revision: number; next_due_at: string; state: Record<string, unknown>; collection_health?: { source?: string; status?: string; collection_lag_seconds: number | null; pagination_complete?: boolean }[] };
export type WorkerHealth = Record<string, unknown>;
export type WatchDetail = Watch & { snapshots: Snapshot[]; runs: { id: string; status: string; started_at: string; receipt: Record<string, unknown> }[]; pattern_reviews: { id: string; pattern_id: string; state: string; reviewer: string; note: string; created_at: string }[]; worker: WorkerHealth };

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(BASE + path, { method, cache: "no-store", headers: { "Content-Type": "application/json" }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : JSON.stringify(value.detail || value));
  return value;
}
export const listWatches = () => request<{ investigations: Watch[]; worker: WorkerHealth }>("/investigations");
export const watchDetail = (id: string) => request<WatchDetail>(`/investigations/${id}`);
export const createWatch = (config: WatchConfig) => request<Watch>("/investigations", "POST", config);
export const configureWatch = (watch: Watch, config: WatchConfig) => request<Watch>(`/investigations/${watch.id}`, "PUT", { config, expected_revision: watch.revision });
export const runWatch = (id: string) => request(`/investigations/${id}/run`, "POST");
export const reviewPattern = (id: string, pattern: string, state: string, reviewer: string, note: string) => request(`/investigations/${id}/patterns/${pattern}/review`, "POST", { state, reviewer, note });
export const observations = (market: string, state: string, offset: number) => request<{ total: number; observations: Observation[] }>("/memory/observations?" + new URLSearchParams({ ...(market ? { market_id: market } : {}), ...(state ? { review_state: state } : {}), offset: String(offset), limit: "20" }));
export const reviewObservation = (id: string, state: string, reviewer: string, note: string) => request<Observation>(`/memory/observations/${id}/review`, "POST", { state, reviewer, note });
export const reviewTemplates = () => request<{ templates: WatchConfig[]; human_review_status: string }>("/investigations/templates");
