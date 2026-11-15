import { describe, expect, it } from "vitest";
import { ResearchApi, ResearchApiError, portfolioStats, slugify, type Project } from "./research-api";

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("research API client", () => {
  it("sends bearer tokens and JSON bodies to the configured base", async () => {
    const calls: [string, RequestInit][] = [];
    const api = new ResearchApi("ua_secret", "https://api.example", async (url, init) => {
      calls.push([String(url), init ?? {}]);
      return respond({ id: "p1" }, 201);
    });
    await api.createProject("w1", { name: "Biomass", slug: "biomass", program: "M1", objective: "" });
    const [url, init] = calls[0];
    expect(url).toBe("https://api.example/api/v1/workspaces/w1/projects");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer ua_secret");
    expect(JSON.parse(String(init.body)).program).toBe("M1");
  });

  it("surfaces server error envelopes as typed errors", async () => {
    const api = new ResearchApi(null, "", async () => respond({ schema_version: "1.0", error: { code: "policy_denied", message: "Denied by policy: role_not_permitted." } }, 403));
    await expect(api.me()).rejects.toMatchObject({ status: 403, code: "policy_denied" });
  });

  it("maps network failures and non-JSON responses", async () => {
    const down = new ResearchApi(null, "", async () => { throw new TypeError("offline"); });
    await expect(down.readiness()).rejects.toBeInstanceOf(ResearchApiError);
    const html = new ResearchApi(null, "", async () => new Response("<html>", { status: 502 }));
    await expect(html.readiness()).rejects.toMatchObject({ status: 502, code: "invalid_response" });
  });

  it("sends the bootstrap secret only as a header", async () => {
    let headers: Record<string, string> = {};
    const api = new ResearchApi(null, "", async (_url, init) => { headers = init?.headers as Record<string, string>; return respond({}, 201); });
    await api.bootstrap("s".repeat(40), { display_name: "O", email: "o@example.test", workspace_name: "Lab", workspace_slug: "lab" });
    expect(headers["X-Bootstrap-Token"]).toHaveLength(40);
    expect(headers.Authorization).toBeUndefined();
  });
});

describe("portfolio helpers", () => {
  it("slugifies names for API slugs", () => {
    expect(slugify("  Savory Yeast — Biomass #1 ")).toBe("savory-yeast-biomass-1");
  });
  it("counts projects per program and active status", () => {
    const base = { workspace_id: "w", slug: "s", name: "n", objective: "", created_at: "", updated_at: "" };
    const projects: Project[] = [
      { ...base, id: "1", program: "M1", status: "active" },
      { ...base, id: "2", program: "M1", status: "planning" },
      { ...base, id: "3", program: "A1", status: "active" },
    ];
    expect(portfolioStats(projects)).toEqual({ total: 3, active: 2, byProgram: { M1: 2, M2: 0, A1: 1, OTHER: 0 } });
  });
});
