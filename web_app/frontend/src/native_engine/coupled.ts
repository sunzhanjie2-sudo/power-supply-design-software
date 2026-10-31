/** Event-resolved mutual-inductance solver, ported from coupled_flyback.py.
 * Outputs remain constant DC capacitor terminals during each period. This is
 * the existing engineering model, not an invented SPICE replacement.
 */
import { type Spec, blockDrop, inputDrop } from "./spec";
import { windingHardware } from "./power";
import {
  type Matrix,
  cholesky,
  inverse,
  transpose,
  mm,
  mv,
  dot,
  symmetricEigen,
  solve,
  leastSquares,
  maxabs,
  root,
} from "./math";
type Segment = {
  t: number;
  dt: number;
  active: number[];
  initial: number[];
  voltage: number[];
  flow: Flow | null;
  on: boolean;
};
export class Flow {
  back: Matrix;
  forward: Matrix;
  cinv: Matrix;
  eigen: number[];
  basis: Matrix;
  constructor(l: Matrix, r: number[]) {
    const c = cholesky(l);
    this.cinv = inverse(c);
    this.forward = transpose(c);
    this.back = inverse(this.forward);
    const s = mm(
        this.cinv.map((row) => row.map((v, j) => v * r[j])),
        transpose(this.cinv),
      ),
      e = symmetricEigen(s);
    this.eigen = e.values.map((v) => Math.max(v, 0));
    this.basis = e.vectors;
  }
  values(initial: number[], voltage: number[], dt: number) {
    const bt = transpose(this.basis),
      q = mv(bt, mv(this.forward, initial)),
      g = mv(bt, mv(this.cinv, voltage)),
      f: number[] = [],
      h: number[] = [],
      e: number[] = [];
    this.eigen.forEach((v, i) => {
      const z = v * dt;
      e[i] = Math.exp(-z);
      if (Math.abs(z) < 1e-4) {
        f[i] = dt * (1 - z / 2 + (z * z) / 6 - z ** 3 / 24);
        h[i] = dt * dt * (0.5 - z / 6 + (z * z) / 24 - z ** 3 / 120);
      } else {
        f[i] = -Math.expm1(-z) / v;
        h[i] = (dt - f[i]) / v;
      }
    });
    return {
      current: mv(
        this.back,
        mv(
          this.basis,
          q.map((v, i) => v * e[i] + g[i] * f[i]),
        ),
      ),
      integral: mv(
        this.back,
        mv(
          this.basis,
          q.map((v, i) => v * f[i] + g[i] * h[i]),
        ),
      ),
    };
  }
}
export class Circuit {
  count: number;
  currentTol = 1e-9;
  voltageTol: number;
  cache = new Map<string, Flow>();
  inverses = new Map<string, Matrix>();
  constructor(
    public L: Matrix,
    public dcr: number[],
    public vin: number,
    public vf: number[],
    public ron: number,
    public rs: number,
    public clamp: number,
    public period: number,
  ) {
    this.count = L.length;
    this.voltageTol = 1e-8 * Math.max(vin, clamp, 1);
  }
  parameters(active: number[], on: boolean, vo: number[]) {
    const resistance = [
        this.dcr[0] + (on ? this.ron + this.rs : 0),
        ...this.dcr.slice(1),
      ],
      applied = [
        on ? this.vin : -this.clamp,
        ...vo.map((v, j) => -v - this.vf[j]),
      ],
      key = active.join(",") + "/" + on;
    let flow = this.cache.get(key);
    if (!flow) {
      flow = new Flow(
        active.map((i) => active.map((j) => this.L[i][j])),
        active.map((i) => resistance[i]),
      );
      this.cache.set(key, flow);
    }
    return { resistance, applied, flow };
  }
  slope(
    active: number[],
    current: number[],
    resistance: number[],
    applied: number[],
  ) {
    const result = Array(this.count).fill(0);
    if (active.length) {
      const key = active.join(",");
      let inv = this.inverses.get(key);
      if (!inv) {
        inv = inverse(active.map((i) => active.map((j) => this.L[i][j])));
        this.inverses.set(key, inv);
      }
      const values = mv(
        inv,
        active.map((i) => applied[i] - resistance[i] * current[i]),
      );
      active.forEach((i, j) => (result[i] = values[j]));
    }
    return result;
  }
  settle(current: number[], seed: number[], on: boolean, vo: number[]) {
    const positive = new Set(
      current.flatMap((v, i) => (v > this.currentTol ? [i] : [])),
    );
    if (on) positive.add(0);
    const active = new Set([...seed, ...positive]),
      seen = new Set<string>(),
      resistance = [
        this.dcr[0] + (on ? this.ron + this.rs : 0),
        ...this.dcr.slice(1),
      ],
      applied = [
        on ? this.vin : -this.clamp,
        ...vo.map((v, j) => -v - this.vf[j]),
      ];
    for (let attempt = 0; attempt < 4 * this.count + 4; attempt++) {
      const a = [...active].sort((a, b) => a - b),
        signature = a.join(",");
      if (seen.has(signature)) break;
      seen.add(signature);
      const slope = this.slope(a, current, resistance, applied),
        bad = a
          .filter((j) => !positive.has(j) && slope[j] < -1e-7)
          .sort((a, b) => slope[a] - slope[b]);
      if (bad.length) {
        active.delete(bad[0]);
        continue;
      }
      const induced = mv(this.L, slope),
        open = induced
          .flatMap((v, j) =>
            !active.has(j) && v < applied[j] - this.voltageTol ? [j] : [],
          )
          .sort((a, b) => induced[a] - applied[a] - induced[b] + applied[b]);
      if (open.length) {
        active.add(open[0]);
        continue;
      }
      return a;
    }
    const optional = Array.from({ length: this.count }, (_, j) => j).filter(
      (j) => !positive.has(j),
    );
    for (let mask = 0; mask < 2 ** optional.length; mask++) {
      const extra = optional.filter((_, k) => mask & (1 << k)),
        a = [...positive, ...extra].sort((a, b) => a - b),
        sl = this.slope(a, current, resistance, applied),
        ind = mv(this.L, sl);
      if (
        extra.every((j) => sl[j] >= -1e-7) &&
        optional.every(
          (j) => a.includes(j) || ind[j] >= applied[j] - this.voltageTol,
        )
      )
        return a;
    }
    throw Error("耦合绕组二极管状态无解，请检查矩阵与钳位参数");
  }
  phase(
    initial: number[],
    on: boolean,
    duration: number,
    vo: number[],
    offset: number,
  ) {
    let current = [...initial],
      seed = current.flatMap((v, j) => (v > this.currentTol ? [j] : [])),
      elapsed = 0;
    const segments: Segment[] = [],
      minimum = this.period * 1e-12;
    if (on && !seed.includes(0)) seed.push(0);
    for (let attempt = 0; attempt < 80; attempt++) {
      const left = duration - elapsed;
      if (left <= minimum) return { end: current, segments };
      const active = this.settle(current, seed, on, vo);
      if (!active.length)
        return {
          end: Array(this.count).fill(0),
          segments: [
            ...segments,
            {
              t: offset + elapsed,
              dt: left,
              active: [],
              initial: [],
              voltage: [],
              flow: null,
              on,
            },
          ],
        };
      const { resistance, applied, flow } = this.parameters(active, on, vo),
        ia = active.map((j) => current[j]),
        ua = active.map((j) => applied[j]),
        inactive = Array.from({ length: this.count }, (_, j) => j).filter(
          (j) => !active.includes(j),
        );
      const constraints = (dt: number) => {
        const value = flow.values(ia, ua, dt).current,
          full = Array(this.count).fill(0);
        active.forEach((j, k) => (full[j] = value[k]));
        const slope = this.slope(active, full, resistance, applied);
        return {
          value,
          slack: mv(this.L, slope).map((v, j) => v - applied[j]),
        };
      };
      let previousT = 0,
        previous = constraints(0),
        event: { when: number; action: string; j: number } | null = null;
      for (let sample = 1; sample <= 12; sample++) {
        const time = (left * sample) / 12,
          c = constraints(time),
          candidates: { when: number; action: string; j: number }[] = [];
        active.forEach((j, k) => {
          if (on && j === 0) return;
          if (c.value[k] < -this.currentTol)
            candidates.push({
              when:
                previous.value[k] <= 0
                  ? previousT
                  : root(
                      (dt) => constraints(dt).value[k],
                      previousT,
                      time,
                      minimum,
                    ),
              action: "open",
              j,
            });
        });
        inactive.forEach((j) => {
          if (c.slack[j] < -this.voltageTol)
            candidates.push({
              when:
                previous.slack[j] <= -this.voltageTol
                  ? previousT
                  : root(
                      (dt) => constraints(dt).slack[j] + this.voltageTol,
                      previousT,
                      time,
                      minimum,
                    ),
              action: "close",
              j,
            });
        });
        if (candidates.length) {
          event = candidates.sort((a, b) => a.when - b.when)[0];
          break;
        }
        previousT = time;
        previous = c;
      }
      const dt = event ? event.when : left;
      if (dt > minimum) {
        segments.push({
          t: offset + elapsed,
          dt,
          active,
          initial: ia,
          voltage: ua,
          flow,
          on,
        });
        const values = flow.values(ia, ua, dt).current;
        current = Array(this.count).fill(0);
        active.forEach(
          (j, k) =>
            (current[j] =
              Math.abs(values[k]) < this.currentTol
                ? 0
                : Math.max(0, values[k])),
        );
        if (Math.min(...values) < -1e-6)
          throw Error("耦合周期存在反向整流电流");
        elapsed += dt;
      }
      seed = [...active];
      if (!event) return { end: current, segments };
      if (event.action === "open") {
        current[event.j] = 0;
        seed = seed.filter((j) => j !== event!.j);
      } else if (!seed.includes(event.j)) seed.push(event.j);
    }
    throw Error("耦合换流事件过密，未收敛");
  }
  cycle(start: number[], voltage: number[], duty: number) {
    const first = this.phase(
        [0, ...start],
        true,
        duty * this.period,
        voltage,
        0,
      ),
      last = this.phase(
        first.end,
        false,
        (1 - duty) * this.period,
        voltage,
        duty * this.period,
      );
    return { end: last.end, segments: [...first.segments, ...last.segments] };
  }
}
function gauss(n = 20) {
  const nodes: number[] = [],
    weights: number[] = [];
  for (let i = 0; i < n; i++) {
    let z = Math.cos((Math.PI * (i + 0.75)) / (n + 0.5)),
      dp = 0;
    for (let it = 0; it < 20; it++) {
      let p = 1,
        q = 0;
      for (let j = 1; j <= n; j++) {
        const next = ((2 * j - 1) * z * p - (j - 1) * q) / j;
        q = p;
        p = next;
      }
      dp = (n * (z * p - q)) / (z * z - 1);
      const next = z - p / dp;
      if (Math.abs(next - z) < 1e-15) {
        z = next;
        break;
      }
      z = next;
    }
    nodes.push(z);
    weights.push(2 / ((1 - z * z) * dp * dp));
  }
  return { nodes, weights };
}
const quadrature = gauss();
export function integrals(segments: Segment[], count: number, squares = true) {
  const charge = Array(count).fill(0),
    squared = Array(count).fill(0);
  let on = 0,
    onSquared = 0,
    clampCharge = 0;
  for (const seg of segments) {
    if (!seg.active.length) continue;
    const q = seg.flow!.values(seg.initial, seg.voltage, seg.dt).integral,
      sq = Array(q.length).fill(0);
    if (squares)
      quadrature.nodes.forEach((node, k) => {
        const value = seg.flow!.values(
          seg.initial,
          seg.voltage,
          ((node + 1) * seg.dt) / 2,
        ).current;
        value.forEach(
          (v, j) => (sq[j] += (quadrature.weights[k] * v * v * seg.dt) / 2),
        );
      });
    seg.active.forEach((j, k) => {
      charge[j] += q[k];
      squared[j] += sq[k];
    });
    const j = seg.active.indexOf(0);
    if (j >= 0) {
      if (seg.on) {
        on += q[j];
        onSquared += sq[j];
      } else clampCharge += q[j];
    }
  }
  return { charge, squared, on, onSquared, clampCharge };
}
export function sample(
  circuit: Circuit,
  segments: Segment[],
  vo: number[],
  duty: number,
  points = 2400,
) {
  const period = circuit.period,
    eps = period * 1e-10,
    t = [
      ...Array.from({ length: points + 1 }, (_, i) => (i * period) / points),
      ...segments.flatMap((s) =>
        [s.t, s.t + s.dt].flatMap((t) => [t, t - eps, t + eps]),
      ),
    ]
      .map((v) => Math.max(0, Math.min(period, v)))
      .sort((a, b) => a - b)
      .filter((v, i, a) => !i || v > a[i - 1]);
  const iw = Array.from({ length: circuit.count }, () =>
      Array(t.length).fill(0),
    ),
    vw = iw.map((a) => [...a]),
    sw = Array(t.length).fill(0),
    clampCurrent = [...sw],
    vds = [...sw],
    im = [...sw];
  let segmentIndex = 0;
  t.forEach((time, i) => {
    while (
      segmentIndex < segments.length - 1 &&
      time >= segments[segmentIndex].t + segments[segmentIndex].dt - eps / 2
    )
      segmentIndex++;
    const s = segments[segmentIndex];
    if (!s.active.length) {
      vds[i] = circuit.vin;
      return;
    }
    const values = s.flow!.values(
        s.initial,
        s.voltage,
        Math.max(0, Math.min(s.dt, time - s.t)),
      ).current,
      full = Array(circuit.count).fill(0);
    s.active.forEach((j, k) => (full[j] = iw[j][i] = values[k]));
    const par = circuit.parameters(s.active, s.on, vo),
      volts = mv(
        circuit.L,
        circuit.slope(s.active, full, par.resistance, par.applied),
      );
    volts.forEach((v, j) => (vw[j][i] = v));
    const j = s.active.indexOf(0);
    if (j >= 0) {
      if (s.on) sw[i] = values[j];
      else clampCurrent[i] = values[j];
    }
    vds[i] =
      time < duty * period
        ? circuit.ron * sw[i]
        : circuit.vin - volts[0] - circuit.dcr[0] * full[0];
    im[i] = dot(circuit.L[0], full) / circuit.L[0][0];
  });
  return {
    t,
    i_winding: iw,
    v_winding: vw,
    i_sw: sw,
    i_in: [...sw],
    i_clamp: clampCurrent,
    v_sw: vds,
    i_magnetizing: im,
  };
}
export function solveCoupled(p: Spec, nominal: Spec) {
  if (p.topology !== "FLYBACK" || p.feedback_mode !== "SSR")
    throw Error("耦合周期模型限固定频率反激 SSR");
  const rr = nominal.outputs?.length
      ? nominal.outputs
      : [{ ...p, id: 1, name: "OUT1" }],
    count = rr.length,
    main = (p.feedback_output || 1) - 1,
    hardware = windingHardware(p, nominal),
    ratios = [1, ...hardware.windings.map((w: Spec) => hardware.Np / w.Ns)],
    k: Matrix = p.coupling_config.k?.length
      ? p.coupling_config.k
      : Array.from({ length: count + 1 }, (_, i) =>
          Array.from({ length: count + 1 }, (_, j) => (i === j ? 1 : 0.995)),
        );
  if (k.length !== count + 1 || k.some((row) => row.length !== count + 1))
    throw Error("耦合矩阵维数不匹配");
  k.forEach((row, i) =>
    row.forEach((v, j) => {
      if (
        !Number.isFinite(v) ||
        v < 0 ||
        v > 1 ||
        Math.abs(v - k[j][i]) > 1e-12 ||
        (i === j && Math.abs(v - 1) > 1e-12)
      )
        throw Error("耦合矩阵必须对称、对角线为 1，且 0≤kij≤1");
    }),
  );
  if (k.every((row) => row.every((v) => Math.abs(v - 1) < 1e-13)))
    return {
      ...nominal,
      coupled_model: { ideal_fallback: true, kind: "ideal-transformer-limit" },
      warnings: [
        "全1矩阵为奇异理想极限，沿用原版显式标称近似，不生成非理想漏感周期解。",
      ],
    };
  const eigen = symmetricEigen(k).values;
  if (Math.min(...eigen) <= 1e-11) throw Error("耦合矩阵非正定或接近奇异");
  const lp = p.L,
    L = k.map((row, i) => row.map((v, j) => (v * lp) / ratios[i] / ratios[j])),
    dcr = [hardware.R_dc_p, ...hardware.windings.map((w: Spec) => w.R_dc)],
    target = rr.map((r: Spec) => r.V_out),
    block = rr.map(blockDrop),
    cap = target.map((v: number, i: number) => v + block[i]),
    rated = rr.map((r: Spec) => r.P_out),
    loads = target.map((v: number, i: number) => (v * v) / rated[i]),
    vf = rr.map((r: Spec) => r.Vf_diode),
    vin = p.V_in - inputDrop(p),
    clampV = p.Kc * ratios[main + 1] * (cap[main] + vf[main]),
    period = 1 / p.f_sw;
  if (rated.some((v: number) => v <= 0))
    throw Error("耦合电阻负载模型要求各路有正的预负载");
  if (
    !(
      vin > 0 &&
      p.Kc > 1 &&
      clampV >
        Math.max(
          ...cap.map((v: number, i: number) => ratios[i + 1] * (v + vf[i])),
        ) *
          1.001
    )
  )
    throw Error("输入或钳位电压不足");
  const circuit = new Circuit(L, dcr, vin, vf, p.Rds_on, p.Rs, clampV, period),
    children = nominal.output_ops || [nominal],
    currentScale = children.map((q: Spec, i: number) =>
      Math.max(q.I_d_pk, rated[i] / target[i], 0.01),
    ),
    initial = children.map(
      (q: Spec, i: number) => Math.max(0, q.I_L_min) * ratios[i + 1],
    ),
    other = target.flatMap((_: number, i: number) => (i !== main ? [i] : [])),
    x0 = [
      ...initial.map((v: number, i: number) => v / currentScale[i]),
      ...other.map(() => 1),
      nominal.D,
    ],
    lo = [...rr.map(() => 0), ...other.map(() => 0.05), 0.005],
    hi = [...rr.map(() => 30), ...other.map(() => 5), 0.9],
    loadScale = rated.map((v: number, i: number) =>
      Math.max(v / target[i], 0.001),
    );
  const decode = (x: number[]) => {
    const volts = [...cap];
    other.forEach(
      (j: number, i: number) =>
        (volts[j] = block[j] + target[j] * x[count + i]),
    );
    return {
      start: x.slice(0, count).map((v, i) => v * currentScale[i]),
      volts,
      duty: x[x.length - 1],
    };
  };
  const residual = (x: number[]) => {
    const { start, volts, duty } = decode(x),
      cycle = circuit.cycle(start, volts, duty),
      avg = integrals(cycle.segments, count + 1, false).charge.map(
        (v) => v / period,
      );
    return [
      ...start.map((v, i) => (cycle.end[i + 1] - v) / currentScale[i]),
      ...volts.map(
        (v, i) => (avg[i + 1] - (v - block[i]) / loads[i]) / loadScale[i],
      ),
      cycle.end[0] / Math.max(nominal.I_sw_pk, 0.01),
    ];
  };
  const solved = leastSquares(residual, x0, lo, hi),
    error = maxabs(residual(solved.x));
  if (error > 2e-5)
    throw Error(
      "耦合周期/电荷平衡未收敛，归一化残差 " + error.toExponential(3),
    );
  const { start, volts, duty } = decode(solved.x),
    cycle = circuit.cycle(start, volts, duty),
    integral = integrals(cycle.segments, count + 1),
    average = integral.charge.map((v) => v / period),
    rms2 = integral.squared.map((v) => v / period),
    solution = sample(circuit, cycle.segments, volts, duty),
    vo = volts.map((v, i) => v - block[i]),
    powers = vo.map((v, i) => (v * v) / loads[i]),
    pc = (clampV * integral.clampCharge) / period,
    pin = (p.V_in * integral.on) / period,
    pout = powers.reduce((a, b) => a + b, 0),
    pcu = dot(dcr, rms2),
    prect = dot(vf, average.slice(1)),
    pblock = dot(block, average.slice(1)),
    pon = (p.Rds_on * integral.onSquared) / period,
    psense = (p.Rs * integral.onSquared) / period,
    balance =
      pin -
      pout -
      pcu -
      prect -
      pblock -
      (inputDrop(p) * integral.on) / period -
      pon -
      psense -
      pc;
  if (Math.abs(balance) > Math.max(0.001, pin * 0.002))
    throw Error("耦合能量平衡未通过：" + balance + " W");
  const im = solution.i_magnetizing,
    leak =
      lp *
      (1 -
        dot(
          k[0].slice(1),
          solve(
            k.slice(1).map((row) => row.slice(1)),
            k.slice(1).map((row) => row[0]),
          ),
        )),
    meta: Spec = {
      enabled: true,
      ideal_fallback: false,
      converged: true,
      model: "coupled-RL-stiff-capacitor-fixed-R",
      labels: ["P", ...rr.map((r: Spec) => "OUT" + r.id)],
      ratios,
      L,
      K: k,
      R: dcr,
      L_leak: Math.max(leak, 0),
      L_leak_primary: Math.max(leak, 0),
      transformer_hardware: hardware,
      dcr_source: "geometry",
      iterations: solved.iterations,
      duty,
      clamp_voltage: clampV,
      load_resistances: loads,
      output_voltages: vo,
      capacitor_voltages: volts,
      output_blocking_drops: block,
      input_bus_voltage: vin,
      P_in: pin,
      P_out: pout,
      P_clamp: pc,
      P_rcd: pc,
      P_dcr: dcr.map((v, i) => v * rms2[i]),
      P_rectifier: vf.map((v: number, i: number) => v * average[i + 1]),
      P_mos_conduction: pon,
      P_sense: psense,
      normalized_residual: error,
      energy_balance_W: balance,
      winding_rms: rms2.map(Math.sqrt),
      feedback_voltage: volts[main],
      feedback_target: cap[main],
    };
  const offIndex = solution.t.findIndex((v) => v >= duty * period),
    op: Spec = {
      ...nominal,
      coupled_model: meta,
      coupled_solution: {
        ...solution,
        output_voltages: vo,
        capacitor_voltages: volts,
      },
      D: duty,
      Dp: 1 - duty,
      mode:
        Math.min(...im) > Math.max(Math.max(...im) * 1e-5, 1e-7)
          ? "CCM"
          : "DCM",
      P_out: pout,
      P_in_est: pin,
      I_in_est: integral.on / period,
      P_loss_budget: pin - pout,
      I_L_pk: Math.max(...im),
      I_L_min: Math.min(...im),
      dI_L: Math.max(...im) - Math.min(...im),
      I_sw_pk: Math.max(...solution.i_sw),
      I_sw_rms: Math.sqrt(integral.onSquared / period),
      I_sw_avg: integral.on / period,
      I_sw_on: Math.max(im[0], 0),
      I_sw_off: solution.i_sw[Math.max(0, offIndex - 1)],
      V_sw_max: Math.max(...solution.v_sw),
      V_out: vo[main],
      V_out_cap: volts[main],
      V_feedback: volts[main],
      V_feedback_target: cap[main],
      V_out_equiv: volts[main] + vf[main],
      R: loads[main],
      R_equiv: loads[main],
      N: ratios[main + 1],
      V_r: ratios[main + 1] * (volts[main] + vf[main]),
      outputs: rr,
    };
  op.clamp = {
    model: "coupled_winding_transient",
    V_plateau: vin + op.V_r,
    V_peak: op.V_sw_max,
    V_clamp: clampV,
    V_ceiling: vin + clampV,
    P_res: pc,
    L_leak: Math.max(leak, 0),
  };
  op.output_ops = rr.map((r: Spec, j: number) => {
    const current = solution.i_winding[j + 1],
      peak = Math.max(...current),
      conducting = solution.t.filter(
        (time, i) =>
          time > duty * period && current[i] > Math.max(peak * 1e-5, 1e-7),
      ),
      last = conducting.at(-1) ?? duty * period,
      mode = last < period - period * 0.003 ? "DCM" : "CCM";
    const child: Spec = {
      ...op,
      ...r,
      coupled_model: meta,
      output_id: r.id,
      N: ratios[j + 1],
      V_out: vo[j],
      V_out_target: target[j],
      V_out_cap: volts[j],
      V_feedback: volts[j],
      V_feedback_target: cap[j],
      V_out_equiv: volts[j] + vf[j],
      P_out: powers[j],
      I_out: vo[j] / loads[j],
      R: loads[j],
      R_equiv: loads[j],
      I_d_pk: peak,
      I_d_rms: Math.sqrt(rms2[j + 1]),
      I_s_rms: Math.sqrt(rms2[j + 1]),
      I_d_avg: average[j + 1],
      mode,
      branch_mode: mode,
      V_d_max: Math.max(
        ...volts.map(() => 0),
        ...solution.v_winding[j + 1].map(
          (v, i) => volts[j] + v + dcr[j + 1] * current[i],
        ),
      ),
      C_min:
        ((vo[j] / loads[j]) * duty) /
        (p.f_sw * Math.max(r.ripple_target, 1e-9) * vo[j]),
    };
    delete child.output_ops;
    delete child.aggregate_op;
    return child;
  });
  for (const key of [
    "I_out",
    "I_d_pk",
    "I_d_rms",
    "I_d_avg",
    "I_s_rms",
    "V_d_max",
    "C_min",
  ])
    op[key] = op.output_ops[main][key];
  return op;
}
