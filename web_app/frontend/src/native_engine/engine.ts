import { windingRows, assess } from "./winding";
import { preview } from "./preview";
export { preview } from "./preview";
import { solveNonisolated } from "./nonisolated";
import {
  type Spec,
  normalize,
  clone,
  reference,
  rails,
  isolated,
  bank,
  capability,
} from "./spec";
import { nominal, windingHardware } from "./power";
import { solveCoupled } from "./coupled";
import { transformer, inductor, ac, nseWaveform } from "./magnetics";
import { waveforms, capacitors, ripple } from "./waveforms";
import {
  mosLoss,
  diodeLoss,
  refs,
  forward,
  selectedCurve,
  stress,
  sourceFor,
} from "./devices";
import { analyze } from "./loop";
import { mean, rms, interpolate } from "./math";
import { designPSR } from "./psr";
import { attachParasitics } from "./parasitics";
import { compensation } from "./compensation";
import { solveForward } from "./acf";
import { reviewCatalog } from "./checks";
import migrationSources from "./migration-sources.json";
export const VERSION = "0.2.0-native-ts";

function magnetic(p: Spec, op: Spec): Spec {
  if (!isolated(p)) {
    const fixed = op.niso_model?.inductor;
    const ind = inductor(op, fixed ? { ...p, _fixed_inductor: fixed } : p);
    if (op.niso_model) {
      const old = ind.P_total;
      ind.R_dc = op.niso_model.dcr;
      ind.P_cu = ind.Fr * ind.R_dc * op.I_L_rms ** 2;
      ind.P_total = ind.P_cu + ind.P_core;
      ind.dT *= ind.P_total / old;
    }
    return { ok: true, inductor: ind, P_total: ind.P_total };
  }
  const rr = op.outputs?.length ? op.outputs : [{ ...p, id: 1, name: "OUT1" }],
    fb = rr[(p.feedback_output || 1) - 1],
    hardware =
      op.coupled_model?.transformer_hardware ||
      op.acf_model?.transformer_hardware ||
      p._fixed_transformer,
    q = {
      ...p,
      ...fb,
      Np: op.output_turns?.Np || p.Np,
      Ns: fb.Ns,
      _fixed_transformer: hardware,
    },
    tr: Spec = transformer(op, q);
  let copper =
      tr.Fr_p *
      tr.R_dc_p *
      (op.coupled_model?.winding_rms?.[0] ??
        op.acf_model?.winding_rms?.[0] ??
        tr.I_rms_p) **
        2,
    area = (tr.Np * tr.n_strand_p * Math.PI * tr.d_wire_p ** 2) / 4;
  tr.windings = rr.map((r: Spec, i: number) => {
    const ch = op.output_ops?.[i] || op,
      frozen = hardware?.windings?.[i],
      turns = frozen?.Ns || r.Ns || tr.Ns,
      strands = frozen?.n_strand_s || r.n_strand_s || 1,
      current = ch.I_s_rms ?? ch.I_d_rms,
      diameter =
        frozen?.d_wire_s ||
        r.d_wire_s ||
        Math.max(50e-6, Math.sqrt((4 * current) / strands / p.J / Math.PI)),
      a = (strands * Math.PI * diameter ** 2) / 4,
      rd = frozen?.R_dc ?? (p.rho * tr.MLT * turns) / a,
      fr = ac(diameter, op.f_sw, p.rho),
      loss = fr * rd * current ** 2;
    copper += loss;
    area += turns * a;
    return {
      id: i + 1,
      name: r.name,
      Ns: turns,
      N: tr.Np / turns,
      n_actual: tr.Np / turns,
      d_wire_s: diameter,
      n_strand_s: strands,
      I_rms: current,
      R_dc: rd,
      Fr: fr,
      P_cu: loss,
      J_actual: current / a,
      V_turns_est:
        (op.aggregate_op?.V_out ?? op.V_out) *
        (turns / tr.Np) *
        (op.aggregate_op?.N ?? op.N),
    };
  });
  if (op.coupled_solution || op.acf_solution) {
    const s = op.coupled_solution || op.acf_solution,
      t = Array.from({ length: 8193 }, (_, i) => (i * op.Ts) / 8192),
      raw = op.acf_solution
        ? s.lambda_p.map((v: number) => v / tr.Np / tr.Ae)
        : s.i_magnetizing.map((v: number) => (v * op.L) / tr.Np / tr.Ae),
      points = s.t.map((time: number, i: number) => [time, raw[i]]),
      flux = t.map((v) => interpolate(points, v));
    tr.B_pk = Math.max(...raw.map(Math.abs));
    tr.dB = Math.max(...raw) - Math.min(...raw);
    tr.P_core = nseWaveform(p, t, flux, tr.Ve);
    tr.I_rms_p = (op.coupled_model || op.acf_model).winding_rms[0];
    tr.J_actual_p =
      tr.I_rms_p / ((tr.n_strand_p * Math.PI * tr.d_wire_p ** 2) / 4);
  }
  tr.P_cu = copper;
  tr.fill = area / tr.Wa;
  tr.P_total = copper + tr.P_core;
  tr.dT = tr.P_total * p.Rth_transformer;
  const selected = tr.windings[(p.feedback_output || 1) - 1];
  tr.R_dc_s = selected.R_dc;
  tr.J_actual_s = selected.J_actual;
  tr.I_rms_s = selected.I_rms;
  const result: Spec = { ok: true, transformer: tr, P_total: tr.P_total };
  if (p.topology === "ACF-FORWARD") {
    result.inductors = rr.map((r: Spec, i: number) =>
      inductor(op.output_ops?.[i] || op, {
        ...p,
        ...r,
        core_choice: r.core_choice_L || p.core_choice_L,
        core_shape: "auto",
        custom_core: r.custom_core_L || {},
        _fixed_inductor: p._fixed_inductors?.[i],
      }),
    );
    result.inductor = result.inductors[(p.feedback_output || 1) - 1];
    result.P_total += result.inductors.reduce(
      (s: number, x: Spec) => s + x.P_total,
      0,
    );
  }
  return result;
}
export function design(raw: Spec, withLoop = true) {
  const p = normalize(raw);
  p.V_in = raw.V_in ?? p.V_in;
  const gaps = capability(p);
  if (gaps.length)
    throw Error(
      "纯前端内核尚未迁移：" +
        gaps.join("、") +
        "。已保留原始配置，请勿当作旧模型等价结果。",
    );
  let op = nominal(p);
  if (p.spice_config?.niso_profile && ["BUCK", "BOOST"].includes(p.topology))
    op = solveNonisolated(p, op);
  if (p.coupling_config?.enabled)
    op =
      p.topology === "ACF-FORWARD" ? solveForward(p, op) : solveCoupled(p, op);
  const wf = waveforms(op);
  const parasitics = attachParasitics(p, op, wf);
  const main = (p.feedback_output || 1) - 1,
    rr = op.outputs?.length ? op.outputs : [{ ...p, id: 1, name: "OUT1" }],
    cap = capacitors({ ...p, ...rr[main] }, op, wf),
    sw = mosLoss(op, p),
    outputs = rr.map((rail: Spec, i: number) => {
      const child = op.output_ops?.[i] || op,
        cwf = wf.outputs?.[i] || wf,
        q = { ...p, ...rail },
        names = refs(p, i + 1),
        diode = diodeLoss(child, q, cwf.i_d, names[0]),
        ca = capacitors(q, child, cwf),
        blocking = rail.d_out_enable
          ? forward([child.I_out], selectedCurve(p, names[2]), rail.Vf_dout)
          : null,
        freewheel =
          p.topology === "ACF-FORWARD"
            ? diodeLoss(child, q, cwf.i_free, names[1], true)
            : null;
      return {
        id: i + 1,
        name: rail.name,
        spec: rail,
        op: child,
        diode,
        freewheel,
        capacitors: ca,
        blocking,
        P_rectifier: diode.P_total + (freewheel?.P_total || 0),
        P_cap: ca.output.caps.reduce(
          (s: number, c: Spec) => s + c.ESR * c.total ** 2,
          0,
        ),
        P_dout: blocking?.P_cond || 0,
        ripple_pp: cwf.ripple_pp,
      };
    }),
    mag = magnetic(p, op),
    aux =
      p.topology === "ACF-FORWARD"
        ? {
            P_cond: p.Rds_aux * op.I_aux_rms ** 2,
            P_gate: p.Qg_aux * p.Vgs * op.f_sw,
            P_coss: 0.5 * p.Coss_aux * op.V_sw_max ** 2 * op.f_sw,
          }
        : null;
  const psr = designPSR(p, op, mag.transformer);
  if (psr) {
    op.psr = psr;
    const tr = mag.transformer,
      ia = psr.Vaux / (psr.RfbH + psr.RfbL),
      current = (ia * op.I_d_rms) / Math.max(op.I_out, 1e-30),
      dw =
        p._fixed_auxiliary?.d_wire ||
        Math.max(50e-6, Math.sqrt((4 * current) / p.J / Math.PI)),
      area = (Math.PI * dw * dw) / 4,
      rd = (p.rho * tr.MLT * psr.Na) / area,
      loss = ac(dw, op.f_sw, p.rho) * rd * current ** 2;
    tr.auxiliary = {
      Na: psr.Na,
      I_rms: current,
      d_wire: dw,
      R_dc: rd,
      P_cu: loss,
    };
    tr.P_cu += loss;
    tr.P_total += loss;
    tr.fill += (psr.Na * area) / tr.Wa;
    tr.dT = tr.P_total * p.Rth_transformer;
    mag.P_total += loss;
  }
  const auxTotal = aux ? Object.values(aux).reduce((s, v) => s + v, 0) : 0,
    semi = {
      switch: sw,
      diode: outputs[main].diode,
      freewheel: outputs[main].freewheel,
      auxiliary: aux ? { ...aux, P_total: auxTotal } : null,
      P_total:
        sw.P_total +
        auxTotal +
        outputs.reduce((s: number, r: Spec) => s + r.P_rectifier, 0),
      n_switches: aux ? 2 : 1,
      n_diodes: outputs.length * (aux ? 2 : 1),
    },
    P_cap = outputs.reduce((s: number, r: Spec) => s + r.P_cap, 0),
    P_cap_in = cap.input.caps.reduce(
      (s: number, c: Spec) => s + c.ESR * c.total ** 2,
      0,
    ),
    P_sense = p.Rs * rms(wf.i_sw) ** 2,
    P_rcd = op.clamp?.P_res || 0,
    P_din = p.d_in_enable
      ? forward(wf.i_in, selectedCurve(p, "D_IN"), p.Vf_din).P_cond
      : 0,
    P_dout = outputs.reduce((s: number, r: Spec) => s + r.P_dout, 0),
    P_clamp =
      p.topology === "ACF-FORWARD" ? op.I_clamp_rms ** 2 * p.ESR_clamp : 0,
    P_total =
      semi.P_total +
      mag.P_total +
      P_cap +
      P_cap_in +
      P_sense +
      P_rcd +
      P_din +
      P_dout +
      P_clamp +
      (psr?.P_controller || 0) +
      (op.P_parasitic || 0);
  let loop = null,
    loop_error = null;
  if (withLoop)
    try {
      loop = analyze(p, op);
    } catch (e) {
      loop_error = String(e instanceof Error ? e.message : e);
    }
  return {
    p,
    op,
    wf,
    semi,
    mag,
    outputs,
    capacitors: cap,
    P_semi: semi.P_total,
    P_mag: mag.P_total,
    P_cap,
    P_cap_in,
    P_sense,
    P_rcd,
    P_din,
    P_dout,
    P_clamp,
    P_controller: psr?.P_controller || 0,
    P_parasitic: op.P_parasitic || 0,
    psr,
    parasitics,
    compensation: (() => {
      try {
        return p.__comp ? compensation(p, op, p.__comp) : null;
      } catch (e) {
        return { error: String(e), buildable: false };
      }
    })(),
    P_total,
    eta: op.P_out / (op.P_out + P_total),
    eta_guess: p.eta_guess,
    eta_delta: op.P_out / (op.P_out + P_total) - p.eta_guess,
    P_in_est: op.P_in_est,
    P_in: op.P_out + P_total,
    P_loss_budget: op.P_loss_budget,
    P_in_delta: op.P_out + P_total - op.P_in_est,
    loop,
    loop_error,
  };
}
export function checks(p: Spec, res: Spec) {
  return reviewCatalog(p, res, componentEvaluation(p, res));
}
export function componentEvaluation(p: Spec, res: Spec) {
  const config = p.component_management || {},
    items = config.items || {},
    zone = config.zone === "II" ? 2 : 1;
  if (
    Object.keys(config.overrides || {}).length &&
    !String(config.override_reason || "").trim()
  )
    throw Error("自定义降额规则必须填写依据");
  for (const [key, value] of Object.entries(config.overrides || {}))
    if (
      !reference.rules[key] ||
      typeof value !== "number" ||
      !(value > 0 && value <= 1)
    )
      throw Error("自定义降额因数无效");
  for (const [ref, item] of Object.entries(items) as [string, Spec][])
    for (const key of ["voltage_V", "ripple_A", "power_W"])
      if (
        item[key] != null &&
        item[key] !== "" &&
        !(
          typeof item[key] === "number" &&
          Number.isFinite(item[key]) &&
          item[key] > 0
        )
      )
        throw Error(ref + " " + key + " 必须为正数，未知留空");
  const inputAc = ripple(res.wf.i_cin, res.wf.dt, bank(p, "input"));
  const inputPeak =
    Math.abs(res.op.V_in_bus ?? p.V_in) + Math.max(...inputAc.map(Math.abs));
  const rows = preview(p).component_rows.map((row) => {
    const item = items[row.ref] || {},
      checks: Spec[] = [];
    const add = (
      metric: string,
      rule: string,
      value: number | null,
      ratingKey: string,
      unit: string,
      note: string,
    ) => {
      const factor =
          config.overrides?.[rule] ?? reference.rules[rule]?.[zone] ?? null,
        rating = item[ratingKey] ?? null;
      const limit = rating !== null && factor !== null ? rating * factor : null;
      const state =
        value === null || limit === null
          ? "undefined"
          : value <= limit + 1e-12
            ? "pass"
            : "review";
      checks.push({
        id: row.ref + "." + metric,
        name: reference.rules[rule]?.[0] || metric,
        metric,
        ref: row.ref,
        value,
        rating,
        utilization: value !== null && rating ? value / rating : null,
        factor,
        limit,
        state,
        unit,
        note,
        source: reference.rules[rule]?.[3],
      });
    };
    const output = row.output || Number(row.ref.match(/\d+/)?.[0]) || 1,
      rail = res.outputs[output - 1];
    if (row.kind === "mos") {
      add(
        "voltage",
        "mos_voltage",
        row.ref === "Q2" ? res.op.V_clamp : stress(res.op).switch.V_block,
        "voltage_V",
        "V",
        "稳态阻断平台；三温耐压与实测仍须复核",
      );
      const narrow =
        res.op.clamp?.t_pulse != null &&
        res.op.clamp.t_pulse < Math.min(1e-6, res.op.Ts / 50);
      add(
        "peak",
        narrow || res.op.clamp?.V_peak == null || row.ref === "Q2"
          ? "mos_spike"
          : "mos_voltage",
        row.ref === "Q2" ? null : (res.op.clamp?.V_peak ?? null),
        "voltage_V",
        "V",
        narrow ? "模型窄尖峰包络" : "未证明窄尖峰宽度条件，采用稳态因数",
      );
    } else if (row.kind === "diode") {
      const blocking =
        row.ref === "D_IN" || row.ref === "D_OUT" || row.ref.startsWith("D_B");
      add(
        "voltage",
        "diode_voltage",
        blocking || row.special === "snubber"
          ? null
          : row.ref === "D2" || row.ref.startsWith("D_F")
            ? (rail?.op.V_free_max ?? res.op.V_free_max)
            : (rail?.op.V_d_max ?? res.op.V_d_max),
        "voltage_V",
        "V",
        blocking
          ? "外部反接/回灌反压未定义，不能用正向电压代替"
          : "未考虑寄生尖峰；具体反压须实测，选型留有余量",
      );
      checks.push({
        id: row.ref + ".spike",
        ref: row.ref,
        name: row.ref + " 尖峰反压",
        metric: "spike",
        value: null,
        rating: item.voltage_V ?? null,
        factor: null,
        limit: null,
        unit: "V",
        utilization: null,
        state: "undefined",
        comparison: "<=",
        source: "原降额速查表 / 半导体尖峰说明",
        note: "未建模的寄生峰值与宽度须实测，不可按稳态通过判整颗器件通过。",
      });
    } else if (row.kind === "resistor") {
      add(
        "power",
        "resistor_power",
        row.ref === "R_S1"
          ? res.P_sense
          : row.ref === "R_SN1"
            ? res.P_rcd
            : null,
        "power_W",
        "W",
        "平均耗散；未覆盖脉冲承受能力及热态降额",
      );
    } else if (row.kind === "capacitor") {
      const type = ["electrolytic", "mlcc", "film"].includes(
        item.capacitor_type,
      )
        ? item.capacitor_type
        : "other";
      const cap = row.special
        ? null
        : row.side === "input"
          ? res.capacitors.input.caps[row.index]
          : rail?.capacitors.output.caps[row.index];
      const wf = res.wf.outputs?.[output - 1] || res.wf;
      const peak =
        row.special === "snubber"
          ? (res.op.clamp?.V_clamp ?? 0) * (1 + (p.dC ?? 0.1) / 2)
          : row.special === "clamp"
            ? res.op.V_clamp
            : row.special === "psr"
              ? null
              : row.side === "input"
                ? inputPeak
                : Math.max(
                    ...wf.vout.map((v: number, i: number) =>
                      Math.abs(
                        (wf.vcap?.[i] ??
                          v +
                            (rail?.op.V_out_cap ?? 0) -
                            (rail?.op.V_out ?? 0)) + (wf.v_esl?.[i] || 0),
                      ),
                    ),
                  );
      add(
        "voltage",
        type + "_voltage",
        peak,
        "voltage_V",
        "V",
        "已建模稳态纹波包络，不含启动、浪涌与跨负载最坏过冲",
      );
      add(
        "ripple",
        type + "_ripple",
        row.special === "clamp" ? res.op.I_clamp_rms : (cap?.total ?? null),
        "ripple_A",
        "A",
        "本颗电容复阻抗分流 RMS；额定值须按温度与频率修正",
      );
    }
    return {
      ...row,
      ...item,
      checks,
      quantity: row.kind === "block" || row.ref === "N_A" ? 0 : 1,
      state: checks.some((r) => r.state === "review")
        ? "review"
        : checks.some((r) => r.state === "undefined") ||
            ["manufacturer", "model", "package"].some((k) => !item[k])
          ? "undefined"
          : checks.length
            ? "pass"
            : "na",
      identity_missing: ["manufacturer", "model", "package"].filter(
        (k) => !item[k],
      ),
      status: checks.some((r) => r.state === "review")
        ? "超出限值"
        : checks.some((r) => r.state === "undefined") ||
            ["manufacturer", "model", "package"].some((k) => !item[k])
          ? "待补充/复核"
          : checks.length
            ? "模型内满足"
            : "不适用",
    };
  });
  return {
    rows,
    checks: rows.flatMap((r) => r.checks),
    counts: Object.fromEntries(
      ["pass", "review", "undefined", "na"].map((s) => [
        s,
        rows.flatMap((r) => r.checks).filter((r) => r.state === s).length,
      ]),
    ),
    inactive_refs: Object.keys(items).filter(
      (ref) => !rows.some((r) => r.ref === ref),
    ),
    note: "依据用户提供速查表初筛，缺少额定值或应力未建模的项目保留待复核。",
  };
}

