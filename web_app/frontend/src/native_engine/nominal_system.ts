/** Explicit rational forms of the desktop averaged plants, for independent pole checks. */
import { type Spec, bank } from "./spec";
import {
  type System,
  polynomialSystem,
  outputFilters,
  series,
  convolve,
} from "./state_space";
export function controllerSystem(p: Spec): System {
  if (p._psr)
    p = {
      ...p,
      KP: p._psr.KP,
      fz1: p._psr.fz,
      fp1: p._psr.fp,
      controller_type: "type2",
    };
  const two =
    p.controller_type === "type2" ||
    (p.controller_type === "auto" && p.control_mode !== "Voltage Mode");
  return polynomialSystem(
    two
      ? [p.KP, p.KP / (2 * Math.PI * p.fz1)]
      : convolve(
          [p.KP, p.KP / (2 * Math.PI * p.fz1)],
          [1, 1 / (2 * Math.PI * p.fz2)],
        ),
    two
      ? [0, 1, 1 / (2 * Math.PI * p.fp1)]
      : convolve(
          [0, 1, 1 / (2 * Math.PI * p.fp1)],
          [1, 1 / (2 * Math.PI * p.fp2)],
        ),
  );
}
export function nominalSystem(p: Spec, op: Spec): System {
  const q = op.aggregate_params || p,
    o = op.aggregate_op || op,
    kind = p.topology,
    v = q.V_in,
    u = o.V_out_equiv,
    r = (u * u) / o.P_in_est,
    l = q.L,
    n = q.N,
    eta = o.eta_guess,
    fi = q.Rs * q.A_sense,
    c = op.outputs?.length
      ? op.outputs.reduce(
          (s: number, r: Spec) =>
            s + bank(r).reduce((a, x) => a + x.C, 0) * (r.V_out / o.V_out) ** 2,
          0,
        )
      : q.output_capacitors != null
        ? bank(q).reduce((s, x) => s + x.C, 0)
        : q.C_out,
    d =
      kind === "FLYBACK"
        ? (n * u) / (v + n * u)
        : kind === "BOOST"
          ? 1 - v / u
          : kind === "BUCK-BOOST"
            ? u / (v + u)
            : u / (kind === "ACF-FORWARD" ? v / n : v),
    dp = 1 - d;
  let sys: System;
  if (kind === "QR-FLYBACK" && p.control_mode === "Peak Current Mode") {
    const a = l * (1 / v + 1 / o.V_r),
      di = o.I_out * (2 / o.I_sw_pk - a / o.Ts),
      dv = o.I_out * (-n / o.V_r + (l * o.I_sw_pk * n) / (o.V_r ** 2 * o.Ts)),
      f = outputFilters([q], [1 / (1 / o.R - dv)], [o.V_out_cap || o.V_out]);
    sys = {
      A: f.A,
      B: f.B.map((r) => [(r[0] * di) / fi]),
      C: f.C,
      D: [[(f.D[0][0] * di) / fi]],
    };
  } else if (o.mode === "DCM" || o.mode === "BCM") {
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
    sys = polynomialSystem([(gain / q.Vm) * eta], [1, 1 / pole]);
  } else {
    const m1 = v / l,
      m2 =
        kind === "BOOST"
          ? (u - v) / l
          : kind === "FLYBACK"
            ? (n * u) / l
            : u / l,
      raw = q.ma_slope + (m1 - m2) / 2,
      fm =
        o.f_sw / (fi * Math.max(Math.abs(raw <= 0 ? (m1 + m2) / 2 : raw), 1));
    if (kind === "BUCK" || kind === "ACF-FORWARD") {
      const vin = kind === "ACF-FORWARD" ? v / n : v,
        dd = u / vin,
        fv = ((1 - 2 * dd) * o.Ts * fi) / (2 * l),
        t1 = (fm * u * fi) / (dd * r),
        t2 = (fm * fv * u) / dd,
        den0 = 1 + t1 + t2,
        w = (1 / Math.sqrt(l * c)) * Math.sqrt(den0),
        quality =
          (r * Math.sqrt(c / l) * Math.sqrt(den0)) /
          (1 + (r * c * fm * u * fi) / dd / l),
        gain = (u * fm) / dd / den0;
      sys =
        p.control_mode === "Voltage Mode"
          ? polynomialSystem([(vin / q.Vm) * eta], [1, l / r, l * c])
          : polynomialSystem([gain * eta], [1, 1 / (quality * w), 1 / (w * w)]);
    } else if (kind === "FLYBACK" || kind === "BUCK-BOOST") {
      const ratio = kind === "FLYBACK" ? n : 1,
        a = (ratio * dp) ** 2,
        gd = u / d / dp,
        nd = [gd, (-gd * d * l) / a / r],
        delta = [1, l / a / r, (l * c) / a];
      if (p.control_mode === "Voltage Mode")
        sys = polynomialSystem(
          nd.map((v) => (v * eta) / q.Vm),
          delta,
        );
      else {
        const fv = (-dp * dp * o.Ts * fi) / (2 * l),
          gi = (ratio * u * (1 + d)) / d / a / r,
          ni = [gi, (gi * r * c) / (1 + d)],
          den = delta.map(
            (v, i) => v + fm * (fi * (ni[i] || 0) + fv * (nd[i] || 0)),
          );
        sys = polynomialSystem(
          nd.map((v) => v * eta * fm),
          den,
        );
      }
    } else {
      const fv = (dp * dp * o.Ts * fi) / (2 * l),
        t1 = (2 * fm * u * fi) / (dp * dp * r),
        t2 = (fm * fv * u) / dp,
        w = (dp / Math.sqrt(l * c)) * Math.sqrt(1 + t1 + t2),
        quality =
          (dp * r * Math.sqrt(c / l) * Math.sqrt(1 + t1 + t2)) /
          (1 + (r * c * fm * u * fi) / (dp * l) - (fm * fv * u) / dp),
        gain = (u * fm) / dp / (1 + t1 + t2),
        g = p.control_mode === "Voltage Mode" ? u / dp / q.Vm : gain;
      sys = polynomialSystem(
        [g * eta, (-g * eta * l) / (dp * dp * r)],
        p.control_mode === "Voltage Mode"
          ? [1, l / (dp * dp * r), (l * c) / (dp * dp)]
          : [1, 1 / (quality * w), 1 / (w * w)],
      );
    }
  }
  if (p.feedback_mode === "PSR-MP6005") {
    const d = op.psr;
    sys = series(
      sys,
      polynomialSystem([d.Hfb, (-d.Hfb * op.Ts) / 4], [1, op.Ts / 4]),
    );
  }
  return sys;
}
