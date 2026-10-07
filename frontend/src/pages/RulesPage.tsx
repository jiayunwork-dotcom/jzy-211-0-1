import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { GradeDiff, RuleItem, RuleVersion } from "../types";

const PARAMS: { key: RuleItem["param"]; label: string }[] = [
  { key: "is", label: "Is 下限/上限 (A)" },
  { key: "n", label: "n 下限/上限" },
  { key: "rs", label: "Rs 下限/上限 (Ω)" },
];

export default function RulesPage() {
  const { waferId } = useParams();
  const wid = waferId ? Number(waferId) : null;
  const [rules, setRules] = useState<RuleVersion[]>([]);
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [diff, setDiff] = useState<GradeDiff | null>(null);
  const [form, setForm] = useState<Record<string, string>>({
    is_lo: "1e-16", is_hi: "1e-9",
    n_lo: "0.9", n_hi: "1.5",
    rs_lo: "0", rs_hi: "100",
  });
  const [failIsBad, setFailIsBad] = useState(false);
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");

  async function load() {
    setRules(await api.listRules());
  }
  useEffect(() => {
    load().catch((e) => setErr(e.message));
  }, []);

  async function publish() {
    setErr("");
    setOk("");
    try {
      const items: RuleItem[] = PARAMS.map(({ key }) => ({
        param: key,
        lower: Number(form[`${key}_lo`]),
        upper: Number(form[`${key}_hi`]),
        fail_is_bad: failIsBad,
      }));
      await api.createRule(items, note);
      setNote("");
      setOk("新版本已发布，并对已有结果重新判级（未重新拟合）");
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function activate(id: number) {
    setErr("");
    try {
      await api.activateRule(id);
      setOk(`版本 #${id} 已激活，已有结果已按其重新判级`);
      await load();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  async function compare() {
    if (wid == null || from == null || to == null) return;
    setDiff(await api.ruleDiff(wid, from, to));
  }

  return (
    <div>
      <h2>判级规则版本</h2>
      {err && <p className="error">{err}</p>}
      {ok && <p style={{ color: "#16a34a" }}>{ok}</p>}

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>发布新版本</h3>
        <table>
          <tbody>
            {PARAMS.map(({ key, label }) => (
              <tr key={key}>
                <th style={{ width: 200 }}>{label}</th>
                <td>
                  <input
                    style={{ width: 110 }}
                    value={form[`${key}_lo`]}
                    onChange={(e) => setForm({ ...form, [`${key}_lo`]: e.target.value })}
                  />
                  {" ~ "}
                  <input
                    style={{ width: 110 }}
                    value={form[`${key}_hi`]}
                    onChange={(e) => setForm({ ...form, [`${key}_hi`]: e.target.value })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="row" style={{ marginTop: 10 }}>
          <label>
            <input
              type="checkbox"
              checked={failIsBad}
              onChange={(e) => setFailIsBad(e.target.checked)}
            />{" "}
            提取失败算不良
          </label>
          <input
            placeholder="版本备注"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <button onClick={publish}>发布并激活</button>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>
          上限小于下限等非法规则会被拒收。发布后已有结果只重判级，参数与拟合不变。
        </p>
      </div>

      <div className="panel">
        <table>
          <thead>
            <tr>
              <th>版本</th><th>状态</th><th>规则</th><th>备注</th><th>发布时间</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.id}>
                <td>v{r.version} (#{r.id})</td>
                <td>{r.is_active ? <span className="badge pass">生效中</span> : "—"}</td>
                <td style={{ fontSize: 12 }}>
                  {r.rules.map((it) => (
                    <div key={it.param}>
                      {it.param} ∈ [{it.lower.toExponential(2)}, {it.upper.toExponential(2)}]
                      {it.fail_is_bad ? "（失败算不良）" : ""}
                    </div>
                  ))}
                </td>
                <td>{r.note}</td>
                <td>{r.published_at ? new Date(r.published_at).toLocaleString() : "未发布"}</td>
                <td>
                  {!r.is_active && (
                    <button className="secondary" onClick={() => activate(r.id)}>
                      激活并重判
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {wid != null && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>
            晶圆 #{wid} 的版本对比{" "}
            <Link to={`/wafers/${wid}`} className="muted" style={{ fontSize: 13 }}>
              ← 晶圆图
            </Link>
          </h3>
          <div className="row">
            <select onChange={(e) => setFrom(Number(e.target.value))} defaultValue="">
              <option value="" disabled>旧版本</option>
              {rules.map((r) => <option key={r.id} value={r.id}>v{r.version}</option>)}
            </select>
            →
            <select onChange={(e) => setTo(Number(e.target.value))} defaultValue="">
              <option value="" disabled>新版本</option>
              {rules.map((r) => <option key={r.id} value={r.id}>v{r.version}</option>)}
            </select>
            <button onClick={compare} disabled={from == null || to == null}>
              对比等级变化
            </button>
          </div>
          {diff && (
            <div style={{ marginTop: 12 }}>
              <p>
                良率：
                {diff.summary_from.yield == null
                  ? "—"
                  : `${(diff.summary_from.yield * 100).toFixed(1)}%`}{" "}
                →{" "}
                <strong>
                  {diff.summary_to.yield == null
                    ? "—"
                    : `${(diff.summary_to.yield * 100).toFixed(1)}%`}
                </strong>
                ，{diff.changed.length} 颗等级变化：
              </p>
              {diff.changed.length === 0 && <p className="muted">无变化</p>}
              <table>
                <thead>
                  <tr><th>管芯</th><th>旧等级</th><th>新等级</th><th></th></tr>
                </thead>
                <tbody>
                  {diff.changed.map((c) => (
                    <tr key={`${c.die_x},${c.die_y}`}>
                      <td>({c.die_x}, {c.die_y})</td>
                      <td><span className={`badge ${c.grade_from}`}>{c.grade_from}</span></td>
                      <td><span className={`badge ${c.grade_to}`}>{c.grade_to}</span></td>
                      <td>
                        <Link to={`/wafers/${wid}/dies/${c.die_x}/${c.die_y}`}>
                          查看拟合
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
