import { useState } from "react";
import { type ResearchApi, type Run, type RunSeries, chartPaths } from "../research-api";
import { OriginBadge, ProjectPicker, message, useLoad } from "./common";

const QUANTITIES = [["biomass_concentration", "Biomass (DCW)"], ["substrate_concentration", "Residual glucose"],
  ["glutamate_concentration", "Free glutamate"]] as const;
const COLORS = ["#a3eeab", "#7fa7e0", "#e0b97f", "#e07fb0", "#b39ddb", "#80cbc4"];

type Normalization = { biomass_yield_g_g: number | null; specific_growth_rate_per_h: number | null; biomass_final_g_l: number | null };

export function ResultsView({ api, workspaceId }: { api: ResearchApi; workspaceId: string }) {
  const [projectId, setProjectId] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [quantity, setQuantity] = useState<string>(QUANTITIES[0][0]);
  const [status, setStatus] = useState<string | null>(null);
  const base = `/api/v1/workspaces/${workspaceId}/projects/${projectId}`;
  const query = chosen.map(id => `run_ids=${id}`).join("&");
  const runs = useLoad<Run[]>(() => projectId ? api.runs(workspaceId, projectId) : Promise.resolve([]), [api, workspaceId, projectId]);
  const series = useLoad<RunSeries[]>(() => chosen.length ? api.get(`${base}/results/series?quantity_kind=${quantity}&${query}`) : Promise.resolve([]), [api, base, quantity, query]);
  const compare = useLoad<{ run: Run; normalization: Normalization }[]>(() => chosen.length ? api.get(`${base}/results/compare?${query}`) : Promise.resolve([]), [api, base, query]);
  const toggle = (id: string) => setChosen(c => c.includes(id) ? c.filter(x => x !== id) : [...c, id].slice(-6));
  const exportFile = async (path: string, name: string) => {
    try {
      const { blob, sha256 } = await api.download(`${base}/exports/${path}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url);
      setStatus(`Downloaded ${name} (sha256 ${sha256?.slice(0, 12)}…)`);
    } catch (err) { setStatus(message(err)); }
  };
  const width = 640, height = 300;
  const chart = chartPaths(series.data ?? [], width, height);
  return <section>
    <ProjectPicker api={api} workspaceId={workspaceId} value={projectId} onChange={id => { setProjectId(id); setChosen([]); }} />
    <div className="panels">
      <div className="panel">
        <h2>Completed runs</h2>
        {runs.data?.filter(r => r.state === "completed").map(r => <label key={r.id} className="inline">
          <input type="checkbox" checked={chosen.includes(r.id)} onChange={() => toggle(r.id)} /> {r.label} <OriginBadge origin={r.origin} />
        </label>)}
        {runs.data?.length === 0 && <p>No runs yet.</p>}
        <h2>Exports</h2>
        <p>Every row keeps its SIMULATED/PHYSICAL origin. Each download reports its SHA-256.</p>
        <button className="ghost" onClick={() => exportFile("measurements.csv", "measurements.csv")}>Measurements CSV</button>{" "}
        <button className="ghost" onClick={() => exportFile("dataset.json", "dataset.json")}>Dataset JSON</button>
        {status && <p>{status}</p>}
      </div>
      <div className="panel">
        <h2>Time course</h2>
        <label>Quantity<select value={quantity} onChange={e => setQuantity(e.target.value)}>
          {QUANTITIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        {chosen.length === 0 ? <p>Select runs to compare.</p> :
          <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Time-course chart" className="chart">
            <line x1="32" y1={height - 32} x2={width - 32} y2={height - 32} className="axis" />
            <line x1="32" y1="32" x2="32" y2={height - 32} className="axis" />
            <text x={width - 32} y={height - 10} textAnchor="end" className="tick">{chart.maxT} h</text>
            <text x="36" y="26" className="tick">{chart.maxY.toFixed(2)} {series.data?.[0]?.unit}</text>
            {chart.paths.map((d, i) => <polyline key={i} points={d} fill="none" stroke={COLORS[i % COLORS.length]} strokeWidth="2.5" />)}
          </svg>}
        <ul className="legend">{series.data?.map((s, i) => <li key={s.run_id}><span style={{ background: COLORS[i % COLORS.length] }} />{s.label} ({s.origin})</li>)}</ul>
      </div>
    </div>
    {compare.data && compare.data.length > 0 && <div className="panel">
      <h2>Comparison</h2>
      <table><thead><tr><th>Run</th><th>T (°C)</th><th>pH</th><th>Final biomass (g/L)</th><th>Yield (g/g)</th><th>µmax (1/h)</th></tr></thead>
        <tbody>{compare.data.map(c => <tr key={c.run.id}><td>{c.run.label} <OriginBadge origin={c.run.origin} /></td>
          <td>{c.run.design.temperature_c}</td><td>{c.run.design.ph}</td>
          <td>{c.normalization.biomass_final_g_l?.toFixed(2) ?? "—"}</td><td>{c.normalization.biomass_yield_g_g?.toFixed(3) ?? "—"}</td>
          <td>{c.normalization.specific_growth_rate_per_h?.toFixed(3) ?? "—"}</td></tr>)}</tbody></table>
    </div>}
  </section>;
}
