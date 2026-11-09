/** Purchased-inductor branch mirrored from inductor_selection.py. */
import { type Spec } from "./spec";

const fields = [
  "inductor_dcr",
  "inductor_rated_current",
  "inductor_saturation_current",
  "inductor_extra_loss",
];
export const purchased = (p: Spec) =>
  ["BUCK", "BOOST", "BUCK-BOOST"].includes(p.topology) &&
  p.inductor_design_enabled === false;

export function purchasedInductor(op: Spec, p: Spec): Spec {
  const fixed = p._fixed_inductor || {}, values: Spec = {};
  for (const key of fields) {
    const value = fixed[key] ?? p[key] ?? 0;
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0)
      throw Error(key + " 必须为有限非负数；0 表示未提供/暂不计入");
    values[key] = value;
  }
  const copper = op.I_L_rms ** 2 * values.inductor_dcr,
    extra = values.inductor_extra_loss;
  let note =
    "外购成品电感：不设计磁芯、匝数、气隙或线径。电感量 L 仍用于工作点、波形和环路；直流铜损为 Irms²×DCR，附加损耗为当前工况输入值，不自动缩放。未建模 L 随电流/温度变化；磁密、绕制和温升未评估。";
  if (!values.inductor_dcr) note += " DCR 未提供，暂按 0 Ω，铜损未覆盖。";
  if (!extra) note += " 附加损耗未提供，磁芯及交流损耗未覆盖，效率可能偏高。";
  return {
    ok: true, design_enabled: false, core: null, core_label: "外购成品电感",
    L: op.L, I_pk: op.I_L_pk, I_rms: op.I_L_rms,
    R_dc: values.inductor_dcr, P_cu: copper, P_core: null, P_extra: extra,
    P_total: copper + extra, B_pk: null, dB: null, dT: null, fill: null,
    DCR_source: "成品电感 DCR 输入", thermal_model: "not_evaluated", note, ...values,
  };
}

export function inductorHardware(device: Spec): Spec {
  if (device.design_enabled === false)
    return {
      design_enabled: false, L: device.L,
      ...Object.fromEntries(fields.map((key) => [key, device[key]])),
    };
  return structuredClone(device);
}
