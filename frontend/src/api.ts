// 轻量 API 封装。开发环境走 vite 代理（/api），生产走 nginx 同源反代。
const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  listBatches: () => request<import("./types").Batch[]>("/batches"),
  createBatch: (name: string) =>
    request("/batches", { method: "POST", body: JSON.stringify({ name }) }),
  listWafers: (batchId: number) =>
    request<import("./types").Wafer[]>(`/batches/${batchId}/wafers`),
  createWafer: (body: {
    batch_id: number;
    name: string;
    die_cols: number;
    die_rows: number;
  }) => request("/wafers", { method: "POST", body: JSON.stringify(body) }),

  uploadChunk: (body: unknown) =>
    request<{ accepted: number; rejected: number; total: number }>("/chunks", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  waferMap: (waferId: number) =>
    request<import("./types").WaferMap>(`/wafers/${waferId}/map`),
  dieDetail: (waferId: number, x: number, y: number) =>
    request<import("./types").DieDetailResponse>(
      `/wafers/${waferId}/dies/${x}/${y}`,
    ),

  startJob: (waferId: number) =>
    request<import("./types").Job>(`/wafers/${waferId}/jobs`, { method: "POST" }),
  getJob: (jobId: number) => request<import("./types").Job>(`/jobs/${jobId}`),
  listJobs: (waferId: number) =>
    request<import("./types").Job[]>(`/wafers/${waferId}/jobs`),
  cancelJob: (jobId: number) =>
    request<import("./types").Job>(`/jobs/${jobId}/cancel`, { method: "POST" }),

  listRules: () =>
    request<import("./types").RuleVersion[]>("/rule-versions"),
  createRule: (rules: import("./types").RuleItem[], note: string) =>
    request("/rule-versions", {
      method: "POST",
      body: JSON.stringify({ rules, note, activate: true }),
    }),
  activateRule: (id: number) =>
    request(`/rule-versions/${id}/activate`, { method: "POST" }),
  ruleDiff: (waferId: number, from: number, to: number) =>
    request<import("./types").GradeDiff>(
      `/wafers/${waferId}/rule-diff/${from}/${to}`,
    ),
};
