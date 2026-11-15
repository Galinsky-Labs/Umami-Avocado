import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type Claim, type Me, type Milestone, type PolicyDecision, type Program, type Project, type ProjectStatus, type Readiness,
  type Run, type SimulationDesign, ResearchApi, ResearchApiError, defaultDesign, portfolioStats, programLabels, slugify, validateDesign,
} from "./research-api";

export const researchPrograms = ["Yeast biomass (M1)", "Yeast extract (M2)", "Avocado (A1)"] as const;
const TOKEN_KEY = "umami.token";
type View = "portfolio" | "simulator" | "claims" | "access";
const viewLabels: Record<View, string> = { portfolio: "Portfolio", simulator: "Simulator", claims: "Claims", access: "My access" };

function readToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function writeToken(token: string | null) {
  try { if (token) localStorage.setItem(TOKEN_KEY, token); else localStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ }
}
function message(error: unknown) {
  return error instanceof ResearchApiError ? `${error.message} (${error.code})` : "Something went wrong.";
}

export function App() {
  const [token, setToken] = useState<string | null>(readToken);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [view, setView] = useState<View>("portfolio");
  const [error, setError] = useState<string | null>(null);
  const api = useMemo(() => new ResearchApi(token), [token]);

  useEffect(() => { new ResearchApi(null).readiness().then(setReadiness).catch(() => setReadiness(null)); }, []);
  useEffect(() => {
    if (!token) { setMe(null); return; }
    api.me().then(result => {
      setMe(result); setError(null);
      setWorkspaceId(current => current ?? result.memberships[0]?.workspace.id ?? null);
    }).catch(err => {
      setError(message(err));
      if (err instanceof ResearchApiError && err.status === 401) { writeToken(null); setToken(null); }
    });
  }, [api, token]);

  const signIn = (value: string) => { writeToken(value); setToken(value); };
  const signOut = () => { writeToken(null); setToken(null); setWorkspaceId(null); };
  const membership = me?.memberships.find(m => m.workspace.id === workspaceId);

  return <div className="app">
    <header className="topbar">
      <div className="brand"><span className="eyebrow">UMAMI AVOCADO</span><strong>Research console</strong></div>
      <StatusPill readiness={readiness} />
      {me && <div className="session">
        {me.memberships.length > 1 && <select aria-label="Workspace" value={workspaceId ?? ""} onChange={e => setWorkspaceId(e.target.value)}>
          {me.memberships.map(m => <option key={m.workspace.id} value={m.workspace.id}>{m.workspace.name}</option>)}
        </select>}
        <span className="who">{me.principal.display_name}{membership ? ` · ${membership.role}` : ""}</span>
        <button className="ghost" onClick={signOut}>Sign out</button>
      </div>}
    </header>
    <p className="notice" role="status">Live laboratory orders are disabled. No physical experiments have been performed; simulated results are always labelled SIMULATED.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {!token || !me ? <SignIn api={api} onToken={signIn} readiness={readiness} /> : !workspaceId ? <p>No workspace membership.</p> : <>
      <nav className="tabs" aria-label="Sections">
        {(Object.keys(viewLabels) as View[]).map(v => <button key={v} className={view === v ? "tab active" : "tab"} onClick={() => setView(v)}>
          {viewLabels[v]}</button>)}
      </nav>
      {view === "portfolio" && <Portfolio api={api} workspaceId={workspaceId} />}
      {view === "simulator" && <Simulator api={api} workspaceId={workspaceId} />}
      {view === "claims" && <Claims api={api} workspaceId={workspaceId} />}
      {view === "access" && <Access api={api} workspaceId={workspaceId} />}
    </>}
  </div>;
}

function StatusPill({ readiness }: { readiness: Readiness | null }) {
  const label = !readiness ? "API UNREACHABLE" : readiness.status === "ready" ? "API READY" : readiness.status === "degraded" ? "DATABASE DEGRADED" : "FOUNDATION ONLY";
  return <span className={`pill ${readiness?.status ?? "down"}`}>{label}</span>;
}

