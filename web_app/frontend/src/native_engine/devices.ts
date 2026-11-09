import { type Spec, clone } from "./spec";
import { interpolate, mean } from "./math";
export function sourceFor(p: Spec, target: string) {
  const settings = p.device_curve_settings;
  if (settings?.mode) return settings.overrides?.[target] || settings.mode;
  return target === "Q1:transfer"
    ? p.mos_miller_mode === "curve"
      ? "curve"
      : p.gfs > 0
        ? "legacy"
        : "fixed"
    : target === "Q1:charge"
      ? p.mos_charge_mode === "curve"
        ? "curve"
        : "fixed"
      : p.diode_curves?.[target]
        ? "curve"
        : "fixed";
}
export function selectedCurve(p: Spec, ref: string) {
  if (sourceFor(p, ref) !== "curve") return null;
  const value = p.diode_curves?.[ref];
  if (!value?.points?.length)
    throw Error(ref + " 已选择曲线计算，但没有导入 If–Vf");
  return value;
}
export function forward(
  current: number[],
  curve: Spec | null,
  vf: number,
  average?: number,
) {
    if (!current.length || current.some((i) => typeof i !== "number" || !Number.isFinite(i)))
      throw Error("二极管电流样本必须是非空有限数值");
    current = current.map((i) => Math.max(0, i));
    if (!curve) {
      if (typeof vf !== "number" || !Number.isFinite(vf) || vf < 0)
        throw Error("固定二极管 Vf 必须为有限非负数");
      const forwardAverage = average ?? mean(current);
      if (typeof forwardAverage !== "number" || !Number.isFinite(forwardAverage) || forwardAverage < 0)
        throw Error("二极管正向平均电流必须为有限非负数");
    return {
      model: "fixed_vf",
        P_cond: vf * forwardAverage,
      Vf: vf,
        notes: ["固定 Vf × 正向平均电流；不叠加动态电阻项，反向样本不计导通损耗"],
    };
    }
  const inverse = curve.points
      .map(([v, i]: number[]) => [i, v])
      .sort((a: number[], b: number[]) => a[0] - b[0]),
    min = inverse[0][0],
    max = inverse.at(-1)![0],
    extrapolations: string[] = [];
  if (current.some((v) => v > 0 && v < min))
    extrapolations.push("低电流沿端点趋势外推");
  if (current.some((v) => v > max)) extrapolations.push("高电流沿端点趋势外推");
  return {
    model: "vf_if_curve",
    P_cond: mean(
      current.map((i) =>
        i > 0 ? i * Math.max(0, interpolate(inverse, i)) : 0,
      ),
    ),
    curve_name: curve.name,
    source: curve.source,
    extrapolations,
    notes: [
      "逐点计算 I×Vf 的周期平均值，不叠加固定 Vf 或动态电阻",
      ...extrapolations,
    ],
  };
}
export function gate(op: Spec, p: Spec) {
  const transfer = sourceFor(p, "Q1:transfer"),
    charge = sourceFor(p, "Q1:charge"),
    manual = p.mos_manual_events?.[p.input_voltage_case || "min"],
    qcurve = p.mos_charge_curve,
    ion = Math.max(op.I_sw_on ?? op.I_L_min, 0),
    ioff = Math.abs(op.I_sw_off ?? op.I_L_pk),
    vth = p.Vth,
    drive = p.Vgs;
  let von = p.Vgp_on,
    voff = p.Vgp_off,
    qth = p.Qg_th,
    qon = p.Qgs,
    qoff = p.Qgs,
    qgd = p.Qgd,
    qt = p.Qg;
  if (transfer === "curve") {
    const c = p.mos_miller_curve;
    if (!c?.kind) throw Error("需要导入 Q1 的 Id–Vgs 转移曲线");
    let inverse: number[][];
    if (c.kind === "transfer")
      inverse = c.points.map(([x, y]: number[]) => [y, x]);
    else {
      if (!(p.mos_curve_vds > 0)) throw Error("Id–Vds 曲线族需要读取 Vds");
      inverse = c.traces.map((r: Spec) => [
        interpolate(
          r.points,
          p.mos_curve_vds,
          c.x_scale === "log",
          c.y_scale === "log",
        ),
        r.Vgs_V,
      ]);
    }
    von = ion
      ? Math.max(
          vth,
          interpolate(inverse, ion, c.y_scale === "log", c.x_scale === "log"),
        )
      : vth;
    voff = ioff
      ? Math.max(
          vth,
          interpolate(inverse, ioff, c.y_scale === "log", c.x_scale === "log"),
        )
      : vth;
  } else if (transfer === "legacy") {
    if (!(p.gfs > 0)) throw Error("旧跨导模式需要正 gfs");
    von = vth + ion / p.gfs;
    voff = vth + ioff / p.gfs;
  } else if (manual) {
    von = manual.on.Vgp;
    voff = manual.off.Vgp;
    qon = manual.on.Qgs;
    qoff = manual.off.Qgs;
  }
  if (charge === "curve") {
    if (!qcurve?.points || !(qcurve.Qplateau_end_C > qcurve.Qgs_ref_C))
      throw Error("Q1 需要有效的 Vgs–Qg 曲线和平台起止");
    const pts = qcurve.points,
      begin = qcurve.Qgs_ref_C,
      end = qcurve.Qplateau_end_C,
      pre = [
        ...pts.filter((r: number[]) => r[0] < begin),
        [begin, interpolate(pts, begin)],
      ].map(([x, y]: number[]) => [y, x]),
      post = [
        [end, interpolate(pts, end)],
        ...pts.filter((r: number[]) => r[0] > end),
      ].map(([x, y]: number[]) => [y, x]);
    qth = Math.max(0, interpolate(pre, vth));
    qon = Math.max(0, interpolate(pre, von));
    qoff = Math.max(0, interpolate(pre, voff));
    qgd = end - begin;
    if (drive <= post[0][0]) throw Error("驱动电压必须高于平台后起点");
    qt = Math.max(0, interpolate(post, drive));
  } else if (transfer !== "fixed") {
    const c = (p.Qgs - qth) / (p.Vgp_on - vth);
    qon = qth + c * (von - vth);
    qoff = qth + c * (voff - vth);
  }
  if (
    !(
      vth > 0 &&
      von >= vth &&
      voff >= vth &&
      von < drive &&
      voff < drive &&
      qon >= qth &&
      qoff >= qth
    )
  )
    throw Error("MOS 平台或电荷不满足驱动/阈值约束，请核对数量级与曲线");
  return {
    mode: transfer === "fixed" ? "fixed" : transfer,
    charge_mode: charge,
    label: transfer === "curve" ? "Id–Vgs 曲线反查平台" : "手动平台",
    I_on: ion,
    I_off: ioff,
    Vgp_on: von,
    Vgp_off: voff,
    Qg_th: qth,
    Qgs_on: qon,
    Qgs_off: qoff,
    Qgd_on: qgd,
    Qgd_off: qgd,
    Qg_on: qt,
    Qg_off: qt,
    notes:
      charge === "curve"
        ? [
            "Qgs 从平台前支路反查；Qgd 为参考平台电荷差；总 Qg 在驱动电压读取。不同电流事件复用同一参考曲线。",
          ]
        : ["固定电荷参数；米勒平台为工程估算。"],
  };
}
export function mosLoss(op: Spec, p: Spec) {
  const g = gate(op, p),
    ron = p.Rg_drive + p.Rs_on + p.Rg,
    roff = p.Rg_drive + p.Rs_off + p.Rg,
    v = p.Vgs,
    th = p.Vth,
    t1 = ((-ron * g.Qg_th) / th) * Math.log1p(-th / v),
    t2 =
      g.Vgp_on === th && g.mode !== "fixed"
        ? 0
        : ((-ron * g.Qgs_on) / g.Vgp_on) * Math.log1p(-g.Vgp_on / v) - t1,
    t3 = (g.Qgd_on * ron) / (v - g.Vgp_on),
    t6 = (g.Qgd_off * roff) / g.Vgp_off,
    t7 =
      g.Vgp_off > th
        ? ((roff * (g.Qgs_off - g.Qg_th)) / (g.Vgp_off - th)) *
          Math.log(g.Vgp_off / th)
        : 0,
    t8 = (3 * roff * g.Qg_th) / th;
  if (t2 < 0) throw Error("栅电荷法得到负 t2，请核对 Qgs 和 Qg(th)");
  const P_cond = p.Rds_on * op.I_sw_rms ** 2,
    P_sw_on =
      op.topology === "QR-FLYBACK"
        ? 0
        : p.k_sw * op.V_sw_max * g.I_on * (t2 + t3) * op.f_sw,
    P_sw_off = p.k_sw * op.V_sw_max * g.I_off * (t6 + t7) * op.f_sw,
    P_coss =
      op.topology === "QR-FLYBACK"
        ? 0
        : 0.5 * p.Coss * op.V_sw_max ** 2 * op.f_sw,
    P_gate = g.Qg_on * v * op.f_sw;
  return {
    P_cond,
    P_sw_on,
    P_sw_off,
    P_coss,
    P_gate,
    P_total: P_cond + P_sw_on + P_sw_off + P_coss + P_gate,
    Ptr: P_sw_on,
    Ptf: P_sw_off,
    gate: g,
    t1,
    t2,
    t3,
    t4: (3 * ron * Math.max(0, g.Qg_on - g.Qgs_on - g.Qgd_on)) / (v - g.Vgp_on),
    t5:
      ((roff * Math.max(0, g.Qg_off - g.Qgs_off - g.Qgd_off)) /
        (v - g.Vgp_off)) *
      Math.log(v / g.Vgp_off),
    t6,
    t7,
    t8,
  };
}
export function diodeLoss(
  op: Spec,
  p: Spec,
  current: number[],
  ref: string,
  free = false,
) {
  const details = forward(
      current,
      selectedCurve(p, ref),
      p.Vf_diode,
      free ? op.I_free_avg : op.I_d_avg,
    ),
    P_rr = p.Qrr * (free ? op.V_free_max : op.V_d_max) * op.f_sw;
  return { ...details, P_rr, P_total: details.P_cond + P_rr, sr: false };
}
export function refs(p: Spec, id = 1) {
  return p.outputs?.length || p.feedback_mode === "PSR-MP6005"
    ? [`D_O${id}`, `D_F${id}`, `D_B${id}`]
    : ["D1", "D2", "D_OUT"];
}
export function stress(op: Spec) {
    let blocking =
        op.topology === "ACF-FORWARD"
          ? op.V_clamp
          : (op.clamp?.V_plateau ?? op.V_sw_max / (1 + op.ring_margin)),
      blockingSource = "",
      blockingNote = "";
    if (["BUCK", "BOOST", "BUCK-BOOST"].includes(op.topology)) {
      if (op.niso_model) {
        blocking = op.V_sw_max;
        blockingSource = "periodic_actual_vds_envelope";
        blockingNote =
          "周期功率级实际 Vds 最大值，保守用于稳态阻断检查；包含模型内导通压降/输出低频纹波，未覆盖 Coss/ESL 等未建模尖峰。";
      } else if (op.efficiency_model === "equivalent_output_burden") {
        blocking =
          op.topology === "BUCK"
            ? op.V_in
            : op.topology === "BOOST"
              ? op.V_out_equiv
              : op.V_in + op.V_out_equiv;
        blockingSource = "legacy_topology_working_point";
        blockingNote =
          "旧等效工作点名义阻断平台；含人工裕量的原 Vds 包络另外保留，不当作已求解尖峰。";
      } else {
        blocking = op.V_sw_max;
        blockingSource = "conservative_available_vds_maximum";
        blockingNote =
          "工作点未区分阻断平台与峰值，保守采用现有最大值，不反除未知裕量。";
      }
    }
  const sw = {
      I_rms: op.I_sw_rms,
      I_pk: op.I_sw_pk,
      I_avg: op.I_sw_avg,
      V_max: op.V_sw_max,
        V_block: blocking,
        ...(blockingSource
          ? {
              blocking_voltage_source: blockingSource,
              blocking_voltage_note: blockingNote,
              ...(blockingSource === "legacy_topology_working_point"
                ? { V_recommended: op.V_sw_max }
                : {}),
            }
          : {}),
        note: "MOS 电压应力须结合实测复核" + (blockingNote ? "；" + blockingNote : ""),
    },
    di = {
      I_rms: op.I_d_rms,
      I_pk: op.I_d_pk,
      I_avg: op.I_d_avg,
      V_max: op.V_d_max,
      V_block: op.V_d_max,
      note: "未考虑寄生尖峰；具体反压需实测，选型建议留有余量",
      includes_parasitic_spikes: false,
    };
  return {
    switch: sw,
    diode: di,
    ...(op.topology === "ACF-FORWARD"
      ? {
          auxiliary: {
            I_rms: op.I_aux_rms,
            I_pk: op.I_aux_pk,
            I_avg: op.I_aux_avg_abs,
            V_max: op.V_sw_max,
            V_block: op.V_clamp,
            note: "钳位MOS与实际换流须复核",
          },
          freewheel: {
            I_rms: op.I_free_rms,
            I_pk: op.I_free_pk,
            I_avg: op.I_free_avg,
            V_max: op.V_free_max,
            V_block: op.V_free_max,
            note: "未考虑未建模尖峰，选型留裕量",
          },
        }
      : {}),
  };
}
