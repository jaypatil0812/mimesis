"use client";
import React, { useEffect, useState } from "react";
import { Watch, WatchConfig, WatchDetail, Observation, SourceWatch, Snapshot, Pattern, listWatches, watchDetail, createWatch, configureWatch, runWatch, reviewPattern, observations, reviewObservation, reviewTemplates } from "../lib/research";

const box = "rounded-xl border border-zinc-800 bg-zinc-900 p-5 space-y-3";
const field = "bg-zinc-950 border border-zinc-700 rounded p-2 w-full text-sm";
const button = "px-3 py-2 rounded border border-zinc-700 hover:bg-zinc-800 text-sm disabled:opacity-40";
const initial = (): WatchConfig => ({ name: "", question: "", scope: { market_id: null, time_basis: "published_at", graph_hops: 3, include_adjacent_markets: true }, sources: [], enabled: false, interval_seconds: 3600, processing_version: "memory-worker-v2" });

function ReviewForm({ states, submit }: { states: string[]; submit: (state: string, reviewer: string, note: string) => Promise<void> }) {
  const [state, setState] = useState(states[0]);
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  return <form className="space-y-2" onSubmit={async e => { e.preventDefault(); setBusy(true); setMessage(""); try { await submit(state, reviewer.trim(), note.trim()); setMessage("Review saved."); } catch (error) { setMessage(String(error)); } finally { setBusy(false); } }}>
    <label className="block text-xs">Review decision<select className={field} value={state} onChange={e => setState(e.target.value)}>{states.map(value => <option key={value}>{value}</option>)}</select></label>
    <input className={field} required aria-label="Human reviewer name" placeholder="Your name" value={reviewer} onChange={e => setReviewer(e.target.value)} />
    <textarea className={field} required aria-label="Review rationale" placeholder="Explain what the source supports, conditions, and any disagreement." value={note} onChange={e => setNote(e.target.value)} />
    <label className="block text-xs text-zinc-400"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> I inspected the supporting passages and qualifications.</label>
    <button className={button} disabled={busy || !confirmed || !reviewer.trim() || !note.trim()}>Save human review</button>
    {message && <p className="text-sm" role="status">{message}</p>}
  </form>;
}

function Passage({ item }: { item: Observation }) {
  return <div className="space-y-2 text-sm">
    <p className="text-xs text-amber-400">{item.observation_type} · {item.review_state} · {item.attribution || "attribution unresolved"}</p>
    <blockquote className="border-l-2 border-zinc-600 pl-3 whitespace-pre-wrap">{item.statement}</blockquote>
    {item.source_url && <a className="text-blue-400 underline" href={item.source_url} target="_blank" rel="noreferrer">Open source</a>}
    <p className="text-xs text-zinc-400">Published: {item.published_at || "unknown"}. Evidence: {item.evidence_ids?.join(", ") || "unavailable"}</p>
    {item.source_spans?.map(span => <details key={span.id}><summary>Exact span {span.start}–{span.end}</summary><p className="whitespace-pre-wrap">{span.text}</p></details>)}
    <details><summary>Conditions, attribution and source family</summary><pre className="text-xs whitespace-pre-wrap break-words">{JSON.stringify({ context: item.context, source_family: item.source_family }, null, 2)}</pre></details>
  </div>;
}

function Counterevidence({ pattern, snapshot }: { pattern: Pattern; snapshot: Snapshot }) {
  const ids = Array.from(new Set([...pattern.contradictory_evidence_ids, ...(pattern.related_opposing_evidence_ids || [])]));
  return <details>
    <summary>Counterevidence records: {ids.length}</summary>
    {ids.length === 0 && <p>No contradiction identified; this does not establish absence.</p>}
    {ids.map(id => {
      const source = snapshot.observations.find(o => o.id === "source:" + id) || snapshot.observations.find(o => o.evidence_ids?.includes(id));
      return source ? <Passage key={id} item={source} /> : <p key={id}>Evidence {id} is unavailable in this saved snapshot.</p>;
    })}
  </details>;
}

