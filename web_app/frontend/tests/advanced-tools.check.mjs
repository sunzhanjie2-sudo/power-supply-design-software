/** Mount the real compiled Vue SFC with a virtual native renderer and mock HTTP.
 * No browser, network, solver, fabricated UI clone, or source-only assertions. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse, compileScript } from '@vue/compiler-sfc';
import { build } from 'esbuild';
import { createRenderer, h, nextTick, reactive } from 'vue';

const here = dirname(fileURLToPath(import.meta.url));
const filename = resolve(here, '../src/AdvancedTools.vue');
const { descriptor } = parse(readFileSync(filename, 'utf8'), { filename });
const compiled = compileScript(descriptor, { id: 'advanced-tools-check', inlineTemplate: true });
const vuePlugin = { name: 'local-vue-sfc', setup(build) {
  build.onLoad({ filter: /\.vue$/ }, ({ path }) => {
    const { descriptor } = parse(readFileSync(path, 'utf8'), { filename: path });
    return { contents: compileScript(descriptor, { id: path, inlineTemplate: true }).content, loader: 'ts', resolveDir: dirname(path) };
  });
} };
const mockApiPlugin = { name: 'mock-only-http-boundary', setup(build) {
  build.onResolve({ filter: /^\.\/api$/ }, () => ({ path: 'mock-api', namespace: 'mock-api' }));
  build.onLoad({ filter: /.*/, namespace: 'mock-api' }, () => ({ contents: `
    export const post = (...args) => globalThis.__advancedApiMock.post(...args);
    export const request = (...args) => globalThis.__advancedApiMock.request(...args);
    export const getBlob = (...args) => globalThis.__advancedApiMock.getBlob(...args);
    export const download = (...args) => globalThis.__advancedApiMock.download(...args);
  `, loader: 'js' }));
} };
const built = (await build({ stdin: { contents: compiled.content + '\nexport { frozenDesigns } from "./advancedMemory";', resolveDir: dirname(filename), sourcefile: filename + '.ts', loader: 'ts' }, bundle: true, write: false, format: 'cjs', platform: 'node', external: ['vue'], plugins: [mockApiPlugin, vuePlugin] })).outputFiles[0].text;
const module = { exports: {} };
new Function('module', 'exports', 'require', built)(module, module.exports, createRequire(import.meta.url));
const Component = module.exports.default;
const frozenDesigns = module.exports.frozenDesigns;

