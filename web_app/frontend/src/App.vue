<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, provide } from "vue";
import Icon from "./Icon.vue";
import FieldInput from "./FieldInput.vue";
import OutputEditor from "./OutputEditor.vue";
import CurveImporter from "./CurveImporter.vue";
import ChartPanel from "./ChartPanel.vue";
import CoreEditor from "./CoreEditor.vue";
import ResultTable from "./ResultTable.vue";
import CapacitorTable from "./CapacitorTable.vue";
import CapacitorBank from "./CapacitorBank.vue";
import AdvancedTools from "./AdvancedTools.vue";
import WindingEditor from "./WindingEditor.vue";
import CurvePlot from "./CurvePlot.vue";
import ComponentManager from "./ComponentManager.vue";
import ControllerLogic from "./ControllerLogic.vue";
import ParasiticEditor from "./ParasiticEditor.vue";
import { request, post, getBlob, download, setToken } from "./api";
import { FONT_SIZES, normalizeFontSize } from "./ui-font";
import type {
  Bootstrap,
  Spec,
  Preview,
  CurveTarget,
  Snapshot,
  Job,
  Parameter,
  Check,
} from "./types";
import { fmt, topologyNames } from "./types";

const integration = defineProps<{
  embedded?: boolean;
  initialSpec?: Spec;
  unitName?: string;
  portal?: HTMLElement;
  documentUrls?: Record<string, string>;
  onState?: (state: Spec) => void;
}>();
provide('power-modal-target', integration.portal || 'body');
provide('power-native', computed(() => !!meta.value?.native));
function notifyHost() {
  if (!meta.value || !integration.onState) return;
  integration.onState({spec: clone(spec.value), preview: preview.value && previewFingerprint === JSON.stringify(spec.value) ? clone(preview.value) : null,
    dirty: dirty.value, busy: busy.value, result: result.value ? clone(result.value) : null});
}
defineExpose({calculate, saveConfig, getSpec: () => clone(spec.value)});

const meta = ref<Bootstrap | null>(null),
  spec = ref<Spec>({}),
  preview = ref<Preview | null>(null);
const spiceFocus = ref('frequency_hz');
const spiceOptions = computed(()=>(meta.value?.spice_options || []).filter(item=>item.topologies.includes(spec.value.topology) &&
  !(Object.keys(spec.value.parasitic_config || {}).length && ['diode_cj_pf','qr_cds_pf'].includes(item.key))));
const result = ref<Snapshot | null>(null),
  job = ref<Job | null>(null),
  busy = ref(false),
  exporting = ref(""),
  dirty = ref(false);
const message = ref("正在连接本地服务…"),
  error = ref(""),
  previewError = ref(""),
  search = ref(""),
  page = ref("overview"),
  activeCase = ref("Vinmin");
const showSidebar = ref(false),
  curveTarget = ref<CurveTarget | null>(null),
  showJson = ref(false),
  jsonDraft = ref(""),
  jsonError = ref("");
const example = ref(""),
  projectTitle = ref("40W CCM 反激设计"),
  crossRegulation = ref(false);
const mosRealTime = ref(false),
  fontSize = ref(16),
  curveViewer = ref<CurveTarget | null>(null);
const reuseCurveTarget = ref("");
const windingPreview = ref<Spec | null>(null),
  windingBusy = ref(false),
  windingError = ref(""),
  windingImage = ref("");
const fileInput = ref<HTMLInputElement>(),
  helpDocuments = ref<HTMLDetailsElement>(),
  isolationDraft = ref<Spec | null>(null),
  revision = ref(0);
let timer: ReturnType<typeof setTimeout> | undefined,
  previewTimer: ReturnType<typeof setTimeout> | undefined,
  previewRevision = 0,
  previewFingerprint = '',
  disposed = false;
