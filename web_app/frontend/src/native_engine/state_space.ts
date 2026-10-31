/** Real state-space systems shared by pole checks, responses and period-map models. */
import { Matrix as MLMatrix, EigenvalueDecomposition } from "ml-matrix";
import { type Spec, bank } from "./spec";
import {
  type Matrix,
  type C,
  zeros,
  eye,
  add,
  scale,
  mm,
  mv,
  inverse,
  solve,
  expm,
} from "./math";
export type System = { A: Matrix; B: Matrix; C: Matrix; D: Matrix };
export type Gain = ((f: number) => C) & { system?: System };
export function eigenvalues(a: Matrix): C[] {
  if (!a.length) return [];
  const n = a.length,
    m = a.map((r) => r.slice());
  // Similarity balance before the nonsymmetric QR eigenvalue decomposition.
  for (let step = 0; step < 30; step++) {
    let changed = false;
    for (let i = 0; i < n; i++) {
      let row = 0,
        col = 0;
      for (let j = 0; j < n; j++)
        if (i !== j) {
          row += Math.abs(m[i][j]);
          col += Math.abs(m[j][i]);
        }
      if (!row || !col) continue;
      let f = 1,
        c = col;
      while (c < row / 2) {
        c *= 4;
        f *= 2;
      }
      while (c > row * 2) {
        c /= 4;
        f /= 2;
      }
      if ((c + row) / f < 0.95 * (col + row)) {
        changed = true;
        for (let j = 0; j < n; j++) {
          m[i][j] /= f;
          m[j][i] *= f;
        }
      }
    }
    if (!changed) break;
  }
  const e = new EigenvalueDecomposition(new MLMatrix(m), {
    assumeSymmetric: false,
  });
  return e.realEigenvalues.map((v, i) => [v, e.imaginaryEigenvalues[i]] as C);
}
export function frequencySystem(s: System, f: number): C[][] {
  const n = s.A.length,
    inputs = s.D[0].length;
  if (!n) return s.D.map((r) => r.map((v) => [v, 0] as C));
  const a = zeros(2 * n);
  for (let i = 0; i < n; i++)
    for (let j = 0; j < n; j++) {
      a[i][j] = a[i + n][j + n] = -s.A[i][j];
      if (i === j) {
        a[i][j + n] = -2 * Math.PI * f;
        a[i + n][j] = 2 * Math.PI * f;
      }
    }
  const response = Array.from({ length: inputs }, (_, j) =>
    solve(a, [...s.B.map((r) => r[j]), ...Array(n).fill(0)]),
  );
  return s.C.map((r, i) =>
    response.map(
      (x, j) =>
        [
          s.D[i][j] + r.reduce((v, c, k) => v + c * x[k], 0),
          r.reduce((v, c, k) => v + c * x[k + n], 0),
        ] as C,
    ),
  );
}
export function systemGain(s: System, output = 0, input = 0): Gain {
  const f: Gain = (hz) => frequencySystem(s, hz)[output][input];
  f.system = s;
  return f;
}
export function polynomialSystem(num: number[], den: number[]): System {
  num = num.slice();
  den = den.slice();
  while (den.length > 1 && den.at(-1) === 0) den.pop();
  const n = den.length - 1;
  if (num.length > den.length) throw Error("不支持非真有理传函");
  if (!n) return { A: [], B: [], C: [[]], D: [[num[0] / den[0]]] };
  const omega = Math.exp(
      (Math.log(Math.max(Math.abs(den[0]), 1e-30)) -
        Math.log(Math.abs(den[n]))) /
        n,
    ),
    w = Number.isFinite(omega) && omega > 1e-12 ? omega : 1,
    leading = den[n] * w ** n,
    d = den.map((v, i) => (v * w ** i) / leading),
    b = Array.from(
      { length: n + 1 },
      (_, i) => ((num[i] || 0) * w ** i) / leading,
    ),
    A = zeros(n),
    B = zeros(n, 1),
    C = [b.slice(0, n).map((v, i) => v - b[n] * d[i])];
  for (let i = 0; i < n - 1; i++) A[i][i + 1] = w;
  for (let j = 0; j < n; j++) A[n - 1][j] = -w * d[j];
  B[n - 1][0] = w;
  return { A, B, C, D: [[b[n]]] };
}
export const convolve = (a: number[], b: number[]) => {
  const r = Array(a.length + b.length - 1).fill(0);
  for (let i = 0; i < a.length; i++)
    for (let j = 0; j < b.length; j++) r[i + j] += a[i] * b[j];
  return r;
};
export function series(first: System, second: System): System {
  // Both SISO; second(first(input)).
  const n = first.A.length,
    m = second.A.length,
    A = zeros(n + m),
    B = zeros(n + m, 1),
    C = zeros(1, n + m),
    D = [[first.D[0][0] * second.D[0][0]]];
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) A[i][j] = first.A[i][j];
    B[i][0] = first.B[i][0];
    C[0][i] = second.D[0][0] * first.C[0][i];
  }
  for (let i = 0; i < m; i++) {
    for (let j = 0; j < n; j++) A[n + i][j] = second.B[i][0] * first.C[0][j];
    for (let j = 0; j < m; j++) A[n + i][n + j] = second.A[i][j];
    B[n + i][0] = second.B[i][0] * first.D[0][0];
    C[0][n + i] = second.C[0][i];
  }
  return { A, B, C, D };
}
export function closeLoop(p: System, c: System, fb = 0): System {
  const n = p.A.length,
    m = c.A.length,
    inputs = p.D[0].length,
    size = n + m,
    k = 1 + c.D[0][0] * p.D[fb][0];
  if (Math.abs(k) < 1e-14) throw Error("闭环代数反馈奇异");
  const ux = [
      ...p.C[fb].map((v) => (-c.D[0][0] * v) / k),
      ...c.C[0].map((v) => v / k),
    ],
    ui = [c.D[0][0] / k, ...p.D[fb].slice(1).map((v) => (-c.D[0][0] * v) / k)],
    yx = p.C[fb].concat(Array(m).fill(0)).map((v, i) => v + p.D[fb][0] * ux[i]),
    yi = ui.map((v, j) => (j ? p.D[fb][j] : 0) + p.D[fb][0] * v),
    A = zeros(size),
    B = zeros(size, inputs);
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < size; j++)
      A[i][j] = (j < n ? p.A[i][j] : 0) + p.B[i][0] * ux[j];
    for (let j = 0; j < inputs; j++)
      B[i][j] = (j ? p.B[i][j] : 0) + p.B[i][0] * ui[j];
  }
  for (let i = 0; i < m; i++) {
    for (let j = 0; j < size; j++)
      A[n + i][j] = (j >= n ? c.A[i][j - n] : 0) - c.B[i][0] * yx[j];
    for (let j = 0; j < inputs; j++)
      B[n + i][j] = c.B[i][0] * ((j === 0 ? 1 : 0) - yi[j]);
  }
  return {
    A,
    B,
    C: p.C.map((r, i) =>
      r.concat(Array(m).fill(0)).map((v, j) => v + p.D[i][0] * ux[j]),
    ),
    D: p.D.map((r, i) => ui.map((v, j) => (j ? r[j] : 0) + r[0] * v)),
  };
}
export function outputFilters(
  rails: Spec[],
  loads: number[],
  voltages: number[],
) {
  const blocks: Spec[] = [],
    banks: Spec[] = [];
  let states = 0;
  rails.forEach((r, j) => {
    const caps = bank(r),
      finite = caps.filter((c) => c.ESR > 0),
      ideal = caps.filter((c) => !c.ESR).reduce((s, c) => s + c.C, 0),
      n = finite.length + (ideal ? 1 : 0),
      a = zeros(n),
      b = Array(n).fill(0),
      c = Array(n).fill(0);
    let d = 0;
    if (ideal) {
      a[0][0] =
        -(1 / loads[j] + finite.reduce((s, c) => s + 1 / c.ESR, 0)) / ideal;
      b[0] = 1 / ideal;
      c[0] = 1;
      finite.forEach((v, k) => {
        a[0][k + 1] = 1 / (ideal * v.ESR);
        a[k + 1][0] = 1 / (v.ESR * v.C);
        a[k + 1][k + 1] = -1 / (v.ESR * v.C);
      });
    } else {
      d = 1 / (1 / loads[j] + finite.reduce((s, c) => s + 1 / c.ESR, 0));
      finite.forEach((v, i) => {
        c[i] = d / v.ESR;
        b[i] = d / (v.ESR * v.C);
      });
      finite.forEach((v, i) => {
        for (let k = 0; k < n; k++)
          a[i][k] = (c[k] - +(i === k)) / (v.ESR * v.C);
      });
    }
    blocks.push({
      a,
      b: b.map((v) => v / voltages[j]),
      c: c.map((v) => v * voltages[j]),
      d,
    });
    states += n;
    banks.push({ output: j + 1, branches: caps, states: n });
  });
  const A = zeros(states),
    B = zeros(states, rails.length),
    C = zeros(rails.length, states),
    D = zeros(rails.length);
  let offset = 0;
  blocks.forEach((q, j) => {
    for (let i = 0; i < q.a.length; i++) {
      for (let k = 0; k < q.a.length; k++)
        A[offset + i][offset + k] = q.a[i][k];
      B[offset + i][j] = q.b[i];
      C[j][offset + i] = q.c[i];
    }
    D[j][j] = q.d;
    offset += q.a.length;
  });
  return { A, B, C, D, banks };
}
export function periodSystem(
  ax: Matrix,
  bx: Matrix,
  jx: Matrix,
  jf: Matrix,
  hx: number[],
  hf: number[],
  rr: Spec[],
  loads: number[],
  volts: number[],
  peak: boolean,
  Vm: number,
): System & { banks: Spec[] } {
  const n = rr.length,
    s = ax.length,
    filters = outputFilters(rr, loads, volts),
    m = filters.A.length,
    algebraic = zeros(n + 1),
    states = zeros(n + 1, s + m),
    inputs = zeros(n + 1, n + 1);
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++)
      algebraic[i][j] = +(i === j) - filters.D[i][i] * jf[i][j];
    algebraic[i][n] = -filters.D[i][i] * jf[i][n];
    for (let j = 0; j < s; j++) states[i][j] = filters.D[i][i] * jx[i][j];
    for (let j = 0; j < m; j++) states[i][s + j] = filters.C[i][j];
    inputs[i][i + 1] = -filters.D[i][i];
  }
  for (let j = 0; j < n; j++) algebraic[n][j] = peak ? hf[j] : 0;
  algebraic[n][n] = peak ? hf[n] : Vm;
  if (algebraic[n][n] <= 1e-8) throw Error("峰值比较器占空比增益非正");
  if (peak) for (let j = 0; j < s; j++) states[n][j] = -hx[j];
  inputs[n][0] = 1;
  const sol = mm(
      inverse(algebraic),
      states.map((r, i) => [...r, ...inputs[i]]),
    ),
    vs = sol.slice(0, n).map((r) => r.slice(0, s + m)),
    ds = sol[n].slice(0, s + m),
    vi = sol.slice(0, n).map((r) => r.slice(s + m)),
    di = sol[n].slice(s + m),
    av = bx.map((r) => r.slice(0, n)),
    ad = bx.map((r) => r[n]),
    jv = jf.map((r) => r.slice(0, n)),
    jd = jf.map((r) => r[n]),
    bjx = mm(filters.B, jx),
    bjv = mm(filters.B, jv),
    bjd = mv(filters.B, jd),
    top = mm(av, vs),
    bottom = mm(bjv, vs),
    btop = mm(av, vi),
    bbottom = mm(bjv, vi);
  for (let i = 0; i < s; i++) {
    for (let j = 0; j < s + m; j++)
      top[i][j] += (j < s ? ax[i][j] : 0) + ad[i] * ds[j];
    for (let j = 0; j < n + 1; j++) btop[i][j] += ad[i] * di[j];
  }
  for (let i = 0; i < m; i++) {
    for (let j = 0; j < s + m; j++)
      bottom[i][j] +=
        (j < s ? bjx[i][j] : filters.A[i][j - s]) + bjd[i] * ds[j];
    for (let j = 0; j < n + 1; j++)
      bbottom[i][j] += bjd[i] * di[j] - (j ? filters.B[i][j - 1] : 0);
  }
  return {
    A: [...top, ...bottom],
    B: [...btop, ...bbottom],
    C: vs,
    D: vi,
    banks: filters.banks,
  };
}
export function stepResponse(
  s: System,
  input: number,
  end: number,
  points = 600,
) {
  if (!(end > 0)) throw Error("响应时间必须大于0");
  const n = s.A.length,
    h = end / (points - 1),
    aug = zeros(n + 1);
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) aug[i][j] = s.A[i][j];
    aug[i][n] = s.B[i][input];
  }
  const e = expm(scale(aug, h));
  let x = Array(n).fill(0);
  const time: number[] = [],
    values = s.C.map(() => [] as number[]);
  for (let i = 0; i < points; i++) {
    time.push(i * h);
    s.C.forEach((r, j) =>
      values[j].push(r.reduce((v, c, k) => v + c * x[k], 0) + s.D[j][input]),
    );
    x = mv(e, [...x, 1]).slice(0, n);
  }
  return { time, values };
}
