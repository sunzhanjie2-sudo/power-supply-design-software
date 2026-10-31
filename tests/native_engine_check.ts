import fixtures from "./fixtures/native_engine_reference.json";
import assert from "node:assert/strict";
import { nominal } from "../web_app/frontend/src/native_engine/power";
import { solveCoupled } from "../web_app/frontend/src/native_engine/coupled";
import { normalize } from "../web_app/frontend/src/native_engine/spec";
import { design } from "../web_app/frontend/src/native_engine/engine";
import { plant } from "../web_app/frontend/src/native_engine/loop";
import { solveNonisolated } from "../web_app/frontend/src/native_engine/nonisolated";
import {
  symmetricEigen,
  mm,
  transpose,
} from "../web_app/frontend/src/native_engine/math";
import { assess } from "../web_app/frontend/src/native_engine/winding";
import { gate, forward } from "../web_app/frontend/src/native_engine/devices";
import { spectrum } from "../web_app/frontend/src/native_engine/waveforms";
import {
  capability,
  clone,
  reference,
} from "../web_app/frontend/src/native_engine/spec";
import { applyCurve } from "../web_app/frontend/src/native_engine/curves";
let failed = 0;
for (const fixture of fixtures) {
  try {
    const p = normalize(fixture.spec);
    p.V_in = fixture.spec.V_in;
    let op = nominal(p);
    if (p.spice_config?.niso_profile) op = solveNonisolated(p, op);
    if (p.coupling_config?.enabled) op = solveCoupled(p, op);
    const compare = (actual: any, expected: any, path: string) => {
      for (const [key, value] of Object.entries(expected)) {
        if (
          value === null ||
          ["coupling", "losses", "gate", "plant_gains", "loop_error"].includes(
            key,
          )
        )
          continue;
        if (Array.isArray(value)) {
          value.forEach((v, i) =>
            compare(
              (key === "outputs" ? actual.output_ops : actual[key])[i],
              v,
              path + "." + key + "[" + i + "]",
            ),
          );
        } else if (typeof value === "number") {
          assert.ok(
            Math.abs(actual[key] - value) <=
              Math.max(1e-7, Math.abs(value) * 3e-4),
            `${path}.${key}: TS=${actual[key]}, Python=${value}`,
          );
        }
      }
    };
    compare(op, fixture.expected, fixture.name);
    const res = design(p, false),
      expected = fixture.expected as any;
    for (const [key, value] of Object.entries(expected.gate || {}))
      assert.ok(
        Math.abs(res.semi.switch.gate[key] - Number(value)) <=
          Math.max(1e-14, Number(value) * 0.004),
        `${fixture.name} gate.${key}: TS=${res.semi.switch.gate[key]}, Python=${value}`,
      );
    for (const [key, value] of Object.entries(expected.losses || {}))
      assert.ok(
        Math.abs((res as any)[key] - Number(value)) <=
          Math.max(1e-7, Number(value) * 0.012),
        `${fixture.name} loss.${key}: TS=${(res as any)[key]}, Python=${value}`,
      );
    if (expected.plant_gains) {
      const g = plant(p, res.op).gain;
      [1, 10, 100, 1000, 10000].forEach((f, i) => {
        const a = g(f),
          b = expected.plant_gains[i],
          error = Math.hypot(a[0] - b[0], a[1] - b[1]) / Math.hypot(b[0], b[1]);
        assert.ok(
          error < 0.003,
          `${fixture.name} plant ${f}Hz error=${error}: TS=${a}, Python=${b}`,
        );
      });
    }
    console.log("PASS", fixture.name);
  } catch (error) {
    failed++;
    console.error("FAIL", fixture.name, String(error));
  }
}
const a = [
    [2, 0.5],
    [0.5, 1],
  ],
  e = symmetricEigen(a),
  reconstructed = mm(
    mm(
      e.vectors,
      e.values.map((v, i) => e.values.map((_, j) => (i === j ? v : 0))),
    ),
    transpose(e.vectors),
  );
