/** Buck/Boost passive periodic C+ESR model. Reference: nonisolated.py. */
import { type Spec, bank, blockDrop, inputDrop } from "./spec";
import { inductor } from "./magnetics";
import { type Gain } from "./state_space";
import {
  zeros,
  eye,
  mm,
  mv,
  expm,
  solve,
  root,
  leastSquares,
  add,
  inverse,
  scale,
  outer,
  mean,
  rms,
  ptp,
  type C,
  cadd,
} from "./math";
export function outputFilter(p: Spec, load: number, voltage: number) {
  const caps = bank(p),
    finite = caps.filter((c) => c.ESR > 0),
    ideal = caps.filter((c) => c.ESR === 0).reduce((s, c) => s + c.C, 0),
    size = finite.length + (ideal ? 1 : 0),
    a = zeros(size),
    b = Array(size).fill(0),
    c = Array(size).fill(0);
  let d = 0;
  if (ideal) {
    a[0][0] = -(1 / load + finite.reduce((s, c) => s + 1 / c.ESR, 0)) / ideal;
    b[0] = 1 / ideal;
    c[0] = 1;
    finite.forEach((cap, i) => {
      const j = i + 1;
      a[0][j] = 1 / (ideal * cap.ESR);
      a[j][0] = 1 / (cap.C * cap.ESR);
      a[j][j] = -1 / (cap.C * cap.ESR);
    });
  } else {
    const conductance = finite.map((c) => 1 / c.ESR);
    d = 1 / (1 / load + conductance.reduce((s, v) => s + v, 0));
    finite.forEach((cap, i) => {
      c[i] = conductance[i] * d;
      b[i] = d / (cap.ESR * cap.C);
      for (let j = 0; j < size; j++)
        a[i][j] = (conductance[j] * d - +(i === j)) / (cap.ESR * cap.C);
    });
  }
  return {
    A: a,
    B: b.map((v) => v / voltage),
    C: c.map((v) => v * voltage),
    D: d,
  };
}
export function effective(p: Spec) {
  const cfg = p.spice_config || {},
    profile = cfg.niso_profile,
    q: Spec = { ...p, f_sw: cfg.frequency_hz || p.f_sw, A_sense: 1 };
  const expected =
    profile === 1
      ? ["BUCK", "Voltage Mode"]
      : profile === 2
        ? ["BUCK", "Peak Current Mode"]
        : profile === 3
          ? ["BOOST", "Peak Current Mode"]
          : null;
  if (!expected || p.topology !== expected[0] || p.control_mode !== expected[1])
    throw Error(
      "控制器原型与拓扑 / 控制模式不一致，请选择对应的 Buck 或 Boost 参考配置。",
    );
  if (profile === 1)
    q.Vm = (p.V_in - inputDrop(p)) * (cfg.niso_ramp_ratio ?? 0.1);
  return q;
}
class Kernel {
  T: number;
  R: number;
  block: number;
  target: number;
  bus: number;
  f: ReturnType<typeof outputFilter>;
  n: number;
  phases: number[][][];
  constructor(
    public p: Spec,
    public dcr: number,
  ) {
    this.T = 1 / p.f_sw;
    this.R = p.V_out ** 2 / p.P_out;
    this.block = blockDrop(p);
    this.target = p.V_out + this.block;
    this.bus = p.V_in - inputDrop(p);
    this.f = outputFilter(p, this.R, this.target);
    this.n = this.f.A.length + 1;
    this.phases = [this.matrix(true), this.matrix(false), this.matrix(null)];
  }
  matrix(on: boolean | null) {
    const p = this.p,
      n = this.n,
      f = this.f,
      a = zeros(n),
      b = Array(n).fill(0),
      injection = on === null || (p.topology === "BOOST" && on) ? 0 : 1,
      c = [f.D * injection, ...f.C],
      v0 = (f.D * this.block) / this.R;
    for (let i = 1; i < n; i++) {
      a[i][0] = f.B[i - 1] * injection;
      b[i] = (f.B[i - 1] * this.block) / this.R;
      for (let j = 1; j < n; j++) a[i][j] = f.A[i - 1][j - 1];
    }
    if (on !== null) {
      const resistance = this.dcr + (on ? p.Rs + p.Rds_on : 0.001),
        sees = p.topology === "BUCK" || !on;
      a[0][0] = -resistance / p.L;
      if (sees) for (let j = 0; j < n; j++) a[0][j] -= c[j] / p.L;
      b[0] =
        ((on || p.topology === "BOOST" ? this.bus : 0) -
          (on ? 0 : p.Vf_diode) -
          (sees ? v0 : 0)) /
        p.L;
    }
    const m = zeros(n + 2);
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) m[i][j] = a[i][j];
      m[i][n + 1] = b[i];
      m[n][i] = c[i];
    }
    m[n][n + 1] = v0;
    return m;
  }
  flow(x: number[], phase: number, t: number) {
    const z = mv(expm(scale(this.phases[phase], t)), [...x, 0, 1]);
    return { state: z.slice(0, this.n), integral: z[this.n] };
  }
  period(x: number[], d: number, limit = true) {
    const first = this.flow(x, 0, d * this.T),
      remain = (1 - d) * this.T;
    let last = this.flow(first.state, 1, remain),
      off = remain;
    if (limit && last.state[0] < 0) {
      off = root(
        (t) => this.flow(first.state, 1, t).state[0],
        0,
        remain,
        1e-16,
      );
      last = this.flow(first.state, 1, off);
      last.state[0] = 0;
      const idle = this.flow(last.state, 2, remain - off);
      last = { state: idle.state, integral: last.integral + idle.integral };
    }
    return {
      end: last.state,
      average: (first.integral + last.integral) / this.T,
      off: off / this.T,
    };
  }
  solve() {
    const max = this.p.spice_config?.duty_max || 0.9,
      fixed = (d: number) => {
        const e = mm(
            expm(scale(this.phases[1], (1 - d) * this.T)),
            expm(scale(this.phases[0], d * this.T)),
          ),
          state = solve(
            eye(this.n).map((r, i) => r.map((v, j) => v - e[i][j])),
            e.slice(0, this.n).map((r) => r[this.n + 1]),
          );
        return { state, average: this.period(state, d, false).average };
      };
    const low = fixed(1e-5).average - this.target,
      high = fixed(max - 1e-5).average - this.target;
    if (low * high >= 0) throw Error("该输入与占空比上限无法达到目标电压");
    let duty = root(
        (d) => fixed(d).average - this.target,
        1e-5,
        max - 1e-5,
        1e-13,
      ),
      state = fixed(duty).state;
    if (state[0] < 0) {
      const x0 = [...state.slice(1), Math.log(duty / (max - duty))],
        fun = (x: number[]) => {
          const v = [0, ...x.slice(0, -1)],
            d = max / (1 + Math.exp(-x.at(-1)!)),
            out = this.period(v, d);
          return [
            ...out.end.slice(1).map((v, i) => v - x[i]),
            (out.average - this.target) / this.target,
          ];
        },
        result = leastSquares(
          fun,
          x0,
          x0.map((_, i) => (i === x0.length - 1 ? -30 : -1e5)),
          x0.map((_, i) => (i === x0.length - 1 ? 30 : 1e5)),
        );
      state = [0, ...result.x.slice(0, -1)];
      duty = max / (1 + Math.exp(-result.x.at(-1)!));
    }
    const result = this.period(state, duty),
      error = Math.max(...state.map((v, i) => Math.abs(v - result.end[i])));
    if (error > 1e-6) throw Error("Buck/Boost 周期边界残差过大");
    return { state, duty, off: result.off, error };
  }
  traces(initial: number[], d: number, off: number, points = 2048) {
    let state = [...initial];
    const times = Array.from(
        { length: points },
        (_, i) => (i * this.T) / points,
      ),
      states: number[][] = Array(points),
      phases = times.map((t) =>
        t < d * this.T ? 0 : t < (d + off) * this.T ? 1 : 2,
      );
    for (const [phase, start, duration] of [
      [0, 0, d],
      [1, d, off],
      [2, d + off, 1 - d - off],
    ]) {
      const indices = phases.flatMap((p, i) => (p === phase ? [i] : []));
      if (indices.length) {
        let z = [
            ...this.flow(state, phase, times[indices[0]] - start * this.T)
              .state,
            0,
            1,
          ],
          step = expm(scale(this.phases[phase], this.T / points));
        for (const i of indices) {
          states[i] = z.slice(0, this.n);
          z = mv(step, z);
        }
      }
      state = this.flow(state, phase, duration * this.T).state;
      if (phase === 1 && off < 1 - d - 1e-10) state[0] = 0;
    }
    const il = states.map((s) => s[0]),
      on = phases.map((p) => p === 0),
      diode = il.map((v, i) => (phases[i] === 1 ? v : 0)),
      voltage = states.map(
        (s, i) =>
          s.slice(1).reduce((sum, v, j) => sum + v * this.f.C[j], 0) +
          this.f.D *
            ((this.p.topology === "BUCK" ? il[i] : diode[i]) +
              this.block / this.R),
      );
    return { times, il, on, diode, voltage };
  }
}
export function solveNonisolated(p: Spec, nominal: Spec) {
  const q = effective(p),
    ind = inductor(nominal, q),
    dcr =
      q.spice_config?.niso_inductor_dcr >= 0
        ? q.spice_config.niso_inductor_dcr
        : ind.R_dc,
    k = new Kernel(q, dcr),
    sol = k.solve(),
    traces = k.traces(sol.state, sol.duty, sol.off),
    { il, on, diode, voltage } = traces,
    sw = il.map((v, i) => (on[i] ? v : 0)),
    vds = il.map((v, i) =>
      on[i]
        ? q.Rds_on * v
        : q.topology === "BUCK"
          ? k.bus + q.Vf_diode
          : voltage[i] + q.Vf_diode,
    ),
    pin = mean(q.topology === "BUCK" ? sw : il) * q.V_in,
    op = {
      ...nominal,
      D: sol.duty,
      Dp: sol.off,
      mode: sol.off < 1 - sol.duty - 1e-8 ? "DCM" : "CCM",
      I_L_avg: mean(il),
      I_L_rms: rms(il),
      I_L_pk: Math.max(...il),
      I_L_min: Math.min(...il),
      dI_L: ptp(il),
      I_sw_avg: mean(sw),
      I_sw_rms: rms(sw),
      I_sw_pk: Math.max(...sw),
      I_d_avg: mean(diode),
      I_d_rms: rms(diode),
      I_d_pk: Math.max(...diode),
      V_sw_max: Math.max(...vds),
      V_d_max: q.topology === "BUCK" ? k.bus : Math.max(...voltage),
      V_out_cap: k.target,
      V_feedback: k.target,
      V_out_equiv: k.target,
      R_equiv: k.R,
      R: k.R,
      P_in_est: pin,
      I_in_est: pin / q.V_in,
      P_loss_budget: pin - q.P_out,
      eta_guess: q.P_out / pin,
      niso_model: {
        converged: true,
        kind: "Buck/Boost passive periodic C+ESR",
        initial: sol.state,
        D: sol.duty,
        Dp: sol.off,
        residual: sol.error,
        dcr,
        parameters: q,
        inductor: ind,
      },
    };
  return op;
}
export function nisoWaveforms(op: Spec, points = 2048) {
  const model = op.niso_model,
    k = new Kernel(model.parameters, model.dcr),
    t = k.traces(model.initial, model.D, model.Dp, points),
    io = t.voltage.map((v) => (v - k.block) / k.R),
    sw = t.il.map((v, i) => (t.on[i] ? v : 0)),
    input = k.p.topology === "BUCK" ? sw : t.il,
    injection = k.p.topology === "BUCK" ? t.il : t.diode,
    lf = t.voltage.map((v) => v - mean(t.voltage)),
    twice = (a: number[]) => [...a, ...a],
    ic = injection.map((v, i) => v - io[i]),
    cin = input.map((v) => v - mean(input)),
    vds = t.il.map((v, i) =>
      t.on[i]
        ? k.p.Rds_on * v
        : k.p.topology === "BUCK"
          ? k.bus + k.p.Vf_diode
          : t.voltage[i] + k.p.Vf_diode,
    );
  return {
    t: [...t.times, ...t.times.map((v) => v + k.T)],
    dt: k.T / points,
    f_sw: op.f_sw,
    iL: twice(t.il),
    i_p: twice(t.il),
    i_sw: twice(sw),
    i_s: twice(t.diode),
    i_d: twice(t.diode),
    i_in: twice(input),
    i_c: twice(ic),
    i_cin: twice(cin),
    v_sw: twice(vds),
    v_d: twice(t.on.map((v) => (v ? op.V_d_max : 0))),
    vout_ripple: twice(lf),
    vout: twice(t.voltage.map((v) => v - k.block)),
    vcap: twice(t.voltage),
    v_esl: Array(points * 2).fill(0),
    ripple_pp: ptp(t.voltage),
    ripple_pp_total: ptp(t.voltage),
    i_c_rms: rms(ic),
    i_cin_rms: rms(cin),
  };
}
export function nisoPlant(p: Spec, op: Spec) {
  if (op.mode !== "CCM") throw Error("控制器专用环路限 CCM，当前为 DCM");
  const q = effective(p),
    m = op.niso_model,
    k = new Kernel(m.parameters, m.dcr),
    x: number[] = m.initial,
    d = m.D,
    n = x.length,
    t = k.T,
    j = zeros(n + 1),
    response = (x: number[], d: number) => {
      const a = k.period(x, d, false);
      return [...a.end, a.average];
    };
  for (let i = 0; i <= n; i++) {
    const h = i < n ? 1e-6 * Math.max(1, Math.abs(x[i])) : 1e-6,
      hi = [...x],
      lo = [...x];
    let dh = d,
      dl = d;
    if (i < n) {
      hi[i] += h;
      lo[i] -= h;
    } else {
      dh += h;
      dl -= h;
    }
    const up = response(hi, dh),
      down = response(lo, dl);
    for (let row = 0; row <= n; row++)
      j[row][i] = (up[row] - down[row]) / (2 * h);
  }
  let a = j.slice(0, n).map((r) => r.slice(0, n)),
    b = j.slice(0, n).map((r) => [r[n]]),
    c = [j[n].slice(0, n)],
    f = [[j[n][n]]];
  if (q.control_mode === "Peak Current Mode") {
    const e = expm(scale(k.phases[0], d * t)),
      at = k.flow(x, 0, d * t).state,
      hx = e[0].slice(0, n).map((v) => q.Rs * v),
      cfg = q.spice_config || {},
      profile = cfg.niso_profile,
      auto =
        profile === 2
          ? ((0.75 * (q.V_out + q.Vf_diode)) / q.L) * q.Rs
          : 45e-6 * q.f_sw * (2000 + (cfg.niso_lm_cs_resistor || 0)),
      design = Math.max(q.ma_slope, 0) * q.Rs,
      slope =
        cfg.slope_mode === 2
          ? cfg.slope
          : cfg.slope_mode === 0
            ? design
            : Math.max(design, auto),
      hd = (q.Rs * mv(k.phases[0], [...at, 0, 1])[0] + slope) * t;
    if (!(hd > 0)) throw Error("峰值比较器斜率非正");
    a = add(
      a,
      scale(
        outer(
          b.map((r) => r[0]),
          hx,
        ),
        -1 / hd,
      ),
    );
    c = add(c, scale([hx], -f[0][0] / hd));
    b = scale(b, 1 / hd);
    f = scale(f, 1 / hd);
  } else {
    b = scale(b, 1 / q.Vm);
    f = scale(f, 1 / q.Vm);
  }
  const inv = inverse(add(eye(n), a)),
    ac = scale(mm(add(a, eye(n), -1), inv), 2 / t),
    bc = scale(mm(inv, b), 2 / t),
    cc = scale(mm(c, inv), 2),
    dc = f[0][0] - mm(mm(c, inv), b)[0][0];
  const gain: Gain = (frequency: number): C => {
    const real = zeros(2 * n);
    for (let i = 0; i < n; i++)
      for (let h = 0; h < n; h++) {
        real[i][h] = real[i + n][h + n] = -ac[i][h];
        if (i === h) {
          real[i][h + n] = -2 * Math.PI * frequency;
          real[i + n][h] = 2 * Math.PI * frequency;
        }
      }
    const state = solve(real, [...bc.map((r) => r[0]), ...Array(n).fill(0)]);
    return [
      dc + state.slice(0, n).reduce((s, v, i) => s + cc[0][i] * v, 0),
      state.slice(n).reduce((s, v, i) => s + cc[0][i] * v, 0),
    ];
  };
  gain.system = { A: ac, B: bc, C: cc, D: [[dc]] };
  return gain;
}
