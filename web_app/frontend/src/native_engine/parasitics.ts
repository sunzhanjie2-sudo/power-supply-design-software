/** Local commutation networks; same physical scope as parasitic_ringing.py. */
import { type Spec, clone } from "./spec";
import { zeros, expm, scale, mv, solve, dot, ptp } from "./math";
import { windingHardware } from "./power";
export const parasiticNote =
  "集中等效 Coss/Cj、绕组/布线寄生与 RC 吸收；0 表示未建模。常数电容，不含反向恢复、温度、分布电容和实际探头。";
export function resolvedParasitics(p: Spec, count = 1): Spec {
  const raw = p.parasitic_config || {},
    old = p.spice_config || {},
    cfg: Spec = {
      mode: "fast",
      coss: 0,
      coss_aux: 0,
      cw_primary: 0,
      lp_pcb: 0,
      rp_pcb: 0,
      snub_r_primary: 10,
      snub_c_primary: 0,
      cj_default: (old.diode_cj_pf ?? 20) * 1e-12,
      r_cj: 0.1,
      ...raw,
    };
  if (!["fast", "transient"].includes(cfg.mode))
    throw Error("寄生模式须为 fast 或 transient");
  for (const key of [
    "coss",
    "coss_aux",
    "cw_primary",
    "lp_pcb",
    "rp_pcb",
    "snub_r_primary",
    "snub_c_primary",
    "cj_default",
    "r_cj",
  ])
    if (!Number.isFinite(cfg[key]) || cfg[key] < 0)
      throw Error(key + " 寄生参数须为有限非负数");
  if (!(cfg.r_cj > 0) || (cfg.snub_c_primary > 0 && cfg.snub_r_primary <= 0))
    throw Error("启用吸收或结电容时阻尼电阻必须大于0");
  cfg.coss_source = cfg.coss ? "寄生配置" : "器件 Coss";
  if (p.topology === "QR-FLYBACK" && !cfg.coss && old.qr_cds_pf > 0) {
    cfg.coss = old.qr_cds_pf * 1e-12;
    cfg.coss_source = "旧 QR 有效漏极电容";
  }
  cfg.coss ||= p.Coss;
  cfg.coss_aux ||= p.Coss_aux || 0;
  cfg.rails = Array.from({ length: count }, (_, i) => {
    const r = {
      cj: cfg.cj_default,
      cj_free: cfg.cj_default,
      cw: 0,
      l_pcb: 0,
      r_pcb: 0,
      snub_r: 10,
      snub_c: 0,
      ...raw.rails?.["OUT" + (i + 1)],
    };
    for (const [k, v] of Object.entries(r))
      if (typeof v !== "number" || !Number.isFinite(v) || v < 0)
        throw Error("OUT" + (i + 1) + "." + k + " 寄生参数无效");
    if (r.snub_c > 0 && r.snub_r <= 0) throw Error("吸收电阻必须为正");
    return r;
  });
  return cfg;
}
export function windingMatrix(p: Spec, op: Spec, legacy = false) {
  const hardware = windingHardware(p, op),
    n = hardware.windings.length,
    ratios = [1, ...hardware.windings.map((w: Spec) => hardware.Np / w.Ns)],
    size = n + 1;
  const k = legacy
    ? Array.from({ length: size }, (_, i) =>
        Array.from({ length: size }, (_, j) =>
          i === j ? 1 : Math.sqrt(p.K ?? 0.95),
        ),
      )
    : p.coupling_config?.k?.length
      ? clone(p.coupling_config.k)
      : Array.from({ length: size }, (_, i) =>
          Array.from({ length: size }, (_, j) => (i === j ? 1 : 0.995)),
        );
  if (k.length !== size || k.some((r: number[]) => r.length !== size))
    throw Error("耦合矩阵维数错误");
  for (let i = 0; i < size; i++)
    for (let j = 0; j < size; j++)
      if (
        !Number.isFinite(k[i][j]) ||
        k[i][j] < 0 ||
        k[i][j] > 1 ||
        Math.abs(k[i][j] - k[j][i]) > 1e-12 ||
        (i === j && k[i][j] !== 1)
      )
        throw Error("耦合矩阵要求对称、对角线为1、0≤kij≤1");
  const lp = p.topology === "ACF-FORWARD" ? p.Lm_forward : p.L,
    L = k.map((r: number[], i: number) =>
      r.map((v, j) => (v * lp) / ratios[i] / ratios[j]),
    ),
    R = [hardware.R_dc_p, ...hardware.windings.map((w: Spec) => w.R_dc)];
  return {
    hardware,
    L,
    R,
    K: k,
    ratios,
    ideal: k.every((r: number[]) => r.every((v) => Math.abs(v - 1) < 1e-13)),
  };
}
export function solveEdge(params: Spec): Spec {
  const {
      inductance: L,
      capacitance: C,
      resistance: R,
      current,
      plateau,
    } = params,
    sr = params.snub_r ?? 10,
    sc = params.snub_c ?? 0,
    v0 = params.initial_voltage ?? plateau;
  for (const v of [L, C, R, current, plateau, sr, sc, v0])
    if (!(v >= 0 && Number.isFinite(v)))
      throw Error("局部 RLC 参数须为有限非负数");
  if (sc && sr <= 0) throw Error("吸收电阻必须大于0");
  if (params.ceiling != null && params.ceiling < plateau)
    throw Error("钳位上限必须不低于平台");
  if (!L || !C || (!current && v0 === plateau))
    return {
      t: [0, 1e-9],
      voltage: [plateau, plateau],
      peak: plateau,
      frequency: null,
      energy_initial: 0.5 * L * current ** 2,
      status: "无有效 LC 激励",
      clamped: false,
    };
  const period = 2 * Math.PI * Math.sqrt(L * C),
    end = Math.min(8 * period, params.duration ?? Infinity),
    top = params.ceiling == null ? Infinity : params.ceiling - plateau,
    bottom = -plateau;
  if (!(end > 0)) throw Error("振铃观察时间必须为正");
  const a = zeros(4);
  a[0][0] = -R / L;
  a[0][1] = -1 / L;
  a[1][0] = 1 / C;
  if (sc) {
    a[1][1] = -1 / (sr * C);
    a[1][2] = 1 / (sr * C);
    a[2][1] = 1 / (sr * sc);
    a[2][2] = -1 / (sr * sc);
  }
  const cache = new Map<string, number[][]>(),
    flow = (x: number[], h: number, bound: number | null) => {
      const key = h + "/" + bound;
      let e = cache.get(key);
      if (!e) {
        const m = a.map((r) => [...r]);
        if (bound !== null) {
          m[0][1] = 0;
          m[0][3] = -bound / L;
          m[1] = [0, 0, 0, 0];
          if (sc) {
            m[2][1] = 0;
            m[2][3] = bound / (sr * sc);
          }
        }
        e = expm(scale(m, h));
        if (cache.size < 16) cache.set(key, e);
      }
      return mv(e, [...x, 1]).slice(0, 3);
    };
  let x = [current, v0 - plateau, v0 - plateau],
    time = 0,
    bound: number | null = null,
    events = 0,
    clamped = false;
  const t = [0],
    states = [x.slice()];
  while (time < end * (1 - 1e-12)) {
    if (events > 64) throw Error("局部钳位事件过密");
    const h = Math.min(period / 96, end - time),
      y = flow(x, h, bound);
    let nextBound: number | null = bound,
      event = false,
      sign = 0;
    const derivative = (z: number[]) => z[0] - (sc ? (z[1] - z[2]) / sr : 0);
    if (bound === null) {
      if (y[1] > top) {
        nextBound = top;
        sign = 1;
        event = true;
      } else if (y[1] < bottom) {
        nextBound = bottom;
        sign = -1;
        event = true;
      }
    } else {
      sign = bound === top ? 1 : -1;
      if (sign * derivative(y) <= 0) {
        nextBound = null;
        event = true;
      }
    }
    let step = h;
    if (event) {
      let lo = 0,
        hi = h;
      for (let j = 0; j < 35; j++) {
        const mid = (lo + hi) / 2,
          z = flow(x, mid, bound),
          cross =
            bound === null
              ? sign * (z[1] - (nextBound as number)) > 0
              : sign * derivative(z) <= 0;
        if (cross) hi = mid;
        else lo = mid;
      }
      step = Math.max((lo + hi) / 2, 1e-15 * period);
    }
    x = flow(x, step, bound);
    time += step;
    if (event) {
      events++;
      if (nextBound !== null) {
        x[1] = nextBound;
        if (nextBound === top) clamped = true;
      } else x[1] = (bound as number) - sign * Math.max(plateau, 1) * 1e-10;
      bound = nextBound;
    }
    t.push(time);
    states.push(x.slice());
  }
  const voltage = states.map((x) => x[1] + plateau),
    last = states.at(-1)!;
  return {
    t,
    voltage,
    peak: Math.max(...voltage),
    frequency: 1 / period,
    energy_initial:
      0.5 * L * current ** 2 + 0.5 * (C + sc) * (v0 - plateau) ** 2,
    status: "集中参数局部换流估算",
    clamped,
    current: states.map((x) => x[0]),
    energy_final:
      0.5 * L * last[0] ** 2 + 0.5 * C * last[1] ** 2 + 0.5 * sc * last[2] ** 2,
  };
}
export function attachParasitics(p: Spec, op: Spec, wf: Spec) {
  if (!["FLYBACK", "QR-FLYBACK", "ACF-FORWARD"].includes(p.topology))
    return null;
  const children = op.output_ops || [op],
    cfg = resolvedParasitics(p, children.length),
    data: Spec = {
      mode: cfg.mode,
      parameters: cfg,
      note: parasiticNote,
      edges: [],
    };
  op.parasitics = data;
  if (cfg.mode === "fast") return data;
  if (p.topology === "ACF-FORWARD") {
    if (!op.acf_solution) throw Error("正激寄生细算需要两两 kij 物理周期模型");
    data.scope =
      "正激寄生与 RC 吸收进入同一 MNA 周期，附加布线/吸收电阻损耗计入效率。";
    return data;
  }
  if (p.feedback_mode !== "SSR")
    throw Error("PSR 的局部高频寄生不在原模型验证范围");
  if (p.topology === "QR-FLYBACK" && children.length > 1)
    throw Error("QR 多路谷底寄生尚不在原模型适用范围");
  const model = windingMatrix(p, op, !p.coupling_config?.enabled),
    L = model.L,
    leakage = (j: number) => {
      if (model.ideal) return 0;
      const rest = L.map((_: any, i: number) => i).filter(
        (i: number) => i !== j,
      );
      return Math.max(
        0,
        L[j][j] -
          dot(
            rest.map((i: number) => L[j][i]),
            solve(
              rest.map((i: number) => rest.map((k: number) => L[i][k])),
              rest.map((i: number) => L[i][j]),
            ),
          ),
      );
    };
  const clamp = op.clamp || {},
    params = {
      inductance: leakage(0) + cfg.lp_pcb,
      capacitance: cfg.coss + cfg.cw_primary,
      resistance: model.R[0] + cfg.rp_pcb,
      current: op.I_sw_off ?? op.I_sw_pk,
      plateau: clamp.V_plateau ?? op.V_in + op.V_r,
      ceiling: p.Kc > 1 ? clamp.V_ceiling : undefined,
      snub_r: cfg.snub_r_primary,
      snub_c: cfg.snub_c_primary,
      duration: (1 - op.D) * op.Ts,
    };
  const trace: Spec = { ...solveEdge(params), ref: "Q1", parameters: params };
  data.edges.push(trace);
  op.V_sw_max = Math.max(op.V_sw_max, trace.peak);
  children.forEach((c: Spec, j: number) => {
    const r = cfg.rails[j],
      w = (wf.outputs || [wf])[j],
      pa = {
        inductance: leakage(j + 1) + r.l_pcb,
        capacitance: r.cj + r.cw,
        resistance: model.R[j + 1] + r.r_pcb + cfg.r_cj,
        current: Math.max(w.i_d.at(-1), 0),
        plateau: c.V_d_max,
        initial_voltage: 0,
        snub_r: r.snub_r,
        snub_c: r.snub_c,
        duration: op.D * op.Ts,
      },
      tr: Spec = {
        ...solveEdge(pa),
        ref: p.outputs.length ? "D_O" + (j + 1) : "D1",
        parameters: pa,
      };
    data.edges.push(tr);
    c.V_d_max = Math.max(c.V_d_max, tr.peak);
    if (j === (p.feedback_output || 1) - 1) op.V_d_max = c.V_d_max;
  });
  if (p.topology === "QR-FLYBACK") {
    const pa = {
      inductance: p.L,
      capacitance: cfg.coss + cfg.cw_primary,
      resistance: model.R[0] + cfg.rp_pcb,
      current: 0,
      plateau: op.V_in,
      initial_voltage: op.V_in + op.V_r,
      duration: op.T_ring,
    };
    data.edges.push({
      ...solveEdge(pa),
      ref: "Q1 · 退磁后首谷底",
      parameters: pa,
    });
  }
  data.scope =
    "各开关沿独立端口 RLC，非多端口完整同时解。Q1 为理想定压钳位；整流支路未含反向恢复，不构成严格应力上界。未迭代吸收损耗，不更改平均电流、直流输出或低频环路。";
  wf.parasitics = data;
  return data;
}