globalThis.Document ??= class Document {};
globalThis.ShadowRoot ??= class ShadowRoot {};
const virtualDocument = new Document();
function node(kind, text = '') {
  const target = { kind, tagName: kind.toUpperCase(), text, props: {}, children: [], parent: null, listeners: {}, value: '', defaultValue: '', checked: false, selected: false, multiple: false, type: kind === 'input' ? 'text' : kind,
    addEventListener(event, listener) { (this.listeners[event] ||= []).push(listener); },
    removeEventListener(event, listener) { this.listeners[event] = (this.listeners[event] || []).filter(value => value !== listener); },
    getRootNode() { return virtualDocument; },
    dispatchEvent(event) { for (const listener of this.listeners[event.type] || []) listener({ ...event, target: this }); },
  };
  Object.defineProperty(target, 'parentNode', { get: () => target.parent });
  Object.defineProperty(target, 'options', { get: () => target.children.flatMap(child => child.kind === 'option' ? [child] : child.kind === 'optgroup' ? child.children : []) });
  Object.defineProperty(target, 'selectedIndex', { get: () => target.options.findIndex(option => option.selected), set: index => { target.options.forEach((option, i) => { option.selected = i === index; }); } });
  return target;
}
const body = node('body');
const renderer = createRenderer({
  createElement: kind => node(kind), createText: text => node('#text', text), createComment: text => node('#comment', text),
  insert(child, parent, anchor = null) {
    if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1);
    const index = anchor ? parent.children.indexOf(anchor) : -1;
    if (index < 0) parent.children.push(child); else parent.children.splice(index, 0, child);
    child.parent = parent;
  },
  remove(child) { if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1); child.parent = null; },
  setText: (target, text) => { target.text = text; },
  setElementText: (target, text) => { target.children = []; target.text = text; },
  parentNode: target => target.parent,
  nextSibling: target => target.parent?.children[target.parent.children.indexOf(target) + 1] || null,
  patchProp(target, key, _previous, next) {
    target.props[key] = next;
    if (key === 'value') { target._value = next; target.value = String(next ?? ''); }
    else if (['checked', 'selected', 'multiple', 'type'].includes(key)) target[key] = next;
  },
  querySelector: query => query === 'body' ? body : null,
});
function text(target) { return target.kind === '#comment' ? '' : target.text + target.children.map(text).join(''); }
function all(target, filter) { return [...(filter(target) ? [target] : []), ...target.children.flatMap(child => all(child, filter))]; }
const clone = value => JSON.parse(JSON.stringify(value));
const baseSpec = { topology: 'FLYBACK', feedback_mode: 'SSR', f_sw: 250000, L: .000008, N: .5, C_out: .00033, Rds_on: .05, V_in_min: 24, V_in_max: 48, V_in: 24, V_out: 30, P_out: 40, fc_target: 3200, pm_target: 82, controller_type: 'type2', KP: 2720, fz1: 115, fz2: 1e6, fp1: 8e6, fp2: 159000 };
function snapshot(identity = 'server-snapshot-A', eta = .91) {
  return { schema: 'power-design.snapshot.v1', snapshot_id: identity, created_at: '2026-10-23', ok: true, spec: { ...baseSpec }, hardware: { transformer: { Np: 6, Ns: 12 } }, provenance: { engine: 'real-server-return' }, cases: ['Vinmin', 'Vinmax'].map(id => ({ id, V_in: id === 'Vinmin' ? 24 : 48, summary: { losses: { eta, P_total: 4.2 }, operating_point: { I_L_pk: 6.5, V_sw_max: 80, ripple_pp: .12 }, magnetics: { dT: 26 }, loop: { fc: 3200, min_pm: 72 } } })), display: [] };
}
function mockApi() {
  const api = { posts: [], requests: [], files: [], downloads: [], serial: 0, result: { feasible: true, design: { KP: 41, fz1: 100 }, achieved: { fc: 2400, min_pm: 70, closed_loop_stable: true }, spec_updates: { KP: 41, fz1: 100 }, notes: ['mock of server calculation'], has_chart: false }, snapshot: snapshot(), customPost: null,
    async post(path, payload) {
      this.posts.push({ path, payload: clone(payload) });
      if (this.customPost) return this.customPost(path, payload);
      return { id: `operation-${++this.serial}`, state: 'queued' };
    },
    async request(path) {
      this.requests.push(path);
      if (/\/jobs\/[^/]+\/result$/.test(path)) return clone(this.snapshot);
      if (path.startsWith('/operations/')) return { id: path.split('/').at(-1), state: 'succeeded', result: clone(this.result) };
      throw new Error(`Unexpected mock API call: ${path}`);
    },
    async getBlob(path) { this.files.push(path); return new Blob(['mock PNG'], { type: 'image/png' }); },
    download(blob, name) { this.downloads.push({ blob, name }); },
  };
  globalThis.__advancedApiMock = api;
  return api;
}
function mount(extra = {}) {
  const root = node('root'), emitted = [], api = mockApi();
  const props = reactive({ mode: 'loop', job: 'job-current', caseId: 'Vinmin', spec: clone(baseSpec), dirty: false, busy: false, ...extra });
  const app = renderer.createApp({ render() { return h(Component, { ...props, onApplied: value => emitted.push(clone(value)) }); } });
  app.mount(root);
  return { root, props, emitted, api, app,
    button: label => all(root, item => item.kind === 'button' && text(item).trim() === label)[0],
    field(label) {
      const parent = all(root, item => item.kind === 'label' && item.children[0] && text(item.children[0]).trim() === label)[0];
      return parent && all(parent, item => item.kind === 'input' || item.kind === 'select')[0];
    },
  };
}
async function flush() { for (let i = 0; i < 5; i++) { await nextTick(); await new Promise(resolve => setImmediate(resolve)); } }
async function fire(target, event = 'click', value) {
  assert.ok(target, 'Expected real rendered interactive control');
  if (value !== undefined) {
    if (typeof value === 'boolean') target.checked = value;
    else if (target.kind === 'select') target.selectedIndex = target.options.findIndex(option => String(option._value ?? option.value) === String(value));
    else target.value = String(value);
  }
  const e = { type: event, target, preventDefault() {}, stopPropagation() {} };
  for (const listener of target.listeners[event] || []) await listener(e);
  const handlers = target.props['on' + event[0].toUpperCase() + event.slice(1)];
  for (const handler of Array.isArray(handlers) ? handlers : handlers ? [handlers] : []) await handler(e);
  await flush();
}
const checks = [];
async function check(name, run) { await run(); checks.push(name); console.log(`PASS ${name}`); }