watch([spec, preview, result, dirty, busy], notifyHost, {deep: true});
const allNav = [
  { id: "overview", name: "设计总览", icon: "grid" },
  { id: "topology", name: "拓扑", icon: "layers" },
  { id: "bom", name: "关键器件与降额", icon: "chip" },
  { id: "power", name: "功率级", icon: "wave" },
  { id: "devices", name: "器件", icon: "chip" },
  { id: "capacitors", name: "电容纹波", icon: "chart" },
  { id: "magnetics", name: "磁件", icon: "layers" },
  { id: "loop", name: "环路", icon: "wave" },
  { id: "efficiency", name: "效率与优化", icon: "chart" },
  { id: "clamp", name: "钳位与吸收", icon: "bolt" },
  { id: "compensation", name: "补偿参考电路", icon: "chip" },
  { id: "psr", name: "MP6005 核算", icon: "chip" },
  { id: "review", name: "工程评审与对比", icon: "shield" },
  { id: "reports", name: "报告与检查", icon: "file" },
];
const nav = computed(() =>
  allNav.filter((item) =>
    item.id === "clamp"
      ? ["FLYBACK", "QR-FLYBACK", "ACF-FORWARD"].includes(spec.value.topology)
      : item.id === "psr"
        ? spec.value.feedback_mode === "PSR-MP6005"
        : item.id === "compensation"
          ? spec.value.feedback_mode !== "PSR-MP6005"
          : true,
  ),
);
const pageName = computed(
  () => nav.value.find((n) => n.id === page.value)?.name || "设计总览",
);
const selected = computed(
  () => result.value?.cases.find((c) => c.id === activeCase.value) || null,
);
const display = computed(
  () => result.value?.display.find((c) => c.id === activeCase.value) || null,
);
const summary = computed(() =>
  selected.value?.summary?.ok ? selected.value.summary : null,
);
const op = computed(() => summary.value?.operating_point || {});
const checks = computed<Check[]>(() => selected.value?.checks || []);
const needsReview = computed(() =>
  checks.value.filter((c) => c.state === "review" || c.state === "undefined"),
);
const isolated = computed(() =>
  ["FLYBACK", "QR-FLYBACK", "ACF-FORWARD"].includes(spec.value.topology),
);
const resultIsolated = computed(() =>
  ["FLYBACK", "QR-FLYBACK", "ACF-FORWARD"].includes(
    result.value?.spec.topology,
  ),
);
const multi = computed(() => Boolean(spec.value.outputs?.length));
const feedback = computed(() => Number(spec.value.feedback_output) || 1);
const groups = computed(() => {
  const rows = meta.value?.parameters || [],
    order = [
      "spec",
      "stage",
      "device",
      "capacitors",
      "drive",
      "sense",
      "mag",
      "psr",
      "ctrl",
      "options",
    ];
  const excluded = new Set([
    'input_capacitors','output_capacitors','Cin1','Rcin1','ESLin1','Cin2','Rcin2','ESLin2','cin2_enable',
    'C_out','Rc','ESL','C_out2','Rc2','ESL2','cout2_enable',
    "component_management",
    "spice_config",
    "parasitic_config",
    "V_in",
    "P_out_min",
    "Vgp_on",
    "Vgp_off",
    "Qgs",
    "gfs",
    "mos_curve_vds",
    "load_frac",
    "sweep_n",
    "sweep_min",
    "sweep_max",
    "target_eta",
    "fc_target",
    "pm_target",
    "feedback_output",
  ]);
  if (multi.value)
    [
      "V_out",
      "P_out",
      "Ns",
      "d_wire_s",
      "n_strand_s",
      "C_out",
      "Rc",
      "ESL",
      "C_out2",
      "Rc2",
      "ESL2",
      "cout2_enable",
      "d_out_enable",
      "Vf_diode",
      "Qrr",
      "Vf_dout",
      "ripple_target",
    ].forEach((k) => excluded.add(k));
  return order
    .map((category) => ({
      category,
      title: meta.value?.sections[category] || "其它计算与评审参数",
      rows: rows.filter((row) => {
        if (
          row.category !== category ||
          !["number", "boolean"].includes(row.type) ||
          row.deprecated ||
          excluded.has(row.name)
        )
          return false;
        if (
          row.topologies.length &&
          !row.topologies.includes(spec.value.topology)
        )
          return false;
        if (
          row.name.startsWith("psr_") &&
          spec.value.feedback_mode !== "PSR-MP6005"
        )
          return false;
        if (
          spec.value.feedback_mode === "PSR-MP6005" &&
          ["KP", "fz1", "fz2", "fp1", "fp2"].includes(row.name)
        )
          return false;
        if (
          ["A_sense", "ma_slope"].includes(row.name) &&
          spec.value.control_mode !== "Peak Current Mode"
        )
          return false;
        if (
          ["K", "Kc", "dC"].includes(row.name) &&
          !["FLYBACK", "QR-FLYBACK"].includes(spec.value.topology)
        )
          return false;
        if (
          row.name === "L" &&
          multi.value &&
          spec.value.topology === "ACF-FORWARD"
        )
          return false;
        if (row.enabled_by && !spec.value[row.enabled_by]) return false;
        if (row.name === "K" && spec.value.coupling_config?.enabled)
          return false;
        return (
          !search.value ||
          `${row.label} ${row.name} ${row.symbol}`
            .toLowerCase()
            .includes(search.value.toLowerCase())
        );
      }),
    }))
    .filter((group) => group.rows.length || group.category==='capacitors');
});
const metadataFields = computed(() =>
  Object.fromEntries((meta.value?.parameters || []).map((p) => [p.name, p])),
);
const chartJob = computed(() => job.value?.id || "");
const comparisonKeys = [
  ["占空比", "D", ""],
  ["原边/电感峰值", "I_L_pk", "A"],
  ["MOS 电压应力", "V_sw_max", "V"],
  ["整流反压（不含尖峰）", "V_d_max", "V"],
];
const statusLabel = computed(() =>
  busy.value
    ? "正在计算"
    : dirty.value
      ? "参数已更改"
      : result.value
        ? "快照已就绪"
        : "等待计算",
);
function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}
function touch() {
  if (exportOperation.value) void post(`/operations/${exportOperation.value}/cancel`, {}).catch(() => {});
  if (windingImage.value) URL.revokeObjectURL(windingImage.value);
  windingImage.value = "";
  windingPreview.value = null;
  revision.value++;
  dirty.value = true;
  error.value = "";
  if (busy.value && job.value) {
    void post(`/jobs/${job.value.id}/cancel`, {}).catch(() => {});
    busy.value = false;
    clearTimeout(timer);
    message.value = "参数已更改，旧计算已取消；请重新计算。";
  } else message.value = "参数已更改，右侧结果需重新计算。";
  queuePreview();
}
function setValue(key: string, value: any) {
  spec.value[key] = value;
  touch();
}
function replaceSpec(value: Spec) {
  spec.value = value;
  touch();
}
function applyUpdates(updates: Spec) {
  replaceSpec({ ...clone(spec.value), ...clone(updates) });
  message.value = "参数已应用；请重新计算核对双输入端点及报告。";
}
function changeFont(value: number) {
  value=normalizeFontSize(value);
  fontSize.value = value;
  if (!integration.embedded) document.documentElement.style.setProperty("--ui-font", value + "px");
  try {
    localStorage.setItem("power-web-font-size", String(value));
  } catch {}
}
async function openManual() {
  if (helpDocuments.value) helpDocuments.value.open = false;
  if (meta.value?.native && integration.documentUrls?.manual) {
    const link = document.createElement('a'); link.href = integration.documentUrls.manual; link.download = '计算方法与公式说明.docx'; link.click(); return;
  }
  try {
    download(await getBlob("/manual"), "计算方法与公式说明.docx");
  } catch (e: any) {
    error.value = e.message;
  }
}
async function openTutorial() {
  if (helpDocuments.value) helpDocuments.value.open = false;
  if (meta.value?.native && integration.documentUrls?.tutorial) {
    const link = document.createElement('a'); link.href = integration.documentUrls.tutorial; link.download = '多路反激电源设计入门教程.docx'; link.click(); return;
  }
  try {
    download(await getBlob("/tutorial"), "多路反激电源设计入门教程.docx");
  } catch (e: any) {
    error.value = e.message;
  }
}
function densityHint(key: string) {
  const tr = display.value?.magnetics?.find(
    (d: Spec) => d.kind === "transformer",
  );
  let j: number | undefined;
  if (["d_wire_p", "n_strand_p"].includes(key)) j = tr?.J_actual_p;
  if (["d_wire_s", "n_strand_s"].includes(key)) j = tr?.J_actual_s;
  return j === undefined
    ? ""
    : (dirty.value ? "上次计算 " : "") + "J = " + fmt(j / 1e6, "A/mm²");
}
function storedCurve(target: CurveTarget | null) {
  if (!target) return {};
  return target.target === "Q1:transfer"
    ? spec.value.mos_miller_curve
    : target.target === "Q1:charge"
      ? spec.value.mos_charge_curve
      : spec.value.diode_curves?.[target.target] || {};
}
const viewingCurve = computed(() => {
  const data = storedCurve(curveViewer.value);
  return (
    data?.curves || [
      {
        name: data?.name || curveViewer.value?.ref,
        points: data?.points || [],
      },
    ]
  );
});
function reuseCurve() {
  if (!curveViewer.value || !reuseCurveTarget.value) return;
  const copy = clone(storedCurve(curveViewer.value));
  spec.value.diode_curves ||= {};
  spec.value.diode_curves[reuseCurveTarget.value] = copy;
  setSource(reuseCurveTarget.value, "curve");
  curveViewer.value = null;
  reuseCurveTarget.value = "";
}
async function evaluateWinding(config: Spec) {
  if (!job.value || !result.value || busy.value || windingBusy.value) return;
  const jobId = job.value.id;
  const generation = revision.value;
  const caseId = activeCase.value;
  const current = () =>
    !disposed &&
    job.value?.id === jobId &&
    revision.value === generation &&
    activeCase.value === caseId;
  windingBusy.value = true;
  windingError.value = "";
  try {
    const command = await post(`/jobs/${jobId}/action`, {
      action: "winding_preview",
      options: { case: caseId, config },
    });
    for (let i = 0; i < 200; i++) {
      const op = await request<any>(`/operations/${command.id}`);
      if (!current()) return;
      if (op.state === "succeeded") {
        windingPreview.value = op.result;
        if (op.result?.has_chart) {
          const blob = await getBlob(`/files/${command.id}`);
          if (!current()) return;
          if (windingImage.value) URL.revokeObjectURL(windingImage.value);
          windingImage.value = URL.createObjectURL(blob);
        }
        return;
      }
      if (["failed", "cancelled"].includes(op.state))
        throw Error(op.error?.message || "几何预览未完成");
      await new Promise((r) => setTimeout(r, 150));
    }
    throw Error("几何预览等待超时");
  } catch (e: any) {
    if (current()) windingError.value = e.message;
  } finally {
    windingBusy.value = false;
  }
}
watch(nav, (items) => {
  if (!items.some((n) => n.id === page.value)) page.value = "overview";
});
watch(
  () => [chartJob.value, activeCase.value],
  () => {
    windingPreview.value = null;
    windingError.value = "";
    if (windingImage.value) URL.revokeObjectURL(windingImage.value);
    windingImage.value = "";
  },
);
function changeTopology(value: string) {
  if (isolated.value)
    isolationDraft.value = {
      outputs: clone(spec.value.outputs || []),
      feedback_output: spec.value.feedback_output,
      feedback_mode: spec.value.feedback_mode,
      coupling_config: clone(spec.value.coupling_config),
    };
  spec.value.topology = value;
  if (!["FLYBACK", "QR-FLYBACK", "ACF-FORWARD"].includes(value)) {
    spec.value.outputs = [];
    spec.value.feedback_mode = "SSR";
    spec.value.feedback_output = 1;
    spec.value.coupling_config = { enabled: false, k: [], dcr: [] };
  } else if (isolationDraft.value) {
    Object.assign(spec.value, clone(isolationDraft.value));
  }
  if (!["FLYBACK", "ACF-FORWARD"].includes(value)) {
    spec.value.feedback_mode = "SSR";
    if (spec.value.coupling_config) spec.value.coupling_config.enabled = false;
  }
  touch();
}
function enableMulti(enabled: boolean) {
  if (!meta.value) return;
  if (enabled) {
    spec.value.outputs = [
      {
        ...clone(meta.value.output_template),
        output_capacitors: clone(spec.value.output_capacitors ?? null),
        name: "OUT1",
        P_out: spec.value.P_out,
        P_out_min: spec.value.P_out,
        V_out: spec.value.V_out,
        Ns: spec.value.Ns || 12,
      },
    ];
  } else {
    const rail = spec.value.outputs?.[feedback.value - 1];
    if (rail) {
      spec.value.V_out = rail.V_out;
      spec.value.P_out = spec.value.outputs.reduce(
        (sum: number, r: Spec) => sum + Number(r.P_out || 0),
        0,
      );
    }
    spec.value.outputs = [];
    spec.value.feedback_output = 1;
    if (spec.value.coupling_config) spec.value.coupling_config.enabled = false;
  }
  touch();
}
function setFeedbackMode(value: string) {
  spec.value.feedback_mode = value;
  if (value === "PSR-MP6005") {
    spec.value.control_mode = "Peak Current Mode";
    spec.value.A_sense = 11;
    spec.value.controller_type = "type2";
  }
  if (value === "PSR-MP6005" && spec.value.coupling_config)
    spec.value.coupling_config.enabled = false;
  touch();
}
function setGlobalMode(value: string) {
  spec.value.device_curve_settings = {
    mode: value,
    overrides: clone(spec.value.device_curve_settings?.overrides || {}),
  };
  touch();
}
function setSource(target: string, value: string) {
  const settings = clone(
    spec.value.device_curve_settings || { mode: "fixed", overrides: {} },
  );
  settings.overrides ||= {};
  if (value === "global") delete settings.overrides[target];
  else settings.overrides[target] = value;
  spec.value.device_curve_settings = settings;
  touch();
}
function removeCurve(target: string) {
  if (target === "Q1:transfer") spec.value.mos_miller_curve = {};
  else if (target === "Q1:charge") spec.value.mos_charge_curve = {};
  else delete spec.value.diode_curves?.[target];
  touch();
}
function manualEvent(
  caseId: string,
  event: string,
  key: string,
  value: string,
) {
  const events = clone(spec.value.mos_manual_events || {});
  for (const c of ["min", "max"]) {
    events[c] ||= {};
    for (const e of ["on", "off"])
      events[c][e] ||= {
        Vgp: spec.value[e === "on" ? "Vgp_on" : "Vgp_off"],
        Qgs: spec.value.Qgs,
      };
  }
  events[caseId][event][key] =
    value === "" ? null : Number(value) * (key === "Qgs" ? 1e-9 : 1);
  spec.value.mos_manual_events = events;
  spec.value.mos_miller_mode = "manual";
  touch();
}
function eventValue(c: string, e: string, k: string) {
  return (
    spec.value.mos_manual_events?.[c]?.[e]?.[k] ??
    spec.value[k === "Qgs" ? "Qgs" : e === "on" ? "Vgp_on" : "Vgp_off"]
  );
}
function toggleCoupling(enabled: boolean) {
  const count = spec.value.outputs?.length || 1;
  const old = spec.value.coupling_config;
  spec.value.coupling_config =
    old?.k?.length === count + 1
      ? clone(old)
      : clone(meta.value?.coupling[String(count)] || {});
  spec.value.coupling_config.enabled = enabled;
  touch();
}
function changeK(i: number, j: number, value: string) {
  const k = spec.value.coupling_config.k;
  k[i][j] = k[j][i] = Number(value);
  touch();
}
function coreChoice(value: string) {
  spec.value.core_choice = value;
  if (value === "自定义（非标准）" && !spec.value.custom_core?.Ae)
    spec.value.custom_core = {
      name: "自定义磁芯",
      Ae: { v: 0, u: "mm²" },
      Ve: { v: 0, u: "mm³" },
      Wa: { v: 0, u: "mm²" },
      MLT: { v: 0, u: "mm" },
    };
  touch();
}
function materialChanged(value: string) {
  spec.value.core_material = value;
  const preset = meta.value?.materials[value];
  if (preset && value !== "Custom") {
    spec.value.k_core = preset.k;
    spec.value.a_core = preset.a;
    spec.value.b_core = preset.b;
  }
  touch();
}
function geometryValue(key: string) {
  const raw = spec.value.custom_core?.[key];
  return typeof raw === "object"
    ? raw.v
    : raw === undefined
      ? ""
      : Number(raw) * (key === "Ve" ? 1e9 : key === "MLT" ? 1e3 : 1e6);
}
function geometryChanged(key: string, value: string) {
  spec.value.custom_core ||= {};
  spec.value.custom_core[key] = {
    v: value === "" ? null : Number(value),
    u: key === "Ve" ? "mm³" : key === "MLT" ? "mm" : "mm²",
  };
  touch();
}
function windowValue(key: string) {
  return Number(spec.value.winding_config?.[key] || 0) * 1e3;
}
function windowChanged(key: string, value: string) {
  spec.value.winding_config ||= {};
  spec.value.winding_config[key] = Number(value) / 1e3;
  touch();
}
async function queuePreview() {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(refreshPreview, 300);
}
async function refreshPreview() {
  if (!meta.value) return;
  const current = ++previewRevision;
  const fingerprint = JSON.stringify(spec.value);
  try {
    const value = await post<Preview>("/preview", { spec: spec.value });
    if (current === previewRevision) {
      previewFingerprint = fingerprint;
      preview.value = value;
      previewError.value = "";
    }
  } catch (e: any) {
    if (current === previewRevision) previewError.value = e.message;
  }
}
async function loadConfig(raw: Spec, title?: string) {
  const value = await post<Spec>("/config", { spec: raw });
  spec.value = value;
  result.value = null;
  touch();
  dirty.value = false;
  projectTitle.value = value.__web_project_title || title || "电源设计";
  message.value = "配置已载入，请检查参数后计算。";
  await refreshPreview();
}
async function selectExample() {
  if (!example.value) return;
  error.value = "";
  try {
    const raw = await request<Spec>("/examples/" + example.value);
    await loadConfig(raw, meta.value?.examples[example.value] || "电源设计");
  } catch (e: any) {
    error.value = e.message;
  }
}
async function importConfig(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0];
  if (!file) return;
  try {
    if (file.size > 16 * 1024 * 1024) throw new Error("配置不可超过16 MiB");
    const raw = JSON.parse(await file.text());
    await loadConfig(
      raw.schema === "power-design.snapshot.v1" ? raw.spec : raw,
      file.name.replace(/\.json$/i, ""),
    );
    showSidebar.value = true;
  } catch (e: any) {
    error.value = "配置导入失败：" + e.message;
  } finally {
    (event.target as HTMLInputElement).value = "";
  }
}
function saveConfig() {
  download(
    new Blob(
      [
        JSON.stringify(
          {
            ...spec.value,
            input_voltage_case: activeCase.value === "Vinmax" ? "max" : "min",
            __web_project_title: projectTitle.value,
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    ),
    projectTitle.value + ".json",
  );
}
async function calculate() {
  if (!meta.value || busy.value) return;
  error.value = "";
  const generation = ++revision.value;
  result.value = null;
  busy.value = true;
  dirty.value = false;
  page.value = page.value === "reports" ? "overview" : page.value;
  message.value = meta.value.native ? "已提交到浏览器后台线程…" : "已提交到独立计算进程…";
  try {
    const submitted = await post<Job>("/jobs", {
      spec: clone(spec.value),
      cross_regulation: crossRegulation.value,
    });
    if (generation !== revision.value) {
      void post(`/jobs/${submitted.id}/cancel`, {}).catch(() => {});
      return;
    }
    job.value = submitted;
    poll(generation);
  } catch (e: any) {
    if (generation === revision.value) {
      busy.value = false;
      error.value = e.message;
    }
  }
}
async function poll(generation: number) {
  if (disposed || !job.value || generation !== revision.value) return;
  try {
    const status = await request<Job>(`/jobs/${job.value.id}`);
    if (generation !== revision.value) return;
    job.value = status;
    message.value = status.message || status.error?.message || "计算中…";
    if (status.state === "succeeded") {
      const snapshot = await request<Snapshot>(`/jobs/${status.id}/result`);
      if (generation !== revision.value) return;
      result.value = snapshot;
      busy.value = false;
      dirty.value = false;
      message.value = snapshot.ok
        ? "双工况快照已就绪 · 工程检查结果请复核"
        : "部分工况未完成，请查看错误说明";
      return;
    }
    if (status.state === "failed" || status.state === "cancelled") {
      busy.value = false;
      error.value = status.error?.message || "计算已取消";
      return;
    }
    timer = setTimeout(() => poll(generation), 350);
  } catch (e: any) {
    if (generation === revision.value) {
      busy.value = false;
      error.value = e.message;
    }
  }
}
async function cancel() {
  if (!job.value) return;
  revision.value++;
  clearTimeout(timer);
  busy.value = false;
  try {
    await post(`/jobs/${job.value.id}/cancel`, {});
    message.value = "已请求取消；底层数值调用完成后生效。";
  } catch (e: any) {
    error.value = e.message;
  }
}
const exportOperation = ref("");
const exportProgress = ref("");
const exportElapsed = ref(0);
function spicePreset(name: "generic" | "mp6005" | "mp6005_acf" | "l6565" | "tps40200" | "ltc3864" | "lm5022", reset = false) {
  // Presets are flat numeric maps; spreading unwraps Vue's reactive proxy.
  const reference = meta.value?.spice_presets[name] || {};
  if (["tps40200", "ltc3864", "lm5022"].includes(name) && !reset) {
    const current = { ...meta.value?.spice_presets.generic, ...(spec.value.spice_config || {}) };
    for (const key of meta.value?.spice_niso_reference_keys || []) current[key] = reference[key];
    setValue("spice_config", current);
    message.value = "已填入控制器参考值；保留 DCR、软启动、补偿与测试设置，请重新计算。";
  } else setValue("spice_config", { ...reference });
}
async function cancelExport() {
  if (exportOperation.value) await post(`/operations/${exportOperation.value}/cancel`, {});
}
async function exportReport(format: string) {
  if (!job.value || dirty.value || busy.value) return;
  error.value = "";
  exporting.value = format;
  exportProgress.value = "正在排队…";
  const started = Date.now();
  exportElapsed.value = 0;
  const generation = revision.value;
  try {
    const operation = await post(`/jobs/${job.value.id}/export`, {
      format,
      mos_real_time: mosRealTime.value,
    });
    exportOperation.value = operation.id;
    const cfg = spec.value.spice_config || {};
    const timeoutSeconds = format === 'comparison' ? 120 + 2 * ((cfg.short_test ? 2 : 1) * (cfg.simulation_timeout_s || 180) + (cfg.fra_enabled === 0 ? 0 : 2 * (cfg.fra_timeout_s || 600)) + (cfg.cross_enabled === 0 ? 0 : cfg.cross_timeout_s || 1200)) : 180;
    const deadline = Date.now() + timeoutSeconds * 1000;
    while (Date.now() < deadline) {
      const state = await request<any>(`/operations/${operation.id}`);
      exportProgress.value = state.message || "正在后台生成…";
      exportElapsed.value = Math.floor((Date.now() - started) / 1000);
      if (state.state === "succeeded") {
        if (generation !== revision.value)
          throw new Error("报告已生成，但参数已变化；请重新计算后导出当前设计");
        const name = projectTitle.value + (format === 'comparison' ? '_仿真与设计计算对比报告' : format === 'zip' ? '_LTspice闭环' : "_Vinmin-Vinmax");
        download(
          await getBlob(
            `/files/${operation.id}?filename=${encodeURIComponent(name)}`,
          ),
          name + "." + (format === 'comparison' ? 'zip' : format),
        );
        message.value =
          format === 'comparison' ? '已生成实际仿真对比报告 ZIP，内含 Word、工程与日志；请先查看报告中的完成状态。' : format === 'zip' ? 'LTspice 工程已导出；解压后打开 Flyback.asc 查看功率级与控制器连接。' : "已导出 " + format.toUpperCase() + " · 来自当前双工况快照";
        if (format === 'comparison' && state.result?.comparison) {
          const summary = state.result.comparison;
          message.value = `瞬态完成 ${summary.successful}/${summary.total}；有效 FRA ${summary.fra_successful}/${summary.fra_total}。`;
          if (!summary.successful) error.value = "所有工况均未完成；下载的是诊断报告，尚无有效对比数据。请查看日志和失败原因。";
          else if (summary.incomplete) message.value += " 存在未完成项目，请查看报告状态。";
        }
        return;
      }
      if (state.state === "failed" || state.state === "cancelled")
        throw new Error(state.error?.message || "导出已取消");
      await new Promise((resolve) => setTimeout(resolve, 300));
    }
    await cancelExport();
    throw new Error("导出等待超时，已请求取消；请检查仿真设置后重试");
  } catch (e: any) {
    error.value = e.message;
  } finally {
    exporting.value = "";
    exportOperation.value = "";
    exportProgress.value = "";
  }
}
function editJson() {
  jsonDraft.value = JSON.stringify(spec.value, null, 2);
  jsonError.value = "";
  showJson.value = true;
}
async function applyJson() {
  try {
    const raw = JSON.parse(jsonDraft.value);
    spec.value = await post<Spec>("/config", { spec: raw });
    touch();
    showJson.value = false;
  } catch (e: any) {
    jsonError.value = e.message;
  }
}
function stateName(state: string) {
  return (
    (
      {
        pass: "通过",
        review: "需复核",
        undefined: "未计算",
        not_applicable: "不适用",
        info: "说明",
      } as Record<string, string>
    )[state] || state
  );
}
onMounted(async () => {
  try {
    const saved = Number(localStorage.getItem("power-web-font-size"));
    changeFont(normalizeFontSize(saved));
  } catch {}
  try {
    meta.value = await request<Bootstrap>("/bootstrap");
    setToken(meta.value!.token);
    if (integration.initialSpec) {
      await loadConfig(integration.initialSpec, integration.unitName);
    } else {
      spec.value = clone(meta.value!.spec);
      preview.value = meta.value!.preview;
    }
    if (integration.unitName) {
      projectTitle.value = integration.unitName;
      spec.value.__web_project_title = integration.unitName;
    }
    message.value = meta.value.native ? "浏览器本机计算已就绪 · 无需后台服务" : "本地服务已连接";
    await calculate();
  } catch (e: any) {
    error.value = e.message;
    message.value = "连接失败，请检查本地服务";
  }
});
onBeforeUnmount(() => {
  disposed = true;
  clearTimeout(timer);
  clearTimeout(previewTimer);
  if (windingImage.value) URL.revokeObjectURL(windingImage.value);
  if (busy.value && job.value) void post(`/jobs/${job.value.id}/cancel`, {}).catch(() => {});
  if (exportOperation.value) void post(`/operations/${exportOperation.value}/cancel`, {}).catch(() => {});
});
</script>

<template>
  <div class="application" :class="{ 'pcs-embedded': integration.embedded, 'large-ui':fontSize>20 }" :style="{ '--ui-font': fontSize + 'px', '--sidebar-width':Math.min(920,420+Math.max(0,fontSize-20)*22)+'px' }">
    <header class="topbar">
      <div class="brand">
        <span class="brand-mark"><Icon name="bolt" :size="24" /></span>
        <div>
          <strong>电源设计工作台</strong
          ><small>POWER DESIGN <span>/</span> LOCAL EDITION</small>
        </div>
      </div>
      <div class="topbar-center">
        <span class="local-dot" />本地运行 · 设计数据不上传
      </div>
      <div class="header-actions">
        <label class="font-control"
          >字号<select
            :value="fontSize"
            aria-label="界面字号"
            @change="
              changeFont(Number(($event.target as HTMLSelectElement).value))
            "
          >
            <option v-for="n in FONT_SIZES" :key="n" :value="n">{{n}}</option>
          </select></label
        >
        <details ref="helpDocuments" class="help-documents" @keydown.esc="helpDocuments && (helpDocuments.open = false)">
          <summary class="button" aria-label="计算说明与教程">
            <Icon name="book" /><span>计算说明</span><Icon name="chevron" :size="14" />
          </summary>
          <div class="help-document-menu">
            <button type="button" aria-label="计算方法与公式说明" @click="openManual">
              <Icon name="file" /><span>计算方法与公式说明<small>公式定义与模型说明 · Word</small></span>
            </button>
            <button type="button" aria-label="多路反激电源设计入门教程" @click="openTutorial">
              <Icon name="book" /><span>多路反激电源设计入门教程<small>从原理到数值算例 · Word</small></span>
            </button>
          </div>
        </details>
        <button
          class="button mobile-parameters"
          @click="showSidebar = !showSidebar"
        >
          <Icon name="settings" />参数</button
        ><button
          class="button"
          aria-label="导入配置"
          @click="fileInput?.click()"
        >
          <Icon name="upload" /><span>导入配置</span></button
        ><button
          class="button"
          aria-label="保存工程"
          :disabled="!meta"
          @click="saveConfig"
        >
          <Icon name="folder" /><span>保存工程</span></button
        ><button
          class="button primary"
          :aria-label="busy ? '计算中' : '重新计算'"
          :disabled="busy || !meta"
          @click="calculate"
        >
          <span v-if="busy" class="spinner" /><Icon
            v-else
            name="play"
            :size="16"
          /><span>{{ busy ? "计算中" : "重新计算" }}</span>
        </button>
      </div>
      <input
        ref="fileInput"
        type="file"
        accept=".json"
        class="visually-hidden"
        @change="importConfig"
      />
    </header>
    <div class="workspace">
      <aside class="sidebar" :class="{ visible: showSidebar }">
        <div class="sidebar-heading">
          <div>
            <Icon name="settings" :size="17" />
            <h2>设计输入</h2>
          </div>
          <button
            class="icon-button"
            title="查看全部 JSON 参数"
            @click="editJson"
          >
            <Icon name="code" :size="17" />
          </button>
          <button
            class="icon-button sidebar-close"
            aria-label="关闭参数面板"
            @click="showSidebar = false"
          >
            <Icon name="close" :size="20" />
          </button>
        </div>
        <template v-if="meta"
          ><div class="sidebar-intro">
            <label class="stacked-label"
              >示例方案<select v-model="example" @change="selectExample">
                <option disabled value="">选择示例方案…</option>
                <option v-for="(label, key) in meta.examples" :value="key">
                  {{ label }}
                </option>
              </select></label
            >
            <div class="search-field">
              <Icon name="search" :size="16" /><input
                v-model="search"
                placeholder="搜索参数 / 符号…"
                aria-label="搜索参数"
              />
            </div>
            <label class="font-control sidebar-font"
              >界面字号<select
                :value="fontSize"
                aria-label="参数区字号"
                @change="
                  changeFont(Number(($event.target as HTMLSelectElement).value))
                "
              >
                <option v-for="n in FONT_SIZES" :key="n" :value="n">{{n}}</option>
              </select></label
            >
          </div>
          <div class="parameter-scroll">
            <section class="setup-section">
              <span class="section-kicker">01 / DESIGN REQUIREMENTS</span
              ><label class="stacked-label"
                >电源拓扑<select
                  :value="spec.topology"
                  @change="
                    changeTopology(($event.target as HTMLSelectElement).value)
                  "
                >
                  <option v-for="topology in meta.topologies" :value="topology">
                    {{ topologyNames[topology] }} · {{ topology }}
                  </option>
                </select></label
              ><label class="stacked-label"
                >控制方式<select
                  v-model="spec.control_mode"
                  :disabled="spec.feedback_mode === 'PSR-MP6005'"
                  @change="touch"
                >
                  <option>Peak Current Mode</option>
                  <option>Voltage Mode</option>
                </select></label
              >
              <div v-if="isolated" class="isolation-controls">
                <label class="checkbox-label"
                  ><input
                    type="checkbox"
                    :checked="multi"
                    @change="
                      enableMulti(($event.target as HTMLInputElement).checked)
                    "
                  />多绕组输出 <span class="muted">最多 6 路</span></label
                ><label class="field-row"
                  >反馈方式<select
                    :value="spec.feedback_mode"
                    @change="
                      setFeedbackMode(
                        ($event.target as HTMLSelectElement).value,
                      )
                    "
                  >
                    <option value="SSR">SSR 副边反馈</option>
                    <option
                      v-if="spec.topology === 'FLYBACK'"
                      value="PSR-MP6005"
                    >
                      MP6005 原边反馈
                    </option>
                  </select></label
                ><label v-if="multi" class="field-row"
                  >主反馈 / PSR 基准路<select
                    :value="feedback"
                    @change="
                      setValue(
                        'feedback_output',
                        Number(($event.target as HTMLSelectElement).value),
                      )
                    "
                  >
                    <option
                      v-for="(_, index) in spec.outputs"
                      :value="index + 1"
                    >
                      OUT{{ index + 1 }}
                    </option>
                  </select></label
                >
                <p class="hint">输出与负载功率在防反管后；反馈取样在防反管前，参考电压包含该路固定防反压降。非反馈路参考电压按匝比及整流／防反压降估算。</p>
              </div>
            </section>
            <details class="parameter-section curve-section" open>
              <summary>
                <Icon name="chart" :size="16" /><strong
                  >器件计算方式与曲线</strong
                ><Icon name="chevron" :size="14" />
              </summary>
              <div class="section-content">
                <div class="mode-switch">
                  <button
                    :class="{
                      active:
                        (spec.device_curve_settings?.mode || 'fixed') ===
                        'fixed',
                    }"
                    @click="setGlobalMode('fixed')"
                  >
                    固定值快速估算</button
                  ><button
                    :class="{
                      active: spec.device_curve_settings?.mode === 'curve',
                    }"
                    @click="setGlobalMode('curve')"
                  >
                    曲线精细计算
                  </button>
                </div>
                <p class="hint">全局选择可逐项覆盖；切换不会删除已导入曲线。</p>
                <div
                  v-for="target in preview?.targets"
                  :key="target.target"
                  class="curve-row"
                >
                  <div class="curve-title">
                    <strong>{{ target.ref }}</strong
                    ><span>{{
                      target.target === "Q1:transfer"
                        ? target.axes.includes("Vds")
                          ? "Id–Vds"
                          : "Id–Vgs"
                        : target.target === "Q1:charge"
                          ? "Vgs–Qg"
                          : "If–Vf"
                    }}</span
                    ><span
                      class="curve-status"
                      :class="
                        target.source === 'curve'
                          ? target.loaded
                            ? 'enabled'
                            : 'missing'
                          : ''
                      "
                      >{{
                        target.source === "curve"
                          ? target.loaded
                            ? "已启用"
                            : "待导入"
                          : target.source === "legacy"
                            ? "兼容跨导"
                            : target.loaded
                              ? "已保存"
                              : "固定值"
                      }}</span
                    >
                  </div>
                  <p>{{ target.role }}</p>
                  <div class="curve-actions">
                    <select
                      :value="
                        spec.device_curve_settings?.overrides?.[
                          target.target
                        ] || 'global'
                      "
                      :aria-label="
                        target.ref + ' ' + target.target + '计算来源'
                      "
                      @change="
                        setSource(
                          target.target,
                          ($event.target as HTMLSelectElement).value,
                        )
                      "
                    >
                      <option value="global">使用全局选择</option>
                      <option value="fixed">此项使用固定值</option>
                      <option value="curve">此项使用曲线</option></select
                    ><button
                      v-if="target.loaded"
                      class="small-button"
                      @click="
                        curveViewer = target;
                        reuseCurveTarget = '';
                      "
                    >
                      预览</button
                    ><button class="small-button" @click="curveTarget = target">
                      {{ target.loaded ? "更换" : "导入" }}</button
                    ><button
                      v-if="target.loaded"
                      class="icon-button small"
                      title="解除该位号的曲线"
                      @click="removeCurve(target.target)"
                    >
                      <Icon name="close" :size="13" />
                    </button>
                  </div>
                  <small
                    v-if="target.filename"
                    class="curve-filename"
                    :title="target.filename"
                    >{{ target.filename }}</small
                  >
                  <FieldInput
                    v-if="
                      target.target === 'Q1:transfer' &&
                      spec.mos_miller_curve?.kind === 'output_family'
                    "
                    :field="metadataFields.mos_curve_vds"
                    :value="spec.mos_curve_vds"
                    @change="setValue('mos_curve_vds', $event)"
                  />
                </div>
                <details class="manual-events">
                  <summary>手动四事件平台与 Qgs</summary>
                  <p class="hint">
                    固定值模式下各事件分别输入。Qgs 为 0 V 至米勒平台的电荷。
                  </p>
                  <div class="event-header">
                    <span>工况 / 事件</span><span>Vgp / V</span
                    ><span>Qgs / nC</span>
                  </div>
                  <template v-for="c in ['min', 'max']"
                    ><div v-for="e in ['on', 'off']" class="event-input">
                      <label
                        >Vin{{ c }} · {{ e === "on" ? "开通" : "关断" }}</label
                      ><input
                        type="number"
                        step="any"
                        :aria-label="'Vin' + c + e + '米勒电压'"
                        :value="eventValue(c, e, 'Vgp')"
                        @input="
                          manualEvent(
                            c,
                            e,
                            'Vgp',
                            ($event.target as HTMLInputElement).value,
                          )
                        "
                      /><input
                        type="number"
                        step="any"
                        :aria-label="'Vin' + c + e + '平台电荷'"
                        :value="Number(eventValue(c, e, 'Qgs')) * 1e9"
                        @input="
                          manualEvent(
                            c,
                            e,
                            'Qgs',
                            ($event.target as HTMLInputElement).value,
                          )
                        "
                      /></div
                  ></template>
                </details>
              </div>
            </details>
            <details v-if="multi && isolated" class="parameter-section" open>
              <summary>
                <Icon name="layers" :size="16" /><strong>各路输出与绕组</strong
                ><Icon name="chevron" :size="14" />
              </summary>
              <div class="section-content">
                <OutputEditor
                  :spec="spec"
                  :meta="meta"
                  :preview="preview"
                  @change="replaceSpec"
                />
              </div>
            </details>
            <details
              v-for="group in groups"
              :key="group.category"
              class="parameter-section"
              open
            >
              <summary>
                <span class="parameter-bullet" /><strong>{{
                  group.title.replace(/^[①②③④⑤⑥⑦⑧]\s*/, "")
                }}</strong
                ><span class="count">{{ group.category==='capacitors'?'可配置':group.rows.length }}</span
                ><Icon name="chevron" :size="14" />
              </summary>
              <div class="section-content">
                <template v-if="group.category==='capacitors'">
                  <CapacitorBank :spec="spec" side="input" :value="spec.input_capacitors" @change="setValue('input_capacitors',$event)" />
                  <CapacitorBank v-if="!multi" :spec="spec" :value="spec.output_capacitors" @change="setValue('output_capacitors',$event)" />
                </template>
                <template
                  v-for="(field, index) in group.rows"
                  :key="field.name"
                >
                  <div
                    v-if="
                      index === 0 ||
                      field.group !== group.rows[index - 1]?.group
                    "
                    class="subsection-heading"
                  >
                    {{ field.group }}
                  </div>
                  <FieldInput
                    :field="field"
                    :value="spec[field.name]"
                    :hint="densityHint(field.name)"
                    :disabled="
                      field.name === 'A_sense' &&
                      spec.feedback_mode === 'PSR-MP6005'
                    "
                    @change="setValue(field.name, $event)"
                  />
                </template>
                <details v-if="group.category==='stage' && isolated" class="parameter-section">
                  <summary>寄生参数与吸收 · 快速 / 寄生瞬态</summary>
                  <ParasiticEditor :spec="spec" :schema="meta!.parasitics" @change="setValue('parasitic_config',$event)" />
                </details>
                <template v-if="group.category === 'mag'">
                  <CoreEditor :spec="spec" :meta="meta" @change="replaceSpec" />
                  <CoreEditor
                    v-if="spec.topology === 'ACF-FORWARD' && !multi"
                    :spec="spec"
                    :meta="meta"
                    inductor
                    :material="false"
                    @change="replaceSpec"
                  />
                  <template v-if="isolated"
                    ><div class="subsection-heading">可绕制窗口</div>
                    <label class="field-row"
                      >净窗口宽度<span class="quantity"
                        ><input
                          type="number"
                          step="any"
                          :value="windowValue('window_width')"
                          @input="
                            windowChanged(
                              'window_width',
                              ($event.target as HTMLInputElement).value,
                            )
                          "
                        /><span class="unit">mm</span></span
                      ></label
                    ><label class="field-row"
                      >净窗口高度<span class="quantity"
                        ><input
                          type="number"
                          step="any"
                          :value="windowValue('window_height')"
                          @input="
                            windowChanged(
                              'window_height',
                              ($event.target as HTMLInputElement).value,
                            )
                          "
                        /><span class="unit">mm</span></span
                      ></label
                    >
                    <p class="hint">
                      完整疏/密绕、利兹线和交错层序请进入“磁件”页配置。DCR
                      由几何自动计算。
                    </p></template
                  ></template
                >
                <template v-if="group.category === 'ctrl'"
                  ><label class="field-row"
                    >补偿器类型<select
                      v-model="spec.controller_type"
                      @change="touch"
                    >
                      <option value="auto">自动选择</option>
                      <option value="type2">Type II</option>
                      <option value="type3">Type III</option>
                    </select></label
                  >
                  <p class="hint">
                    自动整定在“环路”页，阻容计算与反推在“补偿参考电路”页；应用新参数后需重新计算。
                  </p>
                </template>
              </div>
            </details>
            <details
              v-if="['FLYBACK','ACF-FORWARD'].includes(spec.topology) && spec.feedback_mode === 'SSR'"
              class="parameter-section"
            >
              <summary>
                <Icon name="layers" :size="16" /><strong>绕组耦合矩阵</strong
                ><span class="tag amber">实验</span
                ><Icon name="chevron" :size="14" />
              </summary>
              <div class="section-content">
                <label class="checkbox-label"
                  ><input
                    type="checkbox"
                    :checked="spec.coupling_config?.enabled"
                    @change="
                      toggleCoupling(
                        ($event.target as HTMLInputElement).checked,
                      )
                    "
                  />启用两两 kij 反激计算或正激仿真</label
                >
                <p class="hint">
                  输入对称耦合系数，不是 RCD 的
                  K。正激启用矩阵后，同时计算物理钳位、逐路输出电感和电荷平衡。改变路数会重置矩阵，请重新复核。
                </p>
                <div v-if="spec.coupling_config?.enabled" class="matrix-scroll">
                  <table class="matrix">
                    <thead>
                      <tr>
                        <th>kij</th>
                        <th v-for="(_, i) in spec.coupling_config.k">
                          {{ i === 0 ? "P" : "S" + i }}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="(row, i) in spec.coupling_config.k">
                        <th>{{ i === 0 ? "P" : "S" + i }}</th>
                        <td v-for="(v, j) in row">
                          <span v-if="Number(j) <= Number(i)">{{
                            Number(i) === Number(j) ? "1" : Number(v).toFixed(3)
                          }}</span
                          ><input
                            v-else
                            type="number"
                            step=".001"
                            min="0"
                            max="1"
                            :value="v"
                            :aria-label="'耦合' + i + j"
                            @input="
                              changeK(
                                Number(i),
                                Number(j),
                                ($event.target as HTMLInputElement).value,
                              )
                            "
                          />
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            </details>
            <details class="parameter-section">
              <summary>
                <Icon name="shield" :size="16" /><strong
                  >评审目标与计算选项</strong
                ><Icon name="chevron" :size="14" />
              </summary>
              <div class="section-content">
                <FieldInput
                  v-for="key in ['target_eta', 'fc_target', 'pm_target']"
                  :key="key"
                  :field="metadataFields[key]"
                  :value="spec[key]"
                  @change="setValue(key, $event)"
                /><label class="checkbox-label"
                  ><input
                    v-model="crossRegulation"
                    type="checkbox"
                    @change="touch"
                  />计算交叉调整率 <span class="tag amber">较慢</span></label
                >
                <p class="hint">
                  仅适用模型会执行。启用后扫描独立最小/最大负载组合，并纳入报告。
                </p>
              </div>
            </details>
            <p v-if="previewError" class="sidebar-error">
              配置提示：{{ previewError }}
            </p>
            <button class="button full-width json-button" @click="editJson">
              <Icon name="code" :size="16" />查看 / 编辑完整参数 JSON
            </button>
          </div>
          <div class="sidebar-footer">
            <Icon name="shield" :size="14" />{{ meta?.native ? 'TypeScript 内核 · 浏览器本机计算' : 'Python 内核 · 与桌面版共用计算公式' }}
          </div></template
        >
      </aside>
      <main class="main-panel">
        <div class="project-heading">
          <div>
            <div class="breadcrumbs">
              WORKSPACE <span>/</span> 电源设计 <span>/</span>
              {{ spec.topology || "…" }}
            </div>
            <div class="project-title">
              <input v-model="projectTitle" aria-label="工程名称" /><span
                class="tag local"
                >本地工程</span
              >
            </div>
            <p>从电路需求到工程评审，让每一个设计结果都有据可查。</p>
          </div>
          <div class="case-selector">
            <button
              v-for="id in ['Vinmin', 'Vinmax']"
              :class="{ active: activeCase === id }"
              @click="activeCase = id"
            >
              <span>{{ id }}</span
              ><strong>{{
                fmt(
                  result?.cases.find((c) => c.id === id)?.V_in ??
                    spec[id === "Vinmin" ? "V_in_min" : "V_in_max"],
                  "V",
                )
              }}</strong>
            </button>
          </div>
        </div>
        <details v-if="meta?.native" class="notice" style="margin:12px 0">
          <summary>浏览器离线内核 · 已迁移功能与当前边界</summary>
          <p>已支持工作点、损耗、任意并联电容组、磁件、绕制评估、环路、自动整定与 Word / Excel 报告。固定频率反激支持多绕组耦合矩阵和轻重载角点。</p>
          <p>已接入正激耦合周期、MP6005 PSR、局部寄生、补偿电路、优化、固定硬件角点与闭环极点检查；模型边界与原计算器一致。浏览器不调用本机 LTspice。</p>
        </details>
        <nav class="module-tabs" aria-label="设计模块">
          <button
            v-for="(item, index) in nav"
            :key="item.id"
            :class="{ active: page === item.id }"
            @click="page = item.id"
          >
            <span class="tab-number">{{
              String(index + 1).padStart(2, "0")
            }}</span
            >{{ item.name }}
          </button>
        </nav>
        <div class="result-scroll">
          <div v-if="error" class="error-box global-error">
            <Icon name="alert" /><span>{{ error }}</span
            ><button
              class="icon-button"
              aria-label="关闭提示"
              @click="error = ''"
            >
              <Icon name="close" :size="16" />
            </button>
          </div>
          <div v-if="dirty && result" class="notice stale-notice">
            <Icon
              name="info"
            />当前显示上次快照。参数已更改，请重新计算；旧结果不能用于导出当前设计。
          </div>
          <div v-if="busy" class="calculation-banner">
            <span class="spinner" />
            <div>
              <strong>{{ message }}</strong>
              <p>
                {{ meta?.native ? '使用浏览器 Web Worker 求解，保持页面可操作；请勿把计算完成视为全部检查通过。' : '独立进程计算，不会在浏览器主线程执行求解；请勿把计算完成视为全部检查通过。' }}
              </p>
            </div>
            <button class="button" @click="cancel">取消计算</button>
          </div>
          <ComponentManager v-if="page === 'bom'" :value="spec.component_management"
            :rows="preview?.component_rows" :rules="preview?.component_rules" :types="preview?.capacitor_types"
            :note="preview?.component_note" :evaluation="dirty ? undefined : display?.component_management"
            @change="value => setValue('component_management', value)" />
          <template v-if="result && page !== 'bom'"
            ><div v-if="!result.ok" class="notice">
              <Icon
                name="alert"
              />部分输入端点计算不完整。失败工况不会用另一个工况替代。
            </div>
            <div v-if="selected?.error" class="error-box">
              {{ activeCase }}：{{ selected.error }}
            </div>
            <template v-if="summary"
              ><section class="metric-grid">
                <article class="metric-card">
                  <span>额定输出功率<Icon name="bolt" :size="17" /></span
                  ><strong
                    >{{
                      fmt(
                        result.spec.outputs?.length
                          ? result.spec.outputs.reduce(
                              (sum: number, r: Spec) => sum + Number(r.P_out),
                              0,
                            )
                          : result.spec.P_out,
                      )
                    }}<small>W</small></strong
                  >
                  <p>
                    {{ display?.outputs?.length || 1 }} 路输出 ·
                    {{ summary.operating_point.mode }}
                  </p>
                </article>
                <article class="metric-card">
                  <span>模型计算效率<Icon name="chart" :size="17" /></span
                  ><strong
                    >{{ fmt(summary.losses.eta * 100) }}<small>%</small></strong
                  >
                  <p>
                    预设 {{ fmt(summary.losses.eta_guess * 100, "%") }} ·
                    非实测结果
                  </p>
                </article>
                <article class="metric-card">
                  <span>主 MOS 电压应力<Icon name="chip" :size="17" /></span
                  ><strong>{{ fmt(op.V_sw_max) }}<small>V</small></strong>
                  <p>Q1 · 按当前钳位 / 应力模型估算</p>
                </article>
                <article class="metric-card">
                  <span>环路相位裕度<Icon name="wave" :size="17" /></span
                  ><strong>{{ fmt(summary.loop?.pm) }}<small>°</small></strong>
                  <p>
                    {{
                      summary.loop?.fc
                        ? "穿越频率 " + fmt(summary.loop.fc, "Hz")
                        : "当前工况无有效环路结果"
                    }}
                  </p>
                </article>
              </section>
              <section v-if="page === 'overview'" class="overview-grid">
                <div class="overview-main">
                  <ChartPanel
                    :job="chartJob"
                    :case-id="activeCase"
                    kind="topology"
                    title="电路拓扑与器件位号"
                    note="工程参考示意，非可直接布板的 CAD 原理图。"
                  />
                  <section class="card">
                    <div class="card-heading">
                      <h3>输入端点对照</h3>
                      <span class="tag">同一套硬件</span>
                    </div>
                    <div class="table-wrap">
                      <table class="data-table">
                        <thead>
                          <tr>
                            <th>核心指标</th>
                            <th>Vinmin</th>
                            <th>Vinmax</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr>
                            <td>输入电压</td>
                            <td v-for="c in result.cases">
                              {{ fmt(c.V_in, "V") }}
                            </td>
                          </tr>
                          <tr v-for="row in comparisonKeys">
                            <td>{{ row[0] }}</td>
                            <td v-for="c in result.cases">
                              {{
                                fmt(c.summary.operating_point?.[row[1]], row[2])
                              }}
                            </td>
                          </tr>
                          <tr>
                            <td>模型效率</td>
                            <td v-for="c in result.cases">
                              {{ fmt(c.summary.losses?.eta * 100, "%") }}
                            </td>
                          </tr>
                          <tr>
                            <td>低频输出纹波</td>
                            <td v-for="c in result.cases">
                              {{
                                fmt(
                                  c.summary.operating_point?.ripple_pp * 1000,
                                  "mV",
                                )
                              }}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </section>
                </div>
                <div class="overview-aside">
                  <section class="card review-card">
                    <div class="card-heading">
                      <h3>设计检查</h3>
                      <span class="tag amber" v-if="needsReview.length"
                        >{{ needsReview.length }} 项需复核</span
                      ><span v-else class="tag green">已通过</span>
                    </div>
                    <div class="review-score">
                      <span class="review-circle"
                        ><Icon
                          :name="needsReview.length ? 'shield' : 'check'"
                          :size="32"
                      /></span>
                      <div>
                        <strong
                          >{{ checks.filter((c) => c.state === "pass").length
                          }}<small> / {{ checks.length }}</small></strong
                        >
                        <p>检查项通过</p>
                      </div>
                    </div>
                    <div class="check-list">
                      <div v-for="c in checks.slice(0, 7)" :key="c.id">
                        <span class="check-state" :class="c.state"
                          ><Icon
                            :name="c.state === 'pass' ? 'check' : 'info'"
                            :size="13" /></span
                        ><span>{{ c.name }}</span
                        ><small :class="c.state">{{
                          stateName(c.state)
                        }}</small>
                      </div>
                    </div>
                    <button
                      class="text-button review-more"
                      @click="page = 'reports'"
                    >
                      查看全部检查与模型限制 →
                    </button>
                  </section>
                  <section class="card output-summary">
                    <div class="card-heading">
                      <h3>端口输出概况（防反后）</h3>
                      <span>{{ summary.feedback.mode }}</span>
                    </div>
                    <div
                      v-for="rail in display?.outputs?.length
                        ? display.outputs
                        : [
                            {
                              id: 1,
                              name: '主输出',
                              V_out: result.spec.V_out,
                              P_out: result.spec.P_out,
                              mode: op.mode,
                            },
                          ]"
                      class="output-summary-row"
                    >
                      <span
                        ><strong>OUT{{ rail.id }}</strong
                        ><small>{{ rail.name }}</small></span
                      ><span
                        ><strong>{{ fmt(rail.V_out, "V") }}</strong
                        ><small
                          >{{ fmt(rail.P_out, "W") }} · {{ rail.mode }} · 电容端 {{ fmt(rail.V_out_cap ?? op.V_out_cap, "V") }}</small
                        ></span
                      ><span
                        v-if="rail.id === feedback"
                        class="feedback-dot"
                        title="主反馈路"
                      />
                    </div>
                  </section>
                  <section class="card export-shortcut">
                    <div class="export-symbol">
                      <Icon name="file" :size="25" />
                    </div>
                    <h3>把设计变成工程报告</h3>
                    <p>
                      Vinmin 与 Vinmax 左右对照，每个模块独立
                      Sheet，参数、图表和检查一起交付。
                    </p>
                    <button
                      class="button primary full-width"
                      :disabled="dirty || !!exporting"
                      @click="exportReport('xlsx')"
                    >
                      <Icon name="download" :size="16" />{{
                        exporting === "xlsx"
                          ? "正在生成 Excel…"
                          : "导出 Excel 报告"
                      }}</button
                    ><button class="text-button" @click="page = 'reports'">
                      Word 与数据快照 →
                    </button>
                  </section>
                </div>
              </section>
              <template v-if="page === 'topology'"
                ><ChartPanel
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="topology"
                  title="当前拓扑示意与位号"
                />
                <section class="card">
                  <div class="card-heading"><h3>器件位号与参数映射</h3><button class="button" @click="page = 'bom'">关键器件 BOM 与降额管理</button></div>
                  <div class="table-wrap">
                    <table class="data-table">
                      <thead>
                        <tr>
                          <th>位号</th>
                          <th>用途</th>
                          <th>当前参数</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="row in display?.components">
                          <td>
                            <strong>{{ row.ref }}</strong>
                          </td>
                          <td>{{ row.role }}</td>
                          <td class="mono small-text">{{ row.values }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </section></template
              >
              <template v-if="page === 'power'"
                ><section class="card page-toolbar">
                  <label class="checkbox-label"
                    ><input v-model="mosRealTime" type="checkbox" />MOS
                    开通/关断使用真实时间轴（同时用于报告）</label
                  >
                  <p class="hint">
                    取消勾选按 t1–t8
                    分段展开，便于查看纳秒级过程；不会改变损耗计算。
                  </p>
                </section>
                <ChartPanel
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="power"
                  title="功率级关键波形" /><ChartPanel
                  v-if="display?.parasitics?.edges?.length"
                  :job="chartJob" :case-id="activeCase" kind="parasitics"
                  title="寄生换流 · 独立局部 RLC 估算" :note="display?.parasitics?.scope" /><ChartPanel
                  v-for="rail in display?.outputs"
                  :key="rail.id"
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="outputs"
                  :output="rail.id"
                  :title="
                    'OUT' + rail.id + ' · ' + rail.name + ' 支路波形'
                  " /><ChartPanel
                  :job="chartJob"
                  :case-id="activeCase"
                  :kind="mosRealTime ? 'switching_real' : 'switching'"
                  title="MOS 开通 / 关断过程 · t1—t8"
                  note="分段重建示意，与损耗模型使用同一组平台和电荷，不是寄生瞬态仿真。" /><ResultTable
                  :data="display?.operating_point"
                  :keys="[
                    'mode',
                    'V_in',
                    'V_out',
                    'P_out',
                    'I_out',
                    'I_in_est',
                    'eta_guess',
                    'D',
                    'Dp',
                    'f_sw',
                    'f_sw_max',
                    'Ts',
                    'V_r',
                    'V_sw_max',
                    'V_d_max',
                  ]"
                  title="功率级工作点与设计依据"
              /></template>
              <template v-if="page === 'devices'"
                ><div class="two-column">
                  <ResultTable
                    :data="display?.stress?.switch"
                    title="Q1 · MOS 电压 / 电流应力"
                  /><ResultTable
                    :data="display?.stress?.diode"
                    title="D1 · 整流器件应力（未计尖峰）"
                  />
                </div>
                <div v-if="display?.stress?.auxiliary" class="two-column">
                  <ResultTable
                    :data="display.stress.auxiliary"
                    title="Q2 · 辅助 MOS 应力"
                  /><ResultTable
                    :data="display.stress.freewheel"
                    title="续流二极管应力"
                  />
                </div>
                <ChartPanel
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="device_losses"
                  title="MOS / 整流器件损耗分解"
                />
                <div class="two-column">
                  <ResultTable
                    :data="display?.semiconductors?.diode"
                    title="整流损耗与曲线来源"
                  /><ResultTable
                    :data="display?.switch_loss?.gate"
                    title="当前输入工况 · 米勒平台与电荷依据"
                  />
                </div>
                <ChartPanel
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="losses"
                  title="当前工况损耗分配"
                />
                <div class="two-column">
                  <section class="card">
                    <div class="card-heading"><h3>Q1 · 开关损耗与时间</h3></div>
                    <table class="data-table">
                      <tbody>
                        <tr
                          v-for="(label, key) in {
                            P_cond: '导通损耗',
                            P_sw_on: '开通损耗',
                            P_sw_off: '关断损耗',
                            P_coss: 'Coss 损耗',
                            P_gate: '驱动损耗',
                            P_total: 'MOS 总损耗',
                          }"
                        >
                          <td>{{ label }}</td>
                          <td>{{ fmt(display?.switch_loss?.[key], "W") }}</td>
                        </tr>
                        <tr v-for="t in ['t1', 't2', 't3', 't6', 't7', 't8']">
                          <td>{{ t }}</td>
                          <td>
                            {{ fmt(display?.switch_loss?.[t] * 1e9, "ns") }}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </section>
                  <section class="card">
                    <div class="card-heading">
                      <h3>平台与电荷 · 当前输入工况</h3>
                    </div>
                    <table class="data-table">
                      <tbody>
                        <tr
                          v-for="(label, key) in {
                            Vgp_on: '开通米勒平台 / V',
                            Vgp_off: '关断米勒平台 / V',
                            Qgs_on: '开通 Qgs / C',
                            Qgs_off: '关断 Qgs / C',
                            Qgd_on: '开通 Qgd / C',
                            Qgd_off: '关断 Qgd / C',
                          }"
                        >
                          <td>{{ label }}</td>
                          <td class="mono">
                            {{
                              key.startsWith("Q")
                                ? fmt(
                                    display?.switch_loss?.gate?.[key] * 1e9,
                                    "nC",
                                  )
                                : fmt(display?.switch_loss?.gate?.[key], "V")
                            }}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                    <p class="card-note">
                      转移特性是动态米勒平台的近似；实际开关过程需结合器件及样机验证。
                    </p>
                  </section>
                </div>
                <ChartPanel
                  v-for="rail in display?.outputs"
                  :key="rail.id"
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="output_losses"
                  :output="rail.id"
                  :title="'OUT' + rail.id + ' · 器件损耗'"
                />
                <section v-for="rail in display?.outputs" class="card">
                  <div class="card-heading">
                    <h3>OUT{{ rail.id }} · {{ rail.name }} · 整流与防反明细</h3>
                  </div>
                  <div class="two-column">
                    <ResultTable
                      :data="rail.stress?.diode"
                      title="整流管应力"
                    /><ResultTable
                      :data="rail.semiconductors?.diode"
                      title="整流管损耗"
                    /><ResultTable
                      v-if="rail.semiconductors?.freewheel"
                      :data="rail.semiconductors.freewheel"
                      title="续流损耗"
                    /><ResultTable
                      v-if="rail.semiconductors?.blocking"
                      :data="rail.semiconductors.blocking"
                      title="输出防反损耗"
                    />
                  </div>
                </section>
                <div class="notice">
                  <Icon
                    name="alert"
                  />整流二极管反压未考虑尖峰；具体应力需实测，选型应预留余量。
                </div></template
              >
              <template v-if="page === 'capacitors'"
                ><CapacitorTable
                  :bank="display?.capacitors?.input"
                  title="共享输入电容 · 参数与交流 RMS"
                  prefix="C_IN"
                />
                <CapacitorTable
                  v-if="!display?.outputs?.length"
                  :bank="display?.capacitors?.output"
                  title="输出电容 · 参数与交流 RMS"
                  prefix="C_O"
                />
                <ChartPanel
                  :job="chartJob"
                  :case-id="activeCase"
                  :kind="display?.outputs?.length ? 'input_caps' : 'capacitors'"
                  :title="
                    display?.outputs?.length
                      ? '共享输入电容 RMS 与频带（仅计一次）'
                      : '输入 / 输出电容 RMS'
                  "
                /><ChartPanel
                  v-for="rail in display?.outputs"
                  :key="rail.id"
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="output_caps"
                  :output="rail.id"
                  :title="'OUT' + rail.id + ' · 纹波、RMS 与频带分量'"
                />
                <CapacitorTable
                  v-for="rail in display?.outputs"
                  :key="'cap-table-' + rail.id"
                  :bank="rail.capacitors?.output"
                  :title="'OUT' + rail.id + ' · 输出电容参数与交流 RMS'"
                  :prefix="'C_O' + rail.id + '-'"
                />
                <p class="page-note">
                  每路电容的电流与损耗取自对应输出波形。主输入电容只计一次。
                </p></template
              >
              <template v-if="page === 'magnetics'"
                ><ChartPanel
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="magnetic_flux"
                  title="磁通密度与饱和界限" /><ChartPanel
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="magnetics"
                  title="磁件损耗与估算温升" />
                <section v-for="device in display?.magnetics" class="card">
                  <div class="card-heading">
                    <h3>
                      {{
                        device.kind === "transformer"
                          ? "T1 · 变压器"
                          : "L1 · 电感"
                      }}
                      <span class="muted">{{
                        device.core_label || device.core
                      }}</span>
                    </h3>
                  </div>
                  <div class="magnetic-facts">
                    <div
                      v-for="(label, key) in {
                        B_pk: '峰值磁密 / T',
                        dB: '磁通摆幅 / T',
                        Np: '原边匝数',
                        Ns: '副边匝数',
                        MLT: '平均匝长 / m',
                        dT: '温升 / K',
                        P_core: '磁芯损耗 / W',
                        P_cu: '铜损 / W',
                      }"
                    >
                      <span>{{ label }}</span
                      ><strong>{{ fmt(device[key]) }}</strong>
                    </div>
                  </div>
                  <div v-if="device.windings?.length" class="table-wrap">
                    <table class="data-table">
                      <thead>
                        <tr>
                          <th>绕组</th>
                          <th>匝数</th>
                          <th>单股线径</th>
                          <th>股数</th>
                          <th>电流密度</th>
                          <th>几何 DCR</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="w in device.windings">
                          <td>OUT{{ w.id }}</td>
                          <td>{{ w.Ns }}</td>
                          <td>{{ fmt(w.d_wire_s * 1000, "mm") }}</td>
                          <td>{{ w.n_strand_s }}</td>
                          <td>{{ fmt(w.J_actual / 1e6, "A/mm²") }}</td>
                          <td>{{ fmt(w.R_dc * 1000, "mΩ") }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <p class="card-note">
                    变压器温升使用用户输入的 Ri-a。磁损 k、α、β
                    保留原模型和单位约定。
                  </p>
                </section>
                <ResultTable
                  v-for="(device, index) in display?.magnetics"
                  :key="index"
                  :data="device"
                  :title="
                    (device.kind === 'transformer' ? '变压器' : '输出电感') +
                    ' · 完整磁件设计依据'
                  " />
                <WindingEditor
                  v-if="resultIsolated"
                  :spec="spec"
                  :windings="display?.winding_rows"
                  :assessment="
                    windingPreview?.assessment || display?.winding_assessment
                  "
                  :automatic-plan="windingPreview?.automatic_plan"
                  :preview-busy="windingBusy"
                  :preview-error="windingError || windingPreview?.preview_error"
                  @change="replaceSpec"
                  @preview="evaluateWinding" />
                <section v-if="windingImage" class="card">
                  <div class="card-heading">
                    <h3>局部几何预览 · 基于当前已算绕组</h3>
                  </div>
                  <img
                    :src="windingImage"
                    class="chart-image"
                    alt="当前窗口与层序的绕制预览"
                  />
                  <p class="card-note">
                    窗口/层序可局部预览。改变电气匝数或线径后，请先重新计算；正式报告仍以重算后的快照为准。
                  </p>
                </section>
                <ChartPanel
                  v-if="resultIsolated"
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="winding"
                  title="骨架净窗口与绕制横截面"
                  note="疏/密绕、利兹线及交错绕组沿用既有配置；几何评估不等同于安规或量产认证。"
              /></template>
              <template v-if="page === 'loop'"
                ><AdvancedTools
                  mode="loop"
                  :job="chartJob"
                  :case-id="activeCase"
                  :spec="spec"
                  :dirty="dirty"
                  :busy="busy"
                  @applied="applyUpdates"
                />
                <div v-if="summary.loop" class="loop-metrics">
                  <span
                    >穿越频率
                    <strong>{{ fmt(summary.loop.fc, "Hz") }}</strong></span
                  ><span
                    >相位裕度
                    <strong>{{ fmt(summary.loop.pm, "°") }}</strong></span
                  ><span
                    >增益裕度
                    <strong>{{ fmt(summary.loop.gm_db, "dB") }}</strong></span
                  ><span class="tag">只闭合主反馈路</span>
                </div>
                <ChartPanel
                  v-if="display?.loop_available"
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="loop"
                  title="对象、补偿器与开环 Bode 图"
                />
                <div class="notice">
                  <Icon
                    name="info"
                  />环路是当前工作点的小信号近似，多路输出仅闭合主反馈路。耦合模型为低频实验模型，高频外推不能代替
                  SPICE、FRA 或样机稳定性验证。
                </div>
                <p v-if="selected?.loop_error" class="error-box">
                  {{ selected.loop_error }}
                </p></template
              >
              <template v-if="page === 'efficiency'"
                ><ChartPanel
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="efficiency"
                  title="固定硬件下的效率-负载曲线" /><ChartPanel
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="losses"
                  title="完整损耗分配" /><AdvancedTools
                  mode="efficiency"
                  :job="chartJob"
                  :case-id="activeCase"
                  :spec="spec"
                  :dirty="dirty"
                  :busy="busy"
                  @applied="applyUpdates" /><ResultTable
                  :data="summary.losses"
                  title="效率与功率平衡"
              /></template>
              <template v-if="page === 'clamp'"
                ><ChartPanel
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="clamp"
                  title="钳位 / 复位波形" /><ResultTable
                  v-if="display?.rcd"
                  :data="display.rcd"
                  title="RCD 吸收参数与功耗" /><ResultTable
                  v-if="display?.clamp"
                  :data="display.clamp"
                  title="Vds 平台、包络峰值与钳位上限" /><ResultTable
                  v-if="result.spec.topology === 'ACF-FORWARD'"
                  :data="display?.operating_point"
                  :keys="[
                    'D',
                    'V_reset',
                    'V_clamp',
                    'V_clamp_hump',
                    'C_clamp_min',
                    'I_mag_pk',
                    'I_clamp_rms',
                    'f_clamp',
                    'f_clamp_effective',
                    'fc_recommended_max',
                  ]"
                  title="有源钳位正激核算"
              /></template>
              <template v-if="page === 'compensation'"
                ><AdvancedTools
                  mode="compensation"
                  :job="chartJob"
                  :case-id="activeCase"
                  :spec="spec"
                  :dirty="dirty"
                  :busy="busy"
                  @applied="applyUpdates"
              /></template>
              <template v-if="page === 'psr'"
                ><ResultTable
                  :data="display?.psr"
                  title="MP6005 · 辅助绕组、采样、反馈与物理 COMP 核算"
                />
                <p class="notice">
                  仅 PWM 区提供现有平均环路近似，PFM 不伪造 Bode
                  裕度。专有采样/动态补偿尚非完整 IC 仿真。
                </p></template
              >
              <template v-if="page === 'review'"
                ><AdvancedTools
                  mode="review"
                  :job="chartJob"
                  :case-id="activeCase"
                  :spec="spec"
                  :dirty="dirty"
                  :busy="busy"
                  @applied="applyUpdates"
                />
                <section v-if="result.cross_regulation" class="card">
                  <div class="card-heading">
                    <h3>独立负载组合 · 交叉调整率</h3>
                  </div>
                  <p class="card-note">
                    {{
                      result.cross_regulation.reason ||
                      result.cross_regulation.note ||
                      "只报告已完成的稳态角点包络，不是严格全区间极值或阶跃过冲。"
                    }}
                  </p>
                  <div
                    v-if="result.cross_regulation.summary?.length"
                    class="table-wrap"
                  >
                    <table class="data-table">
                      <thead>
                        <tr>
                          <th>输出</th>
                          <th>观察最小值</th>
                          <th>观察最大值</th>
                          <th>跨度</th>
                          <th>完整性</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="row in result.cross_regulation.summary">
                          <td>OUT{{ row.id }} {{ row.name }}</td>
                          <td>{{ fmt(row.V_min, "V") }}</td>
                          <td>{{ fmt(row.V_max, "V") }}</td>
                          <td>{{ fmt(row.span_pct, "%") }}</td>
                          <td>
                            {{
                              row.complete
                                ? "扫描完成"
                                : "部分角点失败，不构成完整边界"
                            }}
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </section></template
              >
              <template v-if="page === 'reports'"
                ><section class="report-hero card">
                  <div>
                    <span class="eyebrow">ENGINEERING DELIVERABLES</span>
                    <h2>一次计算，两种输入工况，完整工程交付。</h2>
                    <p>
                      同一套器件与补偿参数。报告包含需求、器件、波形、电容纹波、磁件、环路及工程检查。
                    </p>
                    <small
                      >快照 {{ result.snapshot_id.slice(0, 16) }} ·
                      {{ result.provenance.model_version }}</small
                    >
                  </div>
                  <Icon name="file" :size="70" />
                </section>
                <section class="card spice-card" v-if="['FLYBACK','QR-FLYBACK','ACF-FORWARD','BUCK','BOOST'].includes(spec.topology) && spec.feedback_mode === 'SSR'">
                  <div class="card-heading"><h3>LTspice 通用电源闭环设置</h3><span class="tag">{{ ['BUCK','BOOST'].includes(spec.topology)?(spec.control_mode==='Voltage Mode'?'TPS40200 · 电压模式':spec.topology==='BUCK'?'LTC3864 · 峰值电流':'LM5022 · 峰值电流'):spec.topology==='QR-FLYBACK'?'L6565 QR · 单路 SSR':spec.topology==='ACF-FORWARD'?'MP6005 · 有源钳位正激':'固定频率 · SSR' }}</span></div>
                  <p>{{ spec.topology==='QR-FLYBACK'?'ZCD 事件触发决定实际周期，主界面 f_sw 为设计频率上限。外部参考缓升与理想 VCC 是模型假设；异常 CS 锁存至 VCC 欠压。':'用户可独立配置频率、软启动和保护。参考配置不是完整芯片模型。' }} 修改后重新计算再导出。</p>
                  <div class="report-actions">
                    <button class="button" :disabled="!!exporting" @click="spicePreset(spec.topology==='BOOST'?'lm5022':spec.topology==='BUCK'?(spec.control_mode==='Voltage Mode'?'tps40200':'ltc3864'):spec.topology==='QR-FLYBACK'?'l6565':spec.topology==='ACF-FORWARD'?'mp6005_acf':'mp6005')">{{ spec.topology==='BOOST'?'填入 LM5022 参考配置':spec.topology==='BUCK'?(spec.control_mode==='Voltage Mode'?'填入 TPS40200 参考配置':'填入 LTC3864 参考配置'):spec.topology==='QR-FLYBACK'?'填入 L6565 QR 参考配置':'填入 MP6005 SSR 参考配置' }}</button>
                    <button class="button" :disabled="!!exporting" @click="spicePreset(spec.topology==='BOOST'?'lm5022':spec.topology==='BUCK'?(spec.control_mode==='Voltage Mode'?'tps40200':'ltc3864'):spec.topology==='QR-FLYBACK'?'l6565':'generic', true)">{{ ['BUCK','BOOST'].includes(spec.topology)?'恢复全部默认':spec.topology==='QR-FLYBACK'?'恢复 QR 参考默认':'恢复通用默认' }}</button>
                  </div>
                  <p v-if="['BUCK','BOOST'].includes(spec.topology)" class="hint">已加载示例时无需再填参考值。参考按钮保留测试设置；仅导出工程不运行仿真，对比报告会运行 Vinmin/Vinmax 与 FRA。FRA 频段应覆盖目标穿越频率上下两侧。</p>
                  <div class="spice-layout"><div>
                  <p v-if="Object.keys(spec.parasitic_config || {}).length" class="hint">Coss / Cj 已集中到左侧“寄生参数与吸收”，避免两处参数冲突。</p>
                  <section v-for="group in [...new Set(spiceOptions.map(item => item.group))]" :key="group">
                    <h4>{{ group }}</h4>
                    <div class="spice-settings">
                    <label v-for="option in spiceOptions.filter(item => item.group === group)" :key="option.key" @focusin="spiceFocus=option.key">
                      <span>{{ option.label }} {{ option.unit }}</span>
                      <select v-if="option.choices" :value="spec.spice_config?.[option.key] ?? option.default"
                        @change="setValue('spice_config', {...(spec.spice_config || {}), [option.key]: Number(($event.target as HTMLSelectElement).value)})">
                        <option v-for="(label,value) in option.choices" :key="value" :value="Number(value)">{{ label }}</option>
                      </select>
                      <input v-else type="number" step="any" :min="option.minimum" :max="option.maximum"
                        :value="spec.spice_config?.[option.key] ?? option.default"
                        @change="setValue('spice_config', {...(spec.spice_config || {}), [option.key]: Number(($event.target as HTMLInputElement).value)})" />
                    </label>
                    </div>
                  </section>
                  </div><ControllerLogic v-if="meta?.spice_logic" :definition="['BUCK','BOOST'].includes(spec.topology)?meta.spice_niso_logic:spec.topology==='QR-FLYBACK'?meta.spice_qr_logic:spec.topology==='ACF-FORWARD'?meta.spice_acf_logic:meta.spice_logic" :values="{...meta.spice_presets.generic,...(spec.spice_config || {})}" :design="spec" :selected="spiceFocus" @selected="spiceFocus=$event" /></div>
                  <p>模型边界：Ron / 常数 Coss / 等效门电容，固定二极管压降，线性磁芯及理想隔离反馈。{{ ['BUCK','BOOST'].includes(spec.topology)?'默认快速闭环关闭结电容尖峰；单路无交叉调整率。Boost 关断 MOS 不会切断输入至输出的短路通路。':spec.topology==='QR-FLYBACK'?'QR 仅支持单路 SSR，当前计算小信号模型为工程近似，应与实际 FRA 分开判读。':'不是 MP6005 精确模型；FRA 和交叉负载角点由试验设置决定。' }}</p>
                </section>
                <p v-if="exporting"><span class="spinner" /> {{ exportProgress }} · 已用时 {{ exportElapsed }} s。仿真可能需要较长时间。<button class="button" @click="cancelExport">取消本次导出与仿真</button></p>
                <div class="report-actions">
                  <button
                    v-for="format in ['xlsx', 'docx', 'json', ...(['FLYBACK','QR-FLYBACK','ACF-FORWARD','BUCK','BOOST'].includes(spec.topology) && spec.feedback_mode === 'SSR' ? (meta?.native?['zip']:['zip','comparison']) : [])]"
                    class="card report-option"
                    :disabled="dirty || !!exporting || (format === 'zip' && (!['FLYBACK','QR-FLYBACK','ACF-FORWARD','BUCK','BOOST'].includes(spec.topology) || spec.feedback_mode !== 'SSR'))"
                    @click="exportReport(format)"
                  >
                    <span class="file-type" :class="format">{{
                      format.toUpperCase()
                    }}</span
                    ><strong>{{
                      format === "xlsx"
                        ? "Excel 模块对照报告"
                        : format === "docx"
                          ? "Word 完整工程报告"
                          : format === 'comparison' ? '仿真与设计计算对比报告' : format === 'zip' ? '离线 SPICE 工程（ASC / CIR）' : "JSON 审计快照"
                    }}</strong>
                    <p>
                      {{
                        format === "xlsx"
                          ? "每个模块一个 Sheet，左右对照 Vinmin / Vinmax"
                          : format === "docx"
                            ? "总览对照 + 两端完整核算，保留原生数学公式"
                            : format === 'comparison' ? '实际运行 LTspice：逐周期检查、原副边电流、逐路纹波、原生 FRA、交叉负载角点。后台耗时较长，可取消；下载 Word 与工程日志 ZIP。' : format === 'zip' ? '原生可读 ASC / 可配置控制器 / 多绕组 / 双工况 / 保护测试' : "包含版本、曲线来源与计算结果，不是运行时对象"
                      }}
                    </p>
                    <span class="text-button"
                      ><span v-if="exporting === format" class="spinner" /><Icon
                        v-else
                        name="download"
                        :size="15"
                      />{{
                        exporting === format ? "后台生成中…" : "生成并下载"
                      }}</span
                    >
                  </button>
                </div>
                <section class="card">
                  <div class="card-heading">
                    <h3>全部工程检查 · {{ activeCase }}</h3>
                    <span class="tag amber"
                      >{{ needsReview.length }} 项需复核 / 未计算</span
                    >
                  </div>
                  <div class="table-wrap">
                    <table class="data-table">
                      <thead>
                        <tr>
                          <th>检查项</th>
                          <th>当前值</th>
                          <th>约束 / 说明</th>
                          <th>状态</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="c in checks" :key="c.id">
                          <td>{{ c.name }}</td>
                          <td>{{ fmt(c.value, c.unit) }}</td>
                          <td>
                            {{
                              c.limit === null
                                ? c.note
                                : c.comparison + " " + fmt(c.limit, c.unit)
                            }}
                          </td>
                          <td>
                            <span
                              class="tag"
                              :class="c.state === 'pass' ? 'green' : 'amber'"
                              >{{ stateName(c.state) }}</span
                            >
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </section>
                <section class="card limitations">
                  <div class="card-heading">
                    <h3>模型假设与限制</h3>
                    <Icon name="shield" :size="18" />
                  </div>
                  <p v-for="warning in summary.warnings">{{ warning }}</p>
                  <div v-if="result.cross_regulation" class="notice">
                    交叉调整率：{{
                      result.cross_regulation.supported
                        ? "已按所选最小/最大负载扫描；失败角点不构成完整边界"
                        : result.cross_regulation.reason || "当前模型不支持"
                    }}
                  </div>
                </section>
                <ChartPanel
                  :job="chartJob"
                  :case-id="activeCase"
                  kind="efficiency"
                  title="同一固定硬件下的模型效率曲线"
              /></template>
            </template>
          </template>
          <div v-else-if="!busy && page !== 'bom'" class="empty-state">
            <span class="empty-icon"><Icon name="wave" :size="40" /></span>
            <h2>
              {{ meta ? "从一个可验证的设计开始" : "正在连接本地计算服务" }}
            </h2>
            <p>
              {{
                meta
                  ? "选择拓扑、填写电路需求，或导入已有 JSON 配置。"
                  : "界面与计算分离，所有设计数据保留在此设备。"
              }}
            </p>
            <button v-if="meta" class="button primary" @click="calculate">
              <Icon name="play" />计算当前方案
            </button>
          </div>
        </div>
        <footer class="statusbar">
          <div>
            <span
              class="status-dot"
              :class="{ busy, stale: dirty }"
            /><strong>{{ statusLabel }}</strong
            ><span class="status-text">{{ message }}</span>
          </div>
          <span v-if="result" class="snapshot-label"
            >{{ activeCase }} · {{ result.snapshot_id.slice(0, 10) }}</span
          ><span v-else>LOCAL ENGINE / V0.2</span>
        </footer>
      </main>
    </div>
    <Teleport :to="integration.portal || 'body'"
      ><CurveImporter
        v-if="curveTarget"
        :target="curveTarget"
        :spec="spec"
        @close="curveTarget = null"
        @applied="
          (value) => {
            replaceSpec(value);
            curveTarget = null;
          }
        "
      />
      <div
        v-if="curveViewer"
        class="modal-backdrop"
        @click.self="curveViewer = null"
      >
        <section
          class="modal curve-viewer"
          role="dialog"
          aria-modal="true"
          aria-label="已导入曲线预览"
        >
          <header>
            <h2>{{ curveViewer.ref }} · 已导入曲线</h2>
            <button
              class="icon-button"
              aria-label="关闭曲线预览"
              @click="curveViewer = null"
            >
              <Icon name="close" />
            </button>
          </header>
          <div class="modal-body">
            <p class="card-note">
              {{ curveViewer.role }} ·
              {{
                curveViewer.axes
              }}。当前保存值按SI显示；请核对曲线与器件测试条件。
            </p>
            <CurvePlot
              :lines="viewingCurve"
              :x-label="curveViewer.axes.split('；')[0]"
              y-label="Y / SI"
            />
            <p
              v-if="
                storedCurve(curveViewer)?.source?.filename ||
                curveViewer.filename
              "
              class="hint"
            >
              来源：{{
                curveViewer.filename ||
                storedCurve(curveViewer)?.source?.filename
              }}
            </p>
            <template v-if="curveViewer.target.startsWith('D')"
              ><p class="notice">
                仅在器件型号与测试条件一致时，将该曲线显式复用到另一个二极管位号。不会自动套用到全部器件。
              </p>
              <label class="stacked-label"
                >复用目标<select v-model="reuseCurveTarget">
                  <option value="">请选择位号</option>
                  <option
                    v-for="row in preview?.targets.filter(
                      (t) =>
                        t.target.startsWith('D') &&
                        t.target !== curveViewer?.target,
                    )"
                    :value="row.target"
                  >
                    {{ row.ref }} · {{ row.role }}
                  </option>
                </select></label
              ><button
                class="button primary"
                :disabled="!reuseCurveTarget"
                @click="reuseCurve"
              >
                确认复制到所选位号
              </button></template
            >
          </div>
        </section>
      </div>
      <div
        v-if="showJson"
        class="modal-backdrop"
        @click.self="showJson = false"
      >
        <section class="modal json-modal">
          <header>
            <div>
              <span class="eyebrow">ADVANCED INPUT</span>
              <h2>完整参数 JSON</h2>
            </div>
            <button
              class="icon-button"
              aria-label="关闭"
              @click="showJson = false"
            >
              <Icon name="close" />
            </button>
          </header>
          <div class="modal-body">
            <p class="hint">
              用于现有高级配置：绕制分层、MP6005
              专用参数、非标准磁芯和兼容字段。未知字段仍由内核拒绝，修改不会执行脚本。
            </p>
            <textarea
              v-model="jsonDraft"
              spellcheck="false"
              aria-label="完整参数 JSON"
            />
            <p v-if="jsonError" class="error-box">{{ jsonError }}</p>
          </div>
          <footer>
            <button class="button" @click="showJson = false">取消</button
            ><button class="button primary" @click="applyJson">
              应用并重新校核
            </button>
          </footer>
        </section>
      </div></Teleport
    >
  </div>
</template>
