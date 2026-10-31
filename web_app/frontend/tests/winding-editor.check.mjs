/** Node-only interactive component checks; no browser install or electrical solve. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parse, compileScript } from "@vue/compiler-sfc";
import { buildSync } from "esbuild";
import { createRenderer, h, nextTick, reactive } from "vue";

const here = dirname(fileURLToPath(import.meta.url));
const filename = resolve(here, "../src/WindingEditor.vue");
const source = readFileSync(filename, "utf8");
const { descriptor } = parse(source, { filename });
const compiled = compileScript(descriptor, { id: "winding-editor-check", inlineTemplate: true });
const built = buildSync({ stdin: { contents: compiled.content, resolveDir: dirname(filename),
  sourcefile: filename + ".ts", loader: "ts" }, bundle: true, write: false,
  format: "cjs", platform: "node", external: ["vue"] }).outputFiles[0].text;
const module = { exports: {} };
new Function("module", "exports", "require", built)(module, module.exports, createRequire(import.meta.url));
const Component = module.exports.default;
globalThis.window = { confirm: () => true };

function node(type, text = "") { return { type, text, props: {}, children: [], parent: null }; }
const renderer = createRenderer({
  createElement: (type) => node(type), createText: (text) => node("#text", text),
  createComment: (text) => node("#comment", text),
  insert(child, parent, anchor = null) {
    if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1);
    const index = anchor ? parent.children.indexOf(anchor) : -1;
    if (index < 0) parent.children.push(child); else parent.children.splice(index, 0, child);
    child.parent = parent;
  },
  remove(child) { if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1); child.parent = null; },
  setText: (target, text) => { target.text = text; },
  setElementText: (target, text) => { target.children = []; target.text = text; },
  parentNode: (target) => target.parent,
  nextSibling: (target) => target.parent?.children[target.parent.children.indexOf(target) + 1] || null,
  patchProp: (target, key, _previous, next) => { target.props[key] = next; },
});
const actual = [
  { id: "P", name: "原边 P", turns: 6, strands: 40, bare_diameter: 0.0001 },
  { id: "OUT1", name: "副边 OUT1", turns: 12, strands: 30, bare_diameter: 0.0001 },
];
function text(target) { return target.type === "#comment" ? "" : target.text + target.children.map(text).join(""); }
function all(target, filter) { return [...(filter(target) ? [target] : []), ...target.children.flatMap((child) => all(child, filter))]; }
function clone(value) { return JSON.parse(JSON.stringify(value)); }
function mount(extra = {}) {
  const root = node("root"), emitted = [];
  const props = reactive({ spec: { topology: "FLYBACK", Np: 6, Ns: 12,
    n_strand_p: 40, n_strand_s: 30, d_wire_p: 0.0001, d_wire_s: 0.0001 },
    windings: clone(actual), ...extra });
  const app = renderer.createApp({ render() { return h(Component, { ...props,
    onChange: (value) => { emitted.push(["change", clone(value)]); props.spec = value; },
    onPreview: (value) => emitted.push(["preview", clone(value)]),
  }); } });
  app.mount(root);
  return { root, props, emitted, app,
    button: (label) => all(root, (item) => item.type === "button" && text(item).trim() === label)[0],
    input: (label) => all(root, (item) => item.type === "input" && item.props["aria-label"] === label)[0],
    fieldInput: (label) => {
      const parent = all(root, (item) => item.type === "label" && item.children[0] && text(item.children[0]) === label)[0];
      return parent && all(parent, (item) => item.type === "input" || item.type === "select")[0];
    },
  };
}
async function fire(target, action, value) {
  assert.ok(target, "expected an interactive control");
  const handler = target.props[action];
  assert.equal(typeof handler, "function", `${target.type} exposes ${action}`);
  handler({ target: typeof value === "boolean" ? { checked: value } : { value: String(value ?? "") } });
  await nextTick();
}
const checks = [];
async function check(name, run) { await run(); checks.push(name); console.log(`PASS ${name}`); }

await check("自动匝数未解算时不猜排层", async () => {
  const test = mount({ windings: [], spec: { topology: "FLYBACK", Np: 0, Ns: 0,
    n_strand_p: 40, n_strand_s: 30 } });
  assert.match(text(test.root), /自动匝数未算出前不生成排层/);
  assert.ok(test.button("评估 / 刷新截面").props.disabled);
  assert.ok(test.button("从已评估自动方案生成").props.disabled);
  assert.match(text(test.root), /待计算/);
  test.app.unmount();
});
await check("窗口mm输入转换SI且保留电气参数", async () => {
  const test = mount(); const before = clone(test.props.spec);
  await fire(test.input("骨架窗口净宽"), "onChange", 6.5);
  assert.equal(test.props.spec.winding_config.window_width, 0.0065);
  for (const [key, value] of Object.entries(before)) assert.deepEqual(test.props.spec[key], value);
  test.app.unmount();
});
await check("并绕束数分配股数且不增加铜量", async () => {
  const test = mount();
  await fire(test.fieldInput("每匝并绕束数"), "onChange", 2);
  assert.match(text(test.root), /20 股 \/ 束/);
  assert.equal(test.props.spec.n_strand_p, 40);
  await fire(test.fieldInput("每匝并绕束数"), "onChange", 3);
  assert.match(text(test.root), /P 并绕束数必须整除每匝总股数 40/);
  test.app.unmount();
});
await check("铜线不压扁，利兹线默认1.5", async () => {
  const test = mount();
  assert.equal(test.fieldInput("利兹线压扁宽度倍数").props.value, 1.5);
  await fire(test.fieldInput("线材类型"), "onChange", "solid");
  assert.ok(test.fieldInput("利兹线压扁宽度倍数").props.disabled);
  assert.match(text(test.root), /实际倍数固定为 1/);
  await fire(test.fieldInput("线材类型"), "onChange", "litz");
  assert.equal(test.fieldInput("利兹线压扁宽度倍数").props.disabled, false);
  test.app.unmount();
});
await check("实测外径按mm写入，窗口/束设置仅几何配置", async () => {
  const test = mount();
  await fire(test.fieldInput("整束未压扁外径（优先实测）"), "onChange", 0.82);
  assert.equal(test.props.spec.winding_config.overrides.P.bundle_diameter, 0.00082);
  await fire(test.button("评估 / 刷新截面"), "onClick");
  assert.equal(test.emitted.at(-1)[0], "preview");
  assert.equal(test.emitted.at(-1)[1].overrides.P.bundle_diameter, 0.00082);
  test.app.unmount();
});
await check("从骨架向外调整绕组顺序", async () => {
  const test = mount();
  await fire(test.button("所选绕组下移"), "onClick");
  assert.deepEqual(test.props.spec.winding_config.order, ["OUT1", "P"]);
  test.app.unmount();
});
await check("手动层新增、拆分和移动保持匝数", async () => {
  const test = mount();
  const toggle = all(test.root, (item) => item.type === "input" && item.props.type === "checkbox")[0];
  await fire(toggle, "onChange", true);
  await fire(test.button("添加层"), "onClick");
  await fire(test.input("第 1 层匝数"), "onChange", 6);
  await fire(test.button("拆分所选层"), "onClick");
  assert.deepEqual(test.props.spec.winding_config.layer_plan.map((row) => row.turns), [3, 3]);
  await fire(test.button("添加层"), "onClick");
  const select = all(test.root, (item) => item.type === "select" && item.props["aria-label"] === "第 3 层绕组")[0];
  await fire(select, "onChange", "OUT1");
  await fire(test.input("第 3 层匝数"), "onChange", 12);
  await fire(test.button("所选层上移"), "onClick");
  assert.deepEqual(test.props.spec.winding_config.layer_plan.map((row) => row.winding_id), ["P", "OUT1", "P"]);
  assert.deepEqual(test.props.spec.winding_config.layer_plan.map((row) => row.turns), [3, 12, 3]);
  assert.match(text(test.root), /实体层：1、3/);
  assert.match(text(test.root), /已分配 6 \/ 6 匝/);
  assert.match(text(test.root), /已分配 12 \/ 12 匝/);
  assert.doesNotMatch(text(test.root), /需完整且不重复分配/);
  test.app.unmount();
});
await check("容量与自动方案只取匹配配置的后端结果", async () => {
  const test = mount();
  await fire(test.input("骨架窗口净宽"), "onChange", 8);
  await fire(test.input("骨架窗口净高"), "onChange", 5);
  test.props.assessment = { config: clone(test.props.spec.winding_config), configured: true,
    fits: true, required_height: 0.003, height_margin: 0.002, total_layer_count: 2,
    windings: actual.map((row) => ({ ...row, capacity: 17, turns_per_layer: 17,
      bundle_width: 0.0005, bundle_height: 0.0003, layers: 1 })), warnings: [] };
  test.props.automaticPlan = [{ winding_id: "P", turns: 6, winding_style: "dense_left" },
    { winding_id: "OUT1", turns: 12, winding_style: "dense_right" }];
  await nextTick();
  assert.equal(test.button("从已评估自动方案生成").props.disabled, false);
  assert.match(text(test.root), /当前几何预评估：窗口可容纳/);
  await fire(test.button("从已评估自动方案生成"), "onClick");
  assert.deepEqual(clone(test.props.spec.winding_config.layer_plan), clone(test.props.automaticPlan));
  assert.ok(test.button("从已评估自动方案生成").props.disabled);
  assert.match(text(test.root), /配置已变化，旧几何评估不再用于显示容量/);
  test.app.unmount();
});
await check("旧矩形束配置必须显式转换", async () => {
  const test = mount({ spec: { topology: "FLYBACK", n_strand_p: 40,
    winding_config: { overrides: { P: { strand_columns: 4, outer_diameter: 0.00013 } } } } });
  assert.ok(test.fieldInput("线材类型").props.disabled);
  assert.equal(test.props.spec.winding_config.overrides.P.wire_type, undefined);
  await fire(test.button("转换为等效圆 / 压扁线束"), "onClick");
  assert.equal(test.props.spec.winding_config.overrides.P.strand_columns, 0);
  assert.equal(test.props.spec.winding_config.overrides.P.outer_diameter, 0.00013);
  assert.equal(test.props.spec.winding_config.overrides.P.flatten_ratio, 1.5);
  test.app.unmount();
});
await check("手动层错误不误判窗口不够且允许自动方案修复", async () => {
  const test = mount();
  await fire(test.input("骨架窗口净宽"), "onChange", 8);
  await fire(test.input("骨架窗口净高"), "onChange", 5);
  test.props.assessment = { config: clone(test.props.spec.winding_config), configured: true,
    fits: null, status: "invalid_plan", windings: [], warnings: ["手动排层未分配完整"] };
  test.props.automaticPlan = [{ winding_id: "P", turns: 6 }, { winding_id: "OUT1", turns: 12 }];
  test.props.previewError = "手动排层未分配完整";
  await nextTick();
  assert.match(text(test.root), /当前几何方案需修正后再评估/);
  assert.doesNotMatch(text(test.root), /当前几何预评估：窗口存在溢出/);
  assert.equal(test.button("从已评估自动方案生成").props.disabled, false);
  test.app.unmount();
});
await check("手动草稿可关闭恢复，但不泄漏到另一工程", async () => {
  const test = mount();
  const toggle = () => all(test.root, (item) => item.type === "input" && item.props.type === "checkbox")[0];
  await fire(toggle(), "onChange", true);
  await fire(test.button("添加层"), "onClick");
  await fire(test.input("第 1 层匝数"), "onChange", 6);
  await fire(toggle(), "onChange", false);
  assert.equal(test.props.spec.winding_config.layer_plan.length, 0);
  await fire(toggle(), "onChange", true);
  assert.equal(test.props.spec.winding_config.layer_plan[0].turns, 6);
  await fire(test.button("删除所选层"), "onClick");
  assert.equal(test.props.spec.winding_config.layer_plan.length, 0);
  assert.equal(toggle().props.checked, true);
  test.props.spec = { ...test.props.spec, winding_config: { window_width: 0.02 } };
  await nextTick();
  assert.equal(toggle().props.checked, false);
  test.app.unmount();
});
await check("全部控件至少14px且声明几何局限", async () => {
  for (const match of source.matchAll(/font-size:\s*(\d+)px/g)) assert.ok(Number(match[1]) >= 14);
  assert.match(source, /min-height: 38px/);
  assert.match(source, /不回写电气股数、DCR、铜损、漏感或耦合系数 kij/);
});
console.log(`\n${checks.length} winding-editor checks passed.`);
