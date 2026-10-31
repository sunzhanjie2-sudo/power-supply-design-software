/** Offline engineering-file export only. Never starts or contacts LTspice. */
import assets from "./spice-assets.json";
import { type Spec, reference, bank, inputDrop, blockDrop } from "./spec";
import { windingMatrix, resolvedParasitics } from "./parasitics";
import { effective } from "./nonisolated";
import { bundle, jsonFile } from "./archive";
const control =
    "FSW MODE DMAX VM A_CS SLOPE CS_LIM TBLANK TONMIN TPROP VG RDRV UVLO VSET TSS TYPE KP FZ1 FP1 FZ2 FP2 CMAX TEN SSMODE SSFRAC COFF SSCLO SSCHI SCMODE SCP SCPBLANK OLPEN TOLP THOLD TOFF CS_TAU".split(
      " ",
    ),
  qrControl =
    "A_CS CS0 VFF VSET TSS TYPE KP FZ1 FP1 FZ2 FP2 RDRV VG UVON UVOFF TLEB TONMIN TPROP CS_TAU ZARM ZTRIG ZDELAY TOFFMIN TOFFLIGHT TSTART OCP TONMAX".split(
      " ",
    );
const ascii = (s: string) => new TextEncoder().encode(s),
  cards = (keys: string[]) => keys.map((k) => k + "={" + k + "}").join(" ");
