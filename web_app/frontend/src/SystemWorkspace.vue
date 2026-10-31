<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from "vue";
import App from "./App.vue";
import LdoWorkspace from "./LdoWorkspace.vue";
import { request, post, setToken, download, getBlob } from "./api";
import { topologyNames, type Spec, type Bootstrap } from "./types";
import { FONT_SIZES, normalizeFontSize } from "./ui-font";
import "../../../shared/power_architecture.js";
import "./system-workspace.css";

const graph = (globalThis as any).PCSAuxGraph;
const KEY = "power-system-workspace.v1",
  SCHEMA = "power.system-network/2";
const collections: Record<string, string> = {
  bus: "sources",
  unit: "units",
  junction: "junctions",
  load: "loads",
};
const nodes = () =>
  Object.entries(collections).flatMap(([kind, key]) =>
    (project.value?.[key] || []).map((n: Spec) => ({ ...n, kind })),
  );
const clone = (x: any) => JSON.parse(JSON.stringify(x));
const project = ref<Spec | null>(null),
  meta = ref<Bootstrap | null>(null),
  view = ref("architecture");
const note = ref("正在准备本地系统工作区…"),
  error = ref(""),
  selected = ref<any>(null),
  draft = ref<Spec>({});
const board = ref<HTMLElement>(),
  file = ref<HTMLInputElement>(),
  calculator = ref<any>();
const review = ref<Spec>({ capacity: [], interfaces: [] }),
  linking = ref<any>(null),
  removal = ref<any>(null);
const report = ref<Spec | null>(null),
  reportBusy = ref(false);
const newInput = ref(""),
  scenarioIndex = ref(0),
  unitWarning = ref("");
const zoom = ref(1);
const studioFont = ref(
  normalizeFontSize(localStorage.getItem("power-system-font-size")),
);
function changeStudioFont() {
  localStorage.setItem("power-system-font-size", String(studioFont.value));
}
const issues = computed(
  () =>
    review.value.capacity.filter((r: Spec) => !r.ok).length +
    review.value.interfaces.filter(
      (r: Spec) => r.enabled !== false && (!r.ok || r.unavailable),
    ).length,
);
let editor: any,
  alive = true,
  validationSequence = 0,
  reportTimer: ReturnType<typeof setTimeout> | undefined;
const current = computed(() =>
  project.value?.units.find((u: Spec) => u.id === project.value?.activeUnit),
);
const ports = (u: Spec) =>
  u.rails?.length
    ? u.rails
    : u.spec.outputs?.length
      ? u.spec.outputs
      : [{ V_out: u.spec.V_out, P_out: u.spec.P_out }];
