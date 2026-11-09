/** Current embedded examples versus current Python inputs, without replacing historical fixtures. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { reference, normalize, bank, clone, type Spec } from "../web_app/frontend/src/native_engine/spec";
import { design, componentEvaluation } from "../web_app/frontend/src/native_engine/engine";
import { stress, sourceFor, forward } from "../web_app/frontend/src/native_engine/devices";
import { inductorHardware, purchasedInductor } from "../web_app/frontend/src/native_engine/inductor_selection";
import { reportModules } from "../web_app/frontend/src/native_engine/reports";
import { chart } from "../web_app/frontend/src/native_engine/charts";
import { cornerAnalysis } from "../web_app/frontend/src/native_engine/actions";

const names = Object.keys(reference.examples),
  oracleScript = String.raw`
import copy,json,sys
from web_app.metadata import read_example,normalize_config
from loss_model import compute_design
names=json.load(sys.stdin)
rows=[]
for name in names:
 p=normalize_config(read_example(name)); cases=[]
 for voltage in sorted(set([p['V_in_min'],p['V_in_max']])):
  q=dict(copy.deepcopy(p),V_in=voltage,input_voltage_case='max' if voltage==p['V_in_max'] and p['V_in_max']!=p['V_in_min'] else 'min')
  res=compute_design(q);op=res['op']
  keys=('D','Dp','f_sw','V_out','I_L_pk','I_sw_rms','I_sw_pk','I_d_rms','I_d_pk','V_sw_max','V_d_max')
  cases.append(dict(voltage=voltage,op={k:op.get(k) for k in keys},losses={k:res[k] for k in ('P_semi','P_mag','P_cap','P_cap_in','P_sense','P_rcd','P_din','P_dout','P_total','eta')},mag=res['mag'].get('inductor')))
 rows.append(dict(name=name,spec=p,cases=cases))
print(json.dumps(rows,ensure_ascii=False,allow_nan=False))
`,
  python = process.env.POWER_DESIGN_PYTHON || path.resolve(".venv-web/Scripts/python.exe"),
  result = spawnSync(python, ["-X", "utf8", "-c", oracleScript], {
    input: JSON.stringify(names), encoding: "utf8", timeout: 180000,
    maxBuffer: 20 * 1024 * 1024,
  });
assert.equal(result.status, 0, result.stderr || String(result.error));
const oracle: Spec[] = JSON.parse(result.stdout), differences: Spec[] = [], completed: Spec[] = [];
assert.equal(names.length, 7, "Only the existing seven embedded examples are refreshed");
function compare(a: number, b: number, label: string, tolerance = 3e-4) {
  if (!Number.isFinite(a) || Math.abs(a - b) > Math.max(1e-9, Math.abs(b) * tolerance))
    differences.push({ label, ts: a, python: b, relative: b ? (a - b) / b : null, tolerance });
}
for (const row of oracle) {
  assert.deepEqual(reference.examples[row.name], row.spec, row.name + " current Python normalization");
  const p = normalize(reference.examples[row.name]), items = p.component_management.items;
  assert.equal(p.device_curve_settings.mode, "fixed");
  for (const key of ["mos_miller_curve", "mos_charge_curve", "mos_manual_events", "diode_curves"])
    assert.deepEqual(p[key], {}, row.name + " anonymous curve binding retired");
  for (const key of ["Rds_on", "Qg", "Qgs", "Qgd", "Qg_th", "Coss", "Vth", "Rg", "Rs", "Vf_diode", "Qrr", "Vf_din", "Vf_dout"])
    assert.equal(p[key], row.spec[key], row.name + " input " + key);
  assert.deepEqual(bank(p, "input"), row.spec.input_capacitors);
  assert.deepEqual(bank(p), row.spec.output_capacitors);
  if (p.topology === "QR-FLYBACK") {
    assert.equal(bank(p).length, 3);
    assert.equal(items.C_O1.model, "EEUFS2A221");
    assert.equal(items.C_O2.voltage_V, 100);
  }
  for (const c of row.cases) {
    const q = { ...clone(p), V_in: c.voltage, input_voltage_case: c.voltage === p.V_in_max ? "max" : "min" },
      run = design(q, false), bom = componentEvaluation(run.p, run),
      bomByRef = Object.fromEntries(bom.rows.map((r: Spec) => [r.ref, r]));
    assert.deepEqual(run.p.input_capacitors, q.input_capacitors);
    assert.equal(run.semi.switch.P_cond, q.Rds_on * run.op.I_sw_rms ** 2, "MOS loss uses selected Rds");
    for (const [ref, item] of Object.entries(items) as [string, Spec][]) {
      assert.ok(bomByRef[ref], row.name + " missing BOM ref " + ref);
      for (const key of ["manufacturer", "model", "package", "voltage_V", "ripple_A", "power_W", "conditions", "note"])
        assert.equal(bomByRef[ref][key], item[key], row.name + " " + ref + " " + key);
    }
    const allCaps = bom.rows.filter((r: Spec) => r.kind === "capacitor" && r.index !== undefined),
      allBanks = [bank(q, "input"), ...(run.outputs.map((r: Spec) => bank(r.spec)))];
    assert.equal(allCaps.length, allBanks.reduce((n: number, b: Spec[]) => n + b.length, 0));
    for (const r of run.outputs)
      assert.equal(r.capacitors.output.caps.length, bank(r.spec).length, "every output capacitor participates in losses");
    const bomRows = reportModules().find((m) => m.name === "BOM与降额")!.rows({ summary: { component_management: bom } });
    assert.ok(bomRows.some((r) => r[0].startsWith("U_CTRL ") && String(r[1]).includes(items.U_CTRL.model)), "controller reference enters report");
    assert.ok(bomRows.some((r) => r[0].startsWith("Q1 ") && String(r[3]).includes(items.Q1.conditions)), "part conditions enter report");
    if (p.inductor_design_enabled === false) {
      const ind = run.mag.inductor;
      assert.equal(ind.design_enabled, false); assert.equal(ind.core, null); assert.equal(ind.P_core, null);
      assert.equal(ind.R_dc, p.inductor_dcr);
      assert.equal(ind.P_total, run.op.I_L_rms ** 2 * p.inductor_dcr + p.inductor_extra_loss);
      assert.equal(run.op.niso_model.dcr, p.inductor_dcr);
      assert.equal(run.P_mag, ind.P_total);
      const frozen = purchasedInductor(run.op, { ...q, inductor_dcr: 10, _fixed_inductor: inductorHardware(ind) });
      assert.equal(frozen.R_dc, ind.R_dc, "frozen purchased DCR owns both endpoints");
      assert.equal(frozen.P_total, ind.P_total);
      compare(run.P_mag, c.losses.P_mag, row.name + "/" + c.voltage + "/purchased_Pmag", 0.001);
      for (const kind of ["magnetics", "magnetic_flux"]) {
        const svg = chart(q, run, kind);
        assert.ok(!svg.includes("NaN") && !svg.includes("undefined"), kind + " has no fictitious core geometry");
      }
      assert.equal(stress(run.op).switch.V_block, run.op.V_sw_max);
      if (c.voltage === row.cases[0].voltage) {
        const corners = cornerAnalysis(run, {v_in_min:p.V_in_min,v_in_max:p.V_in_max,load_fracs:[1]},()=>{});
        assert.ok(corners.corners.every((r:Spec)=>!r.skipped && r.dT===null && r.B_pk===null));
        assert.ok(!("max_dT" in corners.worst) && !("max_B_pk" in corners.worst), "unknown thermal/flux has no numeric worst-case guarantee");
      }
    }
    for (const [key, value] of Object.entries(c.op))
      if (typeof value === "number") compare(run.op[key], value, row.name + "/" + c.voltage + "/" + key);
    for (const [key, value] of Object.entries(c.losses))
      if (typeof value === "number") compare(run[key as keyof typeof run], value, row.name + "/" + c.voltage + "/" + key, 0.012);
    completed.push({ name: row.name, voltage: c.voltage, bom: bom.rows.length, input_caps: bank(q,"input").length, output_caps: run.outputs.map((r: Spec)=>bank(r.spec).length) });
    console.log("CHECK current real parts", row.name, c.voltage, "V");
  }
}
const startup = clone(reference.examples["40W_CCM_FLYBACK.json"]);
Object.assign(startup, { V_in_min: startup.V_in, V_in_max: startup.V_in, input_voltage_case: "min" });
assert.deepEqual(reference.bootstrap.spec, startup);
for (const [key, value] of Object.entries(reference.bootstrap.output_template)) assert.deepEqual(value, startup[key]);
for (const key of ["input_capacitors", "output_capacitors"]) assert.equal(reference.defaults[key], null);
for (const key of ["component_management", "mos_miller_curve", "mos_charge_curve", "mos_manual_events", "diode_curves", "device_curve_settings"])
  assert.deepEqual(reference.defaults[key], {}, "generic defaults do not leak startup hardware");
const legacy = normalize({ topology:"BUCK", V_in:12, V_out:5, P_out:5, f_sw:100e3, L:47e-6,
  Cin1:47e-6,Cin2:22e-6,cin2_enable:true,C_out:100e-6,C_out2:22e-6,cout2_enable:true,
  mos_miller_mode:"curve",mos_miller_curve:{points:[[3,0],[4,10],[5,20]]} });
assert.deepEqual(bank(legacy,"input").map(c=>c.C),[47e-6,22e-6]);
assert.deepEqual(legacy.component_management,{}); assert.equal(sourceFor(legacy,"Q1:transfer"),"curve");
for (const invalid of ["false", 0, null, 1])
  assert.throws(() => design({...legacy,inductor_design_enabled:invalid},false), /必须为布尔值/);
for (const current of [[], [Number.NaN], [Number.POSITIVE_INFINITY]])
  assert.throws(() => forward(current,null,.7), /非空有限/);
for (const vf of [-.1, Number.NaN, Number.POSITIVE_INFINITY])
  assert.throws(() => forward([1],null,vf), /Vf/);
for (const average of [-1, Number.NaN, Number.POSITIVE_INFINITY])
  assert.throws(() => forward([1],null,.7,average), /正向平均/);
const signed = [-4,-2,0,1,3], unitVf = {points:[[1,0],[1,4]],name:"fixed 1V"};
assert.equal(forward(signed,null,1).P_cond, .8);
assert.equal(forward(signed,unitVf,1).P_cond, .8);
assert.equal(forward([-4,-2],null,1).P_cond, 0);
assert.equal(forward([-4,-2],unitVf,1).P_cond, 0);
assert.equal(forward(signed,null,1,2).P_cond,2);
for (const topology of ["BUCK","BOOST","BUCK-BOOST"]) {
  const op={topology,V_in:30,V_out_equiv:25,V_sw_max:55,ring_margin:.3};
  assert.equal(stress({...op,niso_model:{}}).switch.V_block,55);
  assert.equal(stress(op).switch.V_block,55);
  const nominal=topology==="BUCK"?30:topology==="BOOST"?25:55;
  assert.equal(stress({...op,efficiency_model:"equivalent_output_burden"}).switch.V_block,nominal);
}
const output=path.resolve("artifacts/example-real-parts-20261108/native-current-example-check.json");
fs.mkdirSync(path.dirname(output),{recursive:true});
fs.writeFileSync(output,JSON.stringify({scope:"Current seven embedded examples; no old fixture regeneration",completed,differences},null,2));
for (const difference of differences) console.error("DIFF",JSON.stringify(difference));
assert.deepEqual(differences,[],"Current Python/TS model deviations retained in receipt");
console.log("PASS current real-part inputs, BOM/report, capacitor branches, purchased inductors, legacy isolation and Vds semantics");
