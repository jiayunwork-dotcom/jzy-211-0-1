import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { Wafer } from "../types";

export default function WaferListPage() {
  const { batchId } = useParams();
  const id = Number(batchId);
  const [wafers, setWafers] = useState<Wafer[]>([]);
  const [form, setForm] = useState({ name: "", cols: "20", rows: "20" });
  const [err, setErr] = useState("");

  async function load() {
    setWafers(await api.listWafers(id));
  }
  useEffect(() => {
    load().catch((e) => setErr(e.message));
  }, [id]);

  async function create() {
    try {
      await api.createWafer({
        batch_id: id,
        name: form.name || `wafer-${wafers.length + 1}`,
        die_cols: Number(form.cols),
        die_rows: Number(form.rows),
      });
      setForm({ ...form, name: "" });
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <div>
      <h2>
        晶圆列表 <Link to="/batches" className="muted" style={{ fontSize: 13 }}>
          ← 返回批次
        </Link>
      </h2>
      {err && <p className="error">{err}</p>}
      <div className="panel">
        <div className="row">
          <input
            placeholder="晶圆名称"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <label>
            列 <input
              type="number" style={{ width: 70 }}
              value={form.cols}
              onChange={(e) => setForm({ ...form, cols: e.target.value })}
            />
          </label>
          <label>
            行 <input
              type="number" style={{ width: 70 }}
              value={form.rows}
              onChange={(e) => setForm({ ...form, rows: e.target.value })}
            />
          </label>
          <button onClick={create}>登记晶圆</button>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>
          坐标范围按行列定义：x ∈ [0, 列)，y ∈ [0, 行)，超界扫描将被拒收。
        </p>
      </div>

      <div className="panel">
        <table>
          <thead>
            <tr><th>晶圆</th><th>规模（列×行）</th><th></th></tr>
          </thead>
          <tbody>
            {wafers.map((w) => (
              <tr key={w.id}>
                <td>{w.name}</td>
                <td>{w.die_cols} × {w.die_rows}</td>
                <td>
                  <Link to={`/wafers/${w.id}`}>晶圆图</Link>
                  {" · "}
                  <Link to={`/jobs/${w.id}`}>作业</Link>
                  {" · "}
                  <Link to={`/rules/${w.id}`}>规则对比</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