await check('整定提交真实case/fc/pm，候选不自动改变输入且显式应用可用', async () => {
  const t = mount({ caseId: 'Vinmax' });
  assert.equal(Number(t.field('目标穿越频率 fc').value), 3.2);
  await fire(t.field('目标穿越频率 fc'), 'input', 2.4);
  await fire(t.field('目标相位裕度 PM'), 'input', 70);
  await fire(t.field('补偿器类型'), 'change', 'type3');
  await fire(t.button('计算候选补偿参数'));
  assert.deepEqual(t.api.posts[0], { path: '/jobs/job-current/action', payload: { action: 'tune', options: { case: 'Vinmax', fc: 2400, pm: 70, controller_type: 'type3' } } });
  assert.match(text(t.root), /目标可实现/);
  assert.match(text(t.root), /闭环极点稳定/);
  assert.equal(t.props.spec.KP, 2720);
  assert.equal(t.emitted.length, 0);
  await fire(t.button('将候选参数写入输入区'));
  assert.deepEqual(t.emitted, [{ KP: 41, fz1: 100 }]);
  t.app.unmount();
});

await check('不可实现候选明确显示且不能写入', async () => {
  const t = mount();
  t.api.result = { feasible: false, design: { feasible: false }, spec_updates: {}, notes: ['相位提升不足'], has_chart: false };
  await fire(t.button('计算候选补偿参数'));
  assert.match(text(t.root), /当前目标不可实现/);
  assert.match(text(t.root), /相位提升不足/);
  assert.equal(t.button('将候选参数写入输入区'), undefined);
  assert.equal(t.emitted.length, 0);
  t.app.unmount();
});

await check('四种补偿网络发真实输入，工程单位按SI传递，失败仍显示参考图', async () => {
  const t = mount({ mode: 'compensation' });
  const expected = { opamp3: { R1: 10000, Vref: 2.5 }, gm3: { R2: 10000, R1u: 100000, gm: .002 }, tl431nf: { R1: 40000, R_LED: 1000, CTR: 1, Rpullup: 20000, Copto: 2e-9 }, tl431f: { R1: 40000, CTR: 1, Rpullup: 20000, Copto: 2e-9 } };
  for (const key of Object.keys(expected)) {
    await fire(t.field('参考网络'), 'change', key);
    t.api.result = { buildable: false, parts: {}, realized: { KP: 41, fz1: 100 }, targets: { KP: 2720, fz1: 115 }, checks: [{ name: 'fz1', target: 115, actual: 100, ok: false, note: '回代不同' }], notes: ['网络不能实现此目标'], has_chart: true, spec_updates: { __comp: { key, encoding: 'si', vars: {} } } };
    await fire(t.button('计算阻容并显示电路图'));
    const request = t.api.posts.findLast(row => row.path.endsWith('/action'));
    assert.equal(request.payload.action, 'compensate');
    assert.equal(request.payload.options.key, key);
    assert.deepEqual(request.payload.options.inputs, expected[key]);
    assert.match(text(t.root), /参考物理网络未完全实现理想目标/);
    assert.match(text(t.root), /115 Hz/);
    assert.ok(all(t.root, item => item.kind === 'img').length);
  }
  assert.equal(t.api.files.length, 4);
  await fire(t.button('保存补偿电路配置到工程'));
  assert.equal(t.emitted.at(-1).__comp.key, 'tl431f');
  t.app.unmount();
});

