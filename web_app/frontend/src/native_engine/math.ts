/** Small deterministic numerical primitives. All physical quantities use SI. */
export type Matrix = number[][];
export const zeros = (n: number, m = n): Matrix =>
  Array.from({ length: n }, () => Array(m).fill(0));
export const eye = (n: number) =>
  zeros(n).map((r, i) => r.map((_, j) => +(i === j)));
export const transpose = (a: Matrix) =>
  a[0]?.map((_, j) => a.map((r) => r[j])) || [];
export const mv = (a: Matrix, x: number[]) => a.map((r) => dot(r, x));
export const dot = (a: number[], b: number[]) =>
  a.reduce((v, x, i) => v + x * b[i], 0);
export const mm = (a: Matrix, b: Matrix) =>
  a.map((r) => transpose(b).map((c) => dot(r, c)));
export const add = (a: Matrix, b: Matrix, scale = 1) =>
  a.map((r, i) => r.map((v, j) => v + scale * b[i][j]));
export const scale = (a: Matrix, s: number) =>
  a.map((r) => r.map((v) => v * s));
export function expm(a: Matrix) {
  const magnitude = Math.max(
      ...a.map((r) => r.reduce((s, v) => s + Math.abs(v), 0)),
    ),
    s = Math.max(0, Math.ceil(Math.log2(magnitude || 1))),
    b = scale(a, 2 ** -s);
  let value = eye(a.length),
    term = eye(a.length);
  for (let k = 1; k < 65; k++) {
    term = scale(mm(term, b), 1 / k);
    value = add(value, term);
    if (Math.max(...term.flat().map(Math.abs)) < 1e-16) break;
  }
  for (let k = 0; k < s; k++) value = mm(value, value);
  return value;
}
export const outer = (a: number[], b: number[]) =>
  a.map((x) => b.map((y) => x * y));
export const norm = (a: number[]) => Math.sqrt(dot(a, a));
export const maxabs = (a: number[]) => Math.max(...a.map(Math.abs));
export const clamp = (x: number, l: number, h: number) =>
  Math.max(l, Math.min(h, x));
export const mean = (a: number[]) => a.reduce((s, x) => s + x, 0) / a.length;
export const rms = (a: number[]) => Math.sqrt(mean(a.map((x) => x * x)));
export const ptp = (a: number[]) => Math.max(...a) - Math.min(...a);
export function solve(a: Matrix, b: number[]): number[] {
  const n = b.length,
    m = a.map((r, i) => [...r, b[i]]);
  for (let j = 0; j < n; j++) {
    let p = j;
    for (let i = j + 1; i < n; i++)
      if (Math.abs(m[i][j]) > Math.abs(m[p][j])) p = i;
    if (Math.abs(m[p][j]) < 1e-24) throw Error("数值矩阵奇异，无法计算");
    [m[j], m[p]] = [m[p], m[j]];
    for (let i = j + 1; i < n; i++) {
      const s = m[i][j] / m[j][j];
      for (let k = j; k <= n; k++) m[i][k] -= s * m[j][k];
    }
  }
  const x = Array(n).fill(0);
  for (let i = n - 1; i >= 0; i--)
    x[i] = (m[i][n] - dot(m[i].slice(i + 1, n), x.slice(i + 1))) / m[i][i];
  return x;
}
export const inverse = (a: Matrix) =>
  transpose(eye(a.length).map((c) => solve(a, c)));