export default function ResearchWorkspace({ marketId }: { marketId: string }) {
  const [watches, setWatches] = useState<Watch[]>([]);
  const [worker, setWorker] = useState<Record<string, unknown>>({});
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<WatchDetail | null>(null);
  const [snapshotId, setSnapshotId] = useState("");
  const [config, setConfig] = useState<WatchConfig>(initial);
  const [editing, setEditing] = useState<Watch | null>(null);
  const [templates, setTemplates] = useState<WatchConfig[]>([]);
  const [items, setItems] = useState<Observation[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [reviewState, setReviewState] = useState("proposed");
  const [allMemory, setAllMemory] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function refreshList() { const result = await listWatches(); setWatches(result.investigations); setWorker(result.worker); }
  async function refreshMemory() { const result = await observations(allMemory ? "" : marketId, reviewState, offset); setItems(result.observations); setTotal(result.total); }
  useEffect(() => { let active = true; Promise.all([listWatches(), reviewTemplates()]).then(([list, presets]) => { if (active) { setWatches(list.investigations); setWorker(list.worker); setTemplates(presets.templates); } }).catch(e => active && setError(String(e))); return () => { active = false; }; }, []);
  useEffect(() => { let active = true; setItems([]); observations(allMemory ? "" : marketId, reviewState, offset).then(result => { if (active) { setItems(result.observations); setTotal(result.total); } }).catch(e => active && setError(String(e))); return () => { active = false; }; }, [marketId, allMemory, reviewState, offset]);
  useEffect(() => { let active = true; setDetail(null); setSnapshotId(""); if (!selected) return; const load = () => watchDetail(selected).then(result => { if (active) { setDetail(result); setWorker(result.worker); } }).catch(e => active && setError(String(e))); void load(); const timer = setInterval(load, 15000); return () => { active = false; clearInterval(timer); }; }, [selected]);
  const snapshot: Snapshot | undefined = detail?.snapshots.find(s => s.id === snapshotId) || detail?.snapshots[0];
  const updateSource = (index: number, source: SourceWatch) => setConfig({ ...config, sources: config.sources.map((old, i) => i === index ? source : old) });
  async function action(task: () => Promise<unknown>, message: string) { setBusy(true); setError(""); try { await task(); await refreshList(); if (selected) setDetail(await watchDetail(selected)); setNotice(message); } catch (e) { setError(String(e)); } finally { setBusy(false); } }
  return <section className="space-y-6 text-zinc-200">
    <div className={box}><h2 className="text-xl font-semibold">Investigations and connected memory review</h2><p className="text-sm text-zinc-400">Watchlists collect and investigate on a separate worker. Patterns are proposals. Reviewing a pattern records your assessment; it does not approve graph relationships.</p><details><summary>Collection worker status</summary><pre className="text-xs whitespace-pre-wrap">{JSON.stringify(worker, null, 2)}</pre></details><button className={button} onClick={() => action(refreshList, "Status refreshed.")} disabled={busy}>Refresh status</button></div>
    {error && <p role="alert" className="text-red-400">{error}</p>}{notice && <p role="status" className="text-blue-300">{notice}</p>}
    <div className="grid gap-6 lg:grid-cols-2">
      <form className={box} onSubmit={e => { e.preventDefault(); void action(async () => { const saved = editing ? await configureWatch(editing, config) : await createWatch(config); setSelected(saved.id); setEditing(null); setConfig(initial()); }, "Watchlist saved. Queued work requires the collection worker."); }}>
        <h3 className="font-semibold">{editing ? "Edit watchlist" : "Create watchlist"}</h3>
        {!editing && <label className="block text-sm">Start from a research question<select className={field} defaultValue="" onChange={e => { if (e.target.value) setConfig({ ...templates[Number(e.target.value)], scope: { ...templates[Number(e.target.value)].scope, market_id: null } }); }}><option value="">Custom investigation</option>{templates.map((t, i) => <option key={i} value={i}>{t.name}</option>)}</select></label>}
        <label className="block text-sm">Name<input required className={field} value={config.name} onChange={e => setConfig({ ...config, name: e.target.value })} /></label>
        <label className="block text-sm">Customer question<textarea required className={field} value={config.question} onChange={e => setConfig({ ...config, question: e.target.value })} /></label>
        <label className="block text-sm">Evidence boundary<select className={field} value={config.scope.market_id || ""} onChange={e => setConfig({ ...config, scope: { ...config.scope, market_id: e.target.value || null } })}><option value="">Configured source results and their connected paths</option>{marketId && <option value={marketId}>Current market only</option>}{config.scope.market_id && config.scope.market_id !== marketId && <option value={config.scope.market_id}>Existing market scope</option>}</select></label>
        <p className="text-xs text-zinc-400">With no sources and no market boundary, the investigation uses existing global memory. A market boundary never falls back to global evidence.</p>
        <label className="block text-sm">Evidence since<input className={field} type="date" value={config.scope.start_at?.slice(0, 10) || ""} onChange={e => setConfig({ ...config, scope: { ...config.scope, start_at: e.target.value ? e.target.value + "T00:00:00Z" : null } })} /></label>
        <label className="block text-sm">Time basis<select className={field} value={config.scope.time_basis} onChange={e => setConfig({ ...config, scope: { ...config.scope, time_basis: e.target.value } })}><option value="published_at">Publication date</option><option value="known_at">When Mimesis knew the record</option></select></label>
        <label className="block text-sm">Graph steps<input className={field} type="number" min={1} max={6} value={config.scope.graph_hops} onChange={e => setConfig({ ...config, scope: { ...config.scope, graph_hops: Number(e.target.value) } })} /></label>
        <label className="block text-sm"><input type="checkbox" checked={config.scope.include_adjacent_markets} onChange={e => setConfig({ ...config, scope: { ...config.scope, include_adjacent_markets: e.target.checked } })} /> Include supported adjacent-market paths</label>
        {config.sources.map((source, index) => <div key={index} className="border border-zinc-700 p-3 rounded space-y-2"><label className="block text-sm">Source<select className={field} value={source.source} onChange={e => updateSource(index, { source: e.target.value as SourceWatch["source"], query: source.query })}>{["hackernews", "bluesky", "openalex", "github", "rss", "web"].map(value => <option key={value}>{value}</option>)}</select></label><input required className={field} aria-label="Search query" placeholder="Source search query" value={source.query} onChange={e => updateSource(index, { ...source, query: e.target.value })} />{["rss", "web"].includes(source.source) && <input required className={field} type="url" aria-label="Source URL" placeholder={source.source === "web" ? "Page to revisit" : "Feed URL"} value={source.source === "web" ? source.page_url || "" : source.feed_url || ""} onChange={e => updateSource(index, { ...source, ...(source.source === "web" ? { page_url: e.target.value } : { feed_url: e.target.value }) })} />}<button type="button" className={button} onClick={() => setConfig({ ...config, sources: config.sources.filter((_, i) => i !== index) })}>Remove source</button></div>)}
        <button type="button" className={button} disabled={config.sources.length >= 4} onClick={() => setConfig({ ...config, sources: [...config.sources, { source: "hackernews", query: "" }] })}>Add source</button>
        <label className="block text-sm">Repeat every (seconds)<input required className={field} type="number" min={60} max={604800} value={config.interval_seconds} onChange={e => setConfig({ ...config, interval_seconds: Number(e.target.value) })} /></label>
        <label className="block text-sm"><input type="checkbox" checked={config.enabled} onChange={e => setConfig({ ...config, enabled: e.target.checked })} /> Enable scheduled collection and analysis</label>
        <button className={button} disabled={busy}>Save watchlist</button>{editing && <button type="button" className={button} onClick={() => { setEditing(null); setConfig(initial()); }}>Cancel edit</button>}
      </form>
      <div className={box}><h3 className="font-semibold">Watchlists across research boundaries</h3>{watches.length === 0 && <p className="text-sm text-zinc-400">No watchlists yet.</p>}{watches.map(watch => <div key={watch.id} className="border-b border-zinc-800 pb-3 space-y-2"><button className="text-blue-300 text-left" onClick={() => setSelected(watch.id)}>{watch.config.name}</button><p className="text-xs">{watch.config.enabled ? "Scheduled" : "Paused"} · {watch.config.scope.market_id ? "Market scoped" : "Research source / memory scoped"} · Due {new Date(watch.next_due_at).toLocaleString()}</p><div className="flex gap-2"><button className={button} disabled={busy} onClick={() => action(() => runWatch(watch.id), "Run queued; watch worker status for completion.")}>Queue one run</button><button className={button} onClick={() => { setEditing(watch); setConfig(structuredClone(watch.config)); }}>Edit</button><button className={button} disabled={busy} onClick={() => action(() => configureWatch(watch, { ...watch.config, enabled: !watch.config.enabled }), "Schedule updated.")}>{watch.config.enabled ? "Pause" : "Resume"}</button></div></div>)}</div>
    </div>
    {detail && <div className={box}><h3 className="font-semibold">{detail.config.name}: investigation history</h3><p className="text-sm">{detail.config.question}</p><p className="text-xs text-zinc-400">Collection lag describes configured searches, not completeness of the market.</p><pre className="text-xs whitespace-pre-wrap">{JSON.stringify(detail.collection_health || [], null, 2)}</pre>
      <label className="block text-sm">Saved snapshot<select className={field} value={snapshot?.id || ""} onChange={e => setSnapshotId(e.target.value)}>{detail.snapshots.map(s => <option key={s.id} value={s.id}>{new Date(s.created_at).toLocaleString()}</option>)}</select></label>
      {!snapshot && <p>No analysis snapshot yet. Queue a run and check that the worker is active.</p>}
      {snapshot && <><p>Reasoning: {snapshot.reasoning_execution.status}</p><p className="text-sm">{snapshot.change.added_evidence_ids.length} added records; {snapshot.change.removed_from_scope_ids.length} removed from scope. {snapshot.change.comparison_baseline_present ? "Previous snapshot available." : "No previous snapshot baseline."}</p><details><summary>Coverage and gaps</summary><pre className="text-xs whitespace-pre-wrap">{JSON.stringify(snapshot.coverage, null, 2)}</pre><ul>{snapshot.missing_information.map((gap, i) => <li key={i}>{gap}</li>)}</ul></details>{snapshot.patterns.length === 0 && <p>No justified pattern proposed in this snapshot. Inspect the gaps.</p>}
        {snapshot.patterns.map(pattern => <article key={snapshot.id + pattern.id} className="border border-zinc-700 rounded p-4 space-y-3"><h4 className="font-semibold">Provisional: {pattern.category}</h4><p>{pattern.explanation}</p><p className="text-xs">Latest review: {detail.pattern_reviews.filter(r => r.pattern_id === pattern.id).at(-1)?.state || "proposed"}</p><details><summary>Supporting observations</summary>{pattern.supporting_observations.map(item => <Passage key={item.id} item={item} />)}</details><details><summary>Connecting paths</summary>{pattern.connecting_paths.map((path, i) => <p key={i} className="text-sm">{path.map(id => { const edge = snapshot.connecting_relationships.find(e => e.id === id); return edge ? `${edge.from} → ${edge.type} → ${edge.to}` : id; }).join("; ")}</p>)}</details><p>Alternatives: {pattern.alternative_explanations.join("; ")}</p><Counterevidence pattern={pattern} snapshot={snapshot} /><p>Missing: {pattern.missing_information.join("; ")}</p>{pattern.next_investigation && <p>Next: {pattern.next_investigation.question}</p>}<ReviewForm states={["reviewed", "rejected", "proposed"]} submit={async (state, reviewer, note) => { await reviewPattern(detail.id, pattern.id, state, reviewer, note); setDetail(await watchDetail(detail.id)); }} /><details><summary>Review history</summary>{detail.pattern_reviews.filter(r => r.pattern_id === pattern.id).map(r => <p key={r.id}>{r.created_at}: {r.reviewer} · {r.state} · {r.note}</p>)}</details></article>)}
      </>}
      <details><summary>Collection and processing runs</summary>{detail.runs.map(run => <div key={run.id}><p>{run.started_at}: {run.status}</p><pre className="text-xs whitespace-pre-wrap break-words">{JSON.stringify(run.receipt, null, 2)}</pre></div>)}</details>
    </div>}
    <div className={box}><h3 className="font-semibold">Evidence and observation review</h3><p className="text-sm text-zinc-400">Review exact passages, attribution and conditions. Accepting a relationship can promote a graph edge; accepting an interpretation does not prove its conclusion.</p><label><input type="checkbox" checked={allMemory} onChange={e => { setAllMemory(e.target.checked); setOffset(0); }} /> Show memory across all markets</label><label className="block">Review state<select className={field} value={reviewState} onChange={e => { setReviewState(e.target.value); setOffset(0); }}>{["proposed", "accepted", "rejected", "superseded", ""].map(value => <option key={value} value={value}>{value || "All"}</option>)}</select></label><p>{total} observations match this boundary.</p>{items.map(item => <article key={item.id} className="border border-zinc-700 rounded p-4 space-y-3"><Passage item={item} /><ReviewForm states={["accepted", "rejected", "proposed", "superseded"]} submit={async (state, reviewer, note) => { await reviewObservation(item.id, state, reviewer, note); await refreshMemory(); if (selected) setDetail(await watchDetail(selected)); }} /><details><summary>Review history</summary><pre className="text-xs whitespace-pre-wrap">{JSON.stringify(item.reviews || [], null, 2)}</pre></details></article>)}<div className="flex gap-2"><button className={button} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous</button><button className={button} disabled={offset + 20 >= total} onClick={() => setOffset(offset + 20)}>Next</button></div></div>
  </section>;
}
