import { useState } from "react";
import {
  AGENT_ACTIONS, type FullTrace, type Member, type OptimizationRound, type ResearchApi, type ResearchContract, contractActive,
} from "../research-api";
import { ProjectPicker, message, useLoad, when } from "./common";

export function AgentsView({ api, workspaceId }: { api: ResearchApi; workspaceId: string }) {
  const ws = `/api/v1/workspaces/${workspaceId}`;
  const members = useLoad<Member[]>(() => api.get(`${ws}/members`), [api, ws]);
  const contracts = useLoad<ResearchContract[]>(() => api.get(`${ws}/research-contracts`), [api, ws]);
  const traces = useLoad<FullTrace[]>(() => api.get(`${ws}/agent/traces`), [api, ws]);
  const [open, setOpen] = useState<string | null>(null);
  const [grant, setGrant] = useState({ agent_id: "", purpose: "", ttl_days: 14, actions: ["agent.run", "experiment.draft"] as string[] });
  const [error, setError] = useState<string | null>(null);
  const agents = members.data?.filter(m => m.principal.kind === "agent") ?? [];
  const name = (id: string) => members.data?.find(m => m.principal.id === id)?.principal.display_name ?? id.slice(0, 8);
  const submitGrant = async (event: React.FormEvent) => {
    event.preventDefault();
    try { await api.post(`${ws}/research-contracts`, grant); setError(null); contracts.reload(); } catch (err) { setError(message(err)); }
  };
  const revoke = async (id: string) => {
    try { await api.delete(`${ws}/research-contracts/${id}`); contracts.reload(); } catch (err) { setError(message(err)); }
  };
  return <section>
    <div className="panels">
      <div className="panel">
        <h2>Agents and research contracts</h2>
        <p>Agents act only within explicit, expiring contracts granted by a human. They can never approve, spend, ship or touch physical work.</p>
        {agents.length === 0 && <p>No agent principals in this workspace.</p>}
        <table><thead><tr><th>Agent</th><th>Contract</th><th>Actions</th><th>Expires</th><th /></tr></thead>
          <tbody>{contracts.data?.map(c => <tr key={c.id} className={contractActive(c) ? "" : "inactive"}>
            <td>{name(c.agent_id)}</td><td>{c.purpose}</td><td>{c.actions.join(", ")}</td>
            <td>{c.revoked_at ? "revoked" : when(c.expires_at)}</td>
            <td>{contractActive(c) && <button className="ghost" onClick={() => revoke(c.id)}>Revoke</button>}</td></tr>)}</tbody></table>
      </div>
      {agents.length > 0 && <form className="panel" onSubmit={submitGrant}>
        <h2>Grant a contract</h2>
        <label>Agent<select value={grant.agent_id} onChange={e => setGrant({ ...grant, agent_id: e.target.value })} required>
          <option value="">Choose…</option>{agents.map(a => <option key={a.principal.id} value={a.principal.id}>{a.principal.display_name}</option>)}</select></label>
        <label>Purpose<input required value={grant.purpose} onChange={e => setGrant({ ...grant, purpose: e.target.value })} /></label>
        <label>Days (≤90)<input type="number" min={1} max={90} value={grant.ttl_days} onChange={e => setGrant({ ...grant, ttl_days: Number(e.target.value) })} /></label>
        <fieldset className="checks-grid">{AGENT_ACTIONS.map(a => <label key={a} className="inline">
          <input type="checkbox" checked={grant.actions.includes(a)} onChange={() => setGrant({ ...grant,
            actions: grant.actions.includes(a) ? grant.actions.filter(x => x !== a) : [...grant.actions, a] })} /> <code>{a}</code></label>)}</fieldset>
        {error && <p className="error">{error}</p>}
        <button type="submit">Grant</button>
      </form>}
    </div>
    <Optimization api={api} workspaceId={workspaceId} />
    <div className="panel">
      <h2>Execution traces</h2>
      <p>Every planning call: provider, model, input digest, raw draft and the platform's verdict.</p>
      {traces.data?.length === 0 && <p>No traces yet.</p>}
      <ul className="list">{traces.data?.map(t => <li key={t.id}>
        <button className="linkish" onClick={() => setOpen(open === t.id ? null : t.id)}>{when(t.created_at)}</button>{" "}
        <span className={`badge ${t.outcome === "proposal_created" ? "" : "warning"}`}>{t.outcome.replaceAll("_", " ")}</span>{" "}
        {t.provider}/{t.model} · requested by {name(t.requested_by)}
        {open === t.id && <div className="trace-detail">
          <p><strong>Input SHA-256</strong> <code>{t.input_sha256}</code></p>
          {t.errors.map(e => <p key={e} className="error">{e}</p>)}
          {t.output && <pre>{JSON.stringify(t.output, null, 2)}</pre>}
          <details><summary>Input context</summary><pre>{JSON.stringify(t.input, null, 2)}</pre></details>
        </div>}
      </li>)}</ul>
    </div>
  </section>;
}

function Optimization({ api, workspaceId }: { api: ResearchApi; workspaceId: string }) {
  const [projectId, setProjectId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const url = `/api/v1/workspaces/${workspaceId}/projects/${projectId}/optimization/rounds`;
  const rounds = useLoad<OptimizationRound[]>(() => projectId ? api.get(url) : Promise.resolve([]), [api, url, projectId]);
  const suggestRound = async (queue: boolean) => {
    try { await api.post(url, { batch_size: 3, queue_simulated_runs: queue }); setError(null); rounds.reload(); } catch (err) { setError(message(err)); }
  };
  const latest = rounds.data?.[0];
  return <div className="panel">
    <h2>Next-experiment selection</h2>
    <p>Gaussian-process UCB over completed SIMULATED runs, inside bounded parameter limits. Queued runs are SIMULATED only.</p>
    <ProjectPicker api={api} workspaceId={workspaceId} value={projectId} onChange={setProjectId} />
    <button className="ghost" onClick={() => suggestRound(false)}>Suggest</button>{" "}
    <button onClick={() => suggestRound(true)}>Suggest and queue simulations</button>
    {error && <p className="error">{error}</p>}
    {latest && <table><caption>{latest.strategy} · {latest.observations.length} observations · {when(latest.created_at)}</caption>
      <thead><tr><th>T (°C)</th><th>pH</th><th>Glucose (g/L)</th><th>Predicted</th></tr></thead>
      <tbody>{latest.suggestions.map((s, i) => <tr key={i}><td>{s.x.temperature_c}</td><td>{s.x.ph}</td><td>{s.x.initial_glucose_g_l}</td>
        <td>{s.predicted_mean === null ? "exploration" : `${s.predicted_mean.toFixed(2)} ± ${(s.predicted_sd ?? 0).toFixed(2)}`}</td></tr>)}</tbody></table>}
  </div>;
}
