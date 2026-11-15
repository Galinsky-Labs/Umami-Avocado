import { useState } from "react";
import { type ExceptionItem, type ResearchApi, type Run, type TimelineEvent } from "../research-api";
import { OriginBadge, ProjectPicker, useLoad, when } from "./common";

export function RunsView({ api, workspaceId }: { api: ResearchApi; workspaceId: string }) {
  const [projectId, setProjectId] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const runs = useLoad<Run[]>(() => projectId ? api.runs(workspaceId, projectId) : Promise.resolve([]), [api, workspaceId, projectId]);
  const timeline = useLoad<{ run: Run; events: TimelineEvent[] } | null>(
    () => selected && projectId ? api.timeline(workspaceId, projectId, selected) : Promise.resolve(null), [api, workspaceId, projectId, selected]);
  return <section>
    <ProjectPicker api={api} workspaceId={workspaceId} value={projectId} onChange={id => { setProjectId(id); setSelected(null); }} />
    <div className="panels">
      <div className="panel">
        <h2>Runs</h2>
        {runs.error && <p className="error">{runs.error}</p>}
        {runs.data?.length === 0 && <p>No runs yet.</p>}
        <ul className="list">{runs.data?.map(r => <li key={r.id}>
          <button className={selected === r.id ? "linkish active" : "linkish"} onClick={() => setSelected(r.id)}>
            {r.label}</button> <OriginBadge origin={r.origin} /> <span className={`state ${r.state}`}>{r.state}</span>
        </li>)}</ul>
      </div>
      <div className="panel">
        <h2>Timeline</h2>
        {!selected ? <p>Select a run.</p> : timeline.data && <ol className="timeline">
          {timeline.data.events.map((e, i) => <li key={i} className={e.severity}>
            <time>{when(e.at)}</time> <strong>{e.title}</strong>{e.detail && <span className="detail"> — {e.detail}</span>}
          </li>)}
        </ol>}
      </div>
    </div>
  </section>;
}

export function ExceptionsView({ api, workspaceId }: { api: ResearchApi; workspaceId: string }) {
  const { data, error, reload } = useLoad<ExceptionItem[]>(() => api.exceptions(workspaceId), [api, workspaceId]);
  return <section className="panel">
    <h2>Exception center</h2>
    <p>Failures and items waiting for a human decision. Nothing here can trigger physical work.</p>
    <button className="ghost" onClick={reload}>Refresh</button>
    {error && <p className="error">{error}</p>}
    {data?.length === 0 && <p>All clear.</p>}
    {data && data.length > 0 && <table>
      <thead><tr><th>Severity</th><th>Item</th><th>Detail</th><th>When</th></tr></thead>
      <tbody>{data.map(x => <tr key={x.kind + x.ref}><td><span className={`badge ${x.severity}`}>{x.severity}</span></td>
        <td>{x.title}<br /><code>{x.kind}</code></td><td>{x.detail}</td><td>{when(x.at)}</td></tr>)}</tbody>
    </table>}
  </section>;
}
