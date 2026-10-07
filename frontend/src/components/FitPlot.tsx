interface PointSet {
  x: number[];
  y: number[];
}

interface Props {
  measured: PointSet;
  fit?: PointSet;
  usedMask?: boolean[];
  yLog?: boolean;
  height?: number;
  zeroLine?: boolean;
  xLabel?: string;
  yLabel?: string;
}

// 极简 SVG 散点/折线图（电流轴默认对数）
export default function FitPlot({
  measured,
  fit,
  usedMask,
  yLog = true,
  height = 320,
  zeroLine = false,
  xLabel = "电压 V (V)",
  yLabel = "电流 I (A)",
}: Props) {
  const W = 720;
  const H = height;
  const padL = 78;
  const padR = 18;
  const padT = 16;
  const padB = 42;

  const allY = [
    ...measured.y,
    ...(fit ? fit.y : []),
  ].filter((v) => Number.isFinite(v));
  const allX = [...measured.x, ...(fit ? fit.x : [])];
  const xMin = Math.min(...allX);
  const xMax = Math.max(...allX);

  let yMin: number;
  let yMax: number;
  if (yLog) {
    const pos = allY.filter((v) => v > 0);
    yMin = Math.log10(Math.min(...pos));
    yMax = Math.log10(Math.max(...pos));
  } else {
    yMin = Math.min(...allY, zeroLine ? 0 : Infinity);
    yMax = Math.max(...allY);
  }
  if (yMin === yMax) yMax = yMin + 1;

  const X = (v: number) =>
    padL + ((v - xMin) / (xMax - xMin || 1)) * (W - padL - padR);
  const Y = (v: number) => {
    const t = yLog
      ? (Math.log10(Math.max(v, 1e-18)) - yMin) / (yMax - yMin)
      : (v - yMin) / (yMax - yMin || 1);
    return padT + (1 - t) * (H - padT - padB);
  };

  const ticks = 4;
  const yTickVals = Array.from({ length: ticks + 1 }, (_, i) =>
    yMin + ((yMax - yMin) * i) / ticks,
  );

  const fitPath = fit
    ? fit.x
        .map((xv, i) => `${i === 0 ? "M" : "L"}${X(xv).toFixed(1)},${Y(fit.y[i]).toFixed(1)}`)
        .join(" ")
    : "";

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={height < 200 ? "resid-plot" : "fit-plot"}>
      {/* 坐标框与网格 */}
      {yTickVals.map((tv, i) => {
        const yy = Y(yLog ? 10 ** tv : tv);
        return (
          <g key={i}>
            <line x1={padL} x2={W - padR} y1={yy} y2={yy} stroke="#eef0f3" />
            <text x={padL - 6} y={yy + 4} textAnchor="end" fontSize="11" fill="#6b7280">
              {yLog ? `1e${tv.toFixed(1)}` : tv.toFixed(2)}
            </text>
          </g>
        );
      })}
      <line x1={padL} x2={padL} y1={padT} y2={H - padB} stroke="#9ca3af" />
      <line x1={padL} x2={W - padR} y1={H - padB} y2={H - padB} stroke="#9ca3af" />
      <text x={W / 2} y={H - 10} textAnchor="middle" fontSize="12" fill="#374151">
        {xLabel}
      </text>
      <text
        x={16}
        y={H / 2}
        textAnchor="middle"
        fontSize="12"
        fill="#374151"
        transform={`rotate(-90 16 ${H / 2})`}
      >
        {yLabel}
      </text>

      {/* 拟合曲线 */}
      {fit && <path d={fitPath} fill="none" stroke="#2563eb" strokeWidth="2" />}

      {/* 测量点；被底噪剔除的点画空心灰点 */}
      {measured.x.map((xv, i) => {
        const used = usedMask ? usedMask[i] : true;
        return (
          <circle
            key={i}
            cx={X(xv)}
            cy={Y(measured.y[i])}
            r={used ? 3 : 2.5}
                fill={used ? "#dc2626" : "none"}
                stroke={used ? "#dc2626" : "#9ca3af"}
                fillOpacity={used ? 0.75 : 0}
          />
        );
      })}

      {zeroLine && (
        <line
          x1={padL}
          x2={W - padR}
          y1={Y(0)}
          y2={Y(0)}
          stroke="#9ca3af"
          strokeDasharray="4 3"
        />
      )}
    </svg>
  );
}
