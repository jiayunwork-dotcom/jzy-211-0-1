import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { DieDetailResponse } from "../types";
import FitPlot from "../components/FitPlot";
import { fmt } from "../components/colorScale";

export default function DieDetailPage() {
  const { waferId, x, y } = useParams();
  const wid = Number(waferId);
  const dx = Number(x);
  const dy = Number(y);
  const [d, setD] = useState<DieDetailResponse | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .dieDetail(wid, dx, dy)
      .then(setD)
      .catch((e) => setErr(e.message));
  }, [wid, dx, dy]);

  if (err) return <p className="error">{err}</p>;
  if (!d) return <p>加载中…</p>;

  const die = d.die;
  const residAbs = d.point_residual.map((v) => Math.abs(v));
  const maxResid = residAbs.length ? Math.max(...residAbs) : 0;

  return (
    <div>
      <h2>
        管芯 ({dx}, {dy}){" "}
        <Link to={`/wafers/${wid}`} className="muted" style={{ fontSize: 13 }}>
          ← 晶圆图
        </Link>
      </h2>

      <div className="panel">
        <div className="row">
          <span className={`badge ${die.grade}`}>{die.grade}</span>
          {die.fit_ok ? (
            <span className="badge pass">提取成功</span>
          ) : (
            <span className="badge fail">提取失败</span>
          )}
          {!die.rs_reliable && die.fit_ok && (
            <span className="muted">
              ⚠ 串联电阻在本扫描电压范围内不可辨识（Rs 仅供参考）
            </span>
          )}
          <span className="muted">测试温度 {d.temp_k.toFixed(1)} K</span>
          <span className="muted">
            测试时间 {new Date(d.tested_at).toLocaleString()}
          </span>
        </div>
        <table style={{ marginTop: 10 }}>
          <tbody>
            <tr>
              <th>饱和电流 Is</th>
              <td>{fmt(die.is_value)} A</td>
              <th>理想因子 n</th>
              <td>{fmt(die.n_value)}</td>
            </tr>
            <tr>
              <th>串联电阻 Rs</th>
              <td>{die.rs_value == null ? "—" : `${fmt(die.rs_value)} Ω`}</td>
              <th>拟合残差 (log10 I RMSE)</th>
              <td>{die.residual == null ? "—" : `${die.residual.toFixed(4)} decade`}</td>
            </tr>
            <tr>
              <th>扫描点数 / 参与拟合</th>
              <td>{die.n_points} / {die.n_used}</td>
              <th>失败/拒收原因</th>
              <td className="error">{die.fail_reason ?? d.reject_reason ?? "—"}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>I–V 拟合</h3>
        {die.fit_ok ? (
          <>
            <FitPlot
              measured={{ x: d.voltage, y: d.current }}
              fit={{ x: d.fit_voltage, y: d.fit_current }}
              usedMask={d.used_mask}
            />
            <p className="muted" style={{ margin: 0 }}>
              红点＝参与拟合的测量点，空心灰点＝低于底噪被剔除；蓝线＝拟合曲线。
            </p>
            <h3>逐点残差（log10 I拟合 − log10 I测量）</h3>
            <FitPlot
              measured={{ x: d.voltage, y: d.point_residual }}
              yLog={false}
              height={160}
              zeroLine
              yLabel="残差 (decade)"
            />
            <p className="muted" style={{ margin: 0 }}>
              最大绝对残差 {maxResid.toFixed(3)} decade；
              RMSE {die.residual?.toFixed(4)}（超 0.10 判提取失败）。
            </p>
          </>
        ) : (
          <p className="error">该管芯未通过提取：{die.fail_reason}</p>
        )}
      </div>
    </div>
  );
}
