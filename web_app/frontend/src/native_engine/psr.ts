import { type Spec, roundEven, rails, blockDrop } from "./spec";
export function designPSR(p: Spec, op: Spec, tr: Spec = {}): Spec | null {
  if (p.feedback_mode !== "PSR-MP6005") return null;
  if (p.topology !== "FLYBACK") throw Error("MP6005 PSR 仅用于固定频率反激");
  const q = { ...p, ...rails(p)[(p.feedback_output || 1) - 1] },
    v: Spec = {
      psr_Na: 0,
      psr_aux_target: 9,
      psr_RfbH: 47000,
      psr_RfbL: 0,
      psr_Rreg: 6800,
      psr_Rcomp: 10000,
      psr_Ccomp: 10e-9,
      psr_Cpole: 220e-12,
      psr_Vcc: 8.5,
    };
  for (const k in v) {
    v[k] = p[k] ?? v[k];
    if (
      !Number.isFinite(v[k]) ||
      v[k] < 0 ||
      (!["psr_Na", "psr_RfbL", "psr_Rreg"].includes(k) && v[k] === 0)
    )
      throw Error(k + " 参数无效");
  }
  if (!Number.isInteger(v.psr_Na)) throw Error("辅助绕组必须为整数匝数");
  const np = tr.Np || q.Np || 1,
    ns = tr.Ns || q.Ns || Math.max(1, roundEven(np / op.N)),
    cap = q.V_out + blockDrop(q),
    vf = q.Vf_diode,
    na =
      v.psr_Na || Math.max(1, roundEven((ns * v.psr_aux_target) / (cap + vf))),
    va = (na / ns) * (cap + vf),
    rh = v.psr_RfbH,
    rg = v.psr_Rreg;
  const gain = ([
    [0, 1300, 0],
    [3000, 3600, 0.00005],
    [6200, 7500, 0.0001],
    [12700, 13000, 0.0002],
    [24900, 28000, 0],
  ].find(([lo, hi]) => lo <= rg + q.Rs && rg + q.Rs <= hi) || [0, 0, null])[2];
  const vs = q.Rs * op.I_in_est,
    ireg = (gain || 0) * vs,
    den = va - ireg * rh - 2;
  if (!v.psr_RfbL && den <= 0)
    throw Error("辅助电压不足或补偿过大，无法构造正反馈分压");
  const rl = v.psr_RfbL || (rh * 2) / den,
    beta = rl / (rh + rl),
    predicted = ((2 / beta + ireg * rh) * ns) / na - vf - blockDrop(q),
    reflected = (np / ns) * (cap + vf),
    rs = q.Rs,
    r = v.psr_Rcomp,
    cc = v.psr_Ccomp,
    cp = v.psr_Cpole,
    loss = (va * va) / (rh + rl);
  if (!(rs > 0)) throw Error("MP6005 Rs 必须大于0");
  return {
    controller: "MP6005",
    source:
      "https://www.monolithicpower.com/en/documentview/productdocument/index/version/2/document_type/Datasheet/lang/en/sku/MP6005GK/",
    revision: "1.1 (2024-10-11)",
    region: op.regulation_region || "PWM",
    Np: np,
    Ns: ns,
    Na: na,
    Vaux: va,
    RfbH: rh,
    RfbL: rl,
    beta,
    Hfb: (beta * na) / ns,
    Vfb: beta * (va - ireg * rh),
    Vout_set: predicted,
    Vout_error: predicted - q.V_out,
    Ifb_negative: (q.V_in * na) / np / rh,
    RfbH_min: (q.V_in * na) / np / 0.001,
    Rreg: rg,
    compensation_gain: gain,
    Ireg: ireg,
    compensation_offset: (ireg * rh * ns) / na,
    Rs_recommended: 0.128 / op.I_sw_pk,
    Ipk_limit_typ: 0.16 / rs,
    Ipk_limit_min: 0.14 / rs,
    Vcs_peak: rs * op.I_sw_pk,
    Vcs_average: vs,
    Lpri_min: (reflected * 0.7e-6 * rs) / 0.033,
    tcon_min33: (op.L * (0.033 / rs)) / reflected,
    tcon: op.Dp * op.Ts,
    sample_blank: 0.3e-6,
    sample_window: Math.max(0, op.Dp * op.Ts - 0.3e-6),
    minimum_load: 0.5 * op.L * (0.036 / rs) ** 2 * 30000 * op.eta_guess,
    Rcomp: r,
    Ccomp: cc,
    Cpole: cp,
    fz: 1 / (2 * Math.PI * r * cc),
    fp: (cc + cp) / (2 * Math.PI * r * cc * cp),
    KP: 0.00059 / (cc + cp),
    gm: 0.00059,
    Vcc: v.psr_Vcc,
    P_controller: q.V_in * 0.0008 + loss,
    P_feedback: loss,
    note: "MODE 悬空；PSR PWM 为平均模型，含 gEA、辅助分压与半周期延迟近似；内部斜坡、采样细节和动态补偿未建精确模型，PFM 不提供 SSR Bode 裕度。",
  };
}
export function psrCompensation(t: Spec) {
  if (t.comp_type !== "type2" || !(t.fp1 > t.fz1 && t.fz1 > 0 && t.KP > 0))
    throw Error("MP6005 COMP 二型阻容无法实现目标");
  const sum = 0.00059 / t.KP,
    cp = (sum * t.fz1) / t.fp1,
    cc = sum - cp;
  return {
    psr_Rcomp: 1 / (2 * Math.PI * t.fz1 * cc),
    psr_Ccomp: cc,
    psr_Cpole: cp,
  };
}
