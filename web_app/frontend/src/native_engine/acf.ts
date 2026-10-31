/** Independent active-clamp-forward implicit MNA period and analytic sensitivities.
 * Port of acf_periodic.py. No simulator results or fitted correction factors. */
import { type Spec, clone, inputDrop, blockDrop } from "./spec";
import {
  zeros,
  eye,
  inverse,
  mm,
  mv,
  add,
  scale,
  dot,
  maxabs,
  solve,
  leastSquares,
  ptp,
  symmetricEigen,
} from "./math";
import { windingMatrix, resolvedParasitics } from "./parasitics";
type Matrix = number[][];
export function forwardEstimate(
  p: Spec,
  rr: Spec[],
  geometry: Spec,
  K: Matrix,
) {
  const n = rr.length,
    fb = (p.feedback_output || 1) - 1,
    vin = p.V_in - inputDrop(p),
    fs = p.f_sw,
    ratio: number[] = geometry.windings.map((w: Spec) => w.Ns / geometry.Np),
    loads = rr.map((r) => r.V_out ** 2 / Math.max(r.P_out, 1e-15)),
    drops = rr.map((r) => r.Vf_diode + blockDrop(r)),
    k = rr.map((_, j) => K[0][j + 1]),
    primary = p.Lm_forward * (1 - Math.min(...k)),
    secondary = k.map((v, j) => p.Lm_forward * ratio[j] ** 2 * (1 - v)),
    target = rr[fb].V_out;
  const point = (x: number[]) => {
    const vo = x.slice(0, n),
      d = x[n],
      io = vo.map((v, i) => v / loads[i]),
      ip = dot(ratio, io),
      vs = ratio.map((v, j) =>
        Math.max(
          v * (vin - geometry.R_dc_p * ip) - geometry.windings[j].R_dc * io[j],
          1e-5,
        ),
      ),
      commute = ratio.map(
        (v, j) =>
          (fs * (primary * ip + (secondary[j] * io[j]) / v)) /
          Math.max(vin, 1e-6),
      ),
      de = commute.map((v) => Math.max(d - v, 1e-7));
    return vo.map((v, j) => {
      const u = v + drops[j],
        critical = (vs[j] * de[j] * (1 - de[j])) / (2 * rr[j].L * fs);
      return io[j] >= critical
        ? v - (de[j] * vs[j] - drops[j])
        : loads[j] *
            (io[j] -
              (vs[j] * Math.max(vs[j] - u, 0) * de[j] ** 2) /
                (2 * rr[j].L * fs * Math.max(u, 1e-6)));
    });
  };
  const hi = [
      ...ratio.map((r, j) => Math.max(vin * r - drops[j], 0.1)),
      Math.min(p.forward_d_max || 0.7, 0.95),
    ],
    initial = [
      ...rr.map((r) => r.V_out),
      Math.min(0.6, (target + drops[fb]) / (vin * ratio[fb]) + 0.05),
    ].map((v, i) => Math.min(v, hi[i] * 0.999)),
    f = (x: number[]) => [
      ...point(x).map((v) => v / Math.max(target, 1)),
      (x[fb] - target) / Math.max(target, 1),
    ],
    z = leastSquares(f, initial, [...Array(n).fill(1e-6), 1e-5], hi);
  if (maxabs(z.residual) > 1e-5)
    throw Error("正激独立直流预设计未收敛或占空比超限");
  return { voltages: z.x.slice(0, n), duty: z.x[n] };
}
export class ForwardCircuit {
  n: number;
  size: number;
  base: number;
  c: number;
  cs: number;
  cj: number;
  T: number;
  dead: number;
  vin: number;
  load: number[];
  block: number[];
  vf: number[];
  fb: number;
  target: number;
  L: Matrix;
  R: number[];
  K: Matrix;
  E: Matrix;
  A: Matrix;
  b: number[];
  B: Matrix;
  p: Spec;
  rails: Spec[];
  geometry: Spec;
  cfg: Spec;
  extra: any[] = [];
  pairs: any[] = [];
  points: number;
  cache = new Map<
    string,
    {
      flow: Matrix;
      q: Matrix;
      c: number[];
      inv: Matrix;
      a: Matrix;
      b: number[];
    }
  >();
  constructor(p: Spec, rr: Spec[], geometry: Spec, model: Spec, points = 512) {
    this.p = p;
    this.rails = rr;
    this.geometry = geometry;
    this.n = rr.length;
    const n = this.n;
    this.base = 2 * n + 1;
    this.c = 4 * n + 3;
    this.cs = this.c + 1;
    this.cj = this.cs + 1;
    this.size = this.cj + 2 * n + 2;
    this.points = points;
    this.cfg = resolvedParasitics(p, n);
    if (this.cfg.snub_c_primary)
      this.extra.push([
        this.base,
        null,
        this.cfg.snub_r_primary,
        this.cfg.snub_c_primary,
      ]);
    this.cfg.rails.forEach((r: Spec, j: number) => {
      if (r.snub_c)
        this.extra.push([
          this.base + 2 + 2 * j,
          this.base + 3 + 2 * j,
          r.snub_r,
          r.snub_c,
        ]);
    });
    this.size += this.extra.length;
    this.T = 1 / p.f_sw;
    this.dead =
      (p.spice_config?.acf_dead_ns || 0) * 1e-9 || p.forward_dead_time;
    this.vin = p.V_in - inputDrop(p);
    this.block = rr.map(blockDrop);
    this.load = rr.map((r) => r.V_out ** 2 / Math.max(r.P_out, 1e-12));
    this.fb = (p.feedback_output || 1) - 1;
    this.target = rr[this.fb].V_out;
    this.vf = rr.map((r) => r.Vf_diode);
    this.L = model.L.map((r: number[], i: number) =>
      r.map(
        (v, j) =>
          v +
          (i === j ? (i ? this.cfg.rails[i - 1].l_pcb : this.cfg.lp_pcb) : 0),
      ),
    );
    this.R = model.R.map(
      (v: number, i: number) =>
        v + (i ? this.cfg.rails[i - 1].r_pcb : this.cfg.rp_pcb),
    );
    this.K = this.L.map((r, i) =>
      r.map((v, j) => v / Math.sqrt(this.L[i][i] * this.L[j][j])),
    );
    const s = this.size;
    this.E = zeros(s);
    this.A = zeros(s);
    this.b = Array(s).fill(0);
    this.B = zeros(s, n);
    for (let i = 0; i <= n; i++) {
      for (let j = 0; j <= n; j++) this.E[i][j] = this.L[i][j];
      this.A[i][i] = -this.R[i];
    }
    this.A[0][this.base] = -1;
    this.b[0] = this.vin;
    this.A[this.base][0] = 1;
    for (let j = 0; j < n; j++) {
      const rect = this.base + 2 + 2 * j,
        choke = rect + 1;
      this.E[n + 1 + j][n + 1 + j] = rr[j].L;
      this.A[j + 1][rect] = 1;
      this.A[rect][j + 1] = -1;
      this.A[n + 1 + j][choke] = 1;
      this.A[choke][n + 1 + j] = -1;
      this.B[n + 1 + j][j] = -1;
      this.b[n + 1 + j] = -this.block[j];
    }
    this.E[this.base][this.base] =
      Math.max(this.cfg.coss, 1e-12) + this.cfg.cw_primary;
    this.E[this.base + 1][this.base + 1] = Math.max(this.cfg.coss_aux, 1e-12);
    this.cfg.rails.forEach(
      (r: Spec, j: number) =>
        (this.E[this.base + 2 + 2 * j][this.base + 2 + 2 * j] += r.cw),
    );
    this.pairs = [
      [this.base, null],
      [this.base + 1, null],
      ...rr.flatMap((_, j) => [
        [this.base + 2 + 2 * j, this.base + 3 + 2 * j],
        [this.base + 3 + 2 * j, null],
      ]),
    ];
    const caps = [
      ...(p.parasitic_config && Object.keys(p.parasitic_config).length
        ? [0, 0]
        : [this.cfg.cj_default, this.cfg.cj_default]),
      ...this.cfg.rails.flatMap((r: Spec) => [r.cj, r.cj_free]),
    ];
    const shunt = (
      index: number,
      a: number,
      b: number | null,
      r: number,
      c: number,
    ) => {
      const stamp = Array(s).fill(0);
      stamp[a] = 1;
      stamp[index] = -1;
      if (b !== null) stamp[b] = -1;
      this.E[index][index] = c;
      for (let j = 0; j < s; j++) {
        this.A[a][j] -= stamp[j] / r;
        if (b !== null) this.A[b][j] += stamp[j] / r;
        this.A[index][j] += stamp[j] / r;
      }
    };
    this.pairs.forEach(([a, b], i) =>
      shunt(this.cj + i, a, b, this.cfg.r_cj, caps[i]),
    );
    this.extra.forEach(([a, b, r, c], i) =>
      shunt(this.cj + this.pairs.length + i, a, b, r, c),
    );
    const esr = Math.max(p.ESR_clamp, 1e-5);
    this.E[this.c][this.c] = p.C_clamp;
    this.E[this.cs][this.cs] = Math.max(
      (p.spice_config?.cs_filter_ns ?? 15) * 1e-9,
      1e-12,
    );
    this.A[this.cs][this.cs] = -1;
    const stamp = Array(s).fill(0);
    stamp[this.base] = 1;
    stamp[this.base + 1] = -1;
    stamp[this.c] = -1;
    for (let j = 0; j < s; j++) {
      this.A[this.base][j] -= stamp[j] / esr;
      this.A[this.base + 1][j] += stamp[j] / esr;
      this.A[this.c][j] += stamp[j] / esr;
    }
  }
  diodes(x: number[]) {
    const v = x.slice(this.base, this.c),
      r = [-v[0] - 0.8, v[1] - 0.8];
    for (let j = 0; j < this.n; j++)
      r.push(
        v[2 + 2 * j] - v[3 + 2 * j] - this.vf[j],
        -v[3 + 2 * j] - this.vf[j],
      );
    return r;
  }
  matrices(main: boolean, aux: boolean, bits: boolean[], h: number) {
    const key = [+main, +aux, bits.map(Number).join(""), h].join("/"),
      old = this.cache.get(key);
    if (old) return old;
    const a = this.A.map((r) => [...r]),
      b = [...this.b],
      o = this.base,
      n = this.n;
    if (main) {
      for (let j = 0; j <= n; j++)
        a[this.cs][j] = (this.p.Rs * this.L[0][j]) / this.L[0][0];
      for (let j = 0; j < n; j++)
        a[this.cs][n + 1 + j] = (this.p.Rs * this.L[0][j + 1]) / this.L[0][0];
    }
    a[o][o] -= +main / Math.max(this.p.Rds_on + this.p.Rs, 1e-5);
    a[o + 1][o + 1] -= +aux / Math.max(this.p.Rds_aux, 1e-5);
    if (bits[0]) {
      a[o][o] -= 1000;
      b[o] -= 800;
    }
    if (bits[1]) {
      a[o + 1][o + 1] -= 1000;
      b[o + 1] += 800;
    }
    for (let j = 0; j < n; j++) {
      const r = o + 2 + 2 * j,
        k = r + 1;
      if (bits[2 + 2 * j]) {
        a[r][r] -= 1000;
        a[r][k] += 1000;
        a[k][r] += 1000;
        a[k][k] -= 1000;
        b[r] += 1000 * this.vf[j];
        b[k] -= 1000 * this.vf[j];
      }
      if (bits[3 + 2 * j]) {
        a[k][k] -= 1000;
        b[k] -= 1000 * this.vf[j];
      }
    }
    const inv = inverse(add(this.E, a, -h)),
      out = {
        a,
        b,
        inv,
        flow: mm(inv, this.E),
        q: scale(mm(inv, this.B), h),
        c: mv(inv, b).map((v) => v * h),
      };
    this.cache.set(key, out);
    return out;
  }
  cycle(
    initial: number[],
    vo: number[],
    duty: number,
    derivatives = false,
    trace = false,
  ): Spec {
    const n = this.n,
      s = this.size,
      T = this.T,
      dead = this.dead;
    if (!(dead / T < duty && duty < 1 - (2 * dead) / T))
      throw Error("正激占空比/死区无有效区间");
    const phases: [boolean, boolean, number, number, number][] = [
      [true, false, duty * T, T, Math.max(16, Math.floor(this.points / 2))],
      [false, false, dead, 0, Math.max(4, Math.floor(this.points / 32))],
      [
        false,
        true,
        (1 - duty) * T - 2 * dead,
        -T,
        Math.max(16, Math.floor(this.points / 2)),
      ],
      [false, false, dead, 0, Math.max(4, Math.floor(this.points / 32))],
    ];
    let x = initial.slice(),
      jac = eye(s).map((r) => [...r, ...Array(n + 1).fill(0)]),
      chargeJac = zeros(n, s + n + 1),
      integral = Array(n).fill(0),
      bits = this.diodes(x).map((v) => v > 0),
      elapsed = 0,
      threshold = 0,
      thresholdJac: number[] = [];
    const history = [x.slice()],
      times = [0],
      gates = [false],
      auxgates = [false];
    for (const [main, aux, duration, dduration, count] of phases) {
      const h = duration / count,
        hd = dduration / count;
      for (let tick = 0; tick < count; tick++) {
        const before = x,
          previousJac = jac;
        let z: ReturnType<ForwardCircuit["matrices"]> | undefined,
          newX: number[] = [];
        const seen = new Set<string>();
        let settled = false;
        for (let attempt = 0; attempt < 24; attempt++) {
          const signature = bits.map(Number).join("");
          z = this.matrices(main, aux, bits, h);
          newX = mv(z.flow, before).map(
            (v, i) => v + dot(z!.q[i], vo) + z!.c[i],
          );
          const drop = this.diodes(newX),
            updated = drop.map((v, i) =>
              Math.abs(v) < 1e-9 ? bits[i] : v > 0,
            );
          if (updated.every((v, i) => v === bits[i])) {
            settled = true;
            break;
          }
          if (
            seen.has(updated.map(Number).join("")) &&
            Math.max(
              0,
              ...drop.filter((_, i) => updated[i] !== bits[i]).map(Math.abs),
            ) < 1e-7
          ) {
            settled = true;
            break;
          }
          seen.add(signature);
          bits = updated;
        }
        if (!settled) throw Error("正激周期二极管状态迭代未收敛");
        x = newX;
        for (let j = 0; j < n; j++)
          integral[j] += (h * (before[n + 1 + j] + x[n + 1 + j])) / 2;
        if (derivatives) {
          jac = mm(z!.flow, previousJac);
          const dx = mv(
            z!.inv,
            mv(z!.a, x).map((v, i) => v + z!.b[i] + dot(this.B[i], vo)),
          );
          for (let i = 0; i < s; i++) {
            for (let j = 0; j < n; j++) jac[i][s + j] += z!.q[i][j];
            jac[i][s + n] += hd * dx[i];
          }
          for (let i = 0; i < n; i++) {
            for (let j = 0; j < s + n + 1; j++)
              chargeJac[i][j] +=
                (h * (previousJac[n + 1 + i][j] + jac[n + 1 + i][j])) / 2;
            chargeJac[i][s + n] +=
              (hd * (before[n + 1 + i] + x[n + 1 + i])) / 2;
          }
        }
        elapsed += h;
        if (trace) {
          history.push(x.slice());
          times.push(elapsed);
          gates.push(main);
          auxgates.push(aux);
        }
      }
      if (main) {
        const slope =
          this.p.Rs * (this.p.A_sense ?? 1) * (this.p.ma_slope || 0);
        threshold = (this.p.A_sense ?? 1) * x[this.cs] + slope * duty * T;
        if (derivatives) {
          thresholdJac = jac[this.cs].map((v) => (this.p.A_sense ?? 1) * v);
          thresholdJac[s + n] += slope * T;
        }
      }
    }
    return {
      end: x,
      mean: integral.map((v) => v / T),
      threshold,
      ...(derivatives
        ? {
            jac,
            charge_jac: chargeJac.map((r) => r.map((v) => v / T)),
            threshold_jac: thresholdJac,
          }
        : {}),
      ...(trace
        ? {
            t: times,
            states: Array.from({ length: s }, (_, i) =>
              history.map((x) => x[i]),
            ),
            gate: gates,
            aux_gate: auxgates,
          }
        : {}),
    };
  }
  solve(seed?: number[]): Spec {
    const n = this.n,
      s = this.size,
      z0 = forwardEstimate(this.p, this.rails, this.geometry, this.K),
      vo: number[] = z0.voltages,
      d = z0.duty,
      io = vo.map((v: number, j: number) => v / this.load[j]),
      x = Array(s).fill(0),
      vscale = Math.max(this.vin / (1 - d), 1);
    for (let j = 0; j < n; j++) x[n + 1 + j] = io[j];
    x[0] = (-this.vin * d * this.T) / (2 * this.p.Lm_forward);
    x[this.c] = this.vin / (1 - d);
    x[this.base + 1] = -x[this.c];
    for (let j = 0; j < n; j++)
      x[this.base + 2 + 2 * j] = x[this.base + 3 + 2 * j] =
        vo[j] + this.block[j];
    this.pairs.forEach(
      ([a, b], j) => (x[this.cj + j] = x[a] - (b === null ? 0 : x[b])),
    );
    this.extra.forEach(
      ([a, b], j) =>
        (x[this.cj + this.pairs.length + j] = x[a] - (b === null ? 0 : x[b])),
    );
    const scales = [
        Math.max(
          io.reduce((s: number, v: number) => s + v, 0),
          1,
        ),
        ...io.map((v: number) => Math.max(v, 0.03)),
        ...io.map((v: number) => Math.max(v, 0.03)),
        ...Array(2 * n + 2).fill(vscale),
        vscale,
        0.1,
        ...Array(2 * n + 2 + this.extra.length).fill(vscale),
      ],
      allScale = [...scales, ...vo.map((v: number) => Math.max(v, 1)), 1],
      imax = io.map((v: number) => Math.max(v, 0.03));
    const evaluate = (z: number[]): { f: number[]; jac: Matrix } => {
      const physical = z.map((v, i) => v * allScale[i]),
        voltage = physical.slice(s, s + n),
        duty = physical[s + n];
      if (
        !(
          duty > 0.01 &&
          duty < Math.min(this.p.forward_d_max, 1 - (2 * this.dead) / this.T)
        )
      )
        throw Error("正激周期求解超出占空比界限");
      const q = this.cycle(physical.slice(0, s), voltage, duty, true),
        f = [
          ...q.end.map((v: number, i: number) => (v - physical[i]) / scales[i]),
          ...q.mean.map(
            (v: number, i: number) => (v - voltage[i] / this.load[i]) / imax[i],
          ),
          (voltage[this.fb] - this.target) / this.target,
        ],
        jac = q.jac.map((r: number[], i: number) =>
          r.map((v, j) => ((v - +(i === j)) / scales[i]) * allScale[j]),
        );
      for (let i = 0; i < n; i++)
        jac.push(
          q.charge_jac[i].map(
            (v: number, j: number) =>
              ((v - (j === s + i ? 1 / this.load[i] : 0)) / imax[i]) *
              allScale[j],
          ),
        );
      jac.push(
        allScale.map((v, j) => (j === s + this.fb ? v / this.target : 0)),
      );
      return { f, jac };
    };
    let z = (seed || [...x, ...vo, d]).map((v, i) => v / allScale[i]),
      current = evaluate(z),
      count = 1;
    for (
      let iteration = 0;
      iteration < 70 && maxabs(current.f) > 1e-7;
      iteration++
    ) {
      let accepted = false;
      const dx = solve(
          current.jac,
          current.f.map((v) => -v),
        ),
        cost = dot(current.f, current.f);
      for (let trial = 0; trial < 16; trial++) {
        const step = 2 ** -trial,
          next = z.map((v, i) => v + step * dx[i]);
        try {
          const q = evaluate(next);
          count++;
          if (dot(q.f, q.f) < cost) {
            z = next;
            current = q;
            accepted = true;
            break;
          }
        } catch {}
      }
      if (!accepted) {
        const jt = current.jac[0].map((_, j) => current.jac.map((r) => r[j])),
          hess = mm(jt, current.jac),
          grad = mv(jt, current.f);
        for (const lambda of [1e-6, 1e-4, 0.01, 1, 100]) {
          try {
            const delta = solve(
                hess.map((r, i) =>
                  r.map(
                    (v, j) =>
                      v + (i === j ? lambda * Math.max(1, hess[i][i]) : 0),
                  ),
                ),
                grad.map((v) => -v),
              ),
              next = z.map((v, i) => v + delta[i]),
              q = evaluate(next);
            count++;
            if (dot(q.f, q.f) < cost) {
              z = next;
              current = q;
              accepted = true;
              break;
            }
          } catch {}
        }
      }
      if (!accepted) break;
    }
    const residual = maxabs(current.f);
    if (residual > 1e-6)
      throw Error("正激周期/电荷平衡未收敛：" + residual.toExponential(3));
    const physical = z.map((v, i) => v * allScale[i]),
      point = this.cycle(
        physical.slice(0, s),
        physical.slice(s, s + n),
        physical[s + n],
        true,
        true,
      );
    return {
      ...point,
      initial: physical.slice(0, s),
      voltages: physical.slice(s, s + n),
      duty: physical[s + n],
      residual,
      evaluations: count,
      seed: physical,
    };
  }
}
export const trap = (y: number[], t: number[]) => {
  let v = 0;
  for (let j = 1; j < t.length; j++)
    v += ((t[j] - t[j - 1]) * (y[j] + y[j - 1])) / 2;
  return v;
};
const cache = new Map<string, { circuit: ForwardCircuit; z: Spec }>();
export function solveForward(p: Spec, nominal: Spec): Spec {
  const rr = nominal.outputs?.length
      ? nominal.outputs
      : [{ ...p, id: 1, name: "OUT1" }],
    model = windingMatrix(p, nominal),
    n = rr.length;
  if (model.ideal)
    return {
      ...nominal,
      warnings: [
        "全部kij=1为理想奇异极限，保留原版显式标称近似，不输出非理想周期解。",
      ],
    };
  if (Math.min(...symmetricEigen(model.K).values) <= 1e-11)
    throw Error("耦合矩阵非正定或接近奇异");
  const key = JSON.stringify([
    p.V_in,
    p.f_sw,
    p.Lm_forward,
    p.Coss,
    p.Coss_aux,
    p.C_clamp,
    p.ESR_clamp,
    p.Rds_on,
    p.Rds_aux,
    p.Rs,
    p.A_sense,
    p.ma_slope,
    p.forward_dead_time,
    p.forward_d_max,
    p.feedback_output,
    p.d_in_enable,
    p.Vf_din,
    p.parasitic_config,
    p.spice_config?.cs_filter_ns,
    p.spice_config?.acf_dead_ns,
    rr,
    model.hardware,
  ]);
  let cached = cache.get(key),
    circuit: ForwardCircuit,
    z: Spec;
  if (cached) {
    circuit = cached.circuit;
    z = clone(cached.z);
  } else {
    circuit = new ForwardCircuit(p, rr, model.hardware, model, 512);
    let previous = circuit.solve();
    const mesh: Spec[] = [];
    for (const points of [1024, 2048, 4096, 8192]) {
      circuit = new ForwardCircuit(p, rr, model.hardware, model, points);
      z = circuit.solve(previous.seed);
      const measures = (q: Spec) => [
          ...q.voltages,
          q.duty,
          ...q.states.slice(0, 2 * n + 1).map((a: number[]) =>
            Math.sqrt(
              trap(
                a.map((v) => v * v),
                q.t,
              ) / circuit.T,
            ),
          ),
        ],
        a = measures(previous),
        b = measures(z),
        error = Math.max(
          ...a.map(
            (v, i) => Math.abs(v - b[i]) / Math.max(Math.abs(b[i]), 0.02),
          ),
        ),
        vc = Math.max(
          ...a
            .slice(0, n)
            .map((v, i) => Math.abs(v - b[i]) / Math.max(Math.abs(b[i]), 0.01)),
        );
      mesh.push({ points, relative_change: error, voltage_change: vc });
      previous = z;
      if (points >= 2048 && error < 0.01) break;
    }
    if (mesh.at(-1)!.voltage_change > 0.005)
      throw Error("正激电压网格细化差异超过0.5%");
    z = previous;
    z.mesh = mesh;
    if (cache.size >= 12) cache.delete(cache.keys().next().value!);
    cache.set(key, { circuit, z: clone(z) });
  }
  const op = clone(nominal),
    x: number[][] = z.states,
    t: number[] = z.t,
    D = z.duty,
    T = circuit.T,
    average = (a: number[]) => trap(a, t) / T,
    rms = (a: number[]) =>
      Math.sqrt(
        Math.max(
          trap(
            a.map((v) => v * v),
            t,
          ) / T,
          0,
        ),
      ),
    weighted = (a: number[]) =>
      a.slice(1).reduce((s, v, i) => s + (t[i + 1] - t[i]) * v, 0) / T,
    ip = x[0],
    isec = x.slice(1, n + 1).map((a) => a.map((v) => -v)),
    ilo = x.slice(n + 1, 2 * n + 1),
    vn = x.slice(circuit.base, circuit.c),
    main = t.map((v) => v < D * T),
    aux = t.map((v) => v > D * T + circuit.dead && v < T - circuit.dead),
    iw = ip.map((v, i) => (main[i] ? v : 0)),
    ic = vn[0].map(
      (v, i) => (v - vn[1][i] - x[circuit.c][i]) / Math.max(p.ESR_clamp, 1e-5),
    ),
    ia = ic.map((v, i) => (aux[i] ? v : 0)),
    linkage = ip.map((_, i) =>
      dot(
        circuit.L[0],
        x.slice(0, n + 1).map((a) => a[i]),
      ),
    ),
    im = linkage.map((v) => v / circuit.L[0][0]),
    power = z.voltages.map((v: number, j: number) => (v * v) / circuit.load[j]);
  let diss = 0,
    extra = 0;
  for (let j = 0; j <= n; j++)
    diss += circuit.R[j] * weighted(x[j].map((v) => v * v));
  diss +=
    weighted(
      vn[0].map((v, i) =>
        z.gate[i] ? (v * v) / Math.max(p.Rds_on + p.Rs, 1e-5) : 0,
      ),
    ) +
    weighted(
      vn[1].map((v, i) =>
        z.aux_gate[i] ? (v * v) / Math.max(p.Rds_aux, 1e-5) : 0,
      ),
    ) +
    p.ESR_clamp * weighted(ic.map((v) => v * v));
  diss +=
    weighted(vn[0].map((v) => Math.max(-v - 0.8, 0) * 1000 * -v)) +
    weighted(vn[1].map((v) => Math.max(v - 0.8, 0) * 1000 * v));
  circuit.pairs.forEach(
    ([a, b], i) =>
      (diss += weighted(
        x[a].map(
          (v, j) =>
            (v - (b === null ? 0 : x[b][j]) - x[circuit.cj + i][j]) ** 2 /
            circuit.cfg.r_cj,
        ),
      )),
  );
  circuit.extra.forEach(([a, b, r], i) => {
    const loss = weighted(
      x[a].map(
        (v, j) =>
          (v -
            (b === null ? 0 : x[b][j]) -
            x[circuit.cj + circuit.pairs.length + i][j]) **
            2 /
          r,
      ),
    );
    diss += loss;
    extra += loss;
  });
  extra += circuit.cfg.rp_pcb * weighted(ip.map((v) => v * v));
  circuit.cfg.rails.forEach(
    (r: Spec, j: number) =>
      (extra += r.r_pcb * weighted(x[j + 1].map((v) => v * v))),
  );
  const ir: number[][] = [],
    iff: number[][] = [],
    children = rr.map((r: Spec, j: number) => {
      const vr = vn[2 + 2 * j],
        vk = vn[3 + 2 * j],
        forward = vr.map((v, i) =>
          Math.max((v - vk[i] - circuit.vf[j]) * 1000, 0),
        ),
        free = vk.map((v) => Math.max((-v - circuit.vf[j]) * 1000, 0));
      ir.push(forward);
      iff.push(free);
      diss +=
        weighted(
          vr.map(
            (v, i) =>
              Math.max(v - vk[i] - circuit.vf[j], 0) * 1000 * (v - vk[i]),
          ),
        ) +
        weighted(vk.map((v) => Math.max(-v - circuit.vf[j], 0) * 1000 * -v));
      const vo = z.voltages[j],
        il = ilo[j],
        secondary = isec[j],
        io = vo / circuit.load[j],
        mode =
          Math.min(...il) > Math.max(Math.max(...il) * 1e-4, 1e-7)
            ? "CCM"
            : "DCM",
        c = {
          ...(nominal.output_ops?.[j] || nominal),
          D,
          Dp: 1 - D,
          mode,
          V_out: vo,
          V_out_cap: vo + circuit.block[j],
          V_feedback: vo + circuit.block[j],
          V_out_equiv: vo + circuit.block[j] + circuit.vf[j],
          P_out: power[j],
          P_rated: r.P_out,
          R: circuit.load[j],
          R_equiv: circuit.load[j],
          I_out: io,
          I_L_avg: average(il),
          I_L_pk: Math.max(...il),
          I_L_min: Math.min(...il),
          I_L_rms: rms(il),
          dI_L: ptp(il),
          I_s_rms: rms(secondary),
          I_s_pk: Math.max(...secondary),
          I_d_avg: average(secondary),
          I_d_rms: rms(secondary),
          I_d_pk: Math.max(...secondary),
          I_free_avg: average(free),
          I_free_rms: rms(free),
          I_free_pk: Math.max(...free),
          V_d_max: Math.max(...vk.map((v, i) => v - vr[i])),
          V_d_block: Math.max(...vk.map((v, i) => v - vr[i])),
          V_free_max: Math.max(...vk),
          V_free_block: Math.max(...vk),
          output_id: j + 1,
          name: r.name,
          efficiency_model: "periodic-MNA-explicit-circuit",
        };
      const charge = [0];
      for (let i = 1; i < t.length; i++)
        charge.push(
          charge[i - 1] +
            ((il[i - 1] + il[i] - 2 * io) * (t[i] - t[i - 1])) / 2,
        );
      c.C_min = ptp(charge) / Math.max(r.ripple_target * vo, 1e-12);
      c.L_min = ((c.L * c.dI_L) / Math.max(2 * io, 1e-12)) * 1.5;
      return c;
    });
  const energy =
      circuit.vin * weighted(ip) -
      z.voltages.reduce(
        (s: number, v: number, j: number) =>
          s + (v + circuit.block[j]) * weighted(ilo[j]),
        0,
      ) -
      diss,
    relative = Math.abs(energy) / Math.max(circuit.vin * average(ip), 1);
  if (relative > 0.02) throw Error("正激周期能量账本残差超过2%");
  const chief = children[circuit.fb];
  for (const k of [
    "V_out",
    "V_out_cap",
    "V_feedback",
    "V_out_equiv",
    "I_out",
    "R",
    "R_equiv",
    "L",
    "C_out",
    "Rc",
    "ESL",
    "C_out2",
    "Rc2",
    "ESL2",
    "cout2_enable",
    "I_L_avg",
    "I_L_min",
    "I_L_pk",
    "I_L_rms",
    "dI_L",
    "I_s_rms",
    "I_d_avg",
    "I_d_rms",
    "I_d_pk",
    "I_free_avg",
    "I_free_rms",
    "I_free_pk",
    "V_d_max",
    "V_d_block",
    "V_free_max",
    "V_free_block",
    "C_min",
  ])
    op[k] = chief[k];
  Object.assign(op, {
    D,
    Dp: 1 - D,
    mode: chief.mode,
    outputs: rr,
    output_ops: children,
    feedback_output: circuit.fb + 1,
    P_out: power.reduce((s: number, v: number) => s + v, 0),
    P_rated: rr.reduce((s: number, r: Spec) => s + r.P_out, 0),
    P_in_est: p.V_in * average(ip),
    I_in_est: average(ip),
    I_p_rms: rms(ip),
    I_p_avg: average(ip),
    I_sw_rms: rms(iw),
    I_sw_avg: average(iw),
    I_sw_pk: Math.max(...ip.filter((_, i) => main[i])),
    I_sw_on: Math.max(
      im[0] +
        ilo.reduce(
          (s, a, j) => s + (circuit.L[0][j + 1] / circuit.L[0][0]) * a[0],
          0,
        ),
      0,
    ),
    I_sw_on_waveform: ip[0],
    I_sw_off: ip[main.lastIndexOf(true)],
    I_aux_rms: rms(ia),
    I_aux_pk: Math.max(...ia.map(Math.abs)),
    I_aux_avg_abs: average(ia.map(Math.abs)),
    I_mag_pk: Math.max(...im.map(Math.abs)),
    dI_mag: ptp(im),
    V_sw_max: Math.max(...vn[0]),
    V_clamp: average(x[circuit.c]),
    V_clamp_hump: Math.max(...x[circuit.c]) - average(x[circuit.c]),
    V_clamp_pp: ptp(x[circuit.c]),
    V_reset: average(x[circuit.c]) - circuit.vin,
    V_in_bus: circuit.vin,
    I_clamp_rms: rms(ic),
    efficiency_model: "periodic-MNA-explicit-circuit",
    voltage_convention: "output-after-blocking-feedback-before-blocking-v1",
    P_parasitic: extra,
  });
  op.P_loss_budget = op.P_in_est - op.P_out;
  op.f_clamp_effective = (1 - D) * op.f_clamp;
  op.fc_recommended_max = Math.min(op.f_sw / 10, op.f_clamp_effective / 5);
  op.acf_model = {
    kind: "periodic-MNA",
    revision: 1,
    converged: true,
    independent_prediction: true,
    transformer_hardware: model.hardware,
    L: circuit.L,
    R: circuit.R,
    K: circuit.K,
    winding_rms: x.slice(0, n + 1).map(rms),
    load_resistances: circuit.load,
    output_voltages: z.voltages,
    normalized_residual: z.residual,
    mesh: z.mesh,
    energy_balance_W: energy,
    energy_balance_relative: relative,
    current_mesh_verified: z.mesh.at(-1).relative_change <= 0.02,
    state_initial: z.initial,
    period_jac: z.jac,
    charge_jac: z.charge_jac,
    threshold_jac: z.threshold_jac,
    threshold: z.threshold,
    linearization_slope: p.Rs * p.A_sense * p.ma_slope,
    state_scales: x.map((a) => Math.max(...a.map(Math.abs), 0.01)),
    assumptions:
      "两两互感、几何 DCR、独立输出电感、钳位 C/ESR、常数 Coss/Cj、有限导通电阻及双边沿死区。周期电流与各路电荷平衡求解；输出电容直流近似，纹波由逐颗 C+ESR/ESL 重建。预设效率仅作参考，不重复叠加。输出电感未含 DCR；理想边沿不推定 ZVS，未含反向恢复、温度和饱和。",
  };
  op.acf_solution = {
    t,
    i_primary: ip,
    i_mag: im,
    i_sw: iw,
    i_aux: ia,
    i_s: isec,
    iL: ilo,
    i_forward: ir,
    i_free: iff,
    i_clamp: ic,
    v_sw: vn[0],
    v_clamp: x[circuit.c],
    v_primary: vn[0].map((v, i) => circuit.vin - v - circuit.R[0] * ip[i]),
    lambda_p: linkage,
    v_d: rr.map((_: Spec, j: number) =>
      vn[3 + 2 * j].map((v, i) => v - vn[2 + 2 * j][i]),
    ),
    v_free: rr.map((_: Spec, j: number) => vn[3 + 2 * j]),
  };
  op.warnings = [
    op.acf_model.assumptions,
    "二极管反压含常数结电容模型振铃；真实尖峰仍须实测并留余量。",
  ];
  return op;
}
