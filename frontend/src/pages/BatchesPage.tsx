import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Batch } from "../types";

export default function BatchesPage() {
  const [batches, setBatches] = useState<Batch[]>([]);
  const [name, setName] = useState("");
  const [err, setErr] = useState("");

  async function load() {
    setBatches(await api.listBatches());
  }
  useEffect(() => {
    load().catch((e) => setErr(e.message));
  }, []);

  async function create() {
    if (!name.trim()) return;
    try {
      await api.createBatch(name.trim());
      setName("");
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <div>
      <h2>批次</h2>
      {err && <p className="error">{err}</p>}
      <div className="panel">
        <div className="row">
          <input
            placeholder="新批次名称"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button onClick={create}>新建批次</button>
        </div>
      </div>
      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>批次</th>
              <th>创建时间</th>
              <th>晶圆数</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {batches.map((b) => (
              <tr key={b.id}>
                <td>{b.name}</td>
                <td className="muted">{new Date(b.created_at).toLocaleString()}</td>
                <td>{b.n_wafers}</td>
                <td>
                  <Link to={`/batches/${b.id}`}>查看晶圆 →</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