assert.ok(Math.abs(reconstructed[0][1] - 0.5) < 1e-12);
if (failed) process.exitCode = 1;
const p = normalize(fixtures[0].spec) as any;
const q = {
  ...p,
  device_curve_settings: { mode: "curve" },
  Vth: 3,
  Vgs: 10,
  mos_miller_curve: {
    kind: "transfer",
    points: [
      [3, 0],
      [4, 10],
      [5, 20],
    ],
  },
  mos_charge_curve: {
    points: [
      [0, 0],
      [5e-9, 5],
      [7e-9, 5],
      [12e-9, 10],
    ],
    Qgs_ref_C: 5e-9,
    Qplateau_end_C: 7e-9,
  },
};
const g = gate({ I_sw_on: 5, I_sw_off: 15 }, q);
assert.equal(g.Vgp_on, 3.5);
assert.equal(g.Vgp_off, 4.5);
assert.ok(
  Math.abs(g.Qgs_on - 3.5e-9) < 1e-20 && Math.abs(g.Qgs_off - 4.5e-9) < 1e-20,
);
assert.ok(Math.abs(g.Qgd_on - 2e-9) < 1e-20);
const extended = forward(
  [0, 1, 2],
  {
    name: "simple",
    points: [
      [0.5, 0.1],
      [0.7, 1],
    ],
  },
  0.7,
);
assert.ok(extended.P_cond > 0 && extended.extrapolations.length === 1);
const imported = applyCurve({
  filename: "diode.csv",
  content: "x,y\n500,0.1\n700,1\n695,1.1\n800,2",
  target: "D1",
  spec: p,
  x_multiplier: 0.001,
  y_multiplier: 1,
}).spec;
assert.ok(
  imported.diode_curves.D1.points[2][0] >=
    imported.diode_curves.D1.points[1][0],
);
const currents = Array.from({ length: 256 }, (_, i) =>
  Math.sin((2 * Math.PI * i) / 256),
);
const split = spectrum(
  currents,
  1 / 256000,
  1000,
  Array.from({ length: 3 }, () => ({ C: 1e-6, ESR: 0.01, ESL: 0 })),
);
assert.ok(
  split.caps.every((c: any) => Math.abs(c.total - Math.SQRT1_2 / 3) < 1e-10),
);
const wires = [
  { id: "P", name: "P", turns: 6, strands: 40, bare_diameter: 0.0001 },
  { id: "OUT1", name: "OUT1", turns: 12, strands: 30, bare_diameter: 0.0001 },
];
const cfg = {
  window_width: 0.012,
  window_height: 0.01,
  layer_plan: [
    { winding_id: "P", turns: 3 },
    { winding_id: "OUT1", turns: 6 },
    { winding_id: "P", turns: 3 },
    { winding_id: "OUT1", turns: 6 },
  ],
};
const winding = assess(wires, cfg),
  round = assess(wires, {
    ...cfg,
    overrides: { P: { flatten_ratio: 1 }, OUT1: { flatten_ratio: 1 } },
  });
assert.ok(winding.fits);
assert.equal(winding.total_layer_count, 4);
assert.ok(
  Math.abs(
    winding.windings[0].bundle_width / round.windings[0].bundle_width - 1.5,
  ) < 1e-12,
);
assert.ok(
  Math.abs(
    winding.windings[0].bundle_height / round.windings[0].bundle_height -
      1 / 1.5,
  ) < 1e-12,
);
assert.throws(
  () => assess(wires, { ...cfg, layer_plan: [{ winding_id: "P", turns: 4 }] }),
  /总匝数/,
);
assert.equal(capability({ ...p, parasitic_config: { mode: "transient" } }).length,0);
const bad = normalize(clone(reference.examples["40W_CCM_3OUT_FLYBACK.json"]));
bad.coupling_config.k[0][1] = 0.1;
assert.throws(() => design(bad, false), /对称/);
const identity = clone(bad);
identity.coupling_config.k = Array.from({ length: 4 }, () => Array(4).fill(1));
assert.equal(design(identity, false).op.coupled_model.ideal_fallback,true);
console.log(
  "PASS imported MOS / diode curves, extrapolation, 3-cap RMS splitting, interleaved litz geometry, invalid matrix guards",
);