function projectCase(p: Spec, res: Spec, id: string) {
  res.op.ripple_pp = res.wf.ripple_pp;
  const ck = checks(p, res),
    evaluation = componentEvaluation(p, res),
    outputs = res.outputs.map((r: Spec) => ({
      id: r.id,
      name: r.name,
      spec: r.spec,
      I_out: r.op.I_out,
      V_out: r.op.V_out,
      V_out_cap: r.op.V_out_cap,
      P_out: r.op.P_out,
      mode: r.op.branch_mode || r.op.mode,
      I_d_pk: r.op.I_d_pk,
      I_d_rms: r.op.I_d_rms,
      V_d_max: r.op.V_d_max,
      ripple_pp: r.ripple_pp,
      P_rectifier: r.P_rectifier,
      P_cap: r.P_cap,
      P_dout: r.P_dout,
      stress: stress(r.op),
      semiconductors: {
        diode: r.diode,
        freewheel: r.freewheel,
        blocking: r.blocking,
      },
      capacitors: r.capacitors,
    })),
    warnings = [
      "TypeScript 浏览器内核 " +
        VERSION +
        "；计算在本机浏览器后台完成，适用边界见各模型说明。",
      "整流反压不含寄生尖峰；最终效率是模型估算，不含全部辅助与温度损耗。",
      ...(res.loop_error ? ["环路未完成：" + res.loop_error] : []),
      ...res.semi.switch.gate.notes,
    ],
    losses = Object.fromEntries(
      Object.entries(res).filter(
        ([k]) =>
          k.startsWith("P_") || ["eta", "eta_guess", "eta_delta"].includes(k),
      ),
    ),
    mag = res.mag.transformer || res.mag.inductor,
    summary = {
      ok: true,
      topology: p.topology,
      operating_point: Object.fromEntries(
        Object.entries(res.op).filter(
          ([, v]) =>
            v === null || ["number", "string", "boolean"].includes(typeof v),
        ),
      ),
      losses,
      magnetics: mag,
      mosfet: res.semi.switch,
      checks: ck,
      loop: res.loop
        ? {
            fc: res.loop.fc,
            pm: res.loop.pm,
            min_pm: res.loop.min_pm,
            gm_db: res.loop.gm_db,
            gm_infinite: res.loop.gm_infinite,
            model: res.loop.model,
            closed_loop_stable: res.loop.closed_loop_stable,
            closed_loop_poles: res.loop.closed_loop_poles,
          }
        : null,
      outputs: p.outputs.length ? outputs : [],
      feedback: { mode: p.feedback_mode, output: p.feedback_output },
      warnings,
      stress: stress(res.op),
      component_management: evaluation,
    };
  const display = {
    id,
    ripple_pp: res.wf.ripple_pp,
    operating_point: Object.fromEntries(
      Object.entries(res.op).filter(
        ([, v]) =>
          v === null || ["number", "string", "boolean"].includes(typeof v),
      ),
    ),
    components: preview(p).component_rows.map((row) => ({
      ...row,
      name: row.role,
      value:
        row.kind === "mos"
          ? "Rds=" + p.Rds_on + " Ω"
          : row.kind === "capacitor"
            ? row.C + " F"
            : "",
    })),
    component_management: evaluation,
    magnetics: [
      res.mag.transformer
        ? { kind: "transformer", ...res.mag.transformer }
        : null,
      ...(res.mag.inductors?.map((x: Spec) => ({ kind: "inductor", ...x })) ||
        (res.mag.inductor ? [{ kind: "inductor", ...res.mag.inductor }] : [])),
    ].filter(Boolean),
    switch_loss: res.semi.switch,
    semiconductors: res.semi,
    stress: stress(res.op),
    capacitors: res.capacitors,
    capacitor_rms: {
      total_in: res.capacitors.total_in,
      total_out: res.capacitors.total_out,
    },
    outputs: p.outputs.length ? outputs : [],
    loop_available: !!res.loop,
    waveform_points: res.wf.t.length,
    rcd: res.op.clamp
      ? {
          V_clamp: res.op.clamp.V_clamp,
          P_snub: res.P_rcd,
          R_snub: res.P_rcd ? res.op.clamp.V_clamp ** 2 / res.P_rcd : null,
          C_snub:
            res.P_rcd /
            (p.f_sw * Math.max(p.dC || 0.1, 0.001) * res.op.clamp.V_clamp ** 2),
        }
      : null,
    clamp: res.op.clamp,
    winding_rows: windingRows(res),
    winding_assessment: (() => {
      try {
        return assess(windingRows(res), p.winding_config || {});
      } catch (e) {
        return {
          config: p.winding_config,
          configured: true,
          status: "invalid_plan",
          fits: null,
          warnings: [String(e)],
        };
      }
    })(),
    psr: res.psr,
    parasitics: res.parasitics,
    compensation: res.compensation,
    winding_model: res.op.coupled_model || res.op.acf_model || null,
  };
  return {
    case: {
      id,
      V_in: p.V_in,
      parameters: p,
      summary,
      checks: ck,
      error: null,
      loop_error: res.loop_error,
    },
    display,
  };
}
export function calculate(
  raw: Spec,
  progress?: (message: string) => void,
  cross = false,
) {
  const base = normalize(raw),
    cases: Spec[] = [],
    displays: Spec[] = [],
    runs: Spec[] = [];
  let fixed: Spec | undefined,
    fixedInductor: Spec | undefined,
    extraFixed: Spec = {};
  for (const [i, id] of ["Vinmin", "Vinmax"].entries()) {
    progress?.("浏览器后台计算 " + id);
    const p = {
      ...clone(base),
      V_in: i ? base.V_in_max : base.V_in_min,
      input_voltage_case: i ? "max" : "min",
      ...(fixed ? { _fixed_transformer: fixed } : {}),
      ...(fixedInductor ? { _fixed_inductor: fixedInductor } : {}),
      ...extraFixed,
    };
    const res = design(p);
    if (!i) {
      fixed = res.mag.transformer;
      fixedInductor = res.mag.inductor;
      if (res.mag.inductors)
        extraFixed._fixed_inductors = clone(res.mag.inductors);
      if (res.psr) {
        extraFixed.psr_Na = res.psr.Na;
        extraFixed.psr_RfbL = res.psr.RfbL;
        extraFixed._fixed_auxiliary = clone(res.mag.transformer.auxiliary);
      }
    }
    const projection = projectCase(p, res, id);
    cases.push(projection.case);
    displays.push(projection.display);
    runs.push(res);
  }
  const snapshot = {
    schema: "power-design.run.v1",
    snapshot_id: "ts-" + Date.now().toString(36),
    model_version: VERSION,
    created_at: new Date().toISOString(),
    ok: true,
    spec: base,
    cases,
    display: displays,
    hardware: fixed || runs[0].mag.inductor,
    fixed_hardware: true,
    hardware_reference: "Vinmin",
    cross_regulation: cross ? crossRegulation(base, fixed, progress) : null,
    provenance: {
      engine: "TypeScript / Web Worker",
      version: VERSION,
      reference_source_hashes: { ...reference.reference, ...migrationSources },
      python_runtime: false,
    },
  };
  return { snapshot, runs };
}
export function crossRegulation(
  base: Spec,
  fixed: Spec | undefined,
  progress?: (message: string) => void,
) {
  if (
    !["FLYBACK", "ACF-FORWARD"].includes(base.topology) ||
    !base.coupling_config?.enabled
  )
    return {
      supported: false,
      reason:
        "交叉调整率需要启用固定频率反激的完整耦合矩阵模型；不使用理想匝比替代。",
    };
  const rr = rails(base);
  if (rr.length < 2) return { supported: false, reason: "至少需要两路输出" };
  const cases: Spec[] = [],
    voltages = [...new Set([base.V_in_min, base.V_in_max])];
  for (const voltage of voltages)
    for (let mask = 0; mask < 2 ** rr.length; mask++) {
      progress?.(
        `交叉负载角点 ${cases.length + 1}/${voltages.length * 2 ** rr.length}`,
      );
      const powers = rr.map((r, i) =>
          mask & (1 << i) ? r.P_out : r.P_out_min,
        ),
        row: Spec = {
          id: "V" + voltage + "-L" + mask,
          V_in: voltage,
          powers,
          status: "ok",
        };
      try {
        if (powers.some((v) => v <= 0))
          throw Error("0 W 真空载缺少泄放模型，不承诺有限输出电压");
        const p: Spec = {
            ...clone(base),
            V_in: voltage,
            _fixed_transformer: fixed,
            outputs: rr.map((r, i) => {
              const q: Spec = { ...r, P_out: powers[i], P_out_min: powers[i] };
              delete q.id;
              return q;
            }),
          },
          op =
            p.topology === "ACF-FORWARD"
              ? solveForward(p, nominal(p))
              : solveCoupled(p, nominal(p));
        row.voltages = op.output_ops.map((r: Spec) => r.V_out);
      } catch (e) {
        row.status = "failed";
        row.error = String(e);
      }
      cases.push(row);
    }
  const valid = cases.filter((r) => r.status === "ok"),
    complete = valid.length === cases.length,
    summary = rr.map((r, i) => {
      const sorted = valid
          .slice()
          .sort((a, b) => a.voltages[i] - b.voltages[i]),
        lo = sorted[0],
        hi = sorted.at(-1),
        groups = new Map<string, number[]>();
      for (const row of valid) {
        const key = row.V_in + "/" + row.powers[i];
        groups.set(key, [...(groups.get(key) || []), row.voltages[i]]);
      }
      return {
        id: r.id,
        name: r.name,
        feedback: r.id === base.feedback_output,
        V_reference: r.V_out,
        P_min: r.P_out_min,
        P_max: r.P_out,
        complete,
        V_min: lo?.voltages[i] ?? null,
        V_max: hi?.voltages[i] ?? null,
        min_case: lo?.id,
        max_case: hi?.id,
        deviation_min_pct: lo ? 100 * (lo.voltages[i] / r.V_out - 1) : null,
        deviation_max_pct: hi ? 100 * (hi.voltages[i] / r.V_out - 1) : null,
        span_pct: lo
          ? (100 * (hi!.voltages[i] - lo.voltages[i])) / r.V_out
          : null,
        cross_only_pct: valid.length
          ? Math.max(
              ...[...groups.values()].map(
                (a) => ((Math.max(...a) - Math.min(...a)) / r.V_out) * 100,
              ),
            )
          : null,
      };
    });
  return {
    supported: true,
    complete,
    cases,
    summary,
    note: "固定磁件与电阻负载的所有轻/重载组合及 Vin 端点；是稳态采样包络，不是连续区间严格极值或动态过冲。失败角点保留，包络明确标为不完整。",
  };
}
