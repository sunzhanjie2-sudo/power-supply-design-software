/** Detached engineering candidates. Never mutate a completed run or its hardware. */
import { type Spec, clone } from "./spec";
import { design, checks } from "./engine";
import { tune, loopResponse } from "./loop";
import { compensationAction } from "./compensation";
import { lineChart } from "./charts";
import { inductorHardware } from "./inductor_selection";
export function scaleLoad(raw: Spec, fraction: number) {
  const p = clone(raw);
  if (!(fraction > 0 && fraction <= 1)) throw Error("负载比例须为 (0,1]");
  p.P_out *= fraction;
  if (p.outputs?.length)
    p.outputs.forEach((r: Spec) => {
      r.P_out *= fraction;
      r.P_out_min = Math.min(r.P_out_min ?? r.P_out, r.P_out);
    });
  return p;
}
export function pinHardware(run: Spec) {
  const p = clone(run.p);
  if (run.mag.transformer)
    p._fixed_transformer = clone(
      run.op.coupled_model?.transformer_hardware ||
        run.op.acf_model?.transformer_hardware ||
        run.mag.transformer,
    );
  if (run.mag.inductor) p._fixed_inductor = inductorHardware(run.mag.inductor);
  if (run.mag.inductors) p._fixed_inductors = clone(run.mag.inductors);
  if (run.psr) {
    p.psr_Na = run.psr.Na;
    p.psr_RfbL = run.psr.RfbL;
    p._fixed_auxiliary = clone(run.mag.transformer.auxiliary);
  }
  return p;
}
function validVariables(p: Spec, variables: string[]) {
  const allowed = [
    "f_sw",
    "L",
    "N",
    "C_out",
    "Rds_on",
    "Bmax",
    "Lm_forward",
    "C_clamp",
  ];
  if (
    !variables.length ||
    variables.length > 3 ||
    new Set(variables).size !== variables.length ||
    variables.some((k) => !allowed.includes(k))
  )
    throw Error("请选择1～3个合法且不同的设计变量");
  if (
    variables.includes("f_sw") &&
    (p.feedback_mode === "PSR-MP6005" || p.topology === "QR-FLYBACK")
  )
    throw Error("PSR/QR 频率由工作模式确定，不能直接扫描");
  if (
    p.outputs?.length &&
    variables.some(
      (k) => k === "C_out" || (k === "L" && p.topology === "ACF-FORWARD"),
    )
  )
    throw Error("多路支路参数须在输出配置内修改");
  if (
    variables.some((k) => ["Lm_forward", "C_clamp"].includes(k)) &&
    p.topology !== "ACF-FORWARD"
  )
    throw Error("仅正激有励磁/钳位参数");
}
export function cornerAnalysis(
  run: Spec,
  options: Spec,
  progress: (s: string) => void,
) {
  const lo = Number(options.v_in_min),
    hi = Number(options.v_in_max),
    fracs: number[] = options.load_fracs || [];
  if (
    !(0 < lo && lo <= run.p.V_in && run.p.V_in <= hi && Number.isFinite(hi)) ||
    !fracs.length ||
    fracs.length > 8 ||
    fracs.some((f) => !(f > 0 && f <= 1))
  )
    throw Error("输入范围须覆盖当前输入，负载点为1～8个 (0,1] 数");
  const base = { ...run.p, V_in: lo, input_voltage_case: "min" },
    reference = design(base),
    fixed = pinHardware(reference),
    voltages = [
      ...new Set(options.include_nominal ? [lo, run.p.V_in, hi] : [lo, hi]),
    ].sort((a, b) => a - b),
    rows: Spec[] = [];
  for (const vin of voltages)
    for (const frac of fracs) {
      progress(
        `固定硬件角点 ${rows.length + 1}/${voltages.length * fracs.length}`,
      );
      const row: Spec = {
        id: "C" + String(rows.length + 1).padStart(2, "0"),
        V_in: vin,
        load_frac: frac,
      };
      try {
        const p = scaleLoad(fixed, frac);
        Object.assign(p, {
          V_in: vin,
          input_voltage_case: vin === hi && hi !== lo ? "max" : "min",
        });
        const r = design(p),
          devices = [
            r.mag.transformer,
            ...(r.mag.inductors || [r.mag.inductor]),
          ].filter(Boolean),
          ck = checks(p, r),
          finiteMaximum = (key: string) => {
            const values = devices.map((d) => d[key])
              .filter((v) => typeof v === "number" && Number.isFinite(v));
            return values.length ? Math.max(...values) : null;
          };
        Object.assign(row, {
          skipped: false,
          mode: r.op.mode,
          D: r.op.D,
          f_sw: r.op.f_sw,
          I_L_pk: r.op.I_L_pk,
          V_sw_max: r.op.V_sw_max,
          ripple_pp: r.wf.ripple_pp,
          eta: r.eta,
          dT: finiteMaximum("dT"),
          B_pk: finiteMaximum("B_pk"),
          fc: r.loop?.fc,
          pm: r.loop?.pm,
          min_pm: r.loop?.min_pm,
          gm_db: r.loop?.gm_db,
          failed_checks: ck.filter((c) => c.state !== "pass").map((c) => c.id),
          checks: ck,
        });
      } catch (e) {
        Object.assign(row, { skipped: true, error: String(e) });
      }
      rows.push(row);
    }
  const worst: Spec = {},
    worstCases: Spec = {};
  for (const [label, key, isMin] of [
    ["min_eta", "eta", true],
    ["max_I_L_pk", "I_L_pk", false],
    ["max_ripple_pp", "ripple_pp", false],
    ["max_V_sw_max", "V_sw_max", false],
    ["max_dT", "dT", false],
    ["max_B_pk", "B_pk", false],
    ["min_pm", "min_pm", true],
  ] as [string, string, boolean][]) {
    const valid = rows
      .filter((r) => !r.skipped && typeof r[key] === "number" && Number.isFinite(r[key]))
      .sort((a, b) => (isMin ? 1 : -1) * (a[key] - b[key]));
    if (valid.length) {
      worst[label] = valid[0][key];
      worstCases[label] = {
        id: valid[0].id,
        V_in: valid[0].V_in,
        load_frac: valid[0].load_frac,
      };
    }
  }
  return {
    corners: rows,
    worst,
    worst_cases: worstCases,
    v_in: [lo, hi],
    load_fracs: fracs,
    fixed_hardware: true,
    hardware: Object.fromEntries(
      Object.entries(fixed).filter(([k]) => k.startsWith("_fixed_")),
    ),
    notes: ["失败角点保留；最坏值只来自成功工况，非完整连续包络。"],
    chart_svg: lineChart(
      voltages.map((v) => ({
        x: rows
          .filter((r) => r.V_in === v && !r.skipped)
          .map((r) => r.load_frac * 100),
        y: rows
          .filter((r) => r.V_in === v && !r.skipped)
          .map((r) => r.eta * 100),
        label: "Vin " + v + "V",
      })),
      "固定硬件 · 电压与负载角点",
      "η / %",
      false,
      540,
      "负载 / %",
    ),
  };
}
export function efficiencySweep(
  run: Spec,
  action: string,
  opts: Spec,
  progress: (s: string) => void,
): Spec {
  const p = clone(run.p);
  for (const k in p) if (k.startsWith("_fixed_")) delete p[k];
  validVariables(p, [opts.variable]);
  const lo = Number(opts.minimum),
    hi = Number(opts.maximum),
    points = Number(opts.points),
    frac = opts.load_frac ?? 1;
  if (
    !(lo > 0 && hi > lo && Number.isFinite(hi)) ||
    !Number.isInteger(points) ||
    points < 5 ||
    points > 41
  )
    throw Error("扫描须为正的递增范围和5～41点");
  const log = ["f_sw", "L", "C_out", "Rds_on", "Bmax"].includes(opts.variable),
    rows: Spec[] = [];
  for (let i = 0; i < points; i++) {
    const value = log
      ? lo * (hi / lo) ** (i / (points - 1))
      : lo + ((hi - lo) * i) / (points - 1);
    progress(`参数扫描 ${i + 1}/${points}`);
    try {
      const q = scaleLoad(p, frac);
      q[opts.variable] = value;
      rows.push({ value, eta: design(q, false).eta });
    } catch (e) {
      rows.push({ value, eta: null, error: String(e) });
    }
  }
  let target: number | null = null;
  if (action === "find_target") {
    if (!(opts.target_eta > 0 && opts.target_eta <= 1))
      throw Error("目标效率范围无效");
    const i = rows.findIndex((r) => r.eta !== null && r.eta >= opts.target_eta);
    if (i >= 0) {
      target = rows[i].value;
      if (i > 0 && rows[i - 1].eta !== null && rows[i].eta !== rows[i - 1].eta)
        target =
          rows[i - 1].value +
          ((opts.target_eta - rows[i - 1].eta) /
            (rows[i].eta - rows[i - 1].eta)) *
            (rows[i].value - rows[i - 1].value);
    }
  }
  return {
    variable: opts.variable,
    rows,
    target_value: target,
    target_eta: opts.target_eta,
    spec_updates: target !== null ? { [opts.variable]: target } : {},
    notes: [
      "逐点重新设计自动磁件；与固定 BOM 角点不同。失败点留空，目标未达到不提出虚假解。",
    ],
    chart_svg: lineChart(
      [
        {
          x: rows.filter((r) => r.eta !== null).map((r) => r.value),
          y: rows.filter((r) => r.eta !== null).map((r) => r.eta * 100),
          label: opts.variable,
        },
      ],
      "参数扫描 · " + opts.variable,
      "η / %",
      log,
      540,
      opts.variable + " / SI",
    ),
  };
}
export function optimizeEfficiency(
  run: Spec,
  opts: Spec,
  progress: (s: string) => void,
) {
  const p = clone(run.p),
    variables: string[] = opts.variables || [],
    bounds: number[][] = opts.bounds || [];
  for (const k in p) if (k.startsWith("_fixed_")) delete p[k];
  validVariables(p, variables);
  if (
    bounds.length !== variables.length ||
    bounds.some((b) => !(b[0] > 0 && b[1] > b[0] && Number.isFinite(b[1])))
  )
    throw Error("优化边界须为有限正数递增范围");
  const iterations = Math.min(20, Math.max(1, Math.trunc(opts.maxiter || 6))),
    dim = variables.length,
    size = Math.max(5, Math.min(10, Math.trunc(opts.popsize || 5)) * dim),
    budget = Math.max(100, size * (iterations + 1) + 100);
  let seed = Number(opts.seed || 0) >>> 0,
    evaluations = 0,
    best: Spec | null = null;
  const random = () => {
    seed = (seed + 0x6d2b79f5) >>> 0;
    let t = seed;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const evaluate = (x: number[]) => {
    if (evaluations >= budget) return 1;
    evaluations++;
    const q = scaleLoad(p, opts.load_frac ?? 1);
    variables.forEach((k, i) => (q[k] = x[i]));
    let score = 1;
    try {
      const r = design(q, false);
      score = -r.eta + (r.op.mode === "DCM" ? 0.25 : 0);
      if (!best || score < best.fun)
        best = {
          best: Object.fromEntries(variables.map((k, i) => [k, x[i]])),
          eta: r.eta,
          fun: score,
        };
    } catch {}
    if (evaluations % 5 === 0) progress(`优化候选 ${evaluations}/${budget}`);
    return score;
  };
  const population = Array.from({ length: size }, (_, i) =>
      bounds.map((b, j) =>
        i === 0
          ? Math.min(b[1], Math.max(b[0], p[variables[j]]))
          : b[0] + random() * (b[1] - b[0]),
      ),
    ),
    scores = population.map(evaluate);
  let nit = 0,
    ok = false;
  for (; nit < iterations; nit++) {
    for (let i = 0; i < size; i++) {
      const picks: number[] = [];
      while (picks.length < 3) {
        const j = Math.floor(random() * size);
        if (j !== i && !picks.includes(j)) picks.push(j);
      }
      const force = Math.floor(random() * dim),
        candidate = population[i].map((v, j) =>
          random() < 0.7 || j === force
            ? Math.min(
                bounds[j][1],
                Math.max(
                  bounds[j][0],
                  population[picks[0]][j] +
                    0.7 * (population[picks[1]][j] - population[picks[2]][j]),
                ),
              )
            : v,
        ),
        score = evaluate(candidate);
      if (score < scores[i]) {
        population[i] = candidate;
        scores[i] = score;
      }
    }
    const mean = scores.reduce((a, b) => a + b, 0) / size,
      spread = Math.sqrt(
        scores.reduce((a, b) => a + (b - mean) ** 2, 0) / size,
      );
    if (spread <= 1e-6 * Math.abs(mean) && best) {
      ok = true;
      break;
    }
  }
  const result = (best || { best: {}, eta: null, fun: null }) as Spec;
  return {
    ...result,
    ok,
    nit,
    evaluations,
    evaluation_budget: budget,
    limited_budget: true,
    spec_updates: result.best,
    notes: [
      "固定种子、有界差分进化；沿用原效率目标与 DCM 0.25 惩罚。随机序列与 SciPy 实现不同，候选值不要求逐位相同。",
      "候选需应用后重算全部约束；有限预算不构成全局最优或器件选型证明。",
    ],
  };
}
export function advancedAction(
  run: Spec,
  action: string,
  options: Spec,
  progress: (s: string) => void,
): Spec {
  let result: Spec;
  if (action === "compensate")
    result = compensationAction(run.p, run.op, options);
  else if (action === "tune") {
    result = tune(
      run.p,
      run.op,
      options.fc,
      options.pm,
      options.controller_type,
    );
  } else if (action === "sweep" || action === "find_target")
    result = efficiencySweep(run, action, options, progress);
  else if (action === "optimize")
    result = optimizeEfficiency(run, options, progress);
  else if (action === "corners")
    result = cornerAnalysis(run, options, progress);
  else if (action === "loop_response") {
    result = loopResponse(run.p, run.op, options.load_output);
    const f = result.frequency,
      panels = [
        lineChart(
          result.outputs.map((r: Spec) => ({
            x: f,
            y: r.reference_db,
            label: "OUT" + r.id,
          })),
          "主参考 → 各路相对变化率",
          "dB（% / %）",
          true,
        ),
        lineChart(
          result.outputs.map((r: Spec) => ({
            x: f,
            y: r.reference_phase,
            label: "OUT" + r.id,
          })),
          "主参考跟踪相位",
          "deg",
          true,
        ),
      ];
    if (result.outputs.some((r: Spec) => r.load_db)) {
      panels.push(
        lineChart(
          result.outputs
            .filter((r: Spec) => r.load_db)
            .map((r: Spec) => ({ x: f, y: r.load_db, label: "OUT" + r.id })),
          `OUT${options.load_output} 负载扰动 → 各路电压`,
          "dBΩ（20log₁₀|ΔV/ΔI|）",
          true,
        ),
        lineChart(
          result.outputs
            .filter((r: Spec) => r.load_phase)
            .map((r: Spec) => ({ x: f, y: r.load_phase, label: "OUT" + r.id })),
          "负载扰动相位",
          "deg",
          true,
        ),
      );
    }
    if (result.reference_step) {
      const t = result.reference_step;
      panels.push(
        lineChart(
          t.values.map((y: number[], i: number) => ({
            x: t.time.map((v: number) => v * 1000),
            y,
            label: "OUT" + (i + 1),
          })),
          "线性闭环 · 单位主参考阶跃",
          "V / V",
          false,
          540,
          "时间 / ms",
        ),
      );
    }
    result.chart_svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="${panels.length * 540}" viewBox="0 0 1200 ${panels.length * 540}">${panels.map((svg, i) => svg.replace("<svg ", `<svg x="0" y="${i * 540}" `)).join("")}</svg>`;
  } else throw Error("未知高级分析 " + action);
  return {
    ...result,
    action,
    case: options.case || "Vinmin",
    snapshot_unchanged: true,
    has_chart: !!result.chart_svg,
  };
}
