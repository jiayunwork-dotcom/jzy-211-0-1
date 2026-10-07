import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { Job } from "../types";

// 既支持 /jobs（需选择晶圆）也支持 /jobs/:waferId
export default function JobsPage() {
  const { waferId } = useParams();
  const [waferInput, setWaferInput] = useState(waferId ?? "");
  const wid = Number(waferId || waferInput);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    if (!wid) return;
    try {
      setJobs(await api.listJobs(wid));
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [wid]);

  useEffect(() => {
    load();
    const t = setInterval(load, 1500); // 轮询进度
    return () => clearInterval(t);
  }, [load]);

  async function start() {
    try {
      await api.startJob(wid);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function cancel(id: number) {
    await api.cancelJob(id);
    await load();
  }

  const active = jobs.some(
    (j) => j.state === "running" || j.state === "pending",
  );

  return (
    <div>
      <h2>处理作业</h2>
      {err && <p className="error">{err}</p>}
      <div className="panel">
        <div className="row">
          <label>
            晶圆 ID{" "}
            <input
              type="number"
              value={waferId ? wid : waferInput}
              disabled={!!waferId}
              onChange={(e) => setWaferInput(e.target.value)}
              style={{ width: 90 }}
            />
          </label>
          <button onClick={start} disabled={!wid}>发起作业</button>
          <Link to="/batches">从批次列表选择</Link>
        </div>
      </div>

      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>作业</th><th>状态</th><th>进度</th><th>拟合失败</th>
              <th>规则版本</th><th>错误</th><th></th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => {
              const isActive = j.state === "running" || j.state === "pending";
              const pct = j.total ? Math.round((j.processed / j.total) * 100) : 0;
              return (
                <tr key={j.id}>
                  <td>#{j.id}</td>
                  <td><span className={`badge ${j.state}`}>{j.state}</span></td>
                  <td style={{ minWidth: 160 }}>
                    {j.processed}/{j.total}
                    {isActive && (
                      <div style={{
                        background: "#e5e7eb", borderRadius: 4, height: 6,
                        width: 120, marginTop: 3,
                      }}>
                        <div style={{
                          background: "#2563eb", height: "100%",
                          width: `${pct}%`, borderRadius: 4,
                        }} />
                      </div>
                    )}
                  </td>
                  <td>{j.n_failed}</td>
                  <td>#{j.rule_version_id ?? "—"}</td>
                  <td className="error">{j.error ?? ""}</td>
                  <td>
                    {isActive && (
                      <button className="secondary" onClick={() => cancel(j.id)}>
                        取消
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {jobs.length === 0 && (
              <tr><td colSpan={7} className="muted">该晶圆暂无作业</td></tr>
            )}
          </tbody>
        </table>
        <p className="muted" style={{ marginBottom: 0 }}>
          取消在管芯边界生效；未落库的整批计算结果丢弃，不会留下半截晶圆图。
        </p>
      </div>
    </div>
  );
}
