import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { Job, WaferMap } from "../types";
import WaferMapGrid from "../components/WaferMapGrid";
import { fmt, type ColorParam } from "../components/colorScale";

const PARAM_LABEL: Record<ColorParam, string> = {
  is: "饱和电流 Is",
  n: "理想因子 n",
  rs: "串联电阻 Rs",
  grade: "判级",
};

export default function WaferMapPage() {
  const { waferId } = useParams();
  const id = Number(waferId);
  const [data, setData] = useState<WaferMap | null>(null);
  const [param, setParam] = useState<ColorParam>("n");
  const [job, setJob] = useState<Job | null>(null);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const pollRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.waferMap(id));
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const pollJob = useCallback(
    async (jobId: number) => {
      const tick = async () => {
        const j = await api.getJob(jobId);
        setJob(j);
        if (j.state === "done" || j.state === "failed" || j.state === "cancelled") {
          pollRef.current = null;
          await load();
          return;
        }
        pollRef.current = window.setTimeout(tick, 700);
      };
      await tick();
    },
    [load],
  );

  useEffect(() => () => {
    if (pollRef.current) clearTimeout(pollRef.current);
  }, []);

  async function startJob() {
    setErr("");
    setMsg("");
    try {
      const j = await api.startJob(id);
      await pollJob(j.id);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function uploadText(ev: React.FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const ta = (ev.currentTarget.elements.namedItem("chunk") as HTMLTextAreaElement);
    try {
      const parsed = JSON.parse(ta.value);
      const body = Array.isArray(parsed)
        ? { wafer_id: id, scans: parsed }
        : { ...parsed, wafer_id: id };
      const r = await api.uploadChunk(body);
      setMsg(`块已接收：${r.accepted} 条有效，${r.rejected} 条拒收，共 ${r.total} 条`);
      ta.value = "";
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  const s = data?.summary;
  const hasSummary = s && "n_dies" in s && (s as any).n_dies > 0;

  return (
    <div>
      <h2>
        晶圆 #{id}{" "}
        <Link to="/batches" className="muted" style={{ fontSize: 13 }}>
          ← 批次
        </Link>
      </h2>
      {err && <p className="error">{err}</p>}
      {msg && <p style={{ color: "#16a34a" }}>{msg}</p>}

      <div className="panel">
        <div className="row">
          <button onClick={startJob}>发起整片处理作业</button>
          <Link to={`/jobs/${id}`}>查看作业列表</Link>
          {job && (
            <span>
              最近作业 <b>#{job.id}</b>{" "}
              <span className={`badge ${job.state}`}>{job.state}</span>{" "}
              {job.state === "running" || job.state === "pending"
                ? `${job.processed}/${job.total}`
                : ""}
            </span>
          )}
        </div>
      </div>

      <div className="panel">
        <div className="row">
          <strong>着色参数：</strong>
          <select value={param} onChange={(e) => setParam(e.target.value as ColorParam)}>
            {Object.entries(PARAM_LABEL).map(([k, label]) => (
              <option key={k} value={k}>{label}</option>
            ))}
          </select>
          <span className="muted">点击管芯查看拟合</span>
        </div>

        {data && <WaferMapGrid data={data} param={param} />}

        <div className="legend">
          {param === "grade" ? (
            <>
              <span><i className="swatch" style={{ background: "#16a34a" }} />pass</span>
              <span><i className="swatch" style={{ background: "#dc2626" }} />fail</span>
              <span><i className="swatch" style={{ background: "#9ca3af" }} />ungraded</span>
            </>
          ) : (
            <span className="muted">
              蓝=低（p5 截断），红=高（p95 截断）；Is 按 log10 着色
            </span>
          )}
          <span><i className="swatch" style={{ background: "#111827" }} />整颗拒收</span>
          <span><i className="swatch" style={{ background: "#ef4444" }} />✕ 提取失败</span>
          <span><i className="swatch" style={{ background: "#eef0f3" }} />无数据</span>
        </div>
      </div>

      {hasSummary && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>整片汇总</h3>
          <table>
            <thead>
              <tr>
                <th>参数</th><th>p5</th><th>中位数</th><th>p95</th><th>有效点数</th>
              </tr>
            </thead>
            <tbody>
              {(["is", "n", "rs"] as const).map((p) => (
                <tr key={p}>
                  <td>{PARAM_LABEL[p]}</td>
                  <td>{fmt((s as any).params[p].p05)}</td>
                  <td>{fmt((s as any).params[p].median)}</td>
                  <td>{fmt((s as any).params[p].p95)}</td>
                  <td>{(s as any).params[p].count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p style={{ marginBottom: 0 }}>
            管芯 {(s as any).n_dies} 颗　pass {(s as any).n_pass}　fail{" "}
            {(s as any).n_fail}　ungraded {(s as any).n_ungraded}
            提取失败 {(s as any).n_fit_failed} 颗
            <strong>
              良率{" "}
              {(s as any).yield == null
                ? "—"
                : `${((s as any).yield * 100).toFixed(1)}%`}
            </strong>
          </p>
        </div>
      )}

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>上传数据块</h3>
        <form onSubmit={uploadText}>
          <textarea
            name="chunk"
            rows={6}
            style={{ width: "100%", fontFamily: "monospace" }}
            placeholder='JSON 数组：[{"x":0,"y":0,"temp_k":300,"tested_at":"2026-10-01T12:00:00Z","voltage":[...],"current":[...]}]'
          />
          <div style={{ marginTop: 8 }}>
            <button type="submit">上传本块</button>
            <span className="muted" style={{ marginLeft: 10 }}>
              可多次、乱序上传；复测以 tested_at 较晚者为准
            </span>
          </div>
        </form>
      </div>
    </div>
  );
}