await check('旧配置默认v乘前缀，SI必须明确选择，切换后真实表单更新', async () => {
  const t = mount({ mode: 'compensation', spec: { ...baseSpec, __comp: { key: 'tl431f', dir: 'fwd', vars: { R1: { v: 40, u: 'k' }, CTR: { v: 1, u: '' }, Rpullup: { v: 20, u: 'k' }, Copto: { v: 2, u: 'n' } } } } });
  assert.equal(Number(t.field('上分压电阻 R1').value), 40);
  assert.equal(Number(t.field('光耦上拉电阻 Rpullup').value), 20);
  assert.equal(Number(t.field('光耦结电容 Copto').value), 2);
  t.props.spec.__comp = { key: 'tl431f', dir: 'fwd', vars: { R1: { v: 40000, u: 'k' }, CTR: { v: 1, u: '' }, Rpullup: { v: 20000, u: 'k' }, Copto: { v: 2e-9, u: 'n' } } };
  await fire(t.field('已导入补偿配置的数值解释'), 'change', 'si');
  assert.equal(Number(t.field('上分压电阻 R1').value), 40);
  assert.equal(Number(t.field('光耦上拉电阻 Rpullup').value), 20);
  assert.equal(Number(t.field('光耦结电容 Copto').value), 2);
  await fire(t.button('计算阻容并显示电路图'));
  assert.equal(t.api.posts.at(-1).payload.options.inputs.Rpullup, 20000);
  t.app.unmount();
  const tagged = mount({ mode: 'compensation', spec: { ...baseSpec, __comp: { key: 'tl431f', encoding: 'si', dir: 'fwd', vars: { Rpullup: { v: 20000, u: 'k' } } } } });
  assert.equal(Number(tagged.field('光耦上拉电阻 Rpullup').value), 20);
  tagged.app.unmount();
});

await check('扫描硬预算5–41整数，目标查找传正确尺度，超预算不提交', async () => {
  const t = mount({ mode: 'efficiency' });
  await fire(t.field('扫描点数（5–41）'), 'input', 999);
  await fire(t.button('运行参数扫描'));
  assert.equal(t.api.posts.length, 0);
  assert.match(text(t.root), /扫描点数必须为 5–41 的整数/);
  await fire(t.field('扫描点数（5–41）'), 'input', 5.5);
  await fire(t.button('运行参数扫描'));
  assert.equal(t.api.posts.length, 0);
  await fire(t.field('扫描点数（5–41）'), 'input', 41);
  await fire(t.field('计算负载比例'), 'input', 50);
  await fire(t.field('目标模型效率'), 'input', 91);
  t.api.result = { rows: [{ value: 125000, eta: .91 }], target_value: 125000, variable: 'f_sw', spec_updates: { f_sw: 125000 }, has_chart: false };
  await fire(t.button('扫描并查找目标效率'));
  assert.equal(t.api.posts[0].payload.options.points, 41);
  assert.equal(t.api.posts[0].payload.options.load_frac, .5);
  assert.equal(t.api.posts[0].payload.options.target_eta, .91);
  assert.match(text(t.root), /125 kHz/);
  t.app.unmount();
});

