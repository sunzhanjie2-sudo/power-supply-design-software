import { nisoPlant } from "./nonisolated";
import { type Spec, bank } from "./spec";
import { Circuit, integrals } from "./coupled";
import {
  type Gain,
  type System,
  systemGain,
  periodSystem,
  eigenvalues,
  closeLoop,
  frequencySystem,
  stepResponse,
} from "./state_space";
import { controllerSystem, nominalSystem } from "./nominal_system";
import { designPSR, psrCompensation } from "./psr";
import {
  type C,
  type Matrix,
  cadd,
  cmul,
  cdiv,
  cabs,
  zeros,
  eye,
  add,
  scale,
  mm,
  mv,
  inverse,
  outer,
  solve,
  clamp,
} from "./math";
const plus = (...values: C[]) => values.reduce(cadd, [0, 0] as C),
  num = (x: number): C => [x, 0];
function complexSolve(a: C[][], b: C[]) {
  const n = b.length,
    m = zeros(2 * n);
  for (let i = 0; i < n; i++)
    for (let j = 0; j < n; j++) {
      m[i][j] = m[i + n][j + n] = a[i][j][0];
      m[i + n][j] = a[i][j][1];
      m[i][j + n] = -a[i][j][1];
    }
  const x = solve(m, [...b.map((v) => v[0]), ...b.map((v) => v[1])]);
  return x.slice(0, n).map((v, i) => [v, x[i + n]] as C);
}
export function compensator(p: Spec, frequency: number): C {
  if (p._psr) {
    p = {
      ...p,
      KP: p._psr.KP,
      fz1: p._psr.fz,
      fp1: p._psr.fp,
      controller_type: "type2",
    };
  }
  const s: C = [0, 2 * Math.PI * frequency],
    factor = (f: number) => plus(num(1), cdiv(s, num(2 * Math.PI * f))),
    type =
      p.controller_type === "type3" ||
      (p.controller_type === "auto" && p.control_mode === "Voltage Mode")
        ? "type3"
        : "type2";
  let g = cdiv(num(p.KP), s);
  g = cmul(g, cdiv(factor(p.fz1), factor(p.fp1)));
  if (type === "type3") g = cmul(g, cdiv(factor(p.fz2), factor(p.fp2)));
  return g;
}
function nominalPlant(p: Spec, op: Spec): Gain {
  const q = op.aggregate_params || p,
    o = op.aggregate_op || op,
    v = q.V_in,
    u = o.V_out_equiv,
    r = (u * u) / o.P_in_est,
    l = q.L,
    n = q.N,
    d =
      op.topology === "FLYBACK"
        ? (n * u) / (v + n * u)
        : op.topology === "BOOST"
          ? 1 - v / u
          : op.topology === "BUCK-BOOST"
            ? u / (v + u)
            : u / (op.topology === "ACF-FORWARD" ? v / n : v),
    dp = 1 - d,
    c = op.outputs?.length
      ? op.outputs.reduce(
          (s: number, r: Spec) =>
            s + bank(r).reduce((s, x) => s + x.C, 0) * (r.V_out / o.V_out) ** 2,
          0,
        )
      : q.output_capacitors != null
        ? bank(q).reduce((s, x) => s + x.C, 0)
        : q.C_out,
    fi = q.Rs * q.A_sense;
  return (frequency) => {
    const s: C = [0, 2 * Math.PI * frequency],
      s2 = cmul(s, s),
      eta = o.eta_guess,
      kind = p.topology;
    if (kind === "QR-FLYBACK" && p.control_mode === "Peak Current Mode") {
      const vr = o.V_r,
        ip = o.I_sw_pk,
        t = o.Ts,
        a = l * (1 / v + 1 / vr),
        io = o.I_out,
        di = io * (2 / ip - a / t),
        dv = io * (-n / vr + (l * ip * n) / (vr * vr * t));
      let adm = num(1 / o.R - dv);
      for (const cap of bank(q))
        adm = plus(
          adm,
          cdiv(
            cmul(s, num(cap.C)),
            plus(num(1), cmul(s, num(cap.ESR * cap.C))),
          ),
        );
      return cdiv(num(di / fi), adm);
    }
    if (o.mode === "DCM" || o.mode === "BCM") {
      let gain = u / op.D,
        pole = 2 / (r * c);
      if (kind === "BUCK") {
        const m = u / v;
        gain = (((2 * u) / op.D) * (1 - m)) / (2 - m);
        pole = (2 - m) / ((1 - m) * r * c);
      }
      if (kind === "BOOST") {
        const m = u / v;
        gain = (((2 * u) / op.D) * (m - 1)) / (2 * m - 1);
        pole = (2 * m - 1) / ((m - 1) * r * c);
      }
      return cdiv(num((gain / q.Vm) * eta), plus(num(1), cdiv(s, num(pole))));
    }
    let m1 = v / l,
      m2 =
        kind === "BOOST"
          ? (u - v) / l
          : kind === "FLYBACK"
            ? (n * u) / l
            : u / l,
      denSlope = q.ma_slope + (m1 - m2) / 2;
    if (denSlope <= 0) denSlope = (m1 + m2) / 2;
    const fm = o.f_sw / (fi * Math.max(Math.abs(denSlope), 1));
    if (kind === "BUCK" || kind === "ACF-FORWARD") {
      const input = kind === "ACF-FORWARD" ? v / n : v,
        dd = u / input,
        fv = ((1 - 2 * dd) * o.Ts * fi) / (2 * l);
      if (p.control_mode === "Voltage Mode")
        return cdiv(
          num((input / q.Vm) * eta),
          plus(num(1), cmul(s, num(l / r)), cmul(s2, num(l * c))),
        );
      const t1 = (fm * u * fi) / (dd * r),
        t2 = (fm * fv * u) / dd,
        w = (1 / Math.sqrt(l * c)) * Math.sqrt(1 + t1 + t2),
        quality =
          (r * Math.sqrt(c / l) * Math.sqrt(1 + t1 + t2)) /
          (1 + (r * c * fm * u * fi) / dd / l),
        g = (u * fm) / dd / (1 + t1 + t2);
      return cdiv(
        num(g * eta),
        plus(num(1), cdiv(s, num(quality * w)), cdiv(s2, num(w * w))),
      );
    }
    if (kind === "FLYBACK" || kind === "BUCK-BOOST") {
      const ratio = kind === "FLYBACK" ? n : 1,
        delta = plus(
          num(1),
          cmul(s, num(l / (ratio * dp) ** 2 / r)),
          cmul(s2, num((l * c) / (ratio * dp) ** 2)),
        ),
        gvd = cdiv(
          cmul(
            num(u / d / dp),
            plus(num(1), cmul(s, num((-d * l) / (ratio * dp) ** 2 / r))),
          ),
          delta,
        );
      if (p.control_mode === "Voltage Mode") return cmul(num(eta / q.Vm), gvd);
      const fv = (-dp * dp * o.Ts * fi) / (2 * l),
        gid = cdiv(
          cmul(
            num((ratio * u * (1 + d)) / d / (ratio * dp) ** 2 / r),
            plus(num(1), cmul(s, num((r * c) / (1 + d)))),
          ),
          delta,
        );
      return cmul(
        num(eta),
        cdiv(
          cmul(num(fm), gvd),
          plus(
            num(1),
            cmul(num(fm), plus(cmul(num(fi), gid), cmul(num(fv), gvd))),
          ),
        ),
      );
    }
    const fv = (dp * dp * o.Ts * fi) / (2 * l),
      t1 = (2 * fm * u * fi) / (dp * dp * r),
      t2 = (fm * fv * u) / dp,
      w = (dp / Math.sqrt(l * c)) * Math.sqrt(1 + t1 + t2),
      quality =
        (dp * r * Math.sqrt(c / l) * Math.sqrt(1 + t1 + t2)) /
        (1 + (r * c * fm * u * fi) / (dp * l) - (fm * fv * u) / dp),
      gain = (u * fm) / dp / (1 + t1 + t2),
      numerator = plus(num(1), cmul(s, num(-l / dp ** 2 / r)));
    return p.control_mode === "Voltage Mode"
      ? cmul(
          num(eta),
          cdiv(
            cmul(num(u / dp / q.Vm), numerator),
            plus(
              num(1),
              cmul(s, num(l / dp ** 2 / r)),
              cmul(s2, num((l * c) / dp ** 2)),
            ),
          ),
        )
      : cmul(
          num(eta),
          cdiv(
            cmul(num(gain), numerator),
            plus(num(1), cdiv(s, num(quality * w)), cdiv(s2, num(w * w))),
          ),
        );
  };
}
export function coupledPlant(
  p: Spec,
  op: Spec,
): { gain: Gain; metadata: Spec } {
  const meta = op.coupled_model,
    sol = op.coupled_solution,
    rr = op.outputs,
    n = rr.length,
    t = op.Ts,
    d = op.D,
    vc: number[] = meta.capacitor_voltages,
    loads: number[] = meta.load_resistances,
    block: number[] = meta.output_blocking_drops,
    caps = rr.map((r: Spec) => bank(r).reduce((s, c) => s + c.C, 0)),
    scales = [
      ...sol.i_winding.slice(1).map((a: number[]) => Math.max(...a, 0.01)),
      ...vc.map((v) => Math.max(v, 0.01)),
    ],
    state = [
      ...sol.i_winding.slice(1).map((a: number[]) => Math.max(a[0], 0)),
      ...vc,
    ].map((v, i) => v / scales[i]),
    circuit = new Circuit(
      meta.L,
      meta.R,
      meta.input_bus_voltage,
      rr.map((r: Spec) => r.Vf_diode),
      p.Rds_on,
      p.Rs,
      meta.clamp_voltage,
      t,
    );
  const evaluate = (x: number[], duty: number) => {
    const physical = x.map((v, i) => v * scales[i]),
      start = physical.slice(0, n),
      v = physical.slice(n);
    if (start.some((v) => v < 0) || v.some((v) => v <= 0))
      throw Error("环路扰动超出合法周期状态");
    const cycle = circuit.cycle(start, v, duty),
      q = integrals(cycle.segments, n + 1, false).charge.slice(1),
      next = v.map(
        (v, i) => v + (q[i] - (t * (v - block[i])) / loads[i]) / caps[i],
      ),
      on = cycle.segments.filter((s) => s.on && s.active.includes(0)),
      last = on.at(-1);
    if (!last) throw Error("没有可线性化的导通段");
    const peak = last.flow!.values(last.initial, last.voltage, last.dt).current[
        last.active.indexOf(0)
      ],
      threshold = p.Rs * p.A_sense * (peak + p.ma_slope * duty * t);
    return {
      next: [...cycle.end.slice(1), ...next].map((v, i) => v / scales[i]),
      threshold,
    };
  };
  const baseline = evaluate(state, d),
    a = zeros(2 * n),
    hx = Array(2 * n).fill(0),
    step = 5e-5;
  for (let j = 0; j < 2 * n; j++) {
    const hi = [...state],
      lo = [...state];
    hi[j] += step;
    let span = 2 * step,
      lower;
    if (j < n && state[j] < step) {
      lower = baseline;
      span = step;
    } else {
      lo[j] -= step;
      lower = evaluate(lo, d);
    }
    const upper = evaluate(hi, d);
    for (let i = 0; i < 2 * n; i++)
      a[i][j] = (upper.next[i] - lower.next[i]) / span;
    hx[j] = (upper.threshold - lower.threshold) / span;
  }
  const h = Math.min(step, d / 4, (1 - d) / 4),
    upper = evaluate(state, d + h),
    lower = evaluate(state, d - h),
    bd = upper.next.map((v, i) => (v - lower.next[i]) / (2 * h)),
    hd = (upper.threshold - lower.threshold) / (2 * h),
    ai = a.slice(0, n).map((row) => row.slice(0, n)),
    bi = a
      .slice(0, n)
      .map((row, i) => [
        ...row.slice(n).map((v, j) => v / scales[n + j]),
        bd[i],
      ]),
    inv = inverse(add(eye(n), ai)),
    ax = scale(mm(add(ai, eye(n), -1), inv), 2 / t),
    bx = scale(mm(inv, bi), 2 / t),
    chargeScale = caps.map((c: number, i: number) => (c * scales[n + i]) / t),
    ji = a
      .slice(n)
      .map((row, i) => row.slice(0, n).map((v) => v * chargeScale[i])),
    jv = a
      .slice(n)
      .map((row, i) =>
        row
          .slice(n)
          .map(
            (v, j) =>
              (chargeScale[i] * (v - +(i === j))) / scales[n + j] +
              (i === j ? 1 / loads[i] : 0),
          ),
      ),
    jd = bd.slice(n).map((v, i) => chargeScale[i] * v),
    jx = scale(mm(ji, inv), 2),
    jfeed = add(
      jv.map((row, i) => [...row, jd[i]]),
      mm(mm(ji, inv), bi),
      -1,
    ),
    hcurrent = mv(transposeForVector(inv), hx.slice(0, n)).map((v) => 2 * v),
    hfeed = [...hx.slice(n).map((v, j) => v / scales[n + j]), hd].map(
      (v, j) => v - dotRow(hx.slice(0, n), mm(inv, bi), j),
    ),
    main = (op.feedback_output || 1) - 1,
    peak = p.control_mode === "Peak Current Mode";
  if (peak && hd <= 1e-8) throw Error("峰值采样斜率非正，不能建立环路");
  const gain: Gain = (frequency) => {
    const s: C = [0, 2 * Math.PI * frequency],
      size = 2 * n + 1,
      matrix: C[][] = Array.from({ length: size }, () =>
        Array.from({ length: size }, () => [0, 0] as C),
      ),
      rhs = Array.from({ length: size }, () => [0, 0] as C);
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) {
        matrix[i][j] = plus(i === j ? s : num(0), num(-ax[i][j]));
        matrix[i][n + j] = num(-bx[i][j]);
      }
      matrix[i][2 * n] = num(-bx[i][n]);
      let adm = num(1 / loads[i]);
      for (const cap of bank(rr[i]))
        adm = plus(
          adm,
          cdiv(
            cmul(s, num(cap.C)),
            plus(num(1), cmul(s, num(cap.ESR * cap.C))),
          ),
        );
      for (let j = 0; j < n; j++) {
        matrix[n + i][j] = num(-jx[i][j]);
        matrix[n + i][n + j] = plus(i === j ? adm : num(0), num(-jfeed[i][j]));
      }
      matrix[n + i][2 * n] = num(-jfeed[i][n]);
    }
    for (let j = 0; j < n; j++) {
      matrix[2 * n][j] = num(peak ? hcurrent[j] : 0);
      matrix[2 * n][n + j] = num(peak ? hfeed[j] : 0);
    }
    matrix[2 * n][2 * n] = num(peak ? hfeed[n] : p.Vm);
    rhs[2 * n] = num(1);
    return complexSolve(matrix, rhs)[n + main];
  };
  gain.system = periodSystem(
    ax,
    bx,
    jx,
    jfeed,
    hcurrent,
    hfeed,
    rr,
    loads,
    vc,
    peak,
    p.Vm,
  );
  return {
    gain,
    metadata: {
      kind: "coupled-period-map",
      experimental: true,
      inner_spectral_radius: Math.max(
        ...eigenvalues(
          peak
            ? add(ai, scale(outer(bd.slice(0, n), hx.slice(0, n)), -1 / hd))
            : ai,
        ).map((v) => Math.hypot(...v)),
      ),
      revision: "independent-parallel-rc-v1",
      feedback_output: main + 1,
      esr_included: true,
      bandwidth_limit_enabled: false,
      frequency_limit: null,
      outputs: rr.map((r: Spec, i: number) => ({
        id: r.id,
        name: r.name,
        voltage: vc[i] - block[i],
        current: (vc[i] - block[i]) / loads[i],
      })),
      assumptions:
        "完整绕组周期映射线性化，逐颗 C+ESR 导纳联立；仅主反馈闭环，不含 ESL、光耦和大信号模式切换。",
    },
  };
}
function transposeForVector(a: Matrix) {
  return a[0].map((_, j) => a.map((row) => row[j]));
}
function dotRow(a: number[], b: Matrix, j: number) {
  return a.reduce((s, v, i) => s + v * b[i][j], 0);
}
function forwardPlant(p: Spec, op: Spec): { gain: Gain; metadata: Spec } {
  const meta = op.acf_model,
    n = op.outputs.length,
    s = meta.state_initial.length,
    T = op.Ts;
  if (!meta.current_mesh_verified)
    throw Error("此角点高频电流网格尚未收敛，不输出有效环路裕度");
  const slopes = p.spice_config || {},
    design = Math.max(0, p.ma_slope) * p.Rs * p.A_sense,
    recommended =
      0.75 *
      op.outputs.reduce(
        (sum: number, r: Spec, j: number) =>
          sum +
          (((r.V_out + r.Vf_diode + (r.d_out_enable ? r.Vf_dout : 0)) / r.L) *
            meta.transformer_hardware.windings[j].Ns) /
            meta.transformer_hardware.Np,
        0,
      ) *
      p.Rs *
      p.A_sense,
    actual =
      slopes.slope_mode === 2
        ? slopes.slope
        : slopes.slope_mode === 1 && p.control_mode === "Peak Current Mode"
          ? Math.max(design, recommended)
          : design;
  const h: number[] = [...meta.threshold_jac];
  h[h.length - 1] += (actual - meta.linearization_slope) * T;
  const sc: number[] = meta.state_scales,
    a = meta.period_jac.map((r: number[], i: number) =>
      r.slice(0, s).map((v, j) => (v * sc[j]) / sc[i]),
    ),
    b = meta.period_jac.map((r: number[], i: number) =>
      r.slice(s).map((v) => v / sc[i]),
    ),
    ji = meta.charge_jac.map((r: number[]) =>
      r.slice(0, s).map((v, j) => v * sc[j]),
    ),
    feed = meta.charge_jac.map((r: number[]) => r.slice(s)),
    hi = h.slice(0, s).map((v, j) => v * sc[j]),
    hf = h.slice(s),
    inv = inverse(add(eye(s), a)),
    ax = scale(mm(add(a, eye(s), -1), inv), 2 / T),
    bx = scale(mm(inv, b), 2 / T),
    jx = scale(mm(ji, inv), 2),
    jf = add(feed, mm(mm(ji, inv), b), -1),
    hx = mm([hi], inv)[0].map((v) => 2 * v),
    hfeed = hf.map((v, j) => v - mm(mm([hi], inv), b)[0][j]),
    peak = p.control_mode === "Peak Current Mode",
    sys = periodSystem(
      ax,
      bx,
      jx,
      jf,
      hx,
      hfeed,
      op.outputs,
      meta.load_resistances,
      op.output_ops.map((r: Spec) => r.V_out_cap),
      peak,
      p.Vm,
    );
  const sampling = peak
      ? add(
          a,
          scale(
            outer(
              b.map((r: number[]) => r.at(-1)!),
              hi,
            ),
            -1 / h.at(-1)!,
          ),
        )
      : a,
    radius = Math.max(...eigenvalues(sampling).map((v) => Math.hypot(...v)));
  return {
    gain: systemGain(sys, (op.feedback_output || 1) - 1),
    metadata: {
      kind: "acf-periodic-MNA",
      revision: 1,
      experimental: true,
      feedback_output: op.feedback_output,
      esr_included: true,
      capacitor_banks: sys.banks,
      inner_spectral_radius: radius,
      state_count: sys.A.length,
      outputs: op.outputs.map((r: Spec, j: number) => ({
        id: r.id,
        name: r.name,
        voltage: op.output_ops[j].V_out,
        current: op.output_ops[j].I_out,
      })),
      slope_v_per_s: actual,
      frequency_limit: null,
      bandwidth_limit_enabled: false,
      assumptions:
        "正激两两互感、物理钳位和输出电感周期解线性化；逐颗并联 C+ESR 独立状态，仅所选主路反馈；采样核取励磁与反射负载电流包络。低频周期平均模型，高频需实测 FRA。",
    },
  };
}
export function loopResponse(p: Spec, op: Spec, loadOutput = 1): Spec {
  const g = plant(p, op),
    raw = g.gain.system,
    fb = (op.feedback_output || 1) - 1;
  if (!raw) throw Error("当前没有可用状态空间模型");
  if (op.psr) p = { ...p, _psr: op.psr };
  const actual = op.coupled_model?.converged || op.acf_model?.converged,
    closed = closeLoop(raw, controllerSystem(p), actual ? fb : 0),
    f = Array.from({ length: 320 }, (_, i) => 10 ** (-2 + (8 * i) / 319)),
    rows: Spec[] = [],
    n = op.outputs?.length || 1;
  if (loadOutput < 1 || loadOutput > n) throw Error("负载扰动编号超出输出范围");
  const freq = f.map((v) => frequencySystem(closed, v));
  for (let i = 0; i < n; i++) {
    const ratio = actual
        ? g.metadata.outputs[fb].voltage / g.metadata.outputs[i].voltage
        : 1,
      ref = freq.map((v) => v[actual ? i : 0][0].map((x) => x * ratio) as C),
      ld = actual ? freq.map((v) => v[i][loadOutput]) : null;
    const phase = (a: C[]) => {
      let prev = 0,
        offset = 0;
      return a.map((v, j) => {
        const z = (Math.atan2(v[1], v[0]) * 180) / Math.PI;
        if (j && z + offset - prev > 180) offset -= 360;
        if (j && z + offset - prev < -180) offset += 360;
        return (prev = z + offset);
      });
    };
    rows.push({
      id: i + 1,
      reference_db: ref.map((v) => 20 * Math.log10(Math.max(cabs(v), 1e-300))),
      reference_phase: phase(ref),
      load_db:
        ld?.map((v) => 20 * Math.log10(Math.max(cabs(v), 1e-300))) || null,
      load_phase: ld ? phase(ld) : null,
    });
  }
  const poles = eigenvalues(closed.A),
    stable = poles.every((v) => v[0] < 0),
    dominant = Math.max(...poles.map((v) => v[0]));
  const transient = stable
    ? stepResponse(
        closed,
        0,
        Math.min(10, Math.max(0.001, 7 / Math.abs(dominant))),
        600,
      )
    : null;
  return {
    frequency: f,
    outputs: rows,
    feedback_output: fb + 1,
    load_output: loadOutput,
    dc_load: actual
      ? frequencySystem(closed, 0).map((r) => r.slice(1).map((v) => v[0]))
      : null,
    model: g.metadata,
    closed_loop_stable: stable,
    closed_loop_poles: poles,
    reference_step: transient,
    notes: [
      "只闭合主反馈路，各路共用同一闭环分母；负载响应为局部小信号。",
      ...(actual
        ? []
        : ["标称理想匝比模型没有独立负载动态，未生成虚假负载响应。"]),
      ...(!stable ? ["闭环极点不稳定，未生成看似收敛的阶跃曲线。"] : []),
    ],
  };
}
export function plant(p: Spec, op: Spec) {
  if (p.feedback_mode === "PSR-MP6005") {
    if (op.regulation_region !== "PWM")
      throw Error("MP6005 轻载 PFM：不提供 PWM/SSR Bode 裕度");
    const base = nominalPlant(p, op),
      d = op.psr;
    if (!d) throw Error("PSR 物理网络未计算");
    const gain: Gain = (f: number) => {
      const s: C = [0, 2 * Math.PI * f],
        delay = cdiv(
          plus(num(1), cmul(s, num(-op.Ts / 4))),
          plus(num(1), cmul(s, num(op.Ts / 4))),
        );
      return cmul(base(f), cmul(num(d.Hfb), delay));
    };
    gain.system = nominalSystem(p, op);
    return {
      gain,
      metadata: {
        kind: "mp6005-psr-pwm",
        assumptions: d.note,
        esr_included: false,
      },
    };
  }
  if (op.acf_model?.converged) return forwardPlant(p, op);
  if (op.niso_model)
    return {
      gain: nisoPlant(p, op),
      metadata: {
        kind: op.niso_model.kind,
        esr_included: true,
        assumptions: "冻结被动周期解及峰值采样线性化。",
      },
    };
  return op.coupled_model?.converged
    ? coupledPlant(p, op)
    : {
        gain: Object.assign(nominalPlant(p, op), {
          system: nominalSystem(p, op),
        }),
        metadata: {
          kind: "nominal-average",
          esr_included: p.topology === "QR-FLYBACK",
          assumptions: "沿用 Python 标称平均模型；预设效率等效负担。",
        },
      };
}
export function analyze(p: Spec, op: Spec) {
  if (op.psr) p = { ...p, _psr: op.psr };
  const g = plant(p, op),
    f = Array.from({ length: 900 }, (_, i) => 10 ** (-2 + (8 * i) / 899)),
    gains = f.map((h) => {
      const a = g.gain(h),
        b = compensator(p, h);
      return [a, b, cmul(a, b)];
    }),
    phases = [0, 1, 2].map((j) => {
      let previous = 0,
        offset = 0;
      return gains.map((values, i) => {
        let phase = (Math.atan2(values[j][1], values[j][0]) * 180) / Math.PI;
        if (i && phase + offset - previous > 180) offset -= 360;
        if (i && phase + offset - previous < -180) offset += 360;
        previous = phase + offset;
        return previous;
      });
    }),
    db = gains.map((x) => 20 * Math.log10(Math.max(cabs(x[2]), 1e-300))),
    crosses: Spec[] = [],
    margins: number[] = [];
  for (let i = 0; i < f.length - 1; i++) {
    if (db[i] * db[i + 1] <= 0 && db[i] !== db[i + 1]) {
      const k = -db[i] / (db[i + 1] - db[i]);
      crosses.push({
        fc: f[i] * (f[i + 1] / f[i]) ** k,
        pm: 180 + phases[2][i] + k * (phases[2][i + 1] - phases[2][i]),
        direction: db[i + 1] < db[i] ? "down" : "up",
      });
    }
    if ((phases[2][i] + 180) * (phases[2][i + 1] + 180) < 0) {
      const k = (-180 - phases[2][i]) / (phases[2][i + 1] - phases[2][i]);
      margins.push(-(db[i] + k * (db[i + 1] - db[i])));
    }
  }
  const selected = crosses
    .filter((c) => c.direction === "down")
    .sort(
      (a, b) =>
        Math.abs(Math.log(a.fc / (p.fc_target || 1000))) -
        Math.abs(Math.log(b.fc / (p.fc_target || 1000))),
    )[0];
  let poles: C[] | null = null,
    poleError: string | null = null;
  try {
    if (g.gain.system) {
      const closed = closeLoop(
        g.gain.system,
        controllerSystem(p),
        op.coupled_model || op.acf_model ? (op.feedback_output || 1) - 1 : 0,
      );
      poles = eigenvalues(closed.A);
    }
  } catch (e) {
    poleError = String(e);
  }
  return {
    f,
    gains,
    phases,
    fc: selected?.fc ?? null,
    pm: selected?.pm ?? null,
    min_pm: crosses.length ? Math.min(...crosses.map((c) => c.pm)) : null,
    gm_db: margins.length ? Math.min(...margins) : null,
    gm_infinite: false,
    gm_scan_limited: true,
    closed_loop_stable: poles ? poles.every((v) => v[0] < 0) : null,
    closed_loop_poles: poles,
    pole_error: poleError,
    all_crosses: crosses,
    model: g.metadata,
  };
}
export function tune(p: Spec, op: Spec, fc: number, pm: number, type = "auto") {
  if (!(fc > 0 && pm > 0 && pm < 180))
    throw Error("请填写合法穿越频率和相位裕度");
  const source = plant(p, op),
    g = source.gain;
  if (
    source.metadata.experimental &&
    source.metadata.inner_spectral_radius >= 1
  )
    throw Error("周期内环谱半径≥1，请先修正斜坡补偿");
  fc = Math.min(
    fc,
    op.f_sw / (op.psr ? 10 : 6),
    p.topology === "ACF-FORWARD" ? op.fc_recommended_max : Infinity,
  );
  if (op.psr) type = "type2";
  else if (type === "auto")
    type = p.control_mode === "Peak Current Mode" ? "type2" : "type3";
  let previous = 0,
    offset = 0;
  for (let i = 0; i < 400; i++) {
    const gain = g(
      Math.max(fc / 100, 1e-3) * (fc / Math.max(fc / 100, 1e-3)) ** (i / 399),
    );
    let phase = (Math.atan2(gain[1], gain[0]) * 180) / Math.PI;
    if (i && phase + offset - previous > 180) offset -= 360;
    if (i && phase + offset - previous < -180) offset += 360;
    previous = phase + offset;
  }
  if (previous > 90) previous -= 360;
  const required = pm - 90 - previous,
    kind = type === "auto" ? (required <= 75 ? "type2" : "type3") : type,
    boost = clamp(
      required,
      kind === "type2" ? -89.999 : -170,
      kind === "type2" ? 89.999 : 170,
    ),
    k =
      kind === "type2"
        ? Math.tan(((45 + boost / 2) * Math.PI) / 180)
        : Math.tan(((45 + boost / 4) * Math.PI) / 180) ** 2,
    fz = fc / (kind === "type2" ? k : Math.sqrt(k)),
    fp = fc * (kind === "type2" ? k : Math.sqrt(k)),
    draft = {
      ...p,
      KP: 1,
      fz1: fz,
      fp1: fp,
      fz2: fz,
      fp2: fp,
      controller_type: kind,
    },
    kp = 1 / cabs(cmul(g(fc), compensator(draft, fc)));
  const updates: Spec = {
    KP: kp,
    fz1: fz,
    fp1: fp,
    ...(kind === "type3" ? { fz2: fz, fp2: fp } : {}),
    controller_type: kind,
    fc_target: fc,
    pm_target: pm,
  };
  const candidate = { ...p, ...updates },
    candidateOp = { ...op };
  if (op.psr) {
    Object.assign(
      updates,
      psrCompensation({ KP: kp, fz1: fz, fp1: fp, comp_type: kind }),
    );
    Object.assign(candidate, updates);
    candidateOp.psr = designPSR(candidate, candidateOp);
    delete updates.KP;
    delete updates.fz1;
    delete updates.fp1;
    delete updates.controller_type;
  }
  const achieved = analyze(candidate, candidateOp),
    feasible =
      boost === required &&
      achieved.closed_loop_stable === true &&
      achieved.min_pm !== null &&
      achieved.min_pm >= pm - 1;
  return {
    spec_updates: feasible ? updates : {},
    KP: kp,
    fz1: fz,
    fp1: fp,
    comp_type: kind,
    boost,
    K: k,
    required_boost: required,
    feasible,
    achieved: {
      fc: achieved.fc,
      pm: achieved.pm,
      min_pm: achieved.min_pm,
      closed_loop_stable: achieved.closed_loop_stable,
      closed_loop_poles: achieved.closed_loop_poles,
      gm_db: achieved.gm_db,
    },
    fc,
    pm,
    notes:
      fp < fz
        ? ["本工作点要求相位滞后，极点低于零点；物理补偿电路须另核对可实现性。"]
        : feasible
          ? []
          : [
              "候选未通过所需相位提升、全部穿越裕度或闭环极点检查，未提出写回参数。",
            ],
  };
}
