import { MarketSummary, MarketWorkspaceData, AskResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export async function fetchMarkets(): Promise<MarketSummary[]> {
  const res = await fetch(`${API_BASE}/markets`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Failed to fetch markets: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchMarketWorkspace(marketId: string): Promise<MarketWorkspaceData> {
  const res = await fetch(`${API_BASE}/markets/${marketId}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Failed to fetch market workspace: ${res.statusText}`);
  }
  return res.json();
}

export async function askMarket(marketId: string, question: string): Promise<AskResponse> {
  const res = await fetch(`${API_BASE}/markets/${marketId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) {
    throw new Error(`Ask Memesis request failed: ${res.statusText}`);
  }
  return res.json();
}