export function spiceProject(run: Spec): Record<string, Uint8Array> {
  const first = run.runs[0],
    input = first.p,
    op = first.op,
    forward = input.topology === "ACF-FORWARD",
    qr = input.topology === "QR-FLYBACK",
    niso = ["BUCK", "BOOST"].includes(input.topology);
  if (
    !["FLYBACK", "QR-FLYBACK", "ACF-FORWARD", "BUCK", "BOOST"].includes(
      input.topology,
    ) ||
    input.feedback_mode !== "SSR"
  )
    throw Error(
      "原版 SPICE 导出支持反激/正激/Buck/Boost SSR；PSR 与反相升降压无此导出模型",
    );
  const q = niso ? effective(input) : input,
    rr = op.outputs?.length ? op.outputs : [{ ...q, id: 1, name: "OUT1" }],
    n = rr.length,
    settings = {
      ...reference.bootstrap.spice_presets.generic,
      ...q.spice_config,
    },
    cfg = resolvedParasitics(q, n),
    profile = settings.niso_profile,
    selected = q.feedback_output || 1,
    fb = rr[selected - 1],
    freq = qr ? op.f_sw : settings.frequency_hz || q.f_sw,
    gain = niso ? 1 : q.A_sense,
    rs = q.Rs;
  for (const option of reference.bootstrap.spice_options) {
    const v = settings[option.key];
    if (
      v !== undefined &&
      (!Number.isFinite(v) || v < option.minimum || v > option.maximum)
    )
      throw Error(option.label + " 超出允许范围");
  }
  if (qr && (n > 1 || q.control_mode !== "Peak Current Mode"))
    throw Error("原版 QR SPICE 仅支持单路峰值电流 SSR");
  if (niso && !op.niso_model)
    throw Error("请先应用对应 Buck/Boost 控制器原型并重算");
  if (
    !(rs > 0 && gain > 0) ||
    settings.duty_max / freq <=
      Math.max(settings.blanking_ns, settings.min_on_ns) * 1e-9 +
        settings.delay_ns * 1e-9
  )
    throw Error("采样电阻/增益无效，或消隐与最小导通时间相对周期过长");
  const wm = niso ? null : windingMatrix(q, op, !q.coupling_config?.enabled),
    hardware = wm?.hardware || op.niso_model.inductor,
    peak = Math.max(...run.runs.map((r: Spec) => r.op.I_sw_pk)),
    limit = qr ? settings.qr_cs_clamp_v : settings.cs_limit || 1.4 * peak * rs,
    design = Math.max(0, q.ma_slope) * gain * rs;
  let recommended = 0;
  if (!niso)
    recommended = forward
      ? 0.75 *
        rr.reduce(
          (s: number, r: Spec, j: number) =>
            s +
            (((r.V_out + r.Vf_diode + blockDrop(r)) / r.L) *
              hardware.windings[j].Ns) /
              hardware.Np,
          0,
        ) *
        gain *
        rs
      : ((0.75 *
          Math.max(
            ...rr.map(
              (r: Spec, j: number) =>
                ((r.V_out + r.Vf_diode + blockDrop(r)) * hardware.Np) /
                hardware.windings[j].Ns,
            ),
          )) /
          q.L) *
        gain *
        rs;
  else
    recommended =
      profile === 2
        ? ((0.75 * (q.V_out + q.Vf_diode)) / q.L) * rs
        : 45e-6 * q.f_sw * (2000 + (settings.niso_lm_cs_resistor || 0));
  const slope = qr
      ? 0
      : settings.slope_mode === 2
        ? settings.slope
        : settings.slope_mode === 1 && q.control_mode === "Peak Current Mode"
          ? Math.max(design, recommended)
          : design,
    h = niso
      ? ({ 1: 0.7, 2: 0.8, 3: 1.25 } as Spec)[profile] /
        (q.V_out + blockDrop(q))
      : settings.feedback_scale,
    values: Spec = {
      FSW: freq,
      MODE: q.control_mode === "Peak Current Mode" ? 1 : 0,
      DMAX: settings.duty_max,
      VM: q.Vm,
      A_CS: gain,
      SLOPE: slope,
      CS_LIM: limit,
      TBLANK: settings.blanking_ns * 1e-9,
      TONMIN: settings.min_on_ns * 1e-9,
      TPROP: settings.delay_ns * 1e-9,
      VG: q.Vgs,
      RDRV: settings.driver_resistance,
      UVLO: settings.uvlo,
      TSS: settings.soft_start_ms * 1e-3,
      TSTOP: settings.stop_ms * 1e-3,
      TLOAD: settings.step_ms * 1e-3,
      LOAD_AFTER: settings.load_after,
      FB_SCALE: h,
      VSET: (fb.V_out + blockDrop(fb)) * h,
      TYPE:
        q.controller_type === "type2" ||
        (q.controller_type === "auto" && q.control_mode === "Peak Current Mode")
          ? 2
          : 3,
      TEN: settings.enable_delay_ms * 1e-3,
      SSMODE: settings.soft_start_mode,
      SSFRAC: settings.soft_start_current_fraction,
      COFF: qr ? 0 : settings.comp_offset_v,
      SSCLO: settings.ss_comp_start_v,
      SSCHI: settings.ss_comp_end_v,
      SCMODE: qr ? 0 : settings.short_mode,
      SCP: settings.scp_threshold_v,
      SCPBLANK: settings.scp_blanking_ns * 1e-9,
      OLPEN: settings.olp_enabled,
      TOLP: settings.olp_ms * 1e-3,
      THOLD: settings.ocp_hold_us * 1e-6,
      TOFF: settings.hiccup_off_ms * 1e-3,
      DIODE_CJ: niso && !settings.niso_edge_model ? 0 : cfg.cj_default,
      SHORT_EN: settings.short_test,
      SHORT_OUT: settings.short_output,
      TSHORT: settings.short_start_ms * 1e-3,
      TSHORT_DUR: settings.short_duration_ms * 1e-3,
      SHORT_R: settings.short_resistance,
      FB_SELECT: selected,
      CS_TAU: settings.cs_filter_ns * 1e-9,
    };
  for (const k of ["kp", "fz1", "fp1", "fz2", "fp2"])
    values[k.toUpperCase()] = settings[k] || q[k === "kp" ? "KP" : k] || 1000;
  values.KP /= h;
  values.CMAX = values.MODE
    ? gain * limit + (slope * settings.duty_max) / freq
    : q.Vm;
  if (settings.comp_voltage_max) {
    if (settings.comp_voltage_max <= values.COFF)
      throw Error("COMP 上限须高于偏置");
    values.CMAX = Math.min(
      values.CMAX,
      settings.comp_voltage_max - values.COFF,
    );
  }
  if (!qr && settings.short_mode && settings.scp_threshold_v <= limit)
    throw Error("SCP 阈值必须高于逐周期 Vcs 钳位");
  if (settings.short_test && settings.short_output > n)
    throw Error("短路输出编号不存在");
  if (values.VG <= values.UVLO) throw Error("驱动电压必须高于 UVLO");
  if (forward) {
    values.TDEAD = settings.acf_dead_ns * 1e-9 || q.forward_dead_time;
    values.RSYNC = settings.acf_sync_resistance;
    if (2 * values.TDEAD * freq >= Math.min(values.DMAX, 1 - values.DMAX))
      throw Error("正激死区过长");
  }
  if (qr) {
    if (
      settings.qr_vcc_v <= settings.qr_uvlo_on_v ||
      settings.qr_ocp_v <= settings.qr_cs_clamp_v
    )
      throw Error("QR VCC/UVLO 或 CS/OCP 阈值无效");
    Object.assign(values, {
      CS0: settings.qr_cs_clamp_v,
      VFF: settings.qr_vff_v,
      UVON: settings.qr_uvlo_on_v,
      UVOFF: settings.qr_uvlo_off_v,
      TLEB: settings.blanking_ns * 1e-9,
      ZARM: settings.qr_zcd_arm_v,
      ZTRIG: settings.qr_zcd_trigger_v,
      ZDELAY:
        settings.qr_zcd_delay_ns === -1
          ? Math.max(
              0,
              (Math.PI / 2) * Math.sqrt(q.L * (cfg.coss + cfg.cw_primary)) -
                settings.delay_ns * 1e-9,
            )
          : settings.qr_zcd_delay_ns * 1e-9,
      TOFFMIN: settings.qr_off_min_us * 1e-6,
      TOFFLIGHT: settings.qr_off_light_us * 1e-6,
      TSTART: settings.qr_starter_us * 1e-6,
      OCP: settings.qr_ocp_v,
      TONMAX: settings.qr_max_on_us * 1e-6,
      QR_VCC: settings.qr_vcc_v,
      Z_RATIO: settings.qr_aux_ratio,
      Z_R: settings.qr_zcd_r,
      Z_C: settings.qr_zcd_c_pf * 1e-12,
      FSW_LIMIT: q.f_sw,
    });
    values.CS_LIM = values.CS0 * (1 - values.VFF / 3);
  }
  if (niso) {
    const offset = profile === 1 ? 0 : profile === 2 ? 0.8 : 1.4,
      physical =
        profile === 1
          ? 1
          : profile === 2
            ? (settings.niso_ith_gain ?? 0.05)
            : 1 / 3;
    Object.assign(values, {
      PHYS_OFFSET: offset,
      PHYS_SCALE: physical,
      LIMIT_RAMP: profile === 3 ? 1 : 0,
      RAMP_RATIO: settings.niso_ramp_ratio ?? 0.1,
      COFF: 0,
      SSCLO: Math.max(0, settings.ss_comp_start_v - offset) * physical,
      SSCHI: Math.max(0, settings.ss_comp_end_v - offset) * physical,
    });
    if (settings.comp_voltage_max)
      values.CMAX = Math.min(
        values.CMAX,
        (settings.comp_voltage_max - offset) * physical,
      );
  }
  const params: Spec = {},
    body: string[] = [],
    support = [
      "VSHORT short_stim 0 PULSE(0 1 {TSHORT} 1e-6 1e-6 {TSHORT_DUR} {2*TSTOP})",
      ".model SHORT_SW SW(Ron={SHORT_R} Roff=1e12 Vt=0.5 Vh=-0.1)",
      "BDUTY duty_mon 0 V=if(V(gate,sense)>{VG/2},1,0)",
    ],
    coupling: string[] = [],
    extra: string[] = [];
  const value = (k: string, v: number) => {
      if (!Number.isFinite(v)) throw Error("SPICE 参数 " + k + " 非有限值");
      params[k] = v;
      return "{" + k + "}";
    },
    diode = (ref: string, a: string, b: string, v: number, en = 1) =>
      body.push(
        `X${ref} ${a} ${b} GPWR_DIODE VF=${value(ref + "_VF", v)} ACT=${value(ref + "_EN", en)} CJ={DIODE_CJ}`,
      ),
    cap = (ref: string, a: string, b: string, c: Spec, en = 1) =>
      body.push(
        `X${ref} ${a} ${b} GPWR_CAP C=${value(ref + "_C", c.C)} ESR=${value(ref + "_ESR", c.ESR)} ESL=${value(ref + "_ESL", settings.include_cap_esl ? c.ESL : 0)} ACT=${value(ref + "_EN", en)}`,
      );
  body.push(
    "VIN_SOURCE input 0 {VIN}",
    `VCC_SOURCE vcc 0 {${qr ? "QR_VCC" : "VG"}}`,
    "VEN en 0 PULSE(0 1 1e-6 10e-9 10e-9 {2*TSTOP} {3*TSTOP})",
    "V_SECONDARY_REFERENCE sgnd 0 0",
  );
  diode("D_IN", "input", "vin_bus", q.Vf_din, +!!q.d_in_enable);
  function caps(p: Spec, side: string, prefix: string, a: string, b: string) {
    const cs = bank(p, side);
    cap(prefix + "1", a, b, cs[0]);
    cap(prefix + "2", a, b, cs[1] || cs[0], +(cs.length > 1));
    cs.slice(2).forEach((c, j) =>
      extra.push(
        `X${prefix}${j + 3} ${a} ${b} GPWR_CAP C=${c.C} ESR=${c.ESR} ESL=${settings.include_cap_esl ? c.ESL : 0} ACT=1`,
      ),
    );
  }
  caps(q, "input", "C_IN", "vin_bus", "0");
  if (!niso) {
    const oldL: number[] = wm!.L.map((r: number[], i: number) => r[i]),
      newL = oldL.map((v, i) => v + (i ? cfg.rails[i - 1].l_pcb : cfg.lp_pcb));
    body.push(
      `LP vin_bus drain ${value("LP", newL[0])} Rser=${value("RP", wm!.R[0] + cfg.rp_pcb)}`,
      `XQ1 drain gate sense GPWR_MOS RON=${value("Q_RON", q.Rds_on)} COSS=${value("Q_COSS", Math.max(cfg.coss, 1e-12))} CG=${value("Q_CG", Math.max(q.Qg / q.Vgs, 1e-12))} VG={VG} CJ={DIODE_CJ}`,
      `RS1 sense 0 ${value("RSENSE", rs)}`,
    );
    if (!forward) {
      const c = op.clamp || {},
        power = Math.max(c.P_res || 0, 0),
        vc = c.V_clamp || 0,
        R = power > 0 && vc > 0 ? (vc * vc) / power : 1e12,
        C =
          power > 0 && vc > 0 && q.dC > 0
            ? power / (op.f_sw * vc * vc * q.dC)
            : 1e-12;
      diode("D_SN1", "drain", "clamp", 0.7);
      body.push(
        `R_SN1 clamp vin_bus ${value("R_SN1", R)}`,
        `C_SN1 clamp vin_bus ${value("C_SN1", C)} Rser=0.01`,
      );
    } else
      body.push(
        `C_ACTIVE drain aclamp ${value("C_ACTIVE", q.C_clamp)} Rser=${value("ESR_ACTIVE", q.ESR_clamp)}`,
        `XQA aclamp auxgate 0 GACF_PMOS RON=${value("QA_RON", q.Rds_aux)} COSS=${value("QA_COSS", Math.max(cfg.coss_aux, 1e-12))} CG=${value("QA_CG", Math.max(q.Qg_aux / q.Vgs, 1e-12))} VG={VG} CJ={DIODE_CJ}`,
      );
    rr.forEach((r: Spec, j: number) => {
      const i = j + 1;
      body.push(
        `LS${i} ${forward ? "rect" + i + " sgnd" : "sgnd rect" + i} ${value("LS" + i, newL[i])} Rser=${value("RS" + i, wm!.R[i] + cfg.rails[j].r_pcb)}`,
      );
      diode("D_O" + i, "rect" + i, (forward ? "choke" : "cap") + i, r.Vf_diode);
      if (forward) {
        body.push(`LO${i} choke${i} cap${i} ${value("LO" + i, r.L)} Rser=0`);
        body.push(
          `XD_F${i} sgnd choke${i} GPWR_DIODE VF={D_O${i}_VF} CJ={DIODE_CJ}`,
        );
      }
    });
    for (let i = 0; i <= n; i++)
      for (let j = i + 1; j <= n; j++)
        coupling.push(
          `K_${i}_${j} ${i ? "LS" + i : "LP"} LS${j} ${value("K_" + i + "_" + j, wm!.K[i][j] * Math.sqrt((oldL[i] * oldL[j]) / (newL[i] * newL[j])))}`,
        );
  } else {
    value("RSENSE", rs);
    value("L1", q.L);
    value("RL1", op.niso_model.dcr);
    value("Q_RON", q.Rds_on);
    value("Q_COSS", settings.niso_edge_model ? q.Coss : 0);
    value("Q_CG", settings.niso_edge_model ? q.Qg / q.Vgs : 0);
    if (q.topology === "BUCK") {
      body.push(
        "RS1 vin_bus qsource {RSENSE}",
        "L1 sw cap1 {L1} Rser={RL1}",
        "XQ1 sw gate_pin qsource GNISO_PMOS RON={Q_RON} COSS={Q_COSS} CG={Q_CG} VG={VG} CJ={DIODE_CJ}",
      );
      diode("D_O1", "sgnd", "rect1", q.Vf_diode);
      body.push("V_D1 rect1 sw 0");
      support.push(
        "BGATE gate_drive qsource V=-V(gate_cmd)",
        "BCS sense 0 V=V(vin_bus,qsource)",
        "BVDRAIN drain sense V=V(qsource,sw)",
      );
    } else {
      body.push(
        "L1 vin_bus sw {L1} Rser={RL1}",
        "RS1 sense 0 {RSENSE}",
        "XQ1 sw gate_pin sense GNISO_NMOS RON={Q_RON} COSS={Q_COSS} CG={Q_CG} VG={VG} CJ={DIODE_CJ}",
        "V_D1 sw rect1 0",
      );
      diode("D_O1", "rect1", "cap1", q.Vf_diode);
      support.push(
        "BGATE gate_drive sense V=V(gate_cmd)",
        "BVDRAIN drain sw V=0",
      );
    }
    support.push(
      "BGMON gate sense V=V(gate_cmd)",
      "BPHYSICAL comp_pin 0 V={PHYS_OFFSET}+V(comp)/{PHYS_SCALE}",
      "R_GATE gate_drive gate_pin {RDRV}",
    );
  }
  rr.forEach((r: Spec, j: number) => {
    const i = j + 1,
      cs = bank(r);
    cap("C_O" + i, "cap" + i, "sgnd", cs[0]);
    cap("C_O" + i + "_2", "cap" + i, "sgnd", cs[1] || cs[0], +(cs.length > 1));
    cs.slice(2).forEach((c, k) =>
      extra.push(
        `XC_O${i}_${k + 3} cap${i} sgnd GPWR_CAP C=${c.C} ESR=${c.ESR} ESL=${settings.include_cap_esl ? c.ESL : 0} ACT=1`,
      ),
    );
    diode("D_OUT" + i, "cap" + i, "out" + i, r.Vf_dout, +!!r.d_out_enable);
    body.push(
      `BLOAD${i} out${i} sgnd I=V(out${i},sgnd)/${value("RLOAD" + i, r.P_out > 0 ? r.V_out ** 2 / r.P_out : 1e12)}*(1+({LOAD_AFTER}-1)*limit((time-{TLOAD})/1e-6,0,1))`,
    );
    support.push(
      `SSHORT${i} out${i} sgnd short${i} 0 SHORT_SW`,
      `BSHORT${i} short${i} 0 V=if(({SHORT_EN}>0.5)&({SHORT_OUT}==${i}),V(short_stim),0)`,
    );
  });
  body.push(
    "XFBSEL " +
      Array.from({ length: 6 }, (_, j) =>
        j < n ? "cap" + (j + 1) : "sgnd",
      ).join(" ") +
      " sgnd fb 0 GPWR_FEEDBACK SEL={FB_SELECT} H={FB_SCALE}",
  );
  body.push(
    "XU_CTRL fb sense en vcc " +
      (niso ? "gate_cmd" : "gate") +
      " comp ramp ss fault 0" +
      (forward ? " sync auxgate" : qr ? " zcd" : "") +
      " " +
      (niso
        ? "GNISO_CTRL"
        : forward
          ? "GACF_CTRL"
          : qr
            ? "GQR_CTRL"
            : "GFLY_CTRL2") +
      " " +
      cards(qr ? qrControl : control) +
      (forward
        ? " TDEAD={TDEAD} RSYNC={RSYNC}"
        : niso
          ? " LIMIT_RAMP={LIMIT_RAMP}"
          : ""),
  );
  if (qr)
    body.push(
      "XZCD drain vin_bus zcd 0 GQR_ZCD RATIO={Z_RATIO} RZ={Z_R} CZ={Z_C}",
    );
  const parasiticCards: string[] = [];
  if (
    !niso &&
    input.parasitic_config &&
    Object.keys(input.parasitic_config).length
  ) {
    params.PAR_RCJ = cfg.r_cj;
    if (cfg.cw_primary)
      parasiticCards.push(`C_PAR_P vin_bus drain ${cfg.cw_primary}`);
    const rc = (ref: string, a: string, b: string, r: number, c: number) => {
      if (c)
        parasiticCards.push(
          `R_PAR_${ref} ${a} par_${ref} ${r}`,
          `C_PAR_${ref} par_${ref} ${b} ${c}`,
        );
    };
    rc("Q1", "drain", "sense", cfg.snub_r_primary, cfg.snub_c_primary);
    cfg.rails.forEach((r: Spec, j: number) => {
      const i = j + 1;
      params["PAR_D_O" + i + "_CJ"] = r.cj;
      params["PAR_D_F" + i + "_CJ"] = r.cj_free;
      if (r.cw) parasiticCards.push(`C_PAR_S${i} rect${i} sgnd ${r.cw}`);
      rc(
        "D" + i,
        "rect" + i,
        (forward ? "choke" : "cap") + i,
        r.snub_r,
        r.snub_c,
      );
    });
  }
  const voltages = [
      ...new Set(run.snapshot.cases.map((c: Spec) => c.V_in)),
    ] as number[],
    vmin = Math.min(...voltages);
  values.VIN = vmin;
  const inc = [
    ...Object.entries({ ...values, ...params }).map(
      ([k, v]) => ".param " + k + "=" + Number(v).toPrecision(12),
    ),
    ...(niso && profile === 1
      ? [".param VM={RAMP_RATIO*(VIN-D_IN_EN*D_IN_VF)}"]
      : []),
    ...(voltages.length > 1
      ? [".step param VIN list " + voltages.join(" ")]
      : []),
  ];
  if (niso && profile === 1) {
    const idx = inc.findIndex((s) => s.startsWith(".param VM="));
    inc.splice(idx, 1);
  }
  const analysis = [
    `.options threads=${Math.trunc(settings.simulation_threads)} method=gear reltol=0.003 plotwinsize=300`,
    ".tran 0 {TSTOP} 0 {1/FSW/60}",
    `.save V(input) V(drain) V(sense) V(gate) V(comp) V(ramp) V(ss) V(fault) I(${niso ? "L1" : "LP"})`,
  ];
  const measure = (
    name: string,
    method: string,
    expression: string,
    from = "{TLOAD-200/FSW}",
    to = "{TLOAD-10/FSW}",
  ) =>
    analysis.push(
      `.meas tran ${name} ${method} ${expression} FROM ${from} TO ${to}`,
    );
  measure("fault_max", "MAX", "V(fault)", "0", "{TSTOP}");
  measure("primary_rms", "RMS", `I(${niso ? "L1" : "LP"})`);
  measure("primary_avg", "AVG", `I(${niso ? "L1" : "LP"})`);
  measure("vcs_peak", "MAX", "V(sense)");
  measure("vds_peak", "MAX", "V(drain,sense)");
  rr.forEach((r: Spec, j: number) => {
    const i = j + 1;
    analysis.push(
      `.save V(out${i}) V(cap${i}) V(rect${i}) V(sgnd) I(${niso ? "V_D1" : "LS" + i})`,
    );
    for (const [suffix, method, expression] of [
      ["before", "AVG", `V(out${i},sgnd)`],
      ["cap_before", "AVG", `V(cap${i},sgnd)`],
      ["pre_ripple", "PP", `V(cap${i},sgnd)`],
      ["winding_rms", "RMS", `I(${niso ? "V_D1" : "LS" + i})`],
      ["winding_peak", "MAX", `I(${niso ? "V_D1" : "LS" + i})`],
    ])
      measure("out" + i + "_" + suffix, method, expression);
    measure(
      "out" + i + "_after",
      "AVG",
      `V(out${i},sgnd)`,
      "{TSTOP-200/FSW}",
      "{TSTOP-10/FSW}",
    );
  });
  const main = niso ? (q.topology === "BUCK" ? "Buck" : "Boost") : "Flyback",
    template = niso
      ? main + ".asc"
      : qr
        ? "QR_Flyback_1.asc"
        : (forward ? "ACF_Forward_" : "Flyback_") + n + ".asc",
    a: Record<string, string> = assets.files,
    files: Record<string, Uint8Array> = {};
  for (const [name, data] of Object.entries(a))
    if (
      name.endsWith(".asy") ||
      name === "GenericFlybackPWM.lib" ||
      name ===
        (niso
          ? "GenericBuckBoostPWM.lib"
          : forward
            ? "GenericACF_MP6005.lib"
            : qr
              ? "GenericQR_L6565.lib"
              : "")
    )
      files[name] = ascii(data);
  let sheet = a[template];
  if (!sheet) throw Error("原生 ASC 模板缺失");
  if (parasiticCards.length || params.PAR_RCJ) {
    const adapt = (data: string) => {
      let ref = "";
      return data
        .split(/\r?\n/)
        .map((line) => {
          if (line.startsWith("SYMATTR InstName "))
            ref = line.split(" ").at(-1)!;
          if (line.includes("CJ={DIODE_CJ}")) {
            const name = line.startsWith("X")
              ? line.split(" ")[0].slice(1)
              : ref;
            return (
              line.replace(
                "CJ={DIODE_CJ}",
                "CJ={" +
                  (/^D_[OF]\d/.test(name)
                    ? "PAR_" + name + "_CJ"
                    : "DIODE_CJ") +
                  "}",
              ) + " RCJ={PAR_RCJ}"
            );
          }
          return line;
        })
        .join("\n");
    };
    sheet = adapt(sheet) + "\nTEXT 64 1808 Left 2 !.include parasitics.inc\n";
    for (let i = 0; i < body.length; i++) body[i] = adapt(body[i]);
    for (const name of ["GenericFlybackPWM.lib", "GenericACF_MP6005.lib"])
      if (files[name])
        files[name] = ascii(
          new TextDecoder()
            .decode(files[name])
            .replaceAll("CJ=20e-12", "CJ=20e-12 RCJ=0.1")
            .replaceAll("Rser=0.1 m={ACT}", "Rser={RCJ} m={ACT}")
            .replaceAll("VF=0.8 CJ={CJ}", "VF=0.8 CJ=0 RCJ={RCJ}"),
        );
    files["parasitics.inc"] = ascii(parasiticCards.join("\n") + "\n");
  }
  const libs = [
      "GenericFlybackPWM.lib",
      ...(niso
        ? ["GenericBuckBoostPWM.lib"]
        : forward
          ? ["GenericACF_MP6005.lib"]
          : qr
            ? ["GenericQR_L6565.lib"]
            : []),
    ],
    deck = [
      "* PCS browser native export; no simulator run",
      ".include design_params.inc",
      ...libs.map((n) => ".include " + n),
      ".include power_stage.inc",
      ".include coupling.inc",
      ".include support.inc",
      ...(files["parasitics.inc"] ? [".include parasitics.inc"] : []),
      ".include analysis.inc",
      ".end",
    ];
  Object.assign(files, {
    [main + ".asc"]: ascii(sheet),
    [main + ".cir"]: ascii(deck.join("\n") + "\n"),
    "design_params.inc": ascii(inc.join("\n") + "\n"),
    "power_stage.inc": ascii(body.join("\n") + "\n"),
    "coupling.inc": ascii(coupling.join("\n") + "\n"),
    "support.inc": ascii([...support, ...extra].join("\n") + "\n"),
    "analysis.inc": ascii(analysis.join("\n") + "\n"),
    "design.json": jsonFile(run.snapshot.spec),
    "manifest.json": jsonFile({
      schema: "powerdesign-ltspice-browser/1",
      topology: q.topology,
      feedback_output: selected,
      settings,
      resolved_controller: values,
      hardware,
      coupling: wm?.K,
      voltages,
      simulator_invoked: false,
      asset_source_sha256: assets.sha256,
    }),
    "README.md": ascii(
      "# PCS 辅源 · 离线仿真工程\n\n打开 " +
        main +
        ".asc 或 " +
        main +
        ".cir。参数在 design_params.inc，Vin 端点用 .step；原生 ASC 与 CIR 使用同套参数和功率网络。\n软件仅生成文件，未调用 LTspice，未生成实际仿真或对比结论。\n\n模型与原计算器的通用行为库一致：常数 Coss/Cj、线性磁件、理想隔离反馈，非原厂精确芯片模型。整流/防反为固定压降，未含反向恢复、温度与实测非线性。输出在防反后，反馈在防反前。额外并联电容与吸收位于 include 文件，图上首两颗为代表。\n",
    ),
  });
  const plot =
    a[niso ? main + ".plt" : qr ? "QR_Flyback_1.plt" : `ACF_Forward_${n}.plt`];
  if (plot) files[main + ".plt"] = ascii(plot);
  return files;
}
export const exportSpice = (run: Spec) => bundle(spiceProject(run));
