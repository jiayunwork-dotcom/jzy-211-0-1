import { useNavigate } from "react-router-dom";
import type { WaferMap as WaferMapData } from "../types";
import { colorScale, type ColorParam } from "./colorScale";

interface Props {
  data: WaferMapData;
  param: ColorParam;
}

// 失败管芯用 ✕ 叠加标识；只有拒收扫描的格子画成黑色
export default function WaferMapGrid({ data, param }: Props) {
  const navigate = useNavigate();
  const { die_cols, die_rows } = data.wafer;
  const colorOf = colorScale(data.dies, param);
  const byCoord = new Map(data.dies.map((d) => [`${d.die_x},${d.die_y}`, d]));
  const rejectedSet = new Set(data.rejected.map((r) => `${r.die_x},${r.die_y}`));

  const cells = [];
  for (let y = 0; y < die_rows; y++) {
    for (let x = 0; x < die_cols; x++) {
      const key = `${x},${y}`;
      const die = byCoord.get(key);
      const rejected = rejectedSet.has(key);
      const title = rejected
        ? `(${x},${y}) 拒收：${
            data.rejected.find((r) => r.die_x === x && r.die_y === y)?.reason
          }`
        : die
          ? `(${x},${y}) n=${die.n_value?.toFixed(3)} grade=${die.grade}`
          : `(${x},${y}) 无数据`;
      cells.push(
        <div
          key={key}
          className={
            "die" +
            (rejected ? " rejected" : "") +
            (die && !die.fit_ok ? " fit-fail" : "")
          }
          style={{ background: rejected ? undefined : die ? colorOf(die) : "#eef0f3" }}
          title={title}
          onClick={() => die && navigate(`/wafers/${data.wafer.id}/dies/${x}/${y}`)}
        />,
      );
    }
  }

  return (
    <div
      className="wafermap"
      style={{
        gridTemplateColumns: `repeat(${die_cols}, 30px)`,
        gridTemplateRows: `repeat(${die_rows}, 30px)`,
      }}
    >
      {cells}
    </div>
  );
}
