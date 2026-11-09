/** Review catalog ported from design_checks.py; no check implies certification. */
import { type Spec, rails, bank } from "./spec";
export function reviewCatalog(source: Spec, res: Spec, evaluation: Spec) {
  const p = { ...source, ...rails(source)[(source.feedback_output || 1) - 1] },
    op = res.op,
    wf = res.wf,
    loop = res.loop,
    rows: Spec[] = [];
  const add = (
    id: string,
    name: string,
    value: any,
    limit: number | null = null,
    comparison = "<=",
    unit = "",
    state?: string,
    note = "",
  ) => {
    let status = state;
    if (!status)
      status =
        value === null || value === undefined || !Number.isFinite(value)
          ? "undefined"
          : (
                comparison === ">="
                  ? value >= limit!
                  : comparison === ">"
                    ? value > limit!
                    : comparison === "<"
                      ? value < limit!
                      : value <= limit!
              )
            ? "pass"
            : "review";
    rows.push({
      id,
      name,
      value: value ?? null,
      limit,
      comparison,
      unit,
      margin:
        Number.isFinite(value) && limit !== null
          ? ["<", "<="].includes(comparison)
            ? limit - value
            : value - limit
          : null,
      pass_: status === "pass",
      state: status,
      note,
    });
  };
  const caps = bank(p),
    total = caps.reduce((s, c) => s + c.C, 0),
    target = p.ripple_target * op.V_out,
    esr = caps.some((c) => !c.ESR)
      ? 0
      : 1 / caps.reduce((s, c) => s + 1 / c.ESR, 0);
  add(
    "L_min",
    "电感量与设计初选建议",
    op.L,
    op.L_min || 0,
    ">=",
    "H",
    (op.L_min || 0) <= 0 || (op.topology === "FLYBACK" && op.mode !== "CCM")
      ? "na"
      : undefined,
    "初选建议含裕量，不代替实际电流谷值判断工作模式。",
  );
  add("C_charge", "电荷纹波所需输出容量", total, op.C_min, ">=", "F");
  add(
    "ESR_ripple",
    "ESR 纹波初筛",
    (op.topology === "BUCK" || op.topology === "ACF-FORWARD"
      ? op.dI_L
      : op.I_d_pk) * esr,
    target,
    "<=",
    "V",
    undefined,
    "低频并联 ESR 初筛；最终以复阻抗分流纹波为准。",
  );
  add(
    "ripple",
    "低频输出纹波",
    wf.ripple_pp,
    target,
    "<=",
    "V",
    undefined,
    "ESL 尖峰不计入此项。",
  );
  add(
    "efficiency",
    "模型效率目标",
    res.eta,
    p.target_eta ?? 0.92,
    ">=",
    "",
    undefined,
    "仅包含已建模损耗，不含全部系统与热态损耗。",
  );
  add(
    "efficiency_preset_gap",
    "预设与最终效率差值",
    Math.abs(res.eta_delta) * 100,
    2,
    "<=",
    "pp",
    undefined,
    "2个百分点为设计复核提示，不是模型精度保证。",
  );
  const devices = [
    ["inductor", res.mag.inductor],
    ["transformer", res.mag.transformer],
  ].filter(([, d]) => d) as [string, Spec][];
  for (const [kind, d] of devices) {
    const suffix =
        devices.length > 1 ? (kind === "transformer" ? "_T" : "_L") : "",
      title = kind === "transformer" ? "变压器" : "电感";
    if (d.design_enabled === false) {
      for (const [key, label] of [
        ["inductor_rated_current", "成品电感额定 RMS 电流"],
        ["inductor_saturation_current", "成品电感饱和电流"],
      ]) {
        const rating = d[key] || null;
        add(key, label, key === "inductor_rated_current" ? d.I_rms : d.I_pk,
          rating, "<=", "A", rating ? undefined : "undefined",
          "按厂家频温/降感条件初筛；不模拟 L(I)。");
      }
      add("inductor_magnetic_coverage", "成品电感磁芯/交流损耗与温升",
        null, null, "<=", "", "undefined", d.note);
      continue;
    }
    add("B_sat" + suffix, title + "峰值磁密", d.B_pk, p.Bsat, "<", "T");
    add(
      "temp_rise" + suffix,
      title + "估算温升",
      d.dT,
      p.temp_rise_limit ?? 40,
      "<=",
      "K",
    );
    add(
      "window_fill" + suffix,
      title + "裸铜窗口填充率",
      d.fill,
      1,
      "<=",
      "",
      undefined,
      "未含绝缘、骨架及工艺余量。",
    );
  }
  if (!loop)
    add(
      "loop",
      "环路结果",
      null,
      null,
      "<=",
      "",
      "undefined",
      res.loop_error || "尚未计算",
    );
  else if (loop.fc === null)
    add(
      "loop",
      "环路0dB下降穿越",
      null,
      null,
      "<=",
      "",
      "review",
      "扫描内无下降穿越，不能据此判稳定",
    );
  else {
    add(
      "phase_margin",
      "全部穿越最小相位裕度",
      loop.min_pm,
      (p.pm_target ?? 60) - 1,
      ">=",
      "deg",
      undefined,
      "目标容差1°。",
    );
    const highest = Math.max(...loop.all_crosses.map((c: Spec) => c.fc)),
      limit =
        loop.model?.recommended_fc_max || op.fc_recommended_max || op.f_sw / 6;
    add("fc_vs_fsw", "最高穿越与开关/模型频率建议", highest, limit, "<=", "Hz");
    const rhp = loop.model?.experimental
      ? loop.model.rhp_zero_estimate || Infinity
      : op.rhp_zero || Infinity;
    add(
      "rhp_bandwidth",
      "RHP零点带宽建议",
      highest,
      rhp / 5,
      "<=",
      "Hz",
      !Number.isFinite(rhp) ? "na" : undefined,
    );
    add(
      "gain_margin",
      "有限增益裕度",
      loop.gm_db,
      0,
      ">",
      "dB",
      loop.gm_infinite ? "na" : undefined,
      "有限扫描内未检出不代表无限硬件裕量。",
    );
  }
  if (loop?.model) {
    const m = loop.model;
    add(
      "loop_model",
      "环路模型适用边界",
      null,
      null,
      "<=",
      "",
      "review",
      m.assumptions,
    );
    const poles = loop.closed_loop_poles;
    add(
      "loop_closed_poles",
      "近似闭环极点实部最大值",
      poles?.length ? Math.max(...poles.map((c: number[]) => c[0])) : null,
      0,
      "<",
      "rad/s",
      undefined,
      loop.pole_error || "近似模型检查，不替代角点和样机FRA。",
    );
    if (m.inner_spectral_radius !== undefined)
      add(
        "loop_inner_map",
        "功率级采样内环谱半径",
        m.inner_spectral_radius,
        1,
        "<",
        "",
        undefined,
        "大于等于1时自动整定拒绝写回。",
      );
  }
  if (op.f_max)
    add("f_sw_max", "QR工作频率上限", op.f_sw, op.f_max, "<=", "Hz");
  if (p.Kc > 1 && ["FLYBACK", "QR-FLYBACK"].includes(op.topology))
    add("rcd_margin", "RCD钳位高于反射电压", p.Kc * op.V_r, op.V_r, ">", "V");
  if (op.topology === "ACF-FORWARD") {
    add("forward_duty", "正激占空比上限", op.D, op.forward_d_max, "<");
    add("clamp_cap", "钳位电容隆起预算", op.C_clamp, op.C_clamp_min, ">=", "F");
  }
  if (source.outputs?.length)
    for (const rail of res.outputs) {
      const s = rail.spec,
        c = rail.op,
        tag = "OUT" + rail.id;
      add(
        tag + "_ripple",
        tag + "低频纹波",
        rail.ripple_pp,
        s.ripple_target * s.V_out,
        "<=",
        "V",
      );
      add(
        tag + "_cap",
        tag + "电荷所需容量",
        bank(s).reduce((a, c) => a + c.C, 0),
        c.C_min,
        ">=",
        "F",
      );
      if (op.coupled_model || op.acf_model) {
        add(
          tag + "_dc_voltage",
          tag + "解算相对设定/匝比估算偏差",
          Math.abs(c.V_out / s.V_out - 1) * 100,
          2,
          "<=",
          "%",
          undefined,
          "非反馈基准为匝比估算，2%只是复核提示，不是实物稳压精度。",
        );
        add(
          tag + "_small_ripple",
          tag + "小纹波近似适用性",
          (rail.ripple_pp / c.V_out) * 100,
          10,
          "<=",
          "%",
        );
      }
    }
  if (source.outputs?.length)
    for (const w of res.mag.transformer?.windings || [])
      add(
        "OUT" + w.id + "_turns",
        "OUT" + w.id + "匝比近似电压",
        w.V_turns_est,
        null,
        "<=",
        "V",
        "review",
        "仅为整数匝数估算，不是独立稳压通过项。",
      );
  if (source.outputs?.length && !op.coupled_model && !op.acf_model)
    add(
      "cross_regulation",
      "非反馈输出交叉调整率",
      null,
      null,
      "<=",
      "",
      "undefined",
      "标称功率比例/理想匝比模型不能验证交叉调整率。",
    );
  if (op.coupled_model)
    add(
      "coupled_scope",
      "逐对耦合模型边界",
      null,
      null,
      "<=",
      "",
      "review",
      "定频SSR、线性L矩阵、恒阻负载、刚性电容端、理想钳位；不含完整高频寄生同时解或磁饱和。",
    );
  if (op.acf_model) {
    add(
      "acf_periodic_scope",
      "正激周期模型边界",
      null,
      null,
      "<=",
      "",
      "review",
      op.acf_model.assumptions,
    );
    add(
      "acf_periodic_residual",
      "周期与电荷平衡残差",
      op.acf_model.normalized_residual,
      1e-6,
    );
    add(
      "acf_energy_balance",
      "正激数值能量残差",
      op.acf_model.energy_balance_relative * 100,
      2,
      "<=",
      "%",
      undefined,
      "隐式步的数值耗散，不作为真实器件损耗。",
    );
  }
  for (const [i, d] of (res.mag.inductors || []).entries()) {
    add(`OUT${i + 1}_L_B`, `OUT${i + 1}输出电感磁密`, d.B_pk, p.Bsat, "<", "T");
    add(
      `OUT${i + 1}_L_T`,
      `OUT${i + 1}输出电感温升`,
      d.dT,
      p.temp_rise_limit ?? 40,
      "<=",
      "K",
    );
  }
  const psr = res.psr;
  if (psr) {
    for (const row of [
      ["psr_vin_low", "MP6005输入下限", op.V_in, 8, ">=", "V"],
      ["psr_vin_high", "MP6005输入上限", op.V_in, 80, "<=", "V"],
      ["psr_duty", "MP6005占空比", op.D, 0.7, "<=", ""],
      ["psr_cs", "采样电压设计裕量", psr.Vcs_peak, 0.128, "<=", "V"],
      ["psr_limit", "电流限值低端", psr.Vcs_peak, 0.14, "<=", "V"],
      ["psr_L", "最低采样电流下电感", op.L, psr.Lpri_min, ">=", "H"],
      ["psr_t33", "33mV最短退磁导通", psr.tcon_min33, 0.7e-6, ">=", "s"],
      ["psr_tcon", "当前副边导通窗口", psr.tcon, 0.6e-6, ">=", "s"],
      ["psr_fbneg", "负向FB电流", psr.Ifb_negative, 0.001, "<", "A"],
      ["psr_rh", "分压上电阻上限", psr.RfbH, 100000, "<", "Ω"],
      [
        "psr_divider",
        "标称分压设定偏差",
        (Math.abs(psr.Vout_error) / op.V_out) * 100,
        2,
        "<=",
        "%",
      ],
      ["psr_vcc", "VCC上限", psr.Vcc, 16, "<=", "V"],
      ["psr_gate", "驱动不超过VCC", p.Vgs, psr.Vcc, "<=", "V"],
    ] as [string, string, number, number, string, string][])
      add(...row);
    add(
      "psr_reg",
      "Rreg+Rs档位",
      (source.psr_Rreg ?? 6800) + p.Rs,
      null,
      "<=",
      "",
      psr.compensation_gain === null ? "review" : "pass",
      "仅数据表规定的阻值档有效",
    );
    add(
      "psr_model",
      "PSR控制动态验证",
      null,
      null,
      "<=",
      "",
      "undefined",
      psr.note,
    );
  }
  for (const r of evaluation.checks)
    rows.push({
      ...r,
      comparison: r.comparison || "<=",
      margin: r.limit === null || r.value === null ? null : r.limit - r.value,
      pass_: r.state === "pass",
    });
  // Keep the existing native UI identifiers while exposing the full desktop catalog.
  if (loop)
    rows.push({
      id: "phase-margin",
      name: "主反馈相位裕度",
      value: loop.pm,
      limit: p.pm_target,
      comparison: ">=",
      unit: "°",
      state:
        loop.pm === null
          ? "undefined"
          : loop.pm >= p.pm_target
            ? "pass"
            : "review",
      note: "所选穿越；全部穿越检查见上方。",
    });
  rows.push({
    id: "closed-loop-poles",
    name: "闭环极点验证",
    value: loop?.closed_loop_stable ?? null,
    limit: null,
    unit: "",
    state:
      loop?.closed_loop_stable == null
        ? "undefined"
        : loop.closed_loop_stable
          ? "pass"
          : "review",
    note: loop?.pole_error || "直接检查闭环状态矩阵极点。",
  });
  return rows;
}
