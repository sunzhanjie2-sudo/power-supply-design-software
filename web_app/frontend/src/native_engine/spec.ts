import data from "./reference-data.json";
import { single } from "./power";
import { core } from "./magnetics";
export type Spec = Record<string, any>;
export const reference = data as any;
export const clone = <T>(x: T): T => structuredClone(x);
const prefixes: Record<string, number> = {
  p: 1e-12,
  n: 1e-9,
  u: 1e-6,
  µ: 1e-6,
  m: 1e-3,
  c: 1e-2,
  "": 1,
  k: 1e3,
  M: 1e6,
  G: 1e9,
};
export const isolated = (p: Spec) =>
  ["FLYBACK", "QR-FLYBACK", "ACF-FORWARD"].includes(p.topology);
export function decode(raw: Spec) {
  const out: Spec = {};
  for (let [key, value] of Object.entries(raw)) {
    if (
      value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      "v" in value
    ) {
      const unit = value.u || "";
      if (!(unit in prefixes)) throw Error(key + " 的单位数量级未知");
      value = typeof value.v === "number" ? value.v * prefixes[unit] : value.v;
    }
    if (["topology", "control_mode"].includes(key) && typeof value === "string")
      value = value.split(" (")[0];
    key = ({ rcd_K: "K", rcd_Kc: "Kc", rcd_dC: "dC" } as Spec)[key] || key;
    out[key] = clone(value);
  }
  if (out.topology === "FLYBACK-QR") out.topology = "QR-FLYBACK";
  return out;
}
export function bank(p: Spec, side = "output"): Spec[] {
  let values = p[side + "_capacitors"];
  if (values == null) {
    const names =
      side === "input"
        ? ["Cin1", "Rcin1", "ESLin1", "Cin2", "Rcin2", "ESLin2", "cin2_enable"]
        : ["C_out", "Rc", "ESL", "C_out2", "Rc2", "ESL2", "cout2_enable"];
    values = [{ C: p[names[0]], ESR: p[names[1]], ESL: p[names[2]] || 0 }];
    if (p[names[6]])
      values.push({ C: p[names[3]], ESR: p[names[4]], ESL: p[names[5]] || 0 });
  }
  if (!Array.isArray(values) || !values.length || values.length > 256)
    throw Error("电容组需要 1–256 个支路");
  return values.map((r: Spec, i: number) => {
    for (const k of ["C", "ESR", "ESL"])
      if (
        !Number.isFinite(r[k] ?? 0) ||
        (r[k] ?? 0) < 0 ||
        (k === "C" && !(r[k] > 0))
      )
        throw Error(`第 ${i + 1} 颗电容 ${k} 无效`);
    return { C: r.C, ESR: r.ESR || 0, ESL: r.ESL || 0 };
  });
}
export function normalize(raw: Spec) {
  const p = { ...clone(reference.defaults), ...decode(raw) };
  p.V_in_min ??= p.V_in;
  p.V_in_max ??= p.V_in;
  p.input_voltage_case ??= "min";
  p.V_in = p.input_voltage_case === "max" ? p.V_in_max : p.V_in_min;
  p.controller_type = p.controller_type === "pi" ? "auto" : p.controller_type;
  for (const side of ["input", "output"])
    if (p[side + "_capacitors"] != null) {
      const values = bank(p, side),
        keys =
          side === "input"
            ? [
                "Cin1",
                "Rcin1",
                "ESLin1",
                "Cin2",
                "Rcin2",
                "ESLin2",
                "cin2_enable",
              ]
            : ["C_out", "Rc", "ESL", "C_out2", "Rc2", "ESL2", "cout2_enable"];
      values
        .slice(0, 2)
        .forEach((c, i) =>
          ["C", "ESR", "ESL"].forEach((k, j) => (p[keys[i * 3 + j]] = c[k])),
        );
      p[keys[6]] = values.length > 1;
    }
  for (const key of ["Rd_diode", "Rd_din", "Rd_dout"]) p[key] = 0;
  // Fast-mode capacitance overrides have the same meaning as parasitics.py.
  if (isolated(p) && p.parasitic_config) {
    const cfg = p.parasitic_config;
    for (const [source, target] of [
      ["coss", "Coss"],
      ["coss_aux", "Coss_aux"],
    ]) {
      const value = Number(cfg[source] || 0);
      if (!Number.isFinite(value) || value < 0)
        throw Error(source + " 必须为有限非负数");
      if (value > 0) p[target] = value;
    }
  }
  return p;
}
export function validate(p: Spec) {
  for (const key of [
    "V_in",
    "V_out",
    "P_out",
    "f_sw",
    "L",
    "C_out",
    "Cin1",
    "Vm",
    "A_sense",
    "Bmax",
    "Bsat",
    "J",
    "Ku",
  ])
    if (!(p[key] > 0) || !Number.isFinite(p[key]))
      throw Error(key + " 必须为有限正数");
  if (!(p.V_in_min > 0 && p.V_in_max >= p.V_in_min))
    throw Error("输入范围要求 0 < Vinmin ≤ Vinmax");
  if (!(p.eta_guess > 0 && p.eta_guess <= 1))
    throw Error("预设效率必须在 0～1 之间");
  if (p.control_mode === "Peak Current Mode" && !(p.Rs > 0))
    throw Error("峰值电流控制的采样电阻必须大于 0");
  for (const [key, v] of Object.entries(p))
    if (typeof v === "number" && !Number.isFinite(v))
      throw Error(key + " 必须为有限数值");
  bank(p, "input");
  bank(p);
}
export const blockDrop = (r: Spec) => (r.d_out_enable ? r.Vf_dout : 0);
export const inputDrop = (p: Spec) => (p.d_in_enable ? p.Vf_din : 0);
export function rails(p: Spec): Spec[] {
  if (!p.outputs?.length) return [];
  if (!isolated(p) || p.outputs.length > 6)
    throw Error("多绕组仅适用于隔离拓扑，最多六路");
  const selected = Number(p.feedback_output || 1) - 1;
  if (
    selected < 0 ||
    selected >= p.outputs.length ||
    !Number.isInteger(selected)
  )
    throw Error("主反馈编号无效");
  const fields = [
    "V_out",
    "P_out",
    "P_out_min",
    "C_out",
    "Rc",
    "ESL",
    "C_out2",
    "Rc2",
    "ESL2",
    "cout2_enable",
    "Vf_diode",
    "Qrr",
    "d_out_enable",
    "Vf_dout",
    "ripple_target",
    "Ns",
    "d_wire_s",
    "n_strand_s",
    "L",
    "core_choice_L",
    "custom_core_L",
  ];
  const r = p.outputs.map((raw: Spec, i: number) => {
    const e = decode(raw),
      q: Spec = Object.fromEntries(fields.map((k) => [k, p[k]]));
    if (i > 0) {
      q.Ns = 0;
      q.d_wire_s = 0;
    }
    Object.assign(q, e, {
      id: i + 1,
      name: e.name || "OUT" + (i + 1),
      P_out_min: e.P_out_min ?? e.P_out,
      Rd_diode: 0,
      Rd_dout: 0,
    });
    if (!(q.P_out >= 0) || q.P_out_min < 0 || q.P_out_min > q.P_out)
      throw Error(q.name + " 负载范围无效");
    bank(q);
    return q;
  });
  const seed = (rows: Spec[], secondary?: number[]) => {
    const fb = rows[selected],
      fixed = p._fixed_transformer || {},
      np = fixed.Np || p.Np,
      n = secondary?.[selected] || fb.Ns;
    const q: Spec = {
      ...p,
      ...fb,
      outputs: [],
      feedback_mode: "SSR",
      N:
        np && n
          ? np / n
          : p.N *
            (secondary
              ? secondary[0] / secondary[selected]
              : rows[0].V_out / fb.V_out),
      P_out: rows.reduce((s, r) => s + r.P_out, 0),
    };
    if (p.feedback_mode === "PSR-MP6005")
      Object.assign(q, {
        f_sw: 250000,
        A_sense: 11,
        control_mode: "Peak Current Mode",
      });
    if (p.topology === "ACF-FORWARD")
      q.L = 1 / rows.reduce((s, r) => s + (r.V_out / fb.V_out) ** 2 / r.L, 0);
    const op = single(q),
      c = core(p, (2 * op.P_out) / (p.Bmax * p.J * p.Ku * op.f_sw), fixed);
    return Math.max(
      1,
      Math.trunc(
        fixed.Np ||
          p.Np ||
          Math.ceil((op.V_in * op.D * op.Ts) / (p.Bmax * c.Ae)),
      ),
    );
  };
  const fixed = p._fixed_transformer || {};
  for (const w of fixed.windings || [])
    if (r[w.id - 1] && w.Ns) r[w.id - 1].Ns = w.Ns;
  if (fixed.Ns) r[selected].Ns = fixed.Ns;
  const anchor = r.some((q: Spec) => !q.Ns)
      ? seed(r)
      : fixed.Np ||
        p.Np ||
        seed(
          r,
          r.map((q: Spec) => q.Ns),
        ),
    ns = r.map(
      (q: Spec, i: number) =>
        q.Ns ||
        Math.max(
          1,
          roundEven(
            ((r[0].Ns || roundEven(anchor / p.N)) * q.V_out) / r[0].V_out,
          ),
        ),
    );
  r.forEach((q: Spec, i: number) => {
    q.Ns = ns[i];
    if (i !== selected)
      q.V_out =
        ((r[selected].V_out + blockDrop(r[selected]) + r[selected].Vf_diode) *
          ns[i]) /
          ns[selected] -
        q.Vf_diode -
        blockDrop(q);
    if (!(q.V_out > 0)) throw Error(q.name + " 匝比不足以覆盖二极管压降");
  });
  return r;
}
export function roundEven(x: number) {
  const f = Math.floor(x);
  return x - f === 0.5 ? (f % 2 === 0 ? f : f + 1) : Math.round(x);
}
export const capability = (p: Spec) => {
  const gaps: string[] = [];
  return gaps;
};
