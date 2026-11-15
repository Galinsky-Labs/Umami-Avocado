// Hand-written typed client for the authenticated /api/v1 research API.
// The strict generated client (src/generated/api.ts) covers only the foundation contract.

export type Role = "owner" | "admin" | "scientist" | "reviewer" | "viewer" | "agent";
export type Program = "M1" | "M2" | "A1" | "OTHER";
export type ProjectStatus = "planning" | "active" | "paused" | "archived";
export type Origin = "SIMULATED" | "PHYSICAL";

export interface Workspace { id: string; slug: string; name: string; created_at: string }
export interface Principal { id: string; kind: "human" | "agent"; display_name: string; email: string | null }
export interface Me { principal: Principal; memberships: { workspace: Workspace; role: Role }[]; live_lab_orders_enabled: false }
export interface Project {
  id: string; workspace_id: string; slug: string; name: string; program: Program;
  status: ProjectStatus; objective: string; created_at: string; updated_at: string;
}
export interface Claim { id: string; statement: string; status: string; author_kind: string; project_id: string | null; updated_at: string }
export interface PolicyDecision { action: string; allowed: boolean; reason: string }
export interface Readiness { status: "foundation-only" | "ready" | "degraded"; database_connected: boolean; live_lab_orders_enabled: false }
export interface Bootstrapped { principal: Principal; workspace: Workspace; issued: { secret: string } }

export interface SimulationDesign {
  label: string; temperature_c: number; ph: number; initial_glucose_g_l: number;
  duration_h: number; sample_interval_h: number; biological_replicates: number; technical_replicates: number; seed: number;
}
export interface Run {
  id: string; project_id: string; origin: Origin; label: string; model_version: string; design: Record<string, number>;
  state: "queued" | "running" | "completed" | "failed" | "cancelled";
  summary: { biomass_concentration: number; substrate_concentration: number; glutamate_concentration: number; final_time_h: number; samples: number } | null;
  created_at: string;
}
export interface Milestone { achieved: boolean; physical_results_exist: boolean; note: string; checks: { key: string; description: string; met: boolean }[] }

export interface AgentTrace {
  id: string; provider: string; model: string; outcome: "proposal_created" | "rejected" | "provider_error";
  errors: string[]; proposal_id: string | null; output: { title: string; rationale: string } | null; created_at: string;
}

export class ResearchApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) { super(message); }
}

type Fetch = typeof fetch;

export function apiBase(): string {
  const configured = (import.meta.env?.VITE_API_BASE_URL as string | undefined) ?? "";
  return configured.replace(/\/+$/, "");
}

export class ResearchApi {
  constructor(private readonly token: string | null, private readonly base = apiBase(),
              private readonly fetcher: Fetch = (...args) => fetch(...args)) {}

  async request<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
    const init: RequestInit = { method, headers: { Accept: "application/json", ...headers } };
    if (this.token) (init.headers as Record<string, string>).Authorization = `Bearer ${this.token}`;
    if (body !== undefined) {
      (init.headers as Record<string, string>)["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    let response: Response;
    try { response = await this.fetcher(this.base + path, init); }
    catch { throw new ResearchApiError(0, "transport_error", "The API could not be reached."); }
    const text = await response.text();
    let parsed: unknown = null;
    try { parsed = text ? JSON.parse(text) : null; } catch { /* non-JSON */ }
    if (!response.ok) {
      const error = (parsed as { error?: { code?: string; message?: string } } | null)?.error;
      throw new ResearchApiError(response.status, error?.code ?? "invalid_response",
        error?.message ?? "The API returned an unexpected response.");
    }
    return parsed as T;
  }

  readiness() { return this.request<Readiness>("GET", "/api/readiness"); }
  me() { return this.request<Me>("GET", "/api/v1/me"); }
  bootstrap(secret: string, body: { display_name: string; email: string; workspace_name: string; workspace_slug: string }) {
    return this.request<Bootstrapped>("POST", "/api/v1/bootstrap", body, { "X-Bootstrap-Token": secret });
  }
  projects(workspace: string) { return this.request<Project[]>("GET", `/api/v1/workspaces/${workspace}/projects`); }
  createProject(workspace: string, body: { name: string; slug: string; program: Program; objective: string }) {
    return this.request<Project>("POST", `/api/v1/workspaces/${workspace}/projects`, body);
  }
  updateProject(workspace: string, id: string, body: Partial<Pick<Project, "name" | "status" | "objective">>) {
    return this.request<Project>("PATCH", `/api/v1/workspaces/${workspace}/projects/${id}`, body);
  }
  claims(workspace: string) { return this.request<Claim[]>("GET", `/api/v1/workspaces/${workspace}/claims`); }
  runs(workspace: string, project: string) { return this.request<Run[]>("GET", `/api/v1/workspaces/${workspace}/projects/${project}/runs`); }
  simulate(workspace: string, project: string, design: SimulationDesign) {
    return this.request<Run>("POST", `/api/v1/workspaces/${workspace}/projects/${project}/simulated-runs`, design);
  }
  milestone(workspace: string, project: string) {
    return this.request<Milestone>("GET", `/api/v1/workspaces/${workspace}/projects/${project}/digital-milestone`);
  }
  planNext(workspace: string, project: string) {
    return this.request<AgentTrace>("POST", `/api/v1/workspaces/${workspace}/projects/${project}/agent/plan`);
  }
  executeProposal(workspace: string, project: string, proposal: string) {
    return this.request<unknown>("POST", `/api/v1/workspaces/${workspace}/projects/${project}/proposals/${proposal}/execute`);
  }
  decisions(workspace: string) { return this.request<PolicyDecision[]>("GET", `/api/v1/workspaces/${workspace}/policy/decisions`); }
}

export function slugify(name: string): string {
  return name.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64);
}

export const programLabels: Record<Program, string> = {
  M1: "Yeast biomass (M1)", M2: "Yeast extract (M2)", A1: "Avocado (A1)", OTHER: "Other research",
};

export function portfolioStats(projects: Project[]) {
  const byProgram = { M1: 0, M2: 0, A1: 0, OTHER: 0 } as Record<Program, number>;
  let active = 0;
  for (const project of projects) {
    byProgram[project.program] += 1;
    if (project.status === "active") active += 1;
  }
  return { total: projects.length, active, byProgram };
}

export const defaultDesign: SimulationDesign = {
  label: "Run 1", temperature_c: 30, ph: 5, initial_glucose_g_l: 20, duration_h: 24,
  sample_interval_h: 2, biological_replicates: 3, technical_replicates: 1, seed: 1,
};

export function validateDesign(design: SimulationDesign): string | null {
  if (!design.label.trim()) return "Give the run a label.";
  if (design.temperature_c < 4 || design.temperature_c > 45) return "Temperature must be 4–45 °C.";
  if (design.ph < 3 || design.ph > 8) return "pH must be 3–8.";
  if (design.initial_glucose_g_l <= 0 || design.initial_glucose_g_l > 150) return "Glucose must be 0–150 g/L.";
  if (design.duration_h <= 0 || design.duration_h > 96) return "Duration must be up to 96 h.";
  return null;
}
