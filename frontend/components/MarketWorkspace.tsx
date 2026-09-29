"use client";

import React, { useState, useEffect } from "react";
import {
  Activity,
  Users,
  Lightbulb,
  Building2,
  Clock,
  Share2,
  HelpCircle,
  Search,
  ExternalLink,
  ShieldCheck,
  AlertTriangle,
  Zap,
  TrendingUp,
  ChevronRight,
  Database,
  ArrowRight,
  CheckCircle2,
  Layers,
} from "lucide-react";
import { MarketSummary, MarketWorkspaceData, AskResponse } from "../lib/types";
import { fetchMarkets, fetchMarketWorkspace, askMarket } from "../lib/api";

type TabKey = "overview" | "people" | "beliefs" | "companies" | "timeline" | "graph" | "ask";

export default function MarketWorkspace() {
  const [markets, setMarkets] = useState<MarketSummary[]>([]);
  const [selectedMarketId, setSelectedMarketId] = useState<string>("");
  const [data, setData] = useState<MarketWorkspaceData | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("overview");
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Ask Memesis state
  const [question, setQuestion] = useState<string>("Is model routing replacing single frontier models in production?");
  const [askLoading, setAskLoading] = useState<boolean>(false);
  const [askResult, setAskResult] = useState<AskResponse | null>(null);
  const [askError, setAskError] = useState<string | null>(null);

  // Load markets on initial mount
  useEffect(() => {
    fetchMarkets()
      .then((m) => {
        setMarkets(m);
        if (m.length > 0) {
          setSelectedMarketId(m[0].id);
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  // Load market workspace when selected market changes
  useEffect(() => {
    if (!selectedMarketId) return;
    setLoading(true);
    fetchMarketWorkspace(selectedMarketId)
      .then((res) => {
        setData(res);
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [selectedMarketId]);

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedMarketId || !question.trim()) return;
    setAskLoading(true);
    setAskError(null);
    try {
      const res = await askMarket(selectedMarketId, question);
      setAskResult(res);
    } catch (err: any) {
      setAskError(err.message || "Failed to execute query");
    } finally {
      setAskLoading(false);
    }
  };

  const tabs: Array<{ key: TabKey; label: string; icon: React.ReactNode }> = [
    { key: "overview", label: "Overview", icon: <Activity className="w-4 h-4 mr-2" /> },
    { key: "people", label: "People", icon: <Users className="w-4 h-4 mr-2" /> },
    { key: "beliefs", label: "Beliefs", icon: <Lightbulb className="w-4 h-4 mr-2" /> },
    { key: "companies", label: "Companies", icon: <Building2 className="w-4 h-4 mr-2" /> },
    { key: "timeline", label: "Timeline", icon: <Clock className="w-4 h-4 mr-2" /> },
    { key: "graph", label: "Graph", icon: <Share2 className="w-4 h-4 mr-2" /> },
    { key: "ask", label: "Ask Memesis", icon: <HelpCircle className="w-4 h-4 mr-2" /> },
  ];

  return (
    <div className="flex flex-col min-h-screen">
      {/* Top Navbar */}
      <header className="border-b border-zinc-800 bg-zinc-900/60 backdrop-blur sticky top-0 z-20 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="bg-blue-600/20 text-blue-400 p-1.5 rounded-lg border border-blue-500/30">
            <Layers className="w-5 h-5" />
          </div>
          <div>
            <h1 className="font-semibold text-zinc-100 tracking-tight flex items-center gap-2">
              MEMESIS
              <span className="text-xs px-2 py-0.5 rounded-full bg-blue-900/50 text-blue-300 border border-blue-700/50 font-mono">
                v0.1 Provenance Graph
              </span>
            </h1>
          </div>
        </div>

        {/* Market Selector */}
        <div className="flex items-center space-x-3">
          <label className="text-xs text-zinc-400 font-medium">Workspace Market:</label>
          <select
            value={selectedMarketId}
            onChange={(e) => setSelectedMarketId(e.target.value)}
            className="bg-zinc-800 text-zinc-200 border border-zinc-700 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent font-medium"
          >
            {markets.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} ({m.evidence_count} evidence, {m.node_count} nodes)
              </option>
            ))}
          </select>
        </div>
      </header>

      {/* Main Workspace */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6">
        {error && (
          <div className="mb-6 p-4 rounded-lg bg-red-950/50 border border-red-800 text-red-300 flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 flex-shrink-0" />
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Market Header Banner */}
        {data && (
          <div className="mb-6 bg-gradient-to-r from-zinc-900 via-zinc-900/90 to-zinc-900/40 p-6 rounded-xl border border-zinc-800 flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <div className="text-xs font-mono text-zinc-400 uppercase tracking-wider mb-1">
                Market Workspace
              </div>
              <h2 className="text-2xl font-bold text-white tracking-tight">{data.market.name}</h2>
              <div className="flex items-center gap-4 text-xs text-zinc-400 mt-2 font-mono">
                <span>ID: {data.market.id.slice(0, 8)}...</span>
                <span>•</span>
                <span>Provenance: {data.overview.evidence_count} immutable citations</span>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={() => setActiveTab("ask")}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium flex items-center gap-2 transition shadow-sm"
              >
                <HelpCircle className="w-4 h-4" />
                Ask Strategic Question
              </button>
            </div>
          </div>
        )}

        {/* Tab Navigation */}
        <div className="border-b border-zinc-800 flex space-x-1 mb-6 overflow-x-auto">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className={`flex items-center px-4 py-2.5 text-sm font-medium border-b-2 transition whitespace-nowrap ${
                activeTab === t.key
                  ? "border-blue-500 text-blue-400 bg-blue-500/10 rounded-t-lg"
                  : "border-transparent text-zinc-400 hover:text-zinc-200 hover:border-zinc-700"
              }`}
            >
              {t.icon}
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab Views */}
        {loading && !data ? (
          <div className="py-20 text-center text-zinc-500">
            <div className="inline-block animate-spin rounded-full h-8 w-8 border-t-2 border-b-2 border-blue-500 mb-4"></div>
            <p>Loading market subgraph from deterministic ledger...</p>
          </div>
        ) : data ? (
          <div>
            {/* 1. OVERVIEW TAB */}
            {activeTab === "overview" && (
              <div className="space-y-6">
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
                  <StatCard label="Subgraph Nodes" value={data.overview.node_count} icon={<Share2 className="w-4 h-4 text-zinc-400" />} />
                  <StatCard label="Graph Edges" value={data.overview.edge_count} icon={<TrendingUp className="w-4 h-4 text-zinc-400" />} />
                  <StatCard label="Tracked People" value={data.overview.people_count} icon={<Users className="w-4 h-4 text-blue-400" />} />
                  <StatCard label="Active Beliefs" value={data.overview.beliefs_count} icon={<Lightbulb className="w-4 h-4 text-purple-400" />} />
                  <StatCard label="Companies" value={data.overview.companies_count} icon={<Building2 className="w-4 h-4 text-green-400" />} />
                  <StatCard label="Evidence Items" value={data.overview.evidence_count} icon={<Database className="w-4 h-4 text-amber-400" />} />
                </div>

                {/* Adjacent Markets */}
                <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
                  <h3 className="text-sm font-medium text-zinc-200 uppercase tracking-wider mb-4 flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-blue-400" />
                    Adjacent Markets
                  </h3>
                  {data.overview.adjacent_markets.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {data.overview.adjacent_markets.map((adj) => (
                        <div
                          key={adj.id}
                          className="px-3 py-1.5 rounded-lg bg-zinc-800/80 border border-zinc-700/80 text-sm text-zinc-300 font-medium flex items-center gap-2"
                        >
                          <ChevronRight className="w-3.5 h-3.5 text-zinc-500" />
                          {adj.name}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-zinc-500 italic">No adjacent market boundaries detected.</p>
                  )}
                </div>
              </div>
            )}

            {/* 2. PEOPLE TAB */}
            {activeTab === "people" && (
              <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
                <div className="p-4 border-b border-zinc-800 flex justify-between items-center">
                  <h3 className="font-semibold text-zinc-100">Key Actors & Measured Influence</h3>
                  <span className="text-xs text-zinc-500 font-mono">
                    Gated: Influence requires explicit downstream propagation
                  </span>
                </div>
                {data.people.length > 0 ? (
                  <table className="w-full text-left text-sm">
                    <thead className="bg-zinc-950 text-zinc-400 text-xs font-mono uppercase border-b border-zinc-800">
                      <tr>
                        <th className="px-6 py-3">Actor</th>
                        <th className="px-6 py-3">Lead Score (Early Observation)</th>
                        <th className="px-6 py-3">Influence Score (Propagation Verified)</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800/60">
                      {data.people.map((p) => (
                        <tr key={p.id} className="hover:bg-zinc-800/40">
                          <td className="px-6 py-4 font-medium text-zinc-200">{p.name}</td>
                          <td className="px-6 py-4">
                            <span className="px-2.5 py-1 rounded bg-blue-950/60 border border-blue-800/60 text-blue-300 font-mono text-xs">
                              {p.lead_score.toFixed(1)}
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            <span className="px-2.5 py-1 rounded bg-purple-950/60 border border-purple-800/60 text-purple-300 font-mono text-xs">
                              {p.influence_score.toFixed(1)}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="p-8 text-center text-zinc-500 italic">No person entities connected to this market view.</div>
                )}
              </div>
            )}

            {/* 3. BELIEFS TAB */}
            {activeTab === "beliefs" && (
              <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
                <div className="p-4 border-b border-zinc-800 flex justify-between items-center">
                  <h3 className="font-semibold text-zinc-100">Market Beliefs & Dynamics</h3>
                  <span className="text-xs text-zinc-500 font-mono">
                    Bot-Resistant: Diversity gated by multi-source corroboration
                  </span>
                </div>
                {data.beliefs.length > 0 ? (
                  <table className="w-full text-left text-sm">
                    <thead className="bg-zinc-950 text-zinc-400 text-xs font-mono uppercase border-b border-zinc-800">
                      <tr>
                        <th className="px-6 py-3">Belief Proposition</th>
                        <th className="px-6 py-3">Velocity Score</th>
                        <th className="px-6 py-3">Diversity Score</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800/60">
                      {data.beliefs.map((b) => (
                        <tr key={b.id} className="hover:bg-zinc-800/40">
                          <td className="px-6 py-4 text-zinc-200 font-medium">{b.name}</td>
                          <td className="px-6 py-4">
                            <span className="px-2.5 py-1 rounded bg-green-950/60 border border-green-800/60 text-green-300 font-mono text-xs">
                              {b.velocity.toFixed(1)}
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            <span className="px-2.5 py-1 rounded bg-blue-950/60 border border-blue-800/60 text-blue-300 font-mono text-xs">
                              {b.diversity.toFixed(1)}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="p-8 text-center text-zinc-500 italic">No belief nodes recorded for this market.</div>
                )}
              </div>
            )}

            {/* 4. COMPANIES TAB */}
            {activeTab === "companies" && (
              <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
                <div className="p-4 border-b border-zinc-800">
                  <h3 className="font-semibold text-zinc-100">Participating Companies</h3>
                </div>
                {data.companies.length > 0 ? (
                  <table className="w-full text-left text-sm">
                    <thead className="bg-zinc-950 text-zinc-400 text-xs font-mono uppercase border-b border-zinc-800">
                      <tr>
                        <th className="px-6 py-3">Company</th>
                        <th className="px-6 py-3">Observed Graph Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800/60">
                      {data.companies.map((c) => (
                        <tr key={c.id} className="hover:bg-zinc-800/40">
                          <td className="px-6 py-4 text-zinc-200 font-medium">{c.name}</td>
                          <td className="px-6 py-4">
                            <div className="flex flex-wrap gap-1.5">
                              {c.relationships.map((r, i) => (
                                <span key={i} className="px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-300 text-xs font-mono">
                                  {r}
                                </span>
                              ))}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <div className="p-8 text-center text-zinc-500 italic">No companies directly linked in this subgraph.</div>
                )}
              </div>
            )}

            {/* 5. TIMELINE TAB */}
            {activeTab === "timeline" && (
              <div className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden p-6">
                <h3 className="font-semibold text-zinc-100 mb-6 flex items-center gap-2">
                  <Clock className="w-4 h-4 text-blue-400" />
                  Chronological Evidence Ledger
                </h3>
                {data.timeline.length > 0 ? (
                  <div className="space-y-4">
                    {data.timeline.map((item) => (
                      <div key={item.id} className="p-4 rounded-lg bg-zinc-950/60 border border-zinc-800/80 hover:border-zinc-700 transition">
                        <div className="flex items-center justify-between gap-4 mb-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs px-2 py-0.5 rounded bg-zinc-800 font-mono text-zinc-400 uppercase">
                              {item.source_type}
                            </span>
                            <span className="text-xs text-zinc-500 font-mono">
                              {item.published_at ? new Date(item.published_at).toLocaleDateString() : "Historical"}
                            </span>
                          </div>
                          {item.source_url && (
                            <a
                              href={item.source_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 font-mono"
                            >
                              Source <ExternalLink className="w-3 h-3" />
                            </a>
                          )}
                        </div>
                        <p className="text-sm text-zinc-300">{item.text}</p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-zinc-500 italic">No evidence items in this timeline.</p>
                )}
              </div>
            )}

            {/* 6. GRAPH TAB */}
            {activeTab === "graph" && (
              <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="font-semibold text-zinc-100 flex items-center gap-2">
                    <Share2 className="w-4 h-4 text-purple-400" />
                    Market Subgraph Topology
                  </h3>
                  <div className="text-xs font-mono text-zinc-400">
                    {data.graph.nodes.length} nodes • {data.graph.edges.length} edges
                  </div>
                </div>

                <div className="bg-zinc-950 p-4 rounded-lg border border-zinc-800 font-mono text-xs space-y-2 max-h-[500px] overflow-y-auto">
                  <div className="text-zinc-500 uppercase tracking-wider mb-2">Adjacency Relationships:</div>
                  {data.graph.edges.map((e) => {
                    const fromNode = data.graph.nodes.find((n) => n.id === e.from);
                    const toNode = data.graph.nodes.find((n) => n.id === e.to);
                    return (
                      <div key={e.id} className="flex items-center gap-2 py-1 border-b border-zinc-900">
                        <span className="text-blue-400 font-medium">{fromNode?.name || e.from.slice(0, 8)}</span>
                        <span className="text-zinc-600">--[{e.type}]--&gt;</span>
                        <span className="text-purple-400 font-medium">{toNode?.name || e.to.slice(0, 8)}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* 7. ASK MEMESIS TAB */}
            {activeTab === "ask" && (
              <div className="space-y-6">
                {/* Query Input Card */}
                <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 shadow-sm">
                  <h3 className="text-lg font-semibold text-white mb-2 flex items-center gap-2">
                    <HelpCircle className="w-5 h-5 text-blue-400" />
                    Ask Memesis Strategic Engine
                  </h3>
                  <p className="text-sm text-zinc-400 mb-4">
                    Executes deterministic graph retrieval, Jev-style cheap filtering, historical analogue matching, and strict epistemic verification.
                  </p>

                  <form onSubmit={handleAsk} className="flex gap-3">
                    <input
                      type="text"
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      placeholder="e.g. Is model routing replacing single frontier models in production?"
                      className="flex-1 bg-zinc-950 border border-zinc-700 text-zinc-100 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent font-medium"
                    />
                    <button
                      type="submit"
                      disabled={askLoading}
                      className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium flex items-center gap-2 transition shadow-sm"
                    >
                      {askLoading ? (
                        <>
                          <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent"></div>
                          Reasoning...
                        </>
                      ) : (
                        <>
                          <Zap className="w-4 h-4" />
                          Execute Query
                        </>
                      )}
                    </button>
                  </form>

                  {askError && (
                    <div className="mt-4 p-3 rounded-lg bg-red-950/40 border border-red-800 text-red-300 text-sm">
                      {askError}
                    </div>
                  )}
                </div>

                {/* Structured Answer Results */}
                {askResult && (
                  <div className="space-y-6 animate-in fade-in duration-300">
                    {/* Synthesis Summary Banner */}
                    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
                      <div className="flex items-center justify-between mb-3">
                        <span className="text-xs font-mono uppercase tracking-wider text-blue-400 flex items-center gap-1.5 font-semibold">
                          <ShieldCheck className="w-4 h-4" />
                          Deterministic Synthesis
                        </span>
                        <div className="flex items-center gap-2 text-xs font-mono text-zinc-400">
                          <span>Confidence: {(askResult.confidence * 100).toFixed(0)}%</span>
                          <span>•</span>
                          <span>Latency: {askResult.metrics.latency_ms}ms</span>
                          <span>•</span>
                          <span>Tokens: {askResult.metrics.total_tokens}</span>
                        </div>
                      </div>
                      <p className="text-zinc-100 font-medium leading-relaxed">{askResult.summary}</p>
                    </div>

                    {/* Claims Categorization (Observed, Inferred, Speculative) */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                      {/* Observed Claims */}
                      <div className="bg-zinc-900/80 border border-emerald-900/50 rounded-xl p-5">
                        <div className="flex items-center gap-2 text-emerald-400 font-semibold text-xs font-mono uppercase tracking-wider mb-3">
                          <CheckCircle2 className="w-4 h-4" />
                          Observed Claims ({askResult.observed_claims.length})
                        </div>
                        <ul className="space-y-3">
                          {askResult.observed_claims.map((c, i) => (
                            <li key={i} className="text-sm text-zinc-300 border-l-2 border-emerald-500 pl-3 leading-snug">
                              {c.text}
                            </li>
                          ))}
                        </ul>
                      </div>

                      {/* Inferred Claims */}
                      <div className="bg-zinc-900/80 border border-amber-900/50 rounded-xl p-5">
                        <div className="flex items-center gap-2 text-amber-400 font-semibold text-xs font-mono uppercase tracking-wider mb-3">
                          <Zap className="w-4 h-4" />
                          Inferred Claims ({askResult.inferred_claims.length})
                        </div>
                        <ul className="space-y-3">
                          {askResult.inferred_claims.map((c, i) => (
                            <li key={i} className="text-sm text-zinc-300 border-l-2 border-amber-500 pl-3 leading-snug">
                              {c.text}
                            </li>
                          ))}
                        </ul>
                      </div>

                      {/* Speculative Claims */}
                      <div className="bg-zinc-900/80 border border-purple-900/50 rounded-xl p-5">
                        <div className="flex items-center gap-2 text-purple-400 font-semibold text-xs font-mono uppercase tracking-wider mb-3">
                          <HelpCircle className="w-4 h-4" />
                          Speculative ({askResult.speculative_claims.length})
                        </div>
                        {askResult.speculative_claims.length > 0 ? (
                          <ul className="space-y-3">
                            {askResult.speculative_claims.map((c, i) => (
                              <li key={i} className="text-sm text-zinc-300 border-l-2 border-purple-500 pl-3 leading-snug">
                                {c.text}
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="text-xs text-zinc-500 italic">No speculative claims retained.</p>
                        )}
                      </div>
                    </div>

                    {/* Historical Analogues */}
                    {askResult.historical_analogues.length > 0 && (
                      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
                        <h4 className="text-sm font-semibold text-zinc-200 uppercase tracking-wider mb-4 flex items-center gap-2">
                          <TrendingUp className="w-4 h-4 text-blue-400" />
                          Historical Analogues & Patterns
                        </h4>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {askResult.historical_analogues.map((h, i) => (
                            <div key={i} className="p-4 rounded-lg bg-zinc-950 border border-zinc-800">
                              <div className="flex justify-between items-start mb-2">
                                <span className="font-semibold text-blue-300 text-sm">{h.analogue}</span>
                                <span className="text-xs font-mono text-zinc-400 px-2 py-0.5 rounded bg-zinc-900 border border-zinc-700">
                                  Match: {(h.similarity_confidence * 100).toFixed(0)}%
                                </span>
                              </div>
                              <p className="text-xs text-zinc-400 mb-2 font-mono">{h.time_lag_observed}</p>
                              <ul className="space-y-1">
                                {h.similarities.slice(0, 2).map((sim, si) => (
                                  <li key={si} className="text-xs text-zinc-300 flex items-start gap-1.5">
                                    <span className="text-blue-500">•</span> {sim}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Cited Evidence Cards */}
                    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
                      <h4 className="text-sm font-semibold text-zinc-200 uppercase tracking-wider mb-4 flex items-center gap-2">
                        <Database className="w-4 h-4 text-amber-400" />
                        Primary Provenance Citations ({askResult.evidence.length})
                      </h4>
                      <div className="space-y-3">
                        {askResult.evidence.map((ev, i) => (
                          <div key={i} className="p-3.5 rounded-lg bg-zinc-950 border border-zinc-800/80 flex justify-between items-start gap-4">
                            <div>
                              <p className="text-sm text-zinc-200">{ev.text}</p>
                              {ev.published_at && (
                                <span className="text-xs text-zinc-500 font-mono mt-1 inline-block">
                                  Date: {new Date(ev.published_at).toLocaleDateString()}
                                </span>
                              )}
                            </div>
                            {ev.source_url && (
                              <a
                                href={ev.source_url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 font-mono flex-shrink-0"
                              >
                                Source <ExternalLink className="w-3 h-3" />
                              </a>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : null}
      </main>
    </div>
  );
}

function StatCard({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
  return (
    <div className="p-4 rounded-xl bg-zinc-900 border border-zinc-800 flex flex-col justify-between">
      <div className="flex items-center justify-between text-zinc-400 mb-2">
        <span className="text-xs font-medium uppercase tracking-wider">{label}</span>
        {icon}
      </div>
      <div className="text-2xl font-bold text-white tracking-tight font-mono">{value}</div>
    </div>
  );
}
