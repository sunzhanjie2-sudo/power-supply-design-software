import { reference, type Spec, roundEven } from "./spec";
import { gamma } from "./math";
import { purchased, purchasedInductor } from "./inductor_selection";
export function core(p: Spec, ap: number, fixed: Spec = {}) {
  const choice = fixed.core || p.core_choice;
  let geometry = fixed.core_geometry || reference.cores[choice];
  if (choice === "custom" || choice === "CUSTOM") geometry = p.custom_core;
  if (!geometry) {
    const candidates = Object.entries(reference.cores)
      .filter(
        ([name, c]: any) =>
          c.Ae * c.Wa >= ap &&
          (!p.core_shape ||
            p.core_shape === "auto" ||
            name.startsWith(p.core_shape)),
      )
      .sort((a: any, b: any) => a[1].Ae * a[1].Wa - b[1].Ae * b[1].Wa);
    if (!candidates.length) throw Error("磁芯数据库中没有满足面积积的磁芯");
    return { name: candidates[0][0], ...(candidates[0][1] as Spec) };
  }
  for (const k of ["Ae", "Ve", "Wa", "MLT"])
    if (!(geometry[k] > 0)) throw Error("磁芯尺寸 " + k + " 必须大于 0");
  return { name: choice, ...geometry };
}
export function wire(current: number, strands: number, p: Spec, diameter = 0) {
  const d = diameter || Math.sqrt(current / strands / p.J / Math.PI) * 2;
  return { diameter: d, area: (strands * Math.PI * d * d) / 4 };
}
export function ac(d: number, f: number, rho: number) {
  const delta = Math.sqrt(rho / (Math.PI * f * 4e-7 * Math.PI)),
    x = d / delta;
  return 1 + x ** 4 / (48 + 0.8 * x ** 4);
}
export function nse(
  p: Spec,
  f: number,
  db: number,
  on: number,
  off: number,
  ve: number,
) {
  const a = p.a_core,
    b = p.b_core,
    integral = (2 * Math.sqrt(Math.PI) * gamma((a + 1) / 2)) / gamma(a / 2 + 1),
    kn = p.k_core / ((2 * Math.PI) ** (a - 1) * integral);
  return (
    kn *
    ((2 * f) / 1000) ** a *
    (db / 2) ** b *
    (Math.max(on, 1e-9) ** (1 - a) + Math.max(off, 1e-9) ** (1 - a)) *
    1000 *
    ve
  );
}
export function nseWaveform(p: Spec, t: number[], flux: number[], ve: number) {
  const a = p.a_core,
    b = p.b_core,
    integral = (2 * Math.sqrt(Math.PI) * gamma((a + 1) / 2)) / gamma(a / 2 + 1),
    kn = p.k_core / ((2 * Math.PI) ** (a - 1) * integral),
    step = (t[1] - t[0]) * 1000,
    db = Math.max(...flux) - Math.min(...flux);
  let total = 0;
  for (let i = 0; i < t.length; i++) {
    const j = i === 0 ? 0 : i - 1,
      k = i === t.length - 1 ? i : i + 1;
    total += Math.abs((flux[k] - flux[j]) / ((t[k] - t[j]) * 1000)) ** a * step;
  }
  return (
    (((db / 2) ** (b - a) * kn) / ((t.at(-1)! - t[0]) * 1000)) *
    total *
    1000 *
    ve
  );
}
export function transformer(op: Spec, p: Spec) {
  const fixed = p._fixed_transformer || {},
    ap = (2 * op.P_out) / (p.Bmax * p.J * p.Ku * op.f_sw),
    c = core(p, ap, fixed),
    mlt = fixed.MLT || p.MLT || c.MLT;
  const np =
      fixed.Np ||
      p.Np ||
      Math.max(1, Math.ceil((op.V_in * op.D * op.Ts) / p.Bmax / c.Ae)),
    ns = fixed.Ns || p.Ns || Math.max(1, roundEven(np / op.N)),
    strp = fixed.n_strand_p || p.n_strand_p || 1,
    strs = fixed.n_strand_s || p.n_strand_s || 1;
  const ip = op.I_p_rms ?? op.I_sw_rms,
    is = op.I_s_rms ?? op.I_d_rms,
    wp = wire(ip, strp, p, fixed.d_wire_p || p.d_wire_p),
    ws = wire(is, strs, p, fixed.d_wire_s || p.d_wire_s),
    rp = (p.rho * mlt * np) / wp.area,
    rs = (p.rho * mlt * ns) / ws.area,
    frp = ac(wp.diameter, op.f_sw, p.rho),
    frs = ac(ws.diameter, op.f_sw, p.rho);
  const db = (op.V_in * op.D * op.Ts) / (np * c.Ae),
    b = op.topology === "ACF-FORWARD" ? db / 2 : (op.L * op.I_L_pk) / np / c.Ae,
    pcu = frp * rp * ip ** 2 + frs * rs * is ** 2,
    pcore = nse(
      p,
      op.f_sw,
      db,
      op.D,
      op.topology === "ACF-FORWARD" ? 1 - op.D : op.Dp,
      c.Ve,
    );
  return {
    ok: true,
    core: c.name,
    core_label: c.name,
    core_geometry: c,
    Ae: c.Ae,
    Ve: c.Ve,
    Wa: c.Wa,
    MLT: mlt,
    MLT_source: p.MLT ? "用户指定平均匝长" : "磁芯数据库",
    ap,
    Np: np,
    Ns: ns,
    n_actual: np / ns,
    d_wire_p: wp.diameter,
    d_wire_s: ws.diameter,
    n_strand_p: strp,
    n_strand_s: strs,
    R_dc_p: rp,
    R_dc_s: rs,
    Fr_p: frp,
    Fr_s: frs,
    J_actual_p: ip / wp.area,
    J_actual_s: is / ws.area,
    I_rms_p: ip,
    I_rms_s: is,
    B_pk: b,
    dB: db,
    P_cu: pcu,
    P_core: pcore,
    P_total: pcu + pcore,
    fill: (np * wp.area + ns * ws.area) / c.Wa,
    dT: (pcu + pcore) * p.Rth_transformer,
    Rth_transformer: p.Rth_transformer,
    thermal_model: "user-thermal-resistance",
  };
}
export function inductor(op: Spec, p: Spec) {
  if (purchased(p)) return purchasedInductor(op, p);
  const fixed = p._fixed_inductor || {},
    ap = (op.L * op.I_L_pk * op.I_L_rms) / (p.Bmax * p.J * p.Ku),
    c = core(p, ap, fixed),
    mlt = fixed.MLT || p.MLT || c.MLT,
    n = fixed.N || Math.max(1, Math.ceil((op.L * op.I_L_pk) / p.Bmax / c.Ae)),
    d = fixed.d_wire || Math.sqrt((4 * op.I_L_rms) / p.J / Math.PI),
    area = (Math.PI * d * d) / 4,
    rd = (p.rho * mlt * n) / area,
    fr = ac(d, op.f_sw, p.rho),
    db = (op.L * op.dI_L) / n / c.Ae,
    pcu = fr * rd * op.I_L_rms ** 2,
    pcore = nse(p, op.f_sw, db, op.D, op.Dp, c.Ve),
    surf = 2 * (1.5 * c.Ve ** (1 / 3)) ** 2;
  return {
    ok: true,
    core: c.name,
    core_label: c.name,
    core_geometry: c,
    Ae: c.Ae,
    Ve: c.Ve,
    Wa: c.Wa,
    MLT: mlt,
    N: n,
    d_wire: d,
    R_dc: rd,
    Fr: fr,
    J_actual: op.I_L_rms / area,
    I_rms: op.I_L_rms,
    P_cu: pcu,
    P_core: pcore,
    P_total: pcu + pcore,
    dT: (pcu + pcore) / (p.h_conv * surf),
    fill: (n * area) / c.Wa,
    B_pk: (op.L * op.I_L_pk) / n / c.Ae,
    dB: db,
    gap: (4e-7 * Math.PI * n * n * c.Ae) / op.L,
    A_surf: surf,
    ap,
  };
}
