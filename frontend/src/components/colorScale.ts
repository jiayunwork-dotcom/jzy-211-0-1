import type { DieResult } from "../types";

export type ColorParam = "is" | "n" | "rs" | "grade";

// 从蓝（低）到红（高）的简单渐变，按分位裁剪
function lerp(a: number, b: number, t: number) {
  return Math.round(a + (b - a) * t);
}
function ramp(t: number): string {
  // 蓝 -> 青 -> 黄 -> 红
  const stops: [number, [number, number, number]][] = [
    [0.0, [37, 99, 235]],
    [0.4, [16, 185, 129]],
    [0.7, [245, 197, 66]],
    [1.0, [220, 38, 38]],
  ];
  const tt = Math.min(1, Math.max(0, t));
  for (let i = 1; i < stops.length; i++) {
    const [p0, c0] = stops[i - 1];
    const [p1, c1] = stops[i];
    if (tt <= p1) {
      const k = (tt - p0) / (p1 - p0);
      return `rgb(${lerp(c0[0], c1[0], k)},${lerp(c0[1], c1[1], k)},${lerp(
        c0[2],
        c1[2],
        k,
      )})`;
    }
  }
  return "rgb(220,38,38)";
}

function quantile(sorted: number[], q: number): number {
  if (!sorted.length) return 0;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  if (lo === hi) return sorted[lo];
  return sorted[lo] * (hi - pos) + sorted[hi] * (pos - lo);
}

export function colorScale(
  dies: DieResult[],
  param: ColorParam,
): (d: DieResult) => string {
  if (param === "grade") {
    return (d) =>
      d.grade === "pass"
        ? "#16a34a"
        : d.grade === "fail"
          ? "#dc2626"
          : "#9ca3af";
  }
  const vals = dies
    .filter((d) => d.fit_ok && d[`${param}_value`] != null)
    .map((d) => d[`${param}_value`] as number);
  if (param === "is") vals.forEach((_, i) => (vals[i] = Math.log10(vals[i])));
  vals.sort((a, b) => a - b);
  const lo = quantile(vals, 0.05);
  const hi = quantile(vals, 0.95);
  const span = hi - lo || 1;
  return (d) => {
    let v = d[`${param}_value`];
    if (v == null) return "#e5e7eb";
    if (param === "is") v = Math.log10(v);
    return ramp((v - lo) / span);
  };
}

export function fmt(v: number | null | undefined, digits = 4): string {
  if (v == null) return "—";
  if (v === 0) return "0";
  const abs = Math.abs(v);
  if (abs < 1e-3 || abs >= 1e5) return v.toExponential(2);
  return v.toPrecision(digits);
}
