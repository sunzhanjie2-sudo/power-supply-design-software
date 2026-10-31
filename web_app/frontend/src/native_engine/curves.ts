import { type Spec, clone } from "./spec";
export function candidates(filename: string, content: string) {
  if (content.length > 5 * 1024 * 1024) throw Error("曲线文件超过 5 MiB");
  let curves: Spec[] = [],
    simple = true;
  if (filename.toLowerCase().endsWith(".json")) {
    const raw = JSON.parse(content.replace(/^\ufeff/, ""));
    if (Array.isArray(raw)) curves = [{ name: filename, points: raw }];
    else if (raw.schema?.startsWith("power-design.")) {
      curves = [raw];
      simple = false;
    } else
      curves = raw.curves || [
        { name: raw.name || filename, points: raw.points },
      ];
  } else if (filename.toLowerCase().endsWith(".csv")) {
    const lines = content
        .replace(/^\ufeff/, "")
        .trim()
        .split(/\r?\n/)
        .filter((s) => s.trim()),
      delimiter = lines[0].includes("\t")
        ? "\t"
        : lines[0].includes(";")
          ? ";"
          : ",";
    const first = lines[0].split(delimiter).map((s) => s.trim().toLowerCase());
    if (first[0] !== "x" || first[1] !== "y")
      throw Error("简洁 CSV 的表头应为 x,y；轴含义由导入对象确定");
    curves = [
      {
        name: filename.replace(/\.csv$/i, ""),
        points: lines.slice(1).map((s, i) => {
          const p = s.split(delimiter).map(Number);
          if (p.length !== 2 || !p.every(Number.isFinite))
            throw Error("CSV 第 " + (i + 2) + " 行无效");
          return p;
        }),
      },
    ];
  } else throw Error("请选择 CSV 或 JSON");
  for (const c of curves) {
    if (
      !Array.isArray(c.points) ||
      c.points.length < 2 ||
      c.points.length > 20000 ||
      c.points.some(
        (r: any) =>
          !Array.isArray(r) ||
          r.length !== 2 ||
          !r.every((v: any) => typeof v === "number" && Number.isFinite(v)),
      )
    )
      throw Error("曲线需要 2–20000 个有效 x,y 点");
  }
  return { simple, curves, source: { filename } };
}
export function inspect(body: Spec) {
  const data = candidates(body.filename, body.content);
  return {
    ...data,
    curves: data.curves.map((c, i) => ({
      index: i,
      name: c.name || "曲线 " + (i + 1),
      points: c.points.length,
      plateau: null,
      sample_curves: [{ name: c.name, points: c.points }],
    })),
  };
}
function isotonic(points: number[][]) {
  const sorted = points.slice().sort((a, b) => a[1] - b[1]),
    groups: { sum: number; n: number; rows: number[] }[] = [];
  sorted.forEach((p, i) => {
    groups.push({ sum: p[0], n: 1, rows: [i] });
    while (
      groups.length > 1 &&
      groups.at(-2)!.sum / groups.at(-2)!.n >
        groups.at(-1)!.sum / groups.at(-1)!.n
    ) {
      const b = groups.pop()!,
        a = groups.pop()!;
      groups.push({
        sum: a.sum + b.sum,
        n: a.n + b.n,
        rows: [...a.rows, ...b.rows],
      });
    }
  });
  for (const g of groups)
    for (const i of g.rows) sorted[i] = [g.sum / g.n, sorted[i][1]];
  return sorted.filter((r, i) => !i || r[1] > sorted[i - 1][1]);
}
export function applyCurve(body: Spec) {
  const data = candidates(body.filename, body.content),
    curve = clone(data.curves[body.index || 0]);
  if (!curve) throw Error("曲线编号无效");
  if (!data.simple && (body.x_multiplier !== 1 || body.y_multiplier !== 1))
    throw Error("带结构的 SI 数据不能重复乘数量级");
  const x = body.x_multiplier ?? 1,
    y = body.y_multiplier ?? 1;
  if (!(x > 0 && y > 0)) throw Error("坐标倍率必须大于 0");
  if (data.simple)
    curve.points = curve.points.map(([a, b]: number[]) => [a * x, b * y]);
  const p = clone(body.spec);
  if (body.target === "Q1:transfer") {
    Object.assign(curve, {
      schema: "power-design.mos-miller-curve.v1",
      kind: curve.kind || "transfer",
      allow_extrapolation: true,
      x_scale: curve.x_scale || "linear",
      y_scale: curve.y_scale || "linear",
      import_file: data.source,
    });
    curve.points.sort((a: number[], b: number[]) => a[0] - b[0]);
    p.mos_miller_curve = curve;
    p.mos_miller_mode = "curve";
  } else if (body.target === "Q1:charge") {
    const start = data.simple ? body.plateau_start * x : curve.Qgs_ref_C,
      end = data.simple ? body.plateau_end * x : curve.Qplateau_end_C;
    if (!(start >= 0 && end > start)) throw Error("请确认平台起点和终点电荷");
    Object.assign(curve, {
      schema: "power-design.mos-gate-charge.v1",
      Qgs_ref_C: start,
      Qplateau_end_C: end,
      allow_extrapolation: true,
      import_file: data.source,
    });
    p.mos_charge_curve = curve;
    p.mos_charge_mode = "curve";
  } else {
    const original = curve.points;
    curve.points = isotonic(original);
    if (curve.points.length < 2 || curve.points.at(-1)[1] <= 0)
      throw Error("二极管需要两个不同 If 值");
    Object.assign(curve, {
      schema: "power-design.diode-forward.v1",
      source: data.source,
    });
    p.diode_curves = { ...p.diode_curves, [body.target]: curve };
  }
  p.device_curve_settings = {
    mode: "fixed",
    ...p.device_curve_settings,
    overrides: {
      ...p.device_curve_settings?.overrides,
      [body.target]: "curve",
    },
  };
  return { spec: p, curve };
}