export function cholesky(a: Matrix) {
  const n = a.length,
    l = zeros(n);
  for (let i = 0; i < n; i++)
    for (let j = 0; j <= i; j++) {
      let s = a[i][j];
      for (let k = 0; k < j; k++) s -= l[i][k] * l[j][k];
      if (i === j) {
        if (s <= 0) throw Error("耦合矩阵必须为正定矩阵");
        l[i][j] = Math.sqrt(s);
      } else l[i][j] = s / l[j][j];
    }
  return l;
}
export function symmetricEigen(a: Matrix) {
  const n = a.length,
    d = a.map((r) => [...r]),
    v = eye(n);
  for (let step = 0; step < 100 * n * n; step++) {
    let p = 0,
      q = 0,
      big = 0;
    for (let i = 0; i < n; i++)
      for (let j = i + 1; j < n; j++)
        if (Math.abs(d[i][j]) > big) {
          big = Math.abs(d[i][j]);
          p = i;
          q = j;
        }
    if (big <= 1e-13 * Math.max(1, ...d.map((r, i) => Math.abs(r[i])))) break;
    const phi = 0.5 * Math.atan2(2 * d[p][q], d[q][q] - d[p][p]),
      c = Math.cos(phi),
      s = Math.sin(phi),
      pp = d[p][p],
      qq = d[q][q],
      pq = d[p][q];
    for (let k = 0; k < n; k++)
      if (k !== p && k !== q) {
        const x = d[k][p],
          y = d[k][q];
        d[k][p] = d[p][k] = c * x - s * y;
        d[k][q] = d[q][k] = s * x + c * y;
      }
    d[p][p] = c * c * pp - 2 * c * s * pq + s * s * qq;
    d[q][q] = s * s * pp + 2 * c * s * pq + c * c * qq;
    d[p][q] = d[q][p] = 0;
    for (let k = 0; k < n; k++) {
      const x = v[k][p],
        y = v[k][q];
      v[k][p] = c * x - s * y;
      v[k][q] = s * x + c * y;
    }
  }
  return { values: d.map((r, i) => r[i]), vectors: v };
}
export function root(
  f: (x: number) => number,
  a: number,
  b: number,
  tol = 1e-14,
) {
  let fa = f(a);
  for (let i = 0; i < 65 && b - a > tol; i++) {
    const c = (a + b) / 2,
      fc = f(c);
    if (fc >= 0 === fa >= 0) {
      a = c;
      fa = fc;
    } else b = c;
  }
  return (a + b) / 2;
}
export function leastSquares(
  f: (x: number[]) => number[],
  initial: number[],
  lo: number[],
  hi: number[],
) {
  let x = initial.map((v, i) => clamp(v, lo[i] + 1e-9, hi[i] - 1e-9)),
    r = f(x),
    cost = dot(r, r),
    lambda = 1e-4;
  for (let iteration = 0; iteration < 180; iteration++) {
    if (maxabs(r) < 3e-8) return { x, residual: r, iterations: iteration };
    const n = x.length,
      j = zeros(r.length, n);
    for (let k = 0; k < n; k++) {
      const h = Math.max(Math.abs(x[k]) * 2e-5, 2e-7),
        t = [...x];
      t[k] = Math.min(hi[k], x[k] + h);
      const y = f(t);
      for (let i = 0; i < r.length; i++)
        j[i][k] = (y[i] - r[i]) / (t[k] - x[k]);
    }
    const jt = transpose(j),
      a = mm(jt, j),
      g = mv(jt, r);
    let accepted = false;
    for (let trial = 0; trial < 18; trial++) {
      const regular = a.map((row, i) =>
        row.map((v, k) => v + (i === k ? lambda * Math.max(a[i][i], 1) : 0)),
      );
      const dx = solve(
          regular,
          g.map((v) => -v),
        ),
        next = x.map((v, i) => clamp(v + dx[i], lo[i], hi[i]));
      let rr: number[];
      try {
        rr = f(next);
      } catch {
        lambda *= 10;
        continue;
      }
      const cc = dot(rr, rr);
      if (cc < cost) {
        x = next;
        r = rr;
        cost = cc;
        lambda = Math.max(lambda / 4, 1e-13);
        accepted = true;
        break;
      }
      lambda *= 5;
    }
    if (!accepted) break;
  }
  return { x, residual: r, iterations: 180 };
}
export function gamma(z: number): number {
  const p = [
    676.5203681218851, -1259.1392167224028, 771.32342877765313,
    -176.61502916214059, 12.507343278686905, -0.13857109526572012,
    9.984369578019572e-6, 1.5056327351493116e-7,
  ];
  if (z < 0.5) return Math.PI / (Math.sin(Math.PI * z) * gamma(1 - z));
  z -= 1;
  let x = 0.99999999999980993;
  for (let i = 0; i < p.length; i++) x += p[i] / (z + i + 1);
  const t = z + p.length - 0.5;
  return Math.sqrt(2 * Math.PI) * t ** (z + 0.5) * Math.exp(-t) * x;
}
export function interpolate(
  points: number[][],
  x: number,
  xlog = false,
  ylog = false,
) {
  const pts = points
    .filter((p) => p.every(Number.isFinite))
    .slice()
    .sort((a, b) => a[0] - b[0]);
  if (pts.length < 2) throw Error("曲线至少需要两个不同坐标点");
  let i = pts.findIndex((p) => p[0] >= x);
  i = i < 0 ? pts.length - 1 : i === 0 ? 1 : i;
  const [a, b] = [pts[i - 1], pts[i]],
    tx = (v: number) => (xlog ? Math.log(Math.max(v, 1e-30)) : v),
    ty = (v: number) => (ylog ? Math.log(Math.max(v, 1e-30)) : v);
  if (b[0] === a[0]) return b[1];
  const y =
    ty(a[1]) +
    ((ty(b[1]) - ty(a[1])) * (tx(x) - tx(a[0]))) / (tx(b[0]) - tx(a[0]));
  return ylog ? Math.exp(y) : y;
}
export type C = [number, number];
export const cadd = (a: C, b: C): C => [a[0] + b[0], a[1] + b[1]];
export const cmul = (a: C, b: C): C => [
  a[0] * b[0] - a[1] * b[1],
  a[0] * b[1] + a[1] * b[0],
];
export const cdiv = (a: C, b: C): C => {
  const d = b[0] ** 2 + b[1] ** 2;
  return [(a[0] * b[0] + a[1] * b[1]) / d, (a[1] * b[0] - a[0] * b[1]) / d];
};
export const cabs = (a: C) => Math.hypot(...a);
/** Radix-2 FFT, same unnormalized forward transform as numpy.fft. */
export function fft(real: number[], imag?: number[], back = false) {
  const n = real.length,
    r = [...real],
    im = imag ? [...imag] : Array(n).fill(0);
  if (n & (n - 1)) throw Error("FFT 点数必须是 2 的整数次幂");
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [r[i], r[j]] = [r[j], r[i]];
      [im[i], im[j]] = [im[j], im[i]];
    }
  }
  for (let len = 2; len <= n; len *= 2) {
    const angle = ((back ? 2 : -2) * Math.PI) / len;
    for (let i = 0; i < n; i += len) {
      let wr = 1,
        wi = 0;
      for (let j = 0; j < len / 2; j++) {
        const a = i + j,
          b = a + len / 2,
          tr = wr * r[b] - wi * im[b],
          ti = wr * im[b] + wi * r[b];
        r[b] = r[a] - tr;
        im[b] = im[a] - ti;
        r[a] += tr;
        im[a] += ti;
        const w = wr;
        wr = w * Math.cos(angle) - wi * Math.sin(angle);
        wi = w * Math.sin(angle) + wi * Math.cos(angle);
      }
    }
  }
  return {
    real: back ? r.map((x) => x / n) : r,
    imag: back ? im.map((x) => x / n) : im,
  };
}
