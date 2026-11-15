import { useCallback, useEffect, useState } from "react";
import { type Project, type ResearchApi, ResearchApiError } from "../research-api";

export function message(error: unknown) {
  return error instanceof ResearchApiError ? `${error.message} (${error.code})` : "Something went wrong.";
}

export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => { load().then(d => { setData(d); setError(null); }).catch(e => setError(message(e))); }, deps);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, reload, setError };
}

export function ProjectPicker({ api, workspaceId, value, onChange }: { api: ResearchApi; workspaceId: string; value: string; onChange: (id: string) => void }) {
  const { data } = useLoad<Project[]>(() => api.projects(workspaceId), [api, workspaceId]);
  useEffect(() => { if (!value && data?.[0]) onChange(data[0].id); }, [data, value, onChange]);
  if (!data) return null;
  if (data.length === 0) return <p>Create a project first.</p>;
  return <label>Project<select value={value} onChange={e => onChange(e.target.value)}>
    {data.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>;
}

export function OriginBadge({ origin }: { origin: string }) {
  return <span className={`badge origin-${origin.toLowerCase()}`}>{origin}</span>;
}

export function when(iso: string) {
  return new Date(iso).toLocaleString();
}