function SignIn({ api, onToken, readiness }: { api: ResearchApi; onToken: (t: string) => void; readiness: Readiness | null }) {
  const [token, setToken] = useState("");
  const [boot, setBoot] = useState({ secret: "", display_name: "", email: "", workspace_name: "" });
  const [error, setError] = useState<string | null>(null);
  const bootstrap = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      const result = await api.bootstrap(boot.secret, { display_name: boot.display_name, email: boot.email,
        workspace_name: boot.workspace_name, workspace_slug: slugify(boot.workspace_name) || "lab" });
      onToken(result.issued.secret);
    } catch (err) { setError(message(err)); }
  };
  return <section className="panels">
    <form className="panel" onSubmit={e => { e.preventDefault(); if (token.trim()) onToken(token.trim()); }}>
      <h2>Sign in with an API token</h2>
      <p>Tokens start with <code>ua_</code> and are stored only in this browser.</p>
      <label>API token<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} /></label>
      <button type="submit">Sign in</button>
    </form>
    <form className="panel" onSubmit={bootstrap}>
      <h2>First-time setup</h2>
      <p>Creates the first owner once, using the server's bootstrap secret.{readiness?.status === "foundation-only" ? " Requires a configured database." : ""}</p>
      <label>Bootstrap secret<input type="password" autoComplete="off" value={boot.secret} onChange={e => setBoot({ ...boot, secret: e.target.value })} /></label>
      <label>Your name<input value={boot.display_name} onChange={e => setBoot({ ...boot, display_name: e.target.value })} /></label>
      <label>Email<input type="email" value={boot.email} onChange={e => setBoot({ ...boot, email: e.target.value })} /></label>
      <label>Workspace name<input value={boot.workspace_name} onChange={e => setBoot({ ...boot, workspace_name: e.target.value })} /></label>
      {error && <p className="error">{error}</p>}
      <button type="submit">Create owner</button>
    </form>
  </section>;
}

function Portfolio({ api, workspaceId }: { api: ResearchApi; workspaceId: string }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [draft, setDraft] = useState({ name: "", program: "M1" as Program, objective: "" });
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.projects(workspaceId).then(setProjects).catch(e => setError(message(e))), [api, workspaceId]);
  useEffect(() => { load(); }, [load]);
  const stats = portfolioStats(projects);
  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    try {
      await api.createProject(workspaceId, { ...draft, slug: slugify(draft.name) });
      setDraft({ name: "", program: "M1", objective: "" }); setError(null); load();
    } catch (err) { setError(message(err)); }
  };
  const setStatus = async (project: Project, status: ProjectStatus) => {
    try { await api.updateProject(workspaceId, project.id, { status }); load(); } catch (err) { setError(message(err)); }
  };
  return <section>
    <div className="stats">
      <div><span className="eyebrow">PROJECTS</span><strong>{stats.total}</strong></div>
      <div><span className="eyebrow">ACTIVE</span><strong>{stats.active}</strong></div>
      {(Object.keys(programLabels) as Program[]).filter(p => p !== "OTHER").map(p => <div key={p}><span className="eyebrow">{p}</span><strong>{stats.byProgram[p]}</strong></div>)}
    </div>
    <div className="grid">
      {projects.map(project => <article key={project.id}>
        <span className="eyebrow">{programLabels[project.program].toUpperCase()}</span>
        <h3>{project.name}</h3>
        <p>{project.objective || "No objective recorded yet."}</p>
        <label className="inline">Status
          <select value={project.status} onChange={e => setStatus(project, e.target.value as ProjectStatus)}>
            {(["planning", "active", "paused", "archived"] as ProjectStatus[]).map(s => <option key={s}>{s}</option>)}
          </select>
        </label>
      </article>)}
      {projects.length === 0 && <article className="empty"><h3>No projects yet</h3><p>Create the first research project below.</p></article>}
    </div>
    <form className="panel" onSubmit={create}>
      <h2>New project</h2>
      <label>Name<input required value={draft.name} onChange={e => setDraft({ ...draft, name: e.target.value })} /></label>
      <label>Program<select value={draft.program} onChange={e => setDraft({ ...draft, program: e.target.value as Program })}>
        {(Object.keys(programLabels) as Program[]).map(p => <option key={p} value={p}>{programLabels[p]}</option>)}</select></label>
      <label>Objective<textarea value={draft.objective} onChange={e => setDraft({ ...draft, objective: e.target.value })} /></label>
      {error && <p className="error">{error}</p>}
      <button type="submit">Create project</button>
    </form>
  </section>;
}

function Claims({ api, workspaceId }: { api: ResearchApi; workspaceId: string }) {
  const [claims, setClaims] = useState<Claim[] | null>(null);
  useEffect(() => { api.claims(workspaceId).then(setClaims).catch(() => setClaims([])); }, [api, workspaceId]);
  return <section className="panel">
    <h2>Scientific claims</h2>
    <p>Claims are accepted only by a human reviewer who did not author them, with supporting evidence from a verified source or a PHYSICAL measurement.</p>
    {claims === null ? <p>Loading…</p> : claims.length === 0 ? <p>No claims recorded.</p> : <table>
      <thead><tr><th>Statement</th><th>Status</th><th>Author</th></tr></thead>
      <tbody>{claims.map(c => <tr key={c.id}><td>{c.statement}</td><td><span className={`badge ${c.status}`}>{c.status}</span></td><td>{c.author_kind}</td></tr>)}</tbody>
    </table>}
  </section>;
}

