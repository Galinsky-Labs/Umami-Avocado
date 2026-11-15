import { useState } from "react";
import { type ResearchApi, formatUsd as dollars } from "../research-api";
import { message, useLoad, when } from "./common";

type Capability = { code: string; organisms: string[]; assay_keys: string[]; turnaround_days: number; unit_price_cents: number };
type Lab = { id: string; name: string; adapter_key: string; status: string; capabilities: Capability[]; public_contact: string; notes: string; updated_at: string };
type Contract = { id: string; title: string; scope: string; status: string; max_value_cents: number; expires_at: string | null; created_at: string };
type Adapter = { key: string; mode: string; origin: string; dispatch_enabled: boolean };
type Match = { laboratory: Lab; capability: Capability; contracted: boolean; has_signed_contract: boolean };

const ORGANISMS = ["Saccharomyces cerevisiae", "Cyberlindnera jadinii", "Kluyveromyces marxianus"];


export function LabsView({ api, workspaceId }: { api: ResearchApi; workspaceId: string }) {
  const ws = `/api/v1/workspaces/${workspaceId}`;
  const adapters = useLoad<Adapter[]>(() => api.get("/api/v1/lab-adapters"), [api]);
  const labs = useLoad<Lab[]>(() => api.get(`${ws}/laboratories`), [api, ws]);
  const [selected, setSelected] = useState<string | null>(null);
  const contracts = useLoad<Contract[]>(() => selected ? api.get(`${ws}/laboratories/${selected}/contracts`) : Promise.resolve([]), [api, ws, selected]);
  const [draft, setDraft] = useState({ name: "", adapter_key: "manual_cro", code: "batch_fermentation", organism: ORGANISMS[0], price: 0 });
  const [search, setSearch] = useState({ capability: "batch_fermentation", organism: ORGANISMS[0] });
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const register = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await api.post(`${ws}/laboratories`, { name: draft.name, adapter_key: draft.adapter_key,
        capabilities: [{ code: draft.code, organisms: [draft.organism], unit_price_cents: Math.round(draft.price * 100) }] });
      setError(null); labs.reload();
    } catch (err) { setError(message(err)); }
  };
  const setStatus = async (lab: Lab, status: string) => {
    try { await api.patch(`${ws}/laboratories/${lab.id}`, { status }); setError(null); labs.reload(); } catch (err) { setError(message(err)); }
  };
  const find = async () => {
    try { setMatches(await api.get(`${ws}/laboratories/match?capability=${encodeURIComponent(search.capability)}&organism=${encodeURIComponent(search.organism)}`)); }
    catch (err) { setError(message(err)); }
  };
  return <section>
    <p className="notice">Live laboratory submission is disabled. Physical adapters cannot dispatch work; the manual CRO workflow stops at human approval.</p>
    {error && <p className="error">{error}</p>}
    <div className="panels">
      <div className="panel">
        <h2>Integration status</h2>
        <table><thead><tr><th>Adapter</th><th>Mode</th><th>Results</th><th>Dispatch</th></tr></thead>
          <tbody>{adapters.data?.map(a => <tr key={a.key}><td><code>{a.key}</code></td><td>{a.mode}</td><td>{a.origin}</td>
            <td>{a.dispatch_enabled ? "enabled (simulated)" : "blocked"}</td></tr>)}</tbody></table>
      </div>
      <div className="panel">
        <h2>Find a laboratory</h2>
        <label>Capability<input value={search.capability} onChange={e => setSearch({ ...search, capability: e.target.value })} /></label>
        <label>Organism<select value={search.organism} onChange={e => setSearch({ ...search, organism: e.target.value })}>
          {ORGANISMS.map(o => <option key={o}>{o}</option>)}</select></label>
        <button className="ghost" onClick={find}>Search</button>
        {matches && (matches.length === 0 ? <p>No matching laboratories.</p> : <ul className="list">{matches.map(m =>
          <li key={m.laboratory.id + m.capability.code}>{m.laboratory.name} · {m.contracted ? "contracted" : m.laboratory.status}
            {m.has_signed_contract ? " · signed contract" : ""} · {dollars(m.capability.unit_price_cents ?? 0)}</li>)}</ul>)}
      </div>
    </div>
    <div className="panel">
      <h2>Laboratory network</h2>
      {labs.data?.length === 0 && <p>No laboratories registered.</p>}
      <table><thead><tr><th>Name</th><th>Adapter</th><th>Status</th><th>Capabilities</th><th>Updated</th></tr></thead>
        <tbody>{labs.data?.map(l => <tr key={l.id}>
          <td><button className="linkish" onClick={() => setSelected(l.id)}>{l.name}</button></td><td><code>{l.adapter_key}</code></td>
          <td><select aria-label={`Status of ${l.name}`} value={l.status} onChange={e => setStatus(l, e.target.value)}>
            {["prospect", "onboarding", "contracted", "suspended"].map(s => <option key={s}>{s}</option>)}</select></td>
          <td>{l.capabilities.map(c => c.code).join(", ") || "—"}</td><td>{when(l.updated_at)}</td></tr>)}</tbody></table>
      {selected && <>
        <h3>Contracts</h3>
        {contracts.data?.length === 0 && <p>No contracts recorded. A laboratory can be marked contracted only with a signed contract.</p>}
        <ul className="list">{contracts.data?.map(c => <li key={c.id}>{c.title} · {c.status} · cap {dollars(c.max_value_cents)}
          {c.expires_at ? ` · expires ${when(c.expires_at)}` : ""}</li>)}</ul>
      </>}
    </div>
    <form className="panel" onSubmit={register}>
      <h2>Register a laboratory</h2>
      <label>Name<input required value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} /></label>
      <label>Adapter<select value={draft.adapter_key} onChange={e => setDraft({ ...draft, adapter_key: e.target.value })}>
        <option value="manual_cro">manual_cro (supervised human exchange)</option><option value="simulator">simulator</option></select></label>
      <label>Capability code<input value={draft.code} onChange={e => setDraft({ ...draft, code: e.target.value })} /></label>
      <label>Organism<select value={draft.organism} onChange={e => setDraft({ ...draft, organism: e.target.value })}>
        {ORGANISMS.map(o => <option key={o}>{o}</option>)}</select></label>
      <label>Unit price (USD)<input type="number" min={0} step="0.01" value={draft.price} onChange={e => setDraft({ ...draft, price: Number(e.target.value) })} /></label>
      <button type="submit">Register</button>
    </form>
  </section>;
}