const total = computed(
  () =>
    project.value?.sources.reduce((n: number, b: Spec) => n + b.capacity, 0) ||
    0,
);
const chosen = computed(
  () =>
    selected.value &&
    project.value?.[collections[selected.value.kind]]?.find(
      (n: Spec) => n.id === selected.value.id,
    ),
);
const chosenEdge = computed(
  () =>
    selected.value?.kind === "edge" &&
    project.value?.connections.find((e: Spec) => e.id === selected.value.id),
);
const draftDirty = computed(
  () =>
    !!(chosen.value || chosenEdge.value) &&
    JSON.stringify(draft.value) !==
      JSON.stringify(chosenEdge.value || chosen.value),
);
const incoming = computed(
  () =>
    project.value?.connections.filter(
      (e: Spec) => e.target === chosen.value?.id,
    ) || [],
);
const activeScenario = computed(
  () => review.value.cases?.[scenarioIndex.value],
);
const inputChoices = computed(() => {
  if (!project.value) return [];
  const all: any[] = [];
  for (const b of project.value.sources)
    all.push({
      label: b.id + " · DC",
      source: { kind: "bus", id: b.id, output: 1 },
    });
  for (const u of project.value.units)
    if (u.id !== selected.value?.id)
      ports(u).forEach((r: Spec, i: number) =>
        all.push({
          label: `${u.id} · OUT${i + 1} · ${r.V_out.toPrecision(4)}V`,
          source: { kind: "unit", id: u.id, output: i + 1 },
        }),
      );
  for (const j of project.value.junctions)
    if (j.id !== selected.value?.id)
      all.push({
        label: j.id + " · OR BUS",
        source: { kind: "junction", id: j.id, output: 1 },
      });
  return all;
});
function persist() {
  try {
    localStorage.setItem(KEY, JSON.stringify(project.value));
  } catch {
    error.value = "自动恢复空间不足，请保存系统工程 JSON。";
  }
}
function select(s: any) {
  if (JSON.stringify(s) === JSON.stringify(selected.value)) return;
  selected.value = s;
  draft.value = clone(chosenEdge.value || chosen.value || {});
  newInput.value = "";
}
async function validate() {
  if (!project.value) return;
  const generation = ++validationSequence,
    snapshot = clone(project.value);
  const data = await post("/workspace/validate", { project: snapshot });
  if (!alive || generation !== validationSequence) return;
  data.project.layout = clone(project.value.layout || { nodes: {} });
  project.value = data.project;
  review.value = data.checks;
  persist();
}
async function render() {
  editor?.destroy();
  editor = null;
  await nextTick();
  if (!alive || view.value !== "architecture" || !board.value || !project.value)
    return;
  graph.saveLayout(project.value, ports);
  editor = graph.mount(board.value, {
    project: project.value,
    rails: ports,
    names: topologyNames,
    describe: (d: Spec) =>
      d.spec?.topology === "LDO"
        ? `LDO · ${d.spec.V_out}V / ${(d.spec.I_out_max * 1000).toPrecision(3)}mA`
        : null,
    badge: (d: Spec) => {
      const r = review.value.ldo?.find((r: Spec) => r.unit === d.id);
      return r
        ? `${r.max_loss?.toPrecision(3) ?? "—"}W · ${r.dropout_ok && r.thermal_ok ? "静态初查" : "需核对"}`
        : "";
    },
    onOpen: openUnit,
    onSelect: select,
    onDelete: remove,
    onError: (s: string) => (error.value = s),
    onConnect: connect,
    onDisconnect: disconnect,
    onConnection: (s: any) => (linking.value = s),
    onMove: (key: string, position: Spec) => {
      project.value!.layout.nodes[key] = position;
      persist();
    },
    onDiodeMove: (id: string, position: Spec) => {
      project.value!.layout.diodes ||= {};
      project.value!.layout.diodes[id] = position;
      persist();
      note.value = "二极管位置已保存；连接关系与计算参数保持当前配置。";
    },
  });
  applyScale();
}
function applyScale() {
  const svg = board.value?.querySelector("svg");
  if (svg) (svg.style as any).zoom = String(zoom.value);
}
function setZoom(value: number, anchor?: { x: number; y: number }) {
  if (!board.value) return;
  const box = board.value,
    old = zoom.value,
    x = anchor?.x ?? box.clientWidth / 2,
    y = anchor?.y ?? box.clientHeight / 2;
  const wx = (box.scrollLeft + x) / old,
    wy = (box.scrollTop + y) / old;
  zoom.value = Math.max(0.35, Math.min(2.2, value));
  applyScale();
  box.scrollLeft = wx * zoom.value - x;
  box.scrollTop = wy * zoom.value - y;
}
function fitCanvas() {
  const svg = board.value?.querySelector("svg");
  if (!svg || !board.value) return;
  const size = svg.viewBox.baseVal;
  zoom.value = Math.max(
    0.35,
    Math.min(
      1.1,
      (board.value.clientWidth - 30) / size.width,
      (board.value.clientHeight - 30) / size.height,
    ),
  );
  applyScale();
  board.value.scrollLeft = 0;
  board.value.scrollTop = 0;
}
function canvasWheel(e: WheelEvent) {
  if (e.ctrlKey) {
    e.preventDefault();
    const b = board.value!.getBoundingClientRect();
    setZoom(zoom.value * (e.deltaY < 0 ? 1.12 : 1 / 1.12), {
      x: e.clientX - b.left,
      y: e.clientY - b.top,
    });
  }
}
async function resetDiode() {
  if (chosenEdge.value) {
    delete project.value!.layout.diodes?.[chosenEdge.value.id];
    persist();
    await render();
    note.value = "二极管已恢复自动布置。";
  }
}
async function refresh(message = "架构已更新。") {
  try {
    await validate();
    note.value = message;
    error.value = "";
    await render();
  } catch (e: any) {
    error.value = e.message;
  }
}
function nextId(prefix: string) {
  let n = 1;
  const ids = new Set(
    [...nodes(), ...project.value!.connections].map((u: Spec) => u.id),
  );
  while (ids.has(`${prefix}-${String(n).padStart(2, "0")}`)) n++;
  return `${prefix}-${String(n).padStart(2, "0")}`;
}
function fresh(spec: Spec) {
  return {
    schema_version: SCHEMA,
    title: "开关电源系统设计",
    revision: "A",
    sources: [
      {
        id: "BUS-01",
        name: "系统输入源",
        min: spec.V_in_min ?? spec.V_in,
        max: spec.V_in_max ?? spec.V_in,
        capacity: 100,
        enabled: true,
      },
    ],
    units: [{ id: "PSU-01", name: "主电源", spec: clone(spec), enabled: true }],
    loads: [],
    junctions: [],
    connections: [
      {
        id: "LINK-001",
        source: { kind: "bus", id: "BUS-01", output: 1 },
        target: "PSU-01",
        mode: "direct",
        vf: 0.3,
        enabled: true,
      },
    ],
    activeUnit: "PSU-01",
    layout: { nodes: {} },
  };
}
async function newProject() {
  project.value = fresh(meta.value!.spec);
  selected.value = null;
  removal.value = null;
  await refresh("已新建系统工程；旧工程可从之前保存的 JSON 打开。");
}
async function add(kind: string) {
  const p = project.value!;
  if (
    p[collections[kind]].length >= (["bus", "unit"].includes(kind) ? 24 : 48)
  ) {
    error.value = "此类节点已达上限。";
    return;
  }
  const id = nextId(
    (
      { bus: "BUS", unit: "PSU", load: "LOAD", junction: "OR" } as Record<
        string,
        string
      >
    )[kind],
  );
  if (kind === "bus")
    p.sources.push({
      id,
      name: "新增输入源",
      min: 20,
      max: 30,
      capacity: 100,
      enabled: true,
    });
  else if (kind === "unit")
    p.units.push({
      id,
      name: "新增电源",
      spec: clone(meta.value!.spec),
      enabled: true,
    });
  else if (kind === "load")
    p.loads.push({
      id,
      name: "自定义负载",
      power: 1,
      min: 0,
      max: 0,
      enabled: true,
    });
  else
    p.junctions.push({
      id,
      name: "二极管竞争供电母线",
      capacity: 100,
      enabled: true,
    });
  await refresh();
  select({ kind, id });
}
async function addLdo() {
  const d = await request<Spec>("/ldo/defaults");
  const id = nextId("LDO");
  if (project.value!.units.length >= 24) return;
  project.value!.units.push({
    id,
    name: "新增 LDO 线性稳压器",
    spec: clone(d.spec),
    enabled: true,
  });
  await refresh("已增加 LDO；连接上游后进入线性稳压设计。");
  select({ kind: "unit", id });
}
async function connect(id: string, source: Spec) {
  const why = graph.connectionError(project.value, id, source, ports);
  if (why) {
    error.value = why;
    return;
  }
  const ins = project.value!.connections.filter((e: Spec) => e.target === id);
  const diode =
    ins.length > 0 || project.value!.junctions.some((n: Spec) => n.id === id);
  if (ins.length) for (const e of ins) e.mode = "diode";
  project.value!.connections.push({
    id: nextId("LINK"),
    source: clone(source),
    target: id,
    mode: diode ? "diode" : "direct",
    vf: 0.3,
    enabled: true,
  });
  linking.value = null;
  newInput.value = "";
  await refresh(
    diode
      ? "已新增二极管 OR 分支；可选中连线编辑 Vf，未假定均流。"
      : "已新增供电连接。同一输出可以继续连接其他模块或负载。",
  );
}
async function disconnect(id: string) {
  project.value!.connections = project.value!.connections.filter(
    (e: Spec) => e.id !== id,
  );
  selected.value = null;
  await refresh("已断开此支路，其他供电关系与节点参数保留。");
}
async function remove(key: string) {
  removal.value = graph.removeNode(project.value, key);
  selected.value = null;
  await refresh("节点已删除，下级参数保留，可撤销删除。");
}
async function undo() {
  if (removal.value && graph.restoreNode(project.value, removal.value)) {
    removal.value = null;
    await refresh("已撤销删除。");
  }
}
async function applyNode() {
  const old = clone(project.value),
    item = chosenEdge.value || chosen.value;
  try {
    if (!item) return false;
    Object.assign(item, draft.value);
    await validate();
    draft.value = clone(chosenEdge.value || chosen.value);
    error.value = "";
    note.value = "节点信息已保存到当前工程；顶部“保存系统工程”可导出 JSON。";
    await render();
    return true;
  } catch (e: any) {
    project.value = old;
    error.value = e.message;
    return false;
  }
}
async function syncInput() {
  try {
    const data = await post(`/workspace/sync-input/${chosen.value.id}`, {
      project: project.value,
    });
    project.value = data.project;
    review.value = data.checks;
    persist();
    await render();
    note.value = "输入范围已更新，包含已评估掉电/独供情形下的二极管后电压。";
    error.value = "";
  } catch (e: any) {
    error.value = e.message;
  }
}
async function openUnit(id: string) {
  unitWarning.value = "";
  const u = project.value!.units.find((u: Spec) => u.id === id);
  if (
    u.spec.topology === "LDO" &&
    u.spec.follow_input &&
    project.value!.connections.some((e: Spec) => e.target === id && e.enabled)
  ) {
    try {
      const d = await post("/workspace/sync-input/" + id, {
        project: project.value,
      });
      project.value = d.project;
      review.value = d.checks;
    } catch (e: any) {
      unitWarning.value =
        "上游输入未能同步：" + e.message + "；请核对连线，当前保留单元保存值。";
    }
  }
  editor?.destroy();
  editor = null;
  project.value!.activeUnit = id;
  view.value = "unit";
  persist();
}
function unitState(state: Spec) {
  const u = current.value;
  if (!u || !state.spec || !Object.keys(state.spec).length) return;
  u.spec = clone(state.spec);
  if (state.preview) {
    u.rails = clone(
      state.preview.outputs?.length
        ? state.preview.outputs
        : [{ V_out: u.spec.V_out, P_out: u.spec.P_out }],
    );
  }
  project.value!.connections = project.value!.connections.filter(
    (e: Spec) =>
      !(
        e.source.kind === "unit" &&
        e.source.id === u.id &&
        e.source.output > ports(u).length
      ),
  );
  persist();
}
async function back() {
  if (calculator.value?.getSpec) {
    const spec = calculator.value.getSpec();
    if (Object.keys(spec).length) current.value.spec = spec;
  }
  if (current.value?.spec.topology === "LDO") {
    try {
      const r = await post("/ldo/calculate", { spec: current.value.spec });
      current.value.spec = r.spec;
    } catch (e: any) {
      unitWarning.value = e.message;
      return;
    }
  }
  view.value = "architecture";
  selected.value = null;
  await refresh("单元参数已回存系统工程。");
}
async function save() {
  if (draftDirty.value && !(await applyNode())) return;
  try {
    await validate();
    download(
      new Blob([JSON.stringify(project.value, null, 2)], {
        type: "application/json",
      }),
      project.value!.title + ".json",
    );
    note.value = "系统工程已保存，包含所有模块参数、连线与布局。";
  } catch (e: any) {
    error.value = e.message;
  }
}
async function importFile(e: Event) {
  const input = e.target as HTMLInputElement,
    f = input.files?.[0];
  if (!f) return;
  try {
    const raw = JSON.parse(await f.text());
    let candidate = raw;
    if (![SCHEMA, "pcs.aux-workspace/1"].includes(raw.schema_version)) {
      const source = raw.schema === "power.ldo-result/1" ? raw.spec : raw;
      const spec =
        source.topology === "LDO" || source.design_type === "ldo"
          ? (await post("/ldo/calculate", { spec: source })).spec
          : await post("/config", { spec: source });
      candidate = fresh(spec);
      candidate.title = f.name.replace(/\.json$/i, "");
    }
    const data = await post("/workspace/validate", { project: candidate });
    project.value = data.project;
    review.value = data.checks;
    selected.value = null;
    removal.value = null;
    persist();
    await render();
    note.value = "工程已导入。";
    error.value = "";
  } catch (e: any) {
    error.value = e.message;
  } finally {
    input.value = "";
  }
}
async function exportReports() {
  try {
    await validate();
    reportBusy.value = true;
    error.value = "";
    report.value = await post("/workspace/reports", { project: project.value });
    pollReport();
  } catch (e: any) {
    reportBusy.value = false;
    error.value = e.message;
  }
}
async function pollReport() {
  if (!alive || !report.value) return;
  try {
    const r = await request<Spec>(`/jobs/${report.value.id}`);
    report.value = r;
    if (["failed", "cancelled", "completed", "succeeded"].includes(r.state)) {
      reportBusy.value = false;
      if (r.state === "failed")
        throw Error(r.error?.message || r.error || "报告生成失败");
      if (["completed", "succeeded"].includes(r.state))
        download(
          await getBlob(`/pcs/reports/${r.id}`),
          project.value!.title + "报告包.zip",
        );
      return;
    }
    reportTimer = setTimeout(pollReport, 800);
  } catch (e: any) {
    error.value = e.message;
    reportBusy.value = false;
  }
}
async function cancelReport() {
  if (report.value) await post(`/jobs/${report.value.id}/cancel`, {});
}
onMounted(async () => {
  try {
    meta.value = await request<Bootstrap>("/bootstrap");
    setToken(meta.value.token);
    try {
      project.value =
        JSON.parse(localStorage.getItem(KEY) || "null") ||
        fresh(meta.value.spec);
    } catch {
      project.value = fresh(meta.value.spec);
    }
    try {
      await validate();
    } catch {
      project.value = fresh(meta.value.spec);
    }
    await refresh("先配置系统架构，再点击模块进入完整设计。");
    (globalThis as any).PowerSystemWorkspace = {
      snapshot: () => clone(project.value),
    };
  } catch (e: any) {
    error.value = e.message;
  }
});
onBeforeUnmount(() => {
  alive = false;
  editor?.destroy();
  clearTimeout(reportTimer);
  if (reportBusy.value) void cancelReport();
  delete (globalThis as any).PowerSystemWorkspace;
});
</script>