function Access({ api, workspaceId }: { api: ResearchApi; workspaceId: string }) {
  const [decisions, setDecisions] = useState<PolicyDecision[]>([]);
  useEffect(() => { api.decisions(workspaceId).then(setDecisions).catch(() => setDecisions([])); }, [api, workspaceId]);
  return <section className="panel">
    <h2>What you may do here</h2>
    <p>Evaluated live by the server's policy engine.</p>
    <table><thead><tr><th>Action</th><th>Decision</th><th>Reason</th></tr></thead>
      <tbody>{decisions.map(d => <tr key={d.action}><td><code>{d.action}</code></td><td>{d.allowed ? "allowed" : "denied"}</td><td>{d.reason.replaceAll("_", " ")}</td></tr>)}</tbody>
    </table>
  </section>;
}

function Simulator({ api, workspaceId }: { api: ResearchApi; workspaceId: string }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [milestone, setMilestone] = useState<Milestone | null>(null);
  const [design, setDesign] = useState<SimulationDesign>(defaultDesign);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.projects(workspaceId).then(list => { setProjects(list); setProjectId(id => id || list[0]?.id || ""); }).catch(e => setError(message(e))); }, [api, workspaceId]);
  const load = useCallback(() => {
    if (!projectId) return;
    api.runs(workspaceId, projectId).then(setRuns).catch(e => setError(message(e)));
    api.milestone(workspaceId, projectId).then(setMilestone).catch(() => setMilestone(null));
  }, [api, workspaceId, projectId]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!runs.some(r => r.state === "queued" || r.state === "running")) return;
    const timer = setTimeout(load, 2000);
    return () => clearTimeout(timer);
  }, [runs, load]);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const problem = validateDesign(design);
    if (problem) { setError(problem); return; }
    try { await api.simulate(workspaceId, projectId, design); setError(null); load(); } catch (err) { setError(message(err)); }
  };
  const field = (key: keyof SimulationDesign, label: string, step = "any") => <label>{label}
    <input type={key === "label" ? "text" : "number"} step={step} value={design[key]}
      onChange={e => setDesign({ ...design, [key]: key === "label" ? e.target.value : Number(e.target.value) })} /></label>;
  if (projects.length === 0) return <section className="panel"><h2>Simulator</h2><p>Create a project first.</p></section>;
  return <section>
    <p className="notice simulated">Everything on this page is SIMULATED output of a deterministic Monod batch model — not a laboratory measurement.</p>
    <label>Project<select value={projectId} onChange={e => setProjectId(e.target.value)}>
      {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
    <div className="panels">
      <form className="panel" onSubmit={submit}>
        <h2>New simulated run</h2>
        {field("label", "Label")}{field("temperature_c", "Temperature (°C)")}{field("ph", "pH")}
        {field("initial_glucose_g_l", "Initial glucose (g/L)")}{field("duration_h", "Duration (h)")}
        {field("sample_interval_h", "Sample interval (h)")}{field("biological_replicates", "Biological replicates", "1")}
        {field("technical_replicates", "Technical replicates", "1")}{field("seed", "Seed", "1")}
        {error && <p className="error">{error}</p>}
        <button type="submit">Queue simulation</button>
      </form>
      <div className="panel">
        <h2>Digital milestone</h2>
        {milestone ? <ul className="checks">{milestone.checks.map(c => <li key={c.key} className={c.met ? "met" : ""}>{c.met ? "✓" : "○"} {c.description}</li>)}</ul> : <p>Unavailable.</p>}
        {milestone && <p>{milestone.achieved ? "Achieved. " : ""}{milestone.note}</p>}
      </div>
    </div>
    <div className="panel">
      <h2>Runs</h2>
      {runs.length === 0 ? <p>No runs yet.</p> : <table>
        <thead><tr><th>Run</th><th>State</th><th>Final biomass (g/L)</th><th>Residual glucose (g/L)</th><th>Glutamate (g/L)</th></tr></thead>
        <tbody>{runs.map(r => <tr key={r.id}><td>{r.label} <span className="badge">SIMULATED</span></td><td>{r.state}</td>
          <td>{r.summary?.biomass_concentration ?? "—"}</td><td>{r.summary?.substrate_concentration ?? "—"}</td><td>{r.summary?.glutamate_concentration ?? "—"}</td></tr>)}</tbody>
      </table>}
    </div>
  </section>;
}
