/** Port of power_stage.py / isolated_outputs.py, with the same efficiency burden. */
import { type Spec, rails, bank, blockDrop, validate, clone } from "./spec";
import { transformer } from "./magnetics";
export const tri = (hi: number, lo: number, duty: number) =>
  Math.sqrt(
    ((hi * hi + hi * lo + lo * lo) / 3) * Math.max(0, Math.min(1, duty)),
  );
export function single(p: Spec): Spec {
  const eta = p.eta_guess,
    v = p.V_in,
    u = p.V_out / eta,
    power = p.P_out / eta,
    f = p.f_sw,
    l = p.L,
    n = p.N,
    t = 1 / f,
    io = power / u,
    r = (u * u) / power,
    kind = p.topology;
  let d = 0,
    dp = 0,
    di = 0,
    avg = 0,
    hi = 0,
    lo = 0,
    mode = "CCM",
    vs = 0,
    vd = 0,
    rhp = Infinity,
    lmin = 0,
    cmin = 0,
    actualF = f,
    extra: Spec = {};
  if (kind === "QR-FLYBACK") {
    const vr = n * u,
      ring = Math.PI * Math.sqrt(l * p.Coss),
      a = l * (1 / v + 1 / vr),
      b = power * a;
    hi = (b + Math.sqrt(b * b + 2 * l * power * ring)) / l;
    const ton = (l * hi) / v,
      off = (l * hi) / vr;
    actualF = 1 / (ton + off + ring);
    d = ton * actualF;
    dp = off * actualF;
    avg = power / v;
    di = hi;
    mode = "BCM";
    vs = v + (p.Kc > 1 ? p.Kc : 1) * vr;
    vd = u + v / n;
    cmin = (io * d) / (actualF * p.ripple_target * u);
    extra = { T_on: ton, T_demag: off, T_ring: ring, V_r: vr, f_max: f };
  } else if (kind === "BUCK" || kind === "ACF-FORWARD") {
    const input = kind === "BUCK" ? v : v / n;
    if (u >= input) throw Error("Buck/正激要求整流侧输入电压高于输出等效电压");
    d = u / input;
    dp = 1 - d;
    di = ((input - u) * d) / f / l;
    avg = io;
    hi = io + di / 2;
    lo = io - di / 2;
    if (lo < 0) {
      mode = "DCM";
      d = Math.sqrt((2 * io * l * u * f) / (input * (input - u)));
      hi = ((input - u) * d) / f / l;
      dp = ((input - u) * d) / u;
      lo = 0;
      di = hi;
      avg = 0.5 * hi * (d + dp);
    }
    vs = v * (1 + p.ring_margin);
    vd = v;
    lmin = (((input - u) * (u / input)) / (2 * f * io)) * 1.5;
    cmin = di / (8 * f * p.ripple_target * u);
    if (kind === "ACF-FORWARD") {
      if (d >= p.forward_d_max) throw Error("正激占空比达到配置上限");
      const im = (v * d * t) / (2 * p.Lm_forward),
        start = lo / n - im,
        end = hi / n + im,
        vr = v / (1 - d),
        hump = (v * d * (1 - d)) / (8 * p.Lm_forward * f * f * p.C_clamp),
        fr = 1 / (2 * Math.PI * Math.sqrt(p.Lm_forward * p.C_clamp));
      vs = (vr + hump) * (1 + p.ring_margin);
      vd = (vr - v) / n;
      extra = {
        I_sw_on: start,
        I_sw_off: end,
        I_sw_rms: tri(end, start, d),
        I_sw_pk: Math.max(Math.abs(start), Math.abs(end)),
        I_sw_avg: ((start + end) * d) / 2,
        I_free_rms: tri(hi, lo, dp),
        I_free_avg: ((hi + lo) * dp) / 2,
        I_free_pk: hi,
        V_free_max: input,
        I_aux_rms: im * Math.sqrt((1 - d) / 3),
        I_aux_pk: im,
        I_mag_pk: im,
        V_clamp: vr,
        V_reset: vr - v,
        V_clamp_hump: hump,
        Lm_forward: p.Lm_forward,
        C_clamp: p.C_clamp,
        I_clamp_rms: im * Math.sqrt((1 - d) / 3),
        f_clamp: fr,
        f_clamp_effective: (1 - d) * fr,
        C_clamp_min: (v * d * (1 - d)) / (8 * p.Lm_forward * f * f * 0.05 * vr),
      };
    }
  } else if (kind === "BOOST" || kind === "BUCK-BOOST") {
    if (kind === "BOOST" && u <= v)
      throw Error("Boost 要求输出等效电压高于输入");
    d = kind === "BOOST" ? 1 - v / u : u / (v + u);
    dp = 1 - d;
    di = (v * d) / f / l;
    avg = io / dp;
    hi = avg + di / 2;
    lo = avg - di / 2;
    if (lo < 0) {
      mode = "DCM";
      const m = u / v;
      d =
        kind === "BOOST"
          ? Math.sqrt((l * ((2 * m - 1) ** 2 - 1)) / (2 * r * t))
          : m * Math.sqrt((2 * l) / (r * t));
      hi = (v * d * t) / l;
      dp = (2 * io) / hi;
      avg = 0.5 * hi * (d + dp);
      lo = 0;
      di = hi;
    }
    vs = (kind === "BOOST" ? u : v + u) * (1 + p.ring_margin);
    vd = kind === "BOOST" ? u : v + u;
    rhp =
      mode === "CCM"
        ? (dp * dp * r) / (2 * Math.PI * l * (kind === "BOOST" ? 1 : d))
        : Infinity;
    lmin =
      ((v *
        (kind === "BOOST" ? 1 - v / u : u / (v + u)) *
        (kind === "BOOST" ? v / u : 1 - u / (v + u))) /
        (2 * f * io)) *
      1.5;
    cmin = (io * d) / (f * p.ripple_target * u);
  } else if (kind === "FLYBACK") {
    d = (n * u) / (v + n * u);
    dp = 1 - d;
    avg = power / (v * d);
    di = (v * d) / f / l;
    hi = avg + di / 2;
    lo = avg - di / 2;
    if (lo < 0) {
      mode = "DCM";
      d = Math.sqrt(2 * u * io * l * f) / v;
      hi = (v * d * t) / l;
      dp = (2 * io) / (n * hi);
      lo = 0;
      di = hi;
    }
    vs = v + (p.Kc > 1 ? p.Kc : 1) * n * u;
    vd = u + v / n;
    rhp =
      mode === "CCM" ? (v * n * (1 - d)) / (2 * Math.PI * l * io) : Infinity;
    const dc = (n * u) / (v + n * u);
    lmin = ((v * dc) / (f * 0.4 * (power / (v * dc)))) * 1.5;
    cmin = (io * d) / (f * p.ripple_target * u);
    extra.V_r = n * u;
    avg = (hi + lo) / 2;
  } else throw Error("未知拓扑 " + kind);
  const fly = ["FLYBACK", "QR-FLYBACK"].includes(kind),
    op: Spec = {
      ...p,
      topology: kind,
      V_in: v,
      V_out: p.V_out,
      P_out: p.P_out,
      eta_guess: eta,
      V_out_equiv: u,
      R_equiv: r,
      R: p.V_out ** 2 / p.P_out,
      I_out: p.P_out / p.V_out,
      P_in_est: power,
      I_in_est: power / v,
      P_loss_budget: power - p.P_out,
      efficiency_model: "equivalent_output_burden",
      f_sw: actualF,
      Ts: 1 / actualF,
      D: d,
      Dp: dp,
      mode,
      I_L_avg: avg,
      dI_L: di,
      I_L_pk: hi,
      I_L_min: lo,
      I_L_rms: tri(hi, lo, fly ? d : d + dp),
      I_sw_rms: tri(hi, lo, d),
      I_sw_pk: hi,
      I_sw_avg: ((hi + lo) * d) / 2,
      I_d_rms: tri(hi, lo, dp) * (fly ? n : 1),
      I_d_pk: hi * (fly ? n : 1),
      I_d_avg: p.P_out / p.V_out,
      V_sw_max: vs,
      V_d_max: vd,
      rhp_zero: rhp,
      L_min: lmin,
      C_min: cmin / eta,
      pwr_factor: 1,
      ...extra,
    };
  if (kind === "ACF-FORWARD") {
    op.I_p_rms = Math.hypot(op.I_sw_rms, op.I_aux_rms);
    op.I_s_rms = op.I_d_rms;
    op.I_d_avg = ((hi + lo) * d) / 2;
  }
  return attachNodes(attachClamp(op, p), p);
}
export function attachNodes(op: Spec, p: Spec) {
  return Object.assign(op, {
    V_out_cap: op.V_out + blockDrop(p),
    V_feedback: op.V_out + blockDrop(p),
    V_feedback_target: p.V_out + blockDrop(p),
    V_block: blockDrop(p),
    V_in_bus: p.V_in - (p.d_in_enable ? p.Vf_din : 0),
    voltage_convention: "output-after-blocking-feedback-before-blocking-v1",
  });
}
export function attachClamp(op: Spec, p: Spec) {
  if (!["FLYBACK", "QR-FLYBACK"].includes(op.topology)) return op;
  const plateau = op.V_in + op.V_r,
    ceiling = op.V_in + (p.Kc > 1 ? p.Kc : 1) * op.V_r,
    leak = Math.max(0, (1 - (p.K ?? 0.95)) * op.L),
    i0 = op.I_sw_off ?? op.I_L_pk,
    delta = ceiling - plateau,
    c = p.Coss || 0;
  let peak = plateau,
    power = 0,
    rise = 0,
    decay = 0,
    shape = "none",
    start = 0;
  if (p.Kc > 1 && leak > 0 && i0 > 0 && delta > 0) {
    const tau = Math.sqrt(leak * c),
      natural = c ? i0 * Math.sqrt(leak / c) : Infinity;
    if (delta >= natural) {
      peak = plateau + natural;
      rise = (Math.PI / 2) * tau;
      shape = "unclamped_lobe";
    } else {
      rise = c ? tau * Math.asin(delta / natural) : 0;
      start = c ? i0 * Math.sqrt(1 - (delta / natural) ** 2) : i0;
      decay = (leak * start) / delta;
      power = 0.5 * (ceiling - op.V_in) * start * decay * op.f_sw;
      peak = ceiling;
      shape = "clamped";
    }
  }
  op.clamp = {
    model: "nominal_leakage_envelope",
    V_plateau: plateau,
    V_peak: peak,
    V_clamp: ceiling - op.V_in,
    V_ceiling: ceiling,
    P_res: power,
    L_leak: leak,
    t_rise: rise,
    t_decay: decay,
    t_pulse: rise + decay,
    t_lc: Math.sqrt(leak * c),
    I_clamp_start: start,
    I_initial: i0,
    shape,
  };
  op.V_sw_max = Math.max(ceiling, peak);
  return op;
}
export function nominal(p: Spec): Spec {
  validate(p);
  const rr = rails(p);
  const psrSeed = (raw: Spec) => {
    if (p.feedback_mode !== "PSR-MP6005")
      return { op: single(raw), q: raw, region: "PWM" };
    if (p.topology !== "FLYBACK") throw Error("MP6005 PSR 仅支持固定频率反激");
    const q: Spec = {
      ...raw,
      f_sw: 250000,
      control_mode: "Peak Current Mode",
      A_sense: 11,
    };
    let op = single(q),
      region = "PWM";
    if (op.I_sw_pk * q.Rs < 0.036) {
      const minimum = 0.036 / q.Rs,
        required = (2 * op.P_in_est) / (q.L * minimum ** 2);
      if (required < 30000)
        throw Error("MP6005 PSR 低于最小能量负载，请增加预负载");
      q.f_sw = Math.min(required, 250000);
      op = single(q);
      if (op.mode !== "DCM") throw Error("PSR 轻载降频估算仅支持 DCM");
      region = "PFM-estimate";
    }
    return { op, q, region };
  };
  if (!rr.length) {
    const z = psrSeed(p);
    return p.feedback_mode === "PSR-MP6005"
      ? {
          ...z.op,
          aggregate_op: z.op,
          aggregate_params: z.q,
          feedback_mode: p.feedback_mode,
          regulation_region: z.region,
        }
      : z.op;
  }
  const main = (p.feedback_output || 1) - 1,
    fb = rr[main],
    np =
      p._fixed_transformer?.Np ||
      p.Np ||
      transformer(
        single({
          ...p,
          ...fb,
          N: p.N * (rr[0].Ns / fb.Ns),
          P_out: rr.reduce((s, r) => s + r.P_out, 0),
        }),
        p,
      ).Np,
    pp: Spec = {
      ...p,
      ...fb,
      outputs: [],
      feedback_output: 1,
      N: np / fb.Ns,
      Np: np,
      Ns: fb.Ns,
      P_out: rr.reduce((s, r) => s + r.P_out, 0),
    };
  if (p.topology === "ACF-FORWARD")
    pp.L = 1 / rr.reduce((s, r) => s + (r.V_out / fb.V_out) ** 2 / r.L, 0);
  const seed = psrSeed(pp),
    aggregate = seed.op,
    op: Spec = {
      ...aggregate,
      outputs: rr,
      aggregate_op: aggregate,
      aggregate_params: seed.q,
      regulation_region: seed.region,
      feedback_output: main + 1,
      feedback_mode: p.feedback_mode || "SSR",
      output_turns: {
        Np: np,
        Ns: rr.map((r) => r.Ns),
        ratios: rr.map((r) => np / r.Ns),
      },
    };
  op.output_ops = rr.map((r) => {
    const n = np / r.Ns,
      w = r.P_out / pp.P_out;
    let q: Spec;
    if (p.topology === "ACF-FORWARD") q = single({ ...pp, ...r, N: n });
    else
      q = {
        ...aggregate,
        ...r,
        N: n,
        V_out: r.V_out,
        V_out_equiv: r.V_out / p.eta_guess,
        P_out: r.P_out,
        I_out: r.P_out / r.V_out,
        R: (r.V_out * r.V_out) / Math.max(r.P_out, 1e-15),
        I_L_pk: aggregate.I_L_pk * w,
        I_L_min: aggregate.I_L_min * w,
        I_d_pk: aggregate.I_L_pk * w * n,
        I_d_rms: (aggregate.I_d_rms * w * n) / aggregate.N,
        I_d_avg: r.P_out / r.V_out,
        V_d_max: r.V_out / p.eta_guess + p.V_in / n,
        C_min: aggregate.C_min * w * (aggregate.V_out / r.V_out) ** 2,
      };
    return attachNodes({ ...q, output_id: r.id, name: r.name }, r);
  });
  const selected = op.output_ops[main];
  for (const k of [
    "I_out",
    "R",
    "I_d_pk",
    "I_d_rms",
    "I_d_avg",
    "V_d_max",
    "C_min",
    "C_out",
    "Rc",
    "ESL",
    "C_out2",
    "Rc2",
    "ESL2",
    "cout2_enable",
    "V_out_cap",
    "V_feedback",
  ])
    op[k] = selected[k];
  return op;
}
export function windingHardware(p: Spec, op: Spec) {
  const rr = op.outputs?.length ? op.outputs : [{ ...p, id: 1, name: "OUT1" }],
    main = (p.feedback_output || 1) - 1,
    fb = rr[main],
    np = op.output_turns?.Np || p.Np || 6,
    pp: Spec = {
      ...p,
      ...fb,
      Np: np,
      Ns: fb.Ns || p.Ns,
      N: np / (fb.Ns || p.Ns),
    },
    tr = transformer(op, pp),
    fixed = p._fixed_transformer || {};
  const windings = rr.map((r: Spec, i: number) => {
    const f = fixed.windings?.[i] || {},
      ns = f.Ns || r.Ns || tr.Ns,
      strands = f.n_strand_s || r.n_strand_s || 1,
      current = op.output_ops?.[i]?.I_d_rms ?? op.I_d_rms,
      diameter =
        f.d_wire_s ||
        r.d_wire_s ||
        Math.max(50e-6, Math.sqrt((4 * current) / strands / p.J / Math.PI)),
      area = (strands * Math.PI * diameter * diameter) / 4;
    return {
      id: i + 1,
      Ns: ns,
      d_wire_s: diameter,
      n_strand_s: strands,
      R_dc: (p.rho * tr.MLT * ns) / area,
    };
  });
  return { ...tr, windings };
}
