import { type Spec, reference, normalize, rails, isolated, bank } from "./spec";
import { sourceFor, refs } from "./devices";
export function preview(p: Spec) {
  p = normalize(p);
  const output = rails(p),
    targets: Spec[] = [
      {
        target: "Q1:transfer",
        ref: "Q1",
        role: "主开关 · 米勒平台",
        axes: "X=Vgs / V；Y=Id / A",
        kind: "transfer",
      },
      {
        target: "Q1:charge",
        ref: "Q1",
        role: "主开关 · 栅电荷",
        axes: "X=Qg / C；Y=Vgs / V",
        kind: "charge",
      },
    ],
    rows: Spec[] = [
      { ref: "J1", kind: "connector", role: "输入端口" },
      { ref: "Q1", kind: "mos", role: "主 MOSFET" },
      { ref: "R_S1", kind: "resistor", role: "主开关电流采样电阻" },
    ];
  if (p.feedback_mode !== "PSR-MP6005" && p.component_management?.items?.U_CTRL)
    rows.push({
      ref: "U_CTRL",
      kind: "controller",
      role: "控制器型号参考（通用行为模型；未展开引脚/驱动/偏置）",
    });
  if (isolated(p))
    rows.push({ ref: "T1", kind: "transformer", role: "隔离变压器" });
  else rows.push({ ref: "L1", kind: "inductor", role: "储能电感" });
  if (p.topology === "ACF-FORWARD")
    rows.push(
      { ref: "Q2", kind: "mos", role: "有源钳位 MOS" },
      {
        ref: "C_CL1",
        kind: "capacitor",
        role: "有源钳位电容",
        special: "clamp",
      },
    );
  if (["FLYBACK", "QR-FLYBACK"].includes(p.topology) && p.Kc > 1)
    rows.push(
      {
        ref: "D_SN1",
        kind: "diode",
        role: "RCD 钳位二极管",
        special: "snubber",
      },
      {
        ref: "R_SN1",
        kind: "resistor",
        role: "RCD 钳位电阻",
        special: "snubber",
      },
      {
        ref: "C_SN1",
        kind: "capacitor",
        role: "RCD 钳位电容",
        special: "snubber",
      },
    );
  const diode = (ref: string, role: string) => {
    targets.push({
      target: ref,
      ref,
      role,
      axes: "X=Vf / V；Y=If / A",
      kind: "diode",
    });
    rows.push({ ref, role, kind: "diode" });
  };
  if (p.d_in_enable) diode("D_IN", "输入防反");
  (output.length ? output : [{ ...p, id: 1, name: "OUT1" }]).forEach(
    (r: Spec) => {
      const rr = refs(p, r.id);
      rows.push({
        ref:
          output.length || p.feedback_mode === "PSR-MP6005"
            ? "J_O" + r.id
            : "J2",
        kind: "connector",
        role: r.name + " · 输出端口",
      });
      if (p.topology === "ACF-FORWARD")
        rows.push({
          ref: output.length ? "L_O" + r.id : "L1",
          kind: "inductor",
          role: r.name + " · 输出电感",
        });
      diode(rr[0], r.name + " · 输出整流");
      if (p.topology === "ACF-FORWARD") diode(rr[1], r.name + " · 续流");
      if (r.d_out_enable) diode(rr[2], r.name + " · 输出防反");
      bank(r).forEach((c, i) =>
        rows.push({
          ref:
            output.length || p.feedback_mode === "PSR-MP6005"
              ? "C_O" +
                r.id +
                (i < 26 ? String.fromCharCode(65 + i) : "_" + (i + 1))
              : "C_O" + (i + 1),
          role: r.name + " · 输出电容 " + (i + 1),
          kind: "capacitor",
          output: r.id,
          index: i,
          C: c.C,
        }),
      );
    },
  );
  bank(p, "input").forEach((c, i) =>
    rows.push({
      ref: "C_IN" + (i + 1),
      role: "输入电容 " + (i + 1),
      kind: "capacitor",
      side: "input",
      index: i,
      C: c.C,
    }),
  );
  if (p.feedback_mode === "PSR-MP6005") {
    rows.push(
      { ref: "U_PSR", kind: "controller", role: "MP6005 PSR控制器" },
      { ref: "N_A", kind: "magnetic", role: "T1内部辅助采样绕组" },
    );
    for (const ref of ["R_FBH", "R_FBL", "R_REG", "R_COMP"])
      rows.push({
        ref,
        kind: "resistor",
        role: "MP6005 " + ref,
        special: "psr",
      });
    for (const ref of ["C_COMP", "C_POLE"])
      rows.push({
        ref,
        kind: "capacitor",
        role: "MP6005 " + ref,
        special: "psr",
      });
  } else if (isolated(p) && output.length)
    rows.push({ ref: "U_FB", kind: "block", role: "主反馈通路（参考模块）" });
  return {
    outputs: output,
    isolated: isolated(p),
    targets: targets.map((row) => {
      const curve =
        row.target === "Q1:transfer"
          ? p.mos_miller_curve
          : row.target === "Q1:charge"
            ? p.mos_charge_curve
            : p.diode_curves?.[row.target];
      return {
        ...row,
        source: sourceFor(p, row.target),
        loaded: !!curve?.points?.length,
        filename: curve?.import_file?.filename || curve?.source?.filename || "",
      };
    }),
    component_rows: rows,
    component_rules: reference.rules,
    capacitor_types: reference.cap_types,
    component_note:
      "使用随项目提供的降额规范。未填写额定值的项目不会被判定通过。",
    voltage_node_note: "输出在防反管后，反馈在防反管前。",
  };
}
