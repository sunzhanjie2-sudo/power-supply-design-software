/** Physical compensation networks. Equations and active corners match comp_design.py. */
import { type Spec } from "./spec";
const tau = 2 * Math.PI,
  inf = Infinity;
export const networkNames: Spec = {
  opamp3: "普通运放补偿网络",
  gm3: "跨导运放补偿网络",
  tl431nf: "TL431 + 光耦 · 无快车道",
  tl431f: "TL431 + 光耦 · 快车道",
};
export function evaluateParts(key: string, d: Spec): Spec {
  const { R1, R2, R3, C1, C2, C3, gm, CTR, Rpullup, Copto, R_LED, R_pz, C_pz } =
    d;
  if (key === "opamp3")
    return {
      KP: 1 / (R1 * (C1 + C2)),
      wz1: 1 / (R2 * C1),
      wz2: C3 ? 1 / ((R1 + R3) * C3) : inf,
      wp1: C2 ? (C1 + C2) / (R2 * C1 * C2) : inf,
      wp2: C3 ? 1 / (R3 * C3) : inf,
    };
  if (key === "gm3")
    return {
      KP: (gm * R2) / ((C2 + C3) * (R1 + R2)),
      wz1: 1 / (R3 * C2),
      wz2: C1 ? 1 / (R1 * C1) : inf,
      wp1: C3 ? (C2 + C3) / (R3 * C2 * C3) : inf,
      wp2: C1 ? (R1 + R2) / (R1 * C1 * R2) : inf,
    };
  if (key === "tl431nf")
    return {
      KP: (CTR * Rpullup) / (R_LED * R1 * C1),
      wz1: 1 / (R2 * C1),
      wz2: C3 ? 1 / (R1 * C3) : inf,
      wp1: C3 ? 1 / (R3 * C3) : 1 / (Rpullup * (C2 + Copto)),
      wp2: C3 ? 1 / (Rpullup * (C2 + Copto)) : inf,
    };
  if (key === "tl431f")
    return {
      KP: (CTR * Rpullup) / (R_LED * R1 * C1),
      wz1: 1 / (R1 * C1),
      wz2: C_pz ? 1 / ((R_LED + R_pz) * C_pz) : inf,
      wp1: C_pz ? 1 / (R_pz * C_pz) : 1 / (Rpullup * (C2 + Copto)),
      wp2: C_pz ? 1 / (Rpullup * (C2 + Copto)) : inf,
    };
  throw Error("未知补偿参考网络");
}
function split(s: number, z: number, p: number) {
  if (!(0 < z && z < p)) throw Error("该阻容支路需要零点低于极点");
  return [s * (1 - z / p), (s * z) / p];
}
export function solveParts(
  key: string,
  target: Spec,
  input: Spec,
  voltage: number,
  exact = false,
  legacy = false,
): Spec {
  const { KP, wz1: z1, wz2: z2, wp1: p1, wp2: p2 } = target;
  for (const k of ["KP", "wz1", "wp1", ...(exact ? [] : ["wz2", "wp2"])])
    if (!(target[k] > 0 && Number.isFinite(target[k])))
      throw Error("有效 KP 和零极点须为有限正数");
  const positive = (k: string, defaultValue?: number) => {
    const n = Number(input[k] ?? defaultValue);
    if (!(n > 0 && Number.isFinite(n))) throw Error(k + " 必须为有限正数");
    return n;
  };
  let d: Spec = { kind: key, type2: exact || legacy };
  if (key === "opamp3") {
    const R1 = positive("R1"),
      S = 1 / (KP * R1),
      [C1, C2] = legacy ? [S, 0] : split(S, z1, p1);
    if (!exact && !legacy && !(p2 > z2))
      throw Error("普通运放第二支路需要零点低于极点");
    const R3 = exact || legacy ? 0 : (z2 * R1) / (p2 - z2);
    d = {
      ...d,
      R1,
      R2: 1 / (z1 * C1),
      R3,
      C1,
      C2,
      C3: exact || legacy ? 0 : 1 / (p2 * R3),
      Vref: positive("Vref", 2.5),
    };
  } else if (key === "gm3") {
    const R2 = positive("R2"),
      gm = positive("gm");
    let R1 = Number(input.R1u || 0);
    if (exact && !R1) {
      if (voltage <= (input.Vref || 2.5))
        throw Error("输出电压必须高于分压基准");
      R1 = R2 * (voltage / (input.Vref || 2.5) - 1);
    }
    if (!exact && !legacy) {
      if (!(p2 > z2)) throw Error("跨导型补偿支路需要零点低于极点");
      R1 = (R2 * (p2 - z2)) / z2;
    }
    if (!(R1 > 0)) throw Error("R1 必须为正数");
    const S = (gm * R2) / (KP * (R1 + R2)),
      [C2, C3] = legacy ? [S, 0] : split(S, z1, p1);
    d = {
      ...d,
      gm,
      R1,
      R2,
      R3: 1 / (z1 * C2),
      C1: exact || legacy ? 0 : 1 / (z2 * R1),
      C2,
      C3,
    };
  } else {
    if (!["tl431nf", "tl431f"].includes(key)) throw Error("未知补偿参考网络");
    const R1 = positive("R1"),
      CTR = positive("CTR"),
      Rpullup = positive("Rpullup"),
      Copto = Number(input.Copto || 0),
      C2_tot = 1 / ((exact ? p1 : p2) * Rpullup);
    if (!(Copto >= 0 && Number.isFinite(Copto)))
      throw Error("Copto 必须为有限非负数");
    d = {
      ...d,
      R1,
      CTR,
      Rpullup,
      Copto,
      C2_tot,
      C2: C2_tot - Copto,
      Vref: 2.5,
    };
    if (key === "tl431nf") {
      const R_LED = positive("R_LED"),
        C1 = (CTR * Rpullup) / (KP * R1 * R_LED),
        C3 = exact ? 0 : 1 / (z2 * R1);
      Object.assign(d, {
        R_LED,
        C1,
        R2: 1 / (z1 * C1),
        R3: exact ? 0 : 1 / (p1 * C3),
        C3,
        R_LED_max: (voltage - 3.5) / 0.002,
      });
    } else {
      const C1 = 1 / (R1 * z1),
        R_LED = (CTR * Rpullup * z1) / KP;
      let R_pz = 0,
        C_pz = 0;
      if (!exact) {
        if (p1 > z2) {
          R_pz = (R_LED * z2) / (p1 - z2);
          C_pz = 1 / (p1 * R_pz);
        } else {
          const fx = Math.sqrt(
            Math.max(z2, 1) * Math.max(p1, Math.max(z2, 1) * 4),
          );
          R_pz = R_LED / 3;
          C_pz = 1 / (((R_LED + R_pz) * fx) / 2);
          d.warnings = [
            "快车道支路无法精确实现目标极点低于零点；采用旧版近似抵消对，请检查回代偏差。",
          ];
        }
      }
      Object.assign(d, { C1, R_LED, R_pz, C_pz });
    }
  }
  return d;
}
export function compensation(p: Spec, op: Spec, state: Spec): Spec {
  let key = String(state.key || state.topo || "");
  if (!networkNames[key])
    key = key.startsWith("普通运放")
      ? "opamp3"
      : key.startsWith("跨导")
        ? "gm3"
        : key.includes("无快车道")
          ? "tl431nf"
          : key.includes("快车道")
            ? "tl431f"
            : "";
  if (!key) throw Error("请选择补偿参考网络");
  if (p.feedback_mode === "PSR-MP6005")
    throw Error("PSR 使用芯片物理 COMP 阻容，不使用 SSR 参考网络");
  const prefixes: Spec = {
      "": 1,
      p: 1e-12,
      n: 1e-9,
      u: 1e-6,
      μ: 1e-6,
      m: 1e-3,
      k: 1e3,
      M: 1e6,
      G: 1e9,
    },
    inputs: Spec = {};
  for (const [k, v] of Object.entries(state.vars || {}) as [string, Spec][]) {
    if (!(v.u in prefixes) || !Number.isFinite(Number(v.v)))
      throw Error(k + " 的数值或单位无效");
    inputs[k] = Number(v.v) * prefixes[v.u];
  }
  const reverse = state.dir === "rev",
    legacy = !!state.type2,
    targets: Spec = {
      KP: p.KP,
      wz1: tau * p.fz1,
      wz2: tau * p.fz2,
      wp1: tau * p.fp1,
      wp2: tau * p.fp2,
    },
    vout = op.V_feedback ?? op.V_out_cap ?? op.V_out;
  let kind =
      p.controller_type === "auto"
        ? p.control_mode === "Peak Current Mode"
          ? "type2"
          : "type3"
        : p.controller_type || "type3",
    exact = !reverse && kind === "type2" && !legacy;
  const parts = reverse
      ? { ...inputs }
      : solveParts(key, targets, inputs, vout, exact, legacy),
    realized = evaluateParts(key, parts);
  if (Object.values(realized).some((v) => Number.isNaN(v) || v <= 0))
    throw Error("阻容参数不构成有效的补偿网络");
  if (
    reverse &&
    Number.isFinite(realized.wp1) &&
    !Number.isFinite(realized.wz2) &&
    !Number.isFinite(realized.wp2)
  ) {
    kind = "type2";
    exact = true;
  }
  const notes = [...(parts.warnings || [])];
  let buildable = true;
  if (exact) notes.push("标准二型：原点极点 + fz1 + fp1；第二零极点未启用。");
  if (parts.C2 < 0) {
    buildable = false;
    notes.push(
      "外加 C2 为负值，目标光耦极点高于器件自身极点；不能由并联正电容实现。",
    );
  }
  if (
    ["opamp3", "tl431nf", "tl431f"].includes(key) &&
    (key !== "opamp3" || parts.Vref !== undefined)
  ) {
    const vr = parts.Vref ?? 2.5;
    if (vout <= vr) {
      buildable = false;
      notes.push("输出电压不高于分压基准，不能生成有效下分压电阻。");
      delete parts.R_lower;
    } else parts.R_lower = (parts.R1 * vr) / (vout - vr);
    parts.Vref = vr;
  }
  parts.Vout = vout;
  if (key === "gm3")
    notes.push(
      "分压基准回代 " +
        (vout * parts.R2) / (parts.R1 + parts.R2) +
        " V，需核对实际器件。",
    );
  if (key.startsWith("tl431")) {
    notes.push("R_bias 与器件偏置电流须另行核对。");
    if (parts.Copto > 0) {
      parts.fp_opto = 1 / (tau * parts.Rpullup * parts.Copto);
      if (parts.fp_opto < 10 * p.fc_target)
        notes.push("光耦自身极点低于 10×目标 fc，需复核实际相位影响。");
    }
  }
  return {
    key,
    direction: reverse ? "rev" : "fwd",
    type2: legacy || exact,
    exact_type2: exact,
    legacy_type2: legacy,
    controller_type: kind,
    active_fields:
      kind === "type2"
        ? ["KP", "wz1", "wp1"]
        : ["KP", "wz1", "wz2", "wp1", "wp2"],
    inputs,
    parts,
    targets,
    realized,
    buildable,
    notes,
  };
}
export function compensationAction(p: Spec, op: Spec, opts: Spec): Spec {
  const state = {
    key: opts.key,
    encoding: "si",
    dir: opts.direction,
    type2: !!opts.type2,
    vars: Object.fromEntries(
      Object.entries(opts.inputs).map(([k, v]) => [k, { v, u: "" }]),
    ),
  };
  let data: Spec;
  try {
    data = compensation(p, op, state);
  } catch (e) {
    return {
      key: opts.key,
      direction: opts.direction,
      parts: {},
      realized: {},
      checks: [],
      targets: {},
      buildable: false,
      notes: [String(e)],
      spec_updates: { __comp: state },
      chart_svg: compensationDiagram(opts.key),
    };
  }
  const updates: Spec = { __comp: state },
    checks: Spec[] = [],
    realized: Spec = {},
    targets: Spec = {};
  for (const [name, k] of [
    ["KP", "KP"],
    ["fz1", "wz1"],
    ["fz2", "wz2"],
    ["fp1", "wp1"],
    ["fp2", "wp2"],
  ])
    if (data.active_fields.includes(k)) {
      const div = k === "KP" ? 1 : tau,
        a = data.realized[k] / div,
        t = data.targets[k] / div;
      realized[name] = Number.isFinite(a) ? a : null;
      targets[name] = t;
      checks.push({
        name,
        target: t,
        actual: realized[name],
        ok:
          Number.isFinite(a) &&
          Math.abs(a - t) <= 1e-6 * Math.max(Math.abs(t), 1e-30),
        note: Number.isFinite(a)
          ? "代数回代；可实现性另见说明"
          : "省略 / 无限远",
      });
    }
  if (opts.direction === "rev" && data.buildable) {
    const two =
      Number.isFinite(data.realized.wp1) &&
      !Number.isFinite(data.realized.wz2) &&
      !Number.isFinite(data.realized.wp2);
    Object.assign(updates, {
      KP: data.realized.KP,
      controller_type: two ? "type2" : "type3",
    });
    for (const [n, k] of [
      ["fz1", "wz1"],
      ["fp1", "wp1"],
      ...(two
        ? []
        : [
            ["fz2", "wz2"],
            ["fp2", "wp2"],
          ]),
    ])
      updates[n] = Number.isFinite(data.realized[k])
        ? data.realized[k] / tau
        : 1e9;
  }
  return {
    ...data,
    checks,
    realized,
    targets,
    spec_updates: updates,
    chart_svg: compensationDiagram(opts.key),
  };
}
/** Native SVG circuit, same node semantics and part names as the reference networks. */
export function compensationDiagram(key: string) {
  let content = "";
  const line = (x: number, y: number, a: number, b: number) =>
      (content += `<path d="M${x} ${y}L${a} ${b}"/>`),
    label = (x: number, y: number, s: string) =>
      (content += `<text x="${x}" y="${y}" stroke="none" fill="#173b64" font-size="15">${s}</text>`);
  const part = (x: number, y: number, a: number, b: number, n: string) => {
    const cx = (x + a) / 2,
      cy = (y + b) / 2,
      h = x === a;
    line(x, y, h ? x : cx - 24, h ? cy - 22 : y);
    line(h ? x : cx + 24, h ? cy + 22 : y, a, b);
    content += `<rect x="${cx - (h ? 9 : 24)}" y="${cy - (h ? 22 : 9)}" width="${h ? 18 : 48}" height="${h ? 44 : 18}" fill="white"/>`;
    label(cx + (h ? 14 : -20), cy + (h ? 5 : -15), n);
  };
  const cap = (x: number, y: number, a: number, b: number, n: string) => {
    const cx = (x + a) / 2,
      cy = (y + b) / 2,
      h = x === a;
    line(x, y, h ? x : cx - 5, h ? cy - 5 : y);
    line(h ? x : cx + 5, h ? cy + 5 : y, a, b);
    line(
      h ? cx - 18 : cx - 5,
      h ? cy - 5 : cy - 18,
      h ? cx + 18 : cx - 5,
      h ? cy - 5 : cy + 18,
    );
    line(
      h ? cx - 18 : cx + 5,
      h ? cy + 5 : cy - 18,
      h ? cx + 18 : cx + 5,
      h ? cy + 5 : cy + 18,
    );
    label(cx + 14, cy - 12, n);
  };
  const ground = (x: number, y: number) => {
    line(x, y, x, y + 10);
    line(x - 16, y + 10, x + 16, y + 10);
    line(x - 10, y + 16, x + 10, y + 16);
  };
  label(35, 28, networkNames[key] || "补偿参考网络");
  label(35, 51, "位号与计算表一致；理想小信号参考，器件偏置须另核对");
  if (["opamp3", "gm3"].includes(key)) {
    label(45, 160, "Vout");
    part(110, 155, 280, 155, "R1");
    part(280, 155, 280, 380, key === "gm3" ? "R2" : "R_lower");
    ground(280, 380);
    line(280, 155, 380, 155);
    content += '<path d="M380 125L380 245L485 185Z" fill="#edf5ff"/>';
    label(390, 150, "−");
    label(390, 231, "+");
    label(410, 193, key === "gm3" ? "gm" : "EA");
    label(320, 240, "Vref");
    line(350, 235, 380, 235);
    line(485, 185, 880, 185);
    label(830, 170, "Vc");
    if (key === "opamp3") {
      line(280, 155, 280, 100);
      part(280, 100, 510, 100, "R2");
      cap(510, 100, 750, 100, "C1");
      line(750, 100, 750, 185);
      line(280, 100, 280, 85);
      cap(280, 85, 750, 85, "C2");
      line(750, 85, 750, 100);
      line(110, 155, 110, 300);
      part(110, 300, 195, 300, "R3");
      cap(195, 300, 330, 300, "C3");
      line(330, 300, 330, 155);
    } else {
      line(110, 155, 110, 100);
      cap(110, 100, 280, 100, "C1");
      line(280, 100, 280, 155);
      line(650, 185, 650, 245);
      part(650, 245, 650, 315, "R3");
      cap(650, 315, 650, 400, "C2");
      ground(650, 400);
      line(800, 185, 800, 260);
      cap(800, 260, 800, 400, "C3");
      ground(800, 400);
    }
  } else {
    label(55, 130, "Vdd");
    part(100, 135, 100, 260, "Rpullup");
    label(55, 280, "Vc");
    line(100, 260, 235, 260);
    cap(100, 260, 100, 400, "C2 ∥ Copto");
    ground(100, 400);
    content +=
      '<path d="M235 275L235 345M230 290L200 310L230 330M240 287L260 275M240 335L260 345"/>';
    line(235, 260, 235, 275);
    line(235, 345, 235, 400);
    ground(235, 400);
    label(200, 370, "光耦");
    label(350, 130, key === "tl431f" ? "Vout" : "独立 Vdd");
    part(410, 135, 410, 250, "R_LED");
    content += '<path d="M392 255L428 255L410 285ZM392 287L428 287"/>';
    line(410, 250, 410, 255);
    line(410, 287, 410, 330);
    label(345, 355, "阴极");
    content +=
      '<path d="M390 350L430 350L410 380ZM390 382L430 382M430 367L510 367"/>';
    line(410, 330, 410, 350);
    line(410, 382, 410, 440);
    ground(410, 440);
    label(320, 405, "TL431");
    label(735, 130, "Vout");
    line(760, 135, 760, 150);
    part(760, 150, 760, 330, "R1");
    line(760, 330, 760, 367);
    line(510, 367, 760, 367);
    part(760, 367, 760, 440, "R_lower");
    ground(760, 440);
    line(410, 330, 510, 330);
    if (key === "tl431nf") {
      part(510, 330, 590, 330, "R2");
      cap(590, 330, 760, 330, "C1");
      line(760, 150, 880, 150);
      part(880, 150, 880, 240, "R3");
      cap(880, 240, 880, 367, "C3");
      line(880, 367, 760, 367);
    } else {
      cap(510, 330, 760, 330, "C1");
      line(760, 135, 610, 135);
      part(610, 135, 610, 225, "R_pz");
      cap(610, 225, 610, 290, "C_pz");
      line(610, 290, 410, 290);
    }
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="500" viewBox="0 0 960 500"><rect width="960" height="500" rx="14" fill="white"/><g stroke="#173b64" stroke-width="2" fill="none" font-family="Microsoft YaHei,Arial">${content}</g></svg>`;
}
