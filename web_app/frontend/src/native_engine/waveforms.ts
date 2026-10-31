import { nisoWaveforms } from "./nonisolated";
import { type Spec, bank } from "./spec";
import { fft, mean, rms, ptp, cdiv, cmul, cadd, type C } from "./math";
function lookup(t: number[], values: number[], x: number) {
  let lo = 0,
    hi = t.length - 1;
  while (hi - lo > 1) {
    const m = (lo + hi) >> 1;
    if (t[m] > x) hi = m;
    else lo = m;
  }
  return (
    values[lo] + ((values[hi] - values[lo]) * (x - t[lo])) / (t[hi] - t[lo])
  );
}
function impedance(caps: Spec[], frequency: number, esl = true): C {
  let y: C = [0, 0];
  const w = 2 * Math.PI * frequency;
  for (const c of caps)
    y = cadd(y, cdiv([1, 0], [c.ESR, w * (esl ? c.ESL : 0) - 1 / (w * c.C)]));
  return cdiv([1, 0], y);
}
export function ripple(
  current: number[],
  dt: number,
  caps: Spec[],
  esl = true,
) {
  const average = mean(current),
    x = fft(current.map((v) => v - average)),
    n = current.length;
  for (let k = 0; k < n; k++) {
    if (!k) {
      x.real[k] = x.imag[k] = 0;
      continue;
    }
    const frequency = (k <= n / 2 ? k : k - n) / (dt * n),
      value = cmul([x.real[k], x.imag[k]], impedance(caps, frequency, esl));
    x.real[k] = value[0];
    x.imag[k] = value[1];
  }
  return fft(x.real, x.imag, true).real;
}
export function spectrum(
  current: number[],
  dt: number,
  f: number,
  caps: Spec[],
) {
  const ac = current.map((v) => v - mean(current)),
    x = fft(ac),
    n = x.real.length,
    labels = [
      "<0.5f",
      ...Array.from({ length: 20 }, (_, i) => i + 1 + "f"),
      "HF",
    ],
    bins = caps.map(() => Array(22).fill(0));
  for (let k = 1; k <= n / 2; k++) {
    const hz = k / (dt * n),
      power =
        ((k === n / 2 ? 1 : 2) * (x.real[k] ** 2 + x.imag[k] ** 2)) / n ** 2,
      z = impedance(caps, hz),
      w = 2 * Math.PI * hz,
      index = Math.min(21, Math.floor(hz / f + 0.5));
    caps.forEach((c, j) => {
      const ratio = cdiv(z, [c.ESR, w * c.ESL - 1 / (w * c.C)]);
      bins[j][index] += power * (ratio[0] ** 2 + ratio[1] ** 2);
    });
  }
  return {
    total_bank: rms(ac),
    labels,
    caps: caps.map((c, i) => ({
      ...c,
      total: Math.sqrt(bins[i].reduce((s, v) => s + v, 0)),
      bands: bins[i].map(Math.sqrt),
    })),
    spectrum_method: "coherent DFT",
  };
}
function finish(w: Spec, op: Spec) {
  const caps = bank(op),
    lf = ripple(w.i_c, w.dt, caps, false),
    all = ripple(w.i_c, w.dt, caps, true);
  return {
    ...w,
    vout_ripple: lf,
    v_esl: all.map((v, i) => v - lf[i]),
    vout: lf.map((v) => v + op.V_out),
    vcap: lf.map((v) => v + (op.V_out_cap ?? op.V_out)),
    ripple_pp: ptp(lf),
    ripple_pp_total: ptp(all),
    esl_spike_pp: Math.max(...all.map((v, i) => Math.abs(v - lf[i]))),
    i_c_rms: rms(w.i_c),
  };
}
export function waveforms(op: Spec, points = 2048): Spec {
  if (op.niso_model) return nisoWaveforms(op, points);
  if (op.acf_solution) {
    const z = op.acf_solution,
      t = Array.from({ length: points * 2 }, (_, i) => (i * op.Ts) / points),
      ph = t.map((v) => v % op.Ts),
      sample = (a: number[]) => ph.map((v) => lookup(z.t, a, v)),
      input = sample(z.i_primary),
      common: Spec = {
        t,
        dt: op.Ts / points,
        f_sw: op.f_sw,
        topology: op.topology,
        i_primary: input,
        i_p: input,
        i_mag: sample(z.i_mag),
        i_sw: sample(z.i_sw),
        i_aux: sample(z.i_aux),
        i_in: input,
        v_sw: sample(z.v_sw),
        v_primary: sample(z.v_primary),
        v_clamp: sample(z.v_clamp),
        i_clamp: sample(z.i_clamp),
        i_cin: input.map((v) => v - mean(input)),
      };
    common.i_cin_rms = rms(common.i_cin);
    const outputs = op.output_ops.map((q: Spec, j: number) => {
      const il = sample(z.iL[j]);
      return finish(
        {
          ...common,
          iL: il,
          i_s: sample(z.i_s[j]),
          i_d: sample(z.i_forward[j]),
          i_free: sample(z.i_free[j]),
          i_c: il.map((v) => v - q.I_out),
          v_d: sample(z.v_d[j]),
          v_free: sample(z.v_free[j]),
        },
        q,
      );
    });
    return { ...outputs[(op.feedback_output || 1) - 1], outputs };
  }
  if (op.output_ops?.length && !op.coupled_solution) {
    const primary = waveforms(op.aggregate_op, points),
      outputs = op.output_ops.map((q: Spec) => waveforms(q, points)),
      main = outputs[(op.feedback_output || 1) - 1];
    return {
      ...primary,
      ...Object.fromEntries(
        [
          "i_d",
          "i_s",
          "i_c",
          "v_d",
          "vout",
          "vout_ripple",
          "v_esl",
          "ripple_pp",
          "ripple_pp_total",
          "esl_spike_pp",
          "i_c_rms",
        ].map((k) => [k, main[k]]),
      ),
      outputs,
    };
  }
  const t = Array.from({ length: points * 2 }, (_, i) => (i * op.Ts) / points),
    dt = op.Ts / points,
    phase = t.map((v) => (v % op.Ts) / op.Ts),
    on = phase.map((v) => v < op.D),
    pk = op.I_L_pk,
    low = op.I_L_min,
    tri = phase.map((x) =>
      x < op.D
        ? low + ((pk - low) * x) / op.D
        : x < op.D + op.Dp
          ? pk - ((pk - low) * (x - op.D)) / op.Dp
          : 0,
    );
  let w: Spec = {
    t,
    dt,
    f_sw: op.f_sw,
    topology: op.topology,
    iL: tri,
    i_p: tri,
    i_sw: tri.map((v, i) => (on[i] ? v : 0)),
    i_d: tri.map((v, i) => (on[i] ? 0 : v)),
    v_sw: phase.map((_, i) => (on[i] ? 0 : op.V_sw_max / (1 + op.ring_margin))),
    v_d: phase.map((_, i) => (on[i] ? op.V_d_max : 0)),
  };
  if (op.coupled_solution) {
    const sol = op.coupled_solution,
      ph = t.map((v) => v % op.Ts),
      sample = (a: number[]) => ph.map((v) => lookup(sol.t, a, v)),
      secondaries = sol.i_winding.slice(1).map(sample),
      error = Math.max(
        ...secondaries.map(
          (a: number[], i: number) =>
            Math.abs(mean(a) - op.output_ops[i].I_out) /
            Math.max(op.output_ops[i].I_out, 1e-6),
        ),
      );
    if (error > 0.002) {
      if (points >= 131072) throw Error("窄脉冲采样未通过电荷核对");
      return waveforms(op, points * 2);
    }
    w = {
      ...w,
      i_sw: sample(sol.i_sw),
      i_in: sample(sol.i_in),
      v_sw: sample(sol.v_sw),
      iL: sample(sol.i_magnetizing),
      i_p: sample(sol.i_magnetizing),
      i_clamp: sample(sol.i_clamp),
    };
    w.i_cin = w.i_in.map((v: number) => v - mean(w.i_in));
    w.i_cin_rms = rms(w.i_cin);
    const outputs = op.output_ops.map((q: Spec, j: number) => {
      const current = secondaries[j],
        volt = sample(sol.v_winding[j + 1]);
      return finish(
        {
          ...w,
          i_d: current,
          i_s: current,
          i_c: current.map((v: number) => v - q.I_out),
          v_d: current.map((v: number, i: number) =>
            Math.max(0, q.V_out_cap + volt[i] + op.coupled_model.R[j + 1] * v),
          ),
        },
        q,
      );
    });
    const main = outputs[(op.feedback_output || 1) - 1];
    return {
      ...w,
      ...Object.fromEntries(
        [
          "i_d",
          "i_s",
          "i_c",
          "v_d",
          "vout",
          "vout_ripple",
          "v_esl",
          "ripple_pp",
          "ripple_pp_total",
          "esl_spike_pp",
          "i_c_rms",
        ].map((k) => [k, main[k]]),
      ),
      outputs,
    };
  }
  if (["FLYBACK", "QR-FLYBACK"].includes(op.topology)) {
    w.i_d = phase.map((x, i) =>
      on[i] ? 0 : Math.max(0, op.N * (pk - ((pk - low) * (x - op.D)) / op.Dp)),
    );
    w.i_s = w.i_d;
    w.i_in = w.i_sw;
    w.i_c = w.i_d.map((v: number) => v - op.I_out);
    w.v_sw = phase.map((x, i) => {
      if (on[i]) return 0;
      const c = op.clamp,
        t = (x - op.D) * op.Ts;
      let v = c?.V_plateau ?? op.V_in + op.V_r;
      if (c?.shape === "clamped" && t < c.t_pulse)
        v =
          t < c.t_rise
            ? c.V_plateau +
              c.I_initial * Math.sqrt(c.L_leak / op.Coss) * Math.sin(t / c.t_lc)
            : c.V_ceiling;
      if (c?.shape === "unclamped_lobe" && t < c.t_lc * Math.PI)
        v += c.I_initial * Math.sqrt(c.L_leak / op.Coss) * Math.sin(t / c.t_lc);
      return v;
    });
  } else if (op.topology === "BUCK") {
    w.i_in = w.i_sw;
    w.i_c = tri.map((v) => v - op.I_out);
  } else if (op.topology === "ACF-FORWARD") {
    const mag = phase.map((x) =>
      x < op.D
        ? -op.I_mag_pk + (2 * op.I_mag_pk * x) / op.D
        : op.I_mag_pk - (2 * op.I_mag_pk * (x - op.D)) / (1 - op.D),
    );
    w.i_mag = mag;
    w.i_d = tri.map((v, i) => (on[i] ? v : 0));
    w.i_free = tri.map((v, i) => (on[i] ? 0 : v));
    w.i_sw = tri.map((v, i) => (on[i] ? v / op.N + mag[i] : 0));
    w.i_aux = mag.map((v, i) => (on[i] ? 0 : v));
    w.i_in = w.i_sw;
    w.i_s = w.i_d;
    w.i_c = tri.map((v) => v - op.I_out);
    w.v_sw = on.map((v) => (v ? 0 : op.V_clamp));
  } else {
    w.i_in = tri;
    w.i_c = w.i_d.map((v: number) => v - op.I_out);
  }
  w.i_cin = w.i_in.map((v: number) => v - mean(w.i_in));
  w.i_cin_rms = rms(w.i_cin);
  return finish(w, op);
}
export const capacitors = (p: Spec, op: Spec, w: Spec) => ({
  f_sw: op.f_sw,
  total_in: rms(w.i_cin),
  total_out: rms(w.i_c),
  input: spectrum(w.i_cin, w.dt, op.f_sw, bank(p, "input")),
  output: spectrum(w.i_c, w.dt, op.f_sw, bank(p)),
});
