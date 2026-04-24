const BASE = "/api/indexing";

async function get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== "" && v !== null) url.searchParams.set(k, String(v));
    }
  }
  const r = await fetch(url.toString());
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return (await r.json()) as T;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return (await r.json()) as T;
}

async function del<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path, { method: "DELETE" });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return (await r.json()) as T;
}

export type BackendName = "zoekt" | "dense" | "structural";

export interface Repo {
  id: number;
  repo_path: string;
  backend: BackendName;
  last_finished_at: string | null;
  last_duration_s: number | null;
  last_status: "success" | "fail" | "running" | "warn" | null;
  entity_count: number | null;
}

export interface Job {
  id: number;
  repo_id: number;
  repo_path: string;
  backend: BackendName;
  status: "queued" | "running" | "success" | "fail" | "warn";
  started_at: string | null;
  finished_at: string | null;
  duration_s: number | null;
  entity_count: number | null;
}

export interface LogPage {
  content: string;
  offset: number;
  next_offset: number;
  eof: boolean;
}

export interface ReposResponse {
  total: number;
  items: Repo[];
}

export interface RepoDetail {
  repo: Repo;
  jobs: Job[];
}

export const indexingApi = {
  listRepos: (filters?: { backend?: string; status?: string }) =>
    get<ReposResponse>("/repos", filters),

  getRepoDetail: (id: number) =>
    get<RepoDetail>(`/repos/${id}`),

  createJob: (repo_path: string, backend: BackendName) =>
    post<Job>("/jobs", { repo_path, backend }),

  deleteRepo: (id: number, backend: BackendName) =>
    del<{ ok: boolean }>(`/repos/${id}?backend=${encodeURIComponent(backend)}`),

  getJobLog: (jobId: number, offset = 0) =>
    get<LogPage>(`/jobs/${jobId}/log`, { offset }),
};