await check('dirty/busy禁分析与冻结，程序调用也不发送旧参数', async () => {
  const t = mount({ dirty: true });
  assert.equal(t.button('计算候选补偿参数').props.disabled, true);
  await fire(t.button('计算候选补偿参数'));
  assert.equal(t.api.posts.length, 0);
  t.props.mode = 'review'; await flush();
  assert.equal(t.button('冻结当前为 A').props.disabled, true);
  await fire(t.button('冻结当前为 A'));
  assert.equal(t.api.requests.length, 0);
  t.props.dirty = false; t.props.busy = true; await flush();
  assert.equal(t.button('运行固定硬件角点').props.disabled, true);
  t.app.unmount();
});

await check('冻结抓取真实双工况snapshot指标，保留快照并计算A/B差值', async () => {
  frozenDesigns.value = { a: null, b: null };
  const t = mount({ mode: 'review' });
  await fire(t.button('冻结当前为 A'));
  assert.deepEqual(t.api.requests, ['/jobs/job-current/result']);
  assert.equal(frozenDesigns.value.a.snapshot.snapshot_id, 'server-snapshot-A');
  assert.equal(frozenDesigns.value.a.snapshot.cases[0].summary.losses.eta, .91);
  assert.equal(frozenDesigns.value.a.snapshot.hardware.transformer.Np, 6);
  t.api.snapshot = snapshot('server-snapshot-B', .93);
  await fire(t.button('冻结当前为 B'));
  assert.match(text(t.root), /server-snapshot-A/);
  assert.match(text(t.root), /server-snapshot-B/);
  assert.match(text(t.root), /91 %/);
  assert.match(text(t.root), /93 %/);
  assert.match(text(t.root), /2 %/);
  t.props.spec.P_out = 999; t.props.dirty = true; await flush();
  assert.equal(frozenDesigns.value.a.snapshot.spec.P_out, 40);
  assert.match(text(t.root), /server-snapshot-A/);
  t.app.unmount();
  const other = mount({ mode: 'review' });
  assert.match(text(other.root), /server-snapshot-B/);
  await fire(other.button('导出对比快照 JSON'));
  const output = JSON.parse(await other.api.downloads[0].blob.text());
  assert.equal(output.a.snapshot.snapshot_id, 'server-snapshot-A');
  assert.equal(output.b.snapshot.cases[0].summary.losses.eta, .93);
  other.app.unmount();
  frozenDesigns.value = { a: null, b: null };
});

await check('迟到POST在切页后立即取消，不留下旧候选或后台计算', async () => {
  const t = mount();
  let resolvePost;
  t.api.customPost = (path) => path.endsWith('/action') ? new Promise(resolve => { resolvePost = resolve; }) : Promise.resolve({ state: 'cancelled' });
  await fire(t.button('计算候选补偿参数'));
  assert.equal(t.api.posts.length, 1);
  t.props.mode = 'efficiency'; await flush();
  resolvePost({ id: 'late-operation' }); await flush();
  assert.ok(t.api.posts.some(row => row.path === '/operations/late-operation/cancel'));
  assert.equal(t.api.requests.length, 0);
  assert.equal(t.emitted.length, 0);
  assert.doesNotMatch(text(t.root), /候选环路校验/);
  t.app.unmount();
});

await check('单位改动使在途操作失效并请求取消，原冻结数据不受影响', async () => {
  const t = mount();
  let resolveOperation;
  t.api.request = async function(path) { this.requests.push(path); return new Promise(resolve => { resolveOperation = resolve; }); };
  await fire(t.button('计算候选补偿参数'));
  assert.equal(t.api.requests.length, 1);
  t.props.dirty = true; await flush();
  assert.ok(t.api.posts.some(row => row.path === '/operations/operation-1/cancel'));
  resolveOperation({ state: 'succeeded', result: t.api.result }); await flush();
  assert.equal(t.button('将候选参数写入输入区'), undefined);
  assert.equal(t.emitted.length, 0);
  t.app.unmount();
});

console.log(`\n${checks.length} mounted advanced-tools checks passed.`);