<template>
  <div class="system-shell" :style="{ '--studio-font': studioFont + 'px' }">
    <header class="system-header">
      <div class="system-brand">
        <span class="system-brand-mark">PD</span>
        <div>
          <b>开关电源设计工作台</b><small>POWER DESIGN / SYSTEM STUDIO</small>
        </div>
      </div>
      <div class="system-flow">
        <span class="active">01 架构配置</span><i>→</i><span>02 单元设计</span
        ><i>→</i><span>03 工程交付</span>
      </div>
      <span class="system-local"><i />本机计算</span>
    </header>
    <div v-if="view === 'unit' && current" class="system-unit-bar">
      <button class="button primary" @click="back">← 返回系统架构</button
      ><strong>{{ current.id }} · {{ current.name }}</strong
      ><span>退出单元时自动回存参数，报告在单元内导出</span>
    </div>
    <p v-if="view === 'unit' && unitWarning" class="system-error">
      {{ unitWarning }}
    </p>
    <LdoWorkspace
      v-if="view === 'unit' && current?.spec.topology === 'LDO'"
      ref="calculator"
      :key="current.id"
      :initial-spec="current.spec"
      :unit-name="current.name"
      :on-state="unitState"
    />
    <App
      v-else-if="view === 'unit' && current"
      ref="calculator"
      :key="current.id"
      :initial-spec="current.spec"
      :unit-name="current.name"
      :on-state="unitState"
    />
    <main v-else class="system-home">
      <div class="system-toolbar">
        <div>
          <small class="system-eyebrow">DESIGN WORKSPACE</small>
          <h1>辅源供电网络</h1>
          <p>自由布置供电架构，将每一路设计连接成完整系统。</p>
        </div>
        <div class="system-actions system-project-actions">
          <button class="button" @click="newProject" :disabled="!meta">
            新建工程</button
          ><button class="button" @click="file?.click()">
            打开工程 / 原配置</button
          ><button class="button primary" @click="save" :disabled="!project">
            保存系统工程
          </button>
        </div>
      </div>
      <input
        ref="file"
        type="file"
        accept=".json"
        hidden
        @change="importFile"
      />
      <label class="studio-font-control"
        >界面字号<select
          v-model.number="studioFont"
          aria-label="架构界面字号"
          @change="changeStudioFont"
        >
          <option v-for="n in FONT_SIZES" :key="n" :value="n">
            {{ n }} px
          </option>
        </select></label
      >
      <div v-if="project" class="system-project">
        <label
          >当前工程<input
            v-model="project.title"
            maxlength="120"
            @change="refresh()"
        /></label>
        <div>
          <b>{{ project.sources.length }}</b
          ><small>输入源</small>
        </div>
        <div>
          <b>{{ project.units.length }}</b
          ><small>电源模块</small>
        </div>
        <div>
          <b>{{ project.loads.length }}</b
          ><small>终端负载</small>
        </div>
        <div>
          <b>{{ total.toPrecision(4) }} <em>W</em></b
          ><small>输入容量</small>
        </div>
        <span class="system-health" :class="{ 'has-issues': issues }">{{
          issues ? issues + " 项需核对" : "预算与接口未超限"
        }}</span>
      </div>
      <div v-if="error" class="system-error" role="alert">{{ error }}</div>
      <p class="system-note" role="status">{{ note }}</p>
      <section v-if="project" class="system-card">
        <div class="system-canvas-toolbar system-canvas-controls">
          <div>
            <strong>架构画布</strong>
            <p>
              {{
                linking
                  ? "正在连线 · 选择目标 IN 端口，Esc 取消。"
                  : "拖动任意节点或二极管 · 从 OUT 连接 IN · 双击模块进入设计"
              }}
            </p>
          </div>
          <div class="system-actions system-palette">
            <button class="button" @click="add('bus')">增加输入源</button
            ><button class="button" @click="add('unit')">增加电源模块</button
            ><button class="button" @click="addLdo">增加 LDO</button
            ><button class="button" @click="add('junction')">
              增加 OR 汇流</button
            ><button class="button" @click="add('load')">增加负载</button
            ><button
              class="button"
              @click="
                graph.autoArrange(project, ports);
                persist();
                render();
              "
            >
              自动排列</button
            ><button class="button" :disabled="!removal" @click="undo">
              撤销删除
            </button>
          </div>
        </div>
        <div class="system-canvas-grid">
          <div class="system-board-wrap">
            <div
              ref="board"
              class="system-board"
              aria-label="可编辑系统架构"
              @wheel="canvasWheel"
            />
            <div class="system-view-tools">
              <button @click="setZoom(zoom / 1.2)" aria-label="缩小画布">
                −</button
              ><span class="system-zoom-value"
                >{{ Math.round(zoom * 100) }}%</span
              ><button @click="setZoom(zoom * 1.2)" aria-label="放大画布">
                ＋</button
              ><i /><button @click="fitCanvas">适应画布</button>
            </div>
            <div class="system-canvas-hint">
              Ctrl + 滚轮缩放 · 空白区域拖动平移
            </div>
          </div>
          <aside class="system-inspector">
            <div class="system-inspector-head">
              <b>属性检查器</b><small>PROPERTIES</small>
            </div>
            <div class="system-inspector-content">
              <template v-if="chosenEdge"
                ><span class="system-object-type">SUPPLY BRANCH</span>
                <h3>{{ chosenEdge.id }} · 供电支路</h3>
                <p>
                  {{ chosenEdge.source.id }} / OUT{{
                    chosenEdge.source.output
                  }}
                  → {{ chosenEdge.target }}
                </p>
                <label
                  >连接方式<select v-model="draft.mode">
                    <option value="direct">直连（单路输入）</option>
                    <option value="diode">二极管隔离 / OR 竞争供电</option>
                  </select></label
                ><label v-if="draft.mode === 'diode'"
                  >二极管正向压降 Vf / V<input
                    v-model.number="draft.vf"
                    type="number"
                    min="0"
                    step="0.05" /></label
                ><label
                  >支路状态<select v-model="draft.enabled">
                    <option :value="true">启用</option>
                    <option :value="false">停用 / 断路</option>
                  </select></label
                ><button
                  v-if="draft.mode === 'diode'"
                  class="button"
                  @click="resetDiode"
                >
                  重置二极管位置</button
                ><button class="button" @click="disconnect(selected.id)">
                  断开连接
                </button>
                <p>
                  抓住二极管卡片即可独立拖动。多源接入时逐支路隔离，同压不假定均流。
                </p></template
              >
              <template v-else-if="chosen"
                ><h3>{{ chosen.id }} · 节点配置</h3>
                <label>名称<input v-model="draft.name" /></label>
                <template v-if="selected.kind === 'bus'"
                  ><label
                    >最小电压 / V<input
                      v-model.number="draft.min"
                      type="number" /></label
                  ><label
                    >最大电压 / V<input
                      v-model.number="draft.max"
                      type="number" /></label
                  ><label
                    >输入容量 / W<input
                      v-model.number="draft.capacity"
                      type="number" /></label
                ></template>
                <template v-if="selected.kind === 'load'"
                  ><label
                    >负载功耗 / W<input
                      v-model.number="draft.power"
                      type="number"
                      min="0"
                      step="0.1" /></label
                  ><label
                    >允许输入下限 / V（0=不限定）<input
                      v-model.number="draft.min"
                      type="number"
                      min="0" /></label
                  ><label
                    >允许输入上限 / V（0=不限定）<input
                      v-model.number="draft.max"
                      type="number"
                      min="0" /></label
                ></template>
                <label v-if="selected.kind === 'junction'"
                  >OR 母线容量 / W<input
                    v-model.number="draft.capacity"
                    type="number"
                    min="0"
                /></label>
                <label
                  >节点状态<select
                    v-model="draft.enabled"
                    aria-label="节点状态"
                  >
                    <option :value="true">启用</option>
                    <option :value="false">停用 / 掉电</option>
                  </select></label
                >

                <template v-if="selected.kind !== 'bus'"
                  ><label
                    >新增供电关系<select
                      v-model="newInput"
                      @change="
                        newInput && connect(chosen.id, JSON.parse(newInput))
                      "
                    >
                      <option value="">选择上游输出，增加一条连接</option>
                      <option
                        v-for="c in inputChoices"
                        :key="c.label"
                        :value="JSON.stringify(c.source)"
                      >
                        {{ c.label }}
                      </option>
                    </select></label
                  >
                  <p v-if="!incoming.length">输入尚未连接</p>
                  <div v-for="e in incoming" :key="e.id" class="system-branch">
                    <button
                      class="button"
                      @click="select({ kind: 'edge', id: e.id })"
                    >
                      {{ e.source.id }} ·
                      {{ e.mode === "diode" ? "D " + e.vf + "V" : "直连" }}
                      {{ e.enabled ? "" : "[停用]" }} · 编辑
                    </button>
                  </div></template
                >
                <template v-if="selected.kind === 'unit'"
                  ><button class="button" @click="syncInput">
                    沿用上游电压</button
                  ><button class="button primary" @click="openUnit(chosen.id)">
                    进入完整设计 →
                  </button></template
                >
                <button
                  class="button"
                  @click="remove(selected.kind + ':' + selected.id)"
                >
                  删除节点
                </button> </template
              ><template v-else
                ><h3>编辑实际辅源架构</h3>
                <p>一对多：从同一 OUT 继续连到模块或负载。</p>
                <p>
                  多对一：继续连到同一 IN，自动增加二极管 OR
                  支路。也可先汇流，再向多路分配。
                </p>
                <p>
                  节点、负载均可命名；点连线设置 Vf，停用输入源可检查备用供电。
                </p></template
              >
            </div>
            <div
              v-if="chosen || chosenEdge"
              class="system-inspector-save"
              @keydown.ctrl.enter.prevent="applyNode"
            >
              <button
                class="button primary"
                :disabled="!draftDirty"
                @click="applyNode"
              >
                {{ chosenEdge ? "保存支路修改" : "保存节点修改" }}
              </button>
              <p role="status" :class="{ pending: draftDirty }">
                {{
                  draftDirty
                    ? "有未保存修改 · 点击上方蓝色按钮"
                    : "已保存到当前工程；顶部“保存系统工程”可导出 JSON。"
                }}
              </p>
            </div>
          </aside>
        </div>
      </section>
      <section v-if="project" class="system-card">
        <div class="system-canvas-toolbar">
          <div>
            <strong>系统检查与报告</strong>
            <p>
              开关模块按额定输出/预设效率预算，LDO 按实际输入电压、负载和 Iq
              预算；负载占用输出容量，不重复叠加到模块输入。OR
              备用支路分别评估独供能力。
            </p>
          </div>
          <button
            class="button primary"
            :disabled="reportBusy"
            @click="exportReports"
          >
            生成系统报告包</button
          ><button v-if="reportBusy" class="button" @click="cancelReport">
            取消
          </button>
        </div>
        <p v-if="reportBusy">
          {{
            report?.message || "正在按各单元重新计算并生成 Word / Excel 报告…"
          }}
        </p>
        <details class="system-review">
          <summary>
            展开功率预算、电压匹配与供电工况 <span>{{ issues }} 项需核对</span>
          </summary>
          <p class="system-note">{{ review.method }}</p>
          <p v-if="review.coverage_complete === false" class="system-error">
            分支组合过多，检查覆盖不完整，预算不可判为通过。
          </p>
          <div class="system-check-grid">
            <div>
              <h3>正常与备用供电预算</h3>
              <table>
                <thead>
                  <tr>
                    <th>端口</th>
                    <th>正常 / 最坏 / 容量 W</th>
                    <th>检查</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="r in review.capacity"
                    :key="r.port"
                    :title="r.worst_case"
                  >
                    <td>{{ r.port }}</td>
                    <td>
                      {{ r.normal.toPrecision(4) }} /
                      {{ r.allocated.toPrecision(4) }} /
                      {{ r.capacity.toPrecision(4) }}
                    </td>
                    <td :class="r.ok ? 'system-pass' : 'system-warn'">
                      {{ r.ok ? "未超容量" : "待检查" }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div>
              <h3>模块与负载电压匹配</h3>
              <table>
                <thead>
                  <tr>
                    <th>节点</th>
                    <th>可用电压 / V</th>
                    <th>允许范围 / V</th>
                    <th>状态</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="r in review.interfaces" :key="r.unit">
                    <td>{{ r.name || r.unit }}</td>
                    <td>
                      {{
                        r.source_min === null
                          ? "无供电"
                          : r.source_min.toPrecision(4) +
                            "–" +
                            r.source_max.toPrecision(4)
                      }}
                    </td>
                    <td>{{ r.design_min }}–{{ r.design_max || "不限" }}</td>
                    <td
                      :class="
                        r.ok && !r.unavailable ? 'system-pass' : 'system-warn'
                      "
                    >
                      {{
                        r.ok
                          ? r.unavailable
                            ? "部分故障失电"
                            : "已覆盖"
                          : "待检查"
                      }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div v-if="review.ldo?.length" class="system-scenarios">
            <h3>LDO 压差与热设计</h3>
            <p v-for="r in review.ldo" :key="r.unit">
              {{ r.unit }} · 最大芯片损耗
              {{ r.max_loss?.toPrecision(4) ?? "未定义" }} W · 估算结温
              {{ r.max_Tj?.toPrecision(4) ?? "未定义" }} °C ·
              {{
                r.dropout_ok ? "压差满足" : "存在压差不足"
              }}；额定资料及热阻证据见单元检查。
            </p>
          </div>
          <div v-if="review.cases?.length" class="system-scenarios">
            <h3>查看供电工况与竞争结果</h3>
            <select v-model.number="scenarioIndex" aria-label="供电工况">
              <option v-for="(c, i) in review.cases" :key="i" :value="i">
                {{ i + 1 }} · {{ c.name }}
              </option>
            </select>
            <p v-if="activeScenario">
              失电节点：{{
                activeScenario.unavailable.join("、") || "无"
              }}；导通支路：{{
                Object.entries(activeScenario.routes)
                  .map(([id, e]) => id + " ← " + e)
                  .join("；") || "无"
              }}
            </p>
          </div>
        </details>
      </section>
    </main>
  </div>
</template>
