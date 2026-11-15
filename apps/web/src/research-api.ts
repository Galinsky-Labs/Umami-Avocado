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
