<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { Spec } from "./types";
import { fmt } from "./types";
import WindingCanvas from './WindingCanvas.vue';

/** Construction editor only. All capacity/diameter/fit results come from Python. */
const props = withDefaults(defineProps<{
  spec: Spec;
  windings?: Spec[];
  assessment?: Spec | null;
  automaticPlan?: Spec[] | null;
  previewBusy?: boolean;
  previewError?: string;
}>(), { windings: () => [], assessment: null, automaticPlan: null,
  previewBusy: false, previewError: "" });
const emit = defineEmits<{ change: [spec: Spec]; preview: [config: Spec] }>();

const geometryFields = [
  ["window_width", "骨架窗口净宽", "轴向宽度；不是磁芯窗口面积 Wa。"],
  ["window_height", "骨架窗口净高", "径向高度；不含示意挡墙。"],
  ["margin_x", "左右留边（每侧）", "两侧都扣除该尺寸。"],
  ["margin_y", "上下留边（每侧）", "上、下各保留该尺寸。"],
  ["diameter_allowance", "单股含漆外径增量", "外径未指定时，在裸铜直径上增加此值。"],
  ["layer_insulation", "同绕组层间绝缘", "相邻同绕组实体层之间的厚度。"],
  ["interwinding_insulation", "不同绕组间绝缘", "相邻不同绕组实体层之间的厚度。"],
  ["wire_gap", "线束与匝间净隙", "并绕束之间、相邻匝之间的净隙。"],
] as const;
const configDefaults: Spec = {
  window_width: 0, window_height: 0, margin_x: 0.00025, margin_y: 0.00010,
  diameter_allowance: 0.00003, layer_insulation: 0.00005,
  interwinding_insulation: 0.00015, wire_gap: 0,
  order: [], overrides: {}, layer_plan: [],turn_positions:{},
};
const wireDefaults: Spec = {
  outer_diameter: 0, strand_columns: 0, wire_type: "auto", parallel_bundles: 1,
  packing_factor: 0.75, bundle_diameter: 0, flatten_ratio: 1.5,
  winding_style: "sparse", turns_per_layer: 0,
};
const styles = [
  { value: "sparse", label: "疏绕 · 均匀分布" },
  { value: "dense_left", label: "密绕 · 靠左" },
  { value: "dense_right", label: "密绕 · 靠右" },
];
const selected = ref("P");
const selectedLayer = ref<number | null>(null);
const localMessage = ref("");
const manualMode = ref(Boolean(props.spec.winding_config?.layer_plan?.length));
const savedManualPlan = ref<Spec[]>([]);
const ownConfigSignature = ref("");

function clone<T>(value: T): T { return JSON.parse(JSON.stringify(value)); }
function canonical(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") return "{" + Object.entries(value)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, child]) => JSON.stringify(key) + ":" + canonical(child)).join(",") + "}";
  return JSON.stringify(value) ?? "null";
}
function identifyLayers(rows: Spec[]) {
  const used=new Set(rows.map(row=>row.section_id).filter(Boolean));
  const counters=new Map<string,number>();
  for(const row of rows){
    if(row.section_id) continue;
    let n=counters.get(row.winding_id)||0, id:string;
    do {
      let index=n++, suffix='';
      while(index>=0){suffix=String.fromCharCode(65+index%26)+suffix;index=Math.floor(index/26)-1;}
      id=row.winding_id+'_'+suffix;
    } while(used.has(id));
    row.section_id=id;used.add(id);counters.set(row.winding_id,n);
  }
  return rows;
}
const config = computed<Spec>(() => {
  const c={...clone(configDefaults),...clone(props.spec.winding_config || {})};
  identifyLayers(c.layer_plan);
  return c;
});
const plan = computed<Spec[]>(() => config.value.layer_plan || []);
const layerInsulation = computed(() => plan.value.map((entry, index) => {
  const previous = plan.value[index - 1];
  if (!previous) return { label: "首层 · 靠骨架", thickness: null };
  const sameWinding = previous.winding_id === entry.winding_id;
  return {
    label: `${sameWinding ? "同绕组层间" : "不同绕组间"} · ${previous.winding_id} → ${entry.winding_id}`,
    thickness: config.value[sameWinding ? "layer_insulation" : "interwinding_insulation"],
  };
}));
const actualRows = computed<Spec[]>(() => props.windings.filter((row) =>
  typeof row.id === "string" && Number.isInteger(row.turns) && row.turns > 0 &&
  Number.isInteger(row.strands) && row.strands > 0 &&
  Number.isFinite(row.bare_diameter) && row.bare_diameter > 0));
const hasResolvedWindings = computed(() => actualRows.value.length > 0);
const rows = computed<Spec[]>(() => {
  let source = actualRows.value;
  // Show known winding identities before the first run, never invent automatic turns.
  if (!source.length) {
    const rails: Spec[] = props.spec.outputs?.length ? props.spec.outputs : [{
      name: "副边", Ns: props.spec.Ns, n_strand_s: props.spec.n_strand_s,
      d_wire_s: props.spec.d_wire_s,parallel_wires_s:props.spec.parallel_wires_s||1,
    }];
    source = [{ id: "P", name: "原边 P", turns: props.spec.Np || null,
      strands: props.spec.n_strand_p || null,parallel_wires:props.spec.parallel_wires_p||1,bare_diameter: props.spec.d_wire_p || null },
      ...rails.map((row, index) => ({ id: `OUT${index + 1}`,
        name: `OUT${index + 1} · ${row.name || "副边"}`, turns: row.Ns || null,
        strands: row.n_strand_s || null,parallel_wires:row.parallel_wires_s||1,bare_diameter: row.d_wire_s || null }))];
  }
  const order: string[] = config.value.order || [];
  const known = new Map(source.map((row) => [row.id, row]));
  return [...order.filter((id) => known.has(id)),
    ...source.map((row) => row.id).filter((id) => !order.includes(id))]
    .map((id) => known.get(id)!);
});
const selectedRow = computed(() => rows.value.find((row) => row.id === selected.value));
const wire = computed<Spec>(() => ({ ...wireDefaults,
  ...(config.value.overrides?.[selected.value] || {}) }));
const legacy = computed(() => Number(wire.value.strand_columns) > 0);
const perBundle = computed<number | null>(() => {
  const total = Number(selectedRow.value?.strands);
  const bundles = Number(wire.value.parallel_bundles);
  return Number.isInteger(total) && total > 0 && Number.isInteger(bundles) &&
    bundles > 0 && total % bundles === 0 ? total / bundles : null;
});
const flattened = computed(() => wire.value.wire_type !== "solid" &&
  (perBundle.value || 0) > 1);
const assessmentFresh = computed(() => Boolean(props.assessment?.config &&
  canonical(props.assessment.config) === canonical(config.value)));
const assessmentRows = computed<Spec[]>(() => assessmentFresh.value ?
  props.assessment?.windings || [] : []);
const currentAssessment = computed(() => assessmentRows.value.find((row) => row.id === selected.value));
const automaticReady = computed(() => assessmentFresh.value &&
  Array.isArray(props.automaticPlan) && props.automaticPlan.length > 0);
const unknownIds = computed(() => {
  const ids = new Set(rows.value.map((row) => row.id));
  return [...new Set([
    ...Object.keys(config.value.overrides || {}), ...(config.value.order || []),
    ...plan.value.map((row) => row.winding_id),
  ].filter((id) => !ids.has(id)))];
});
const allocations = computed(() => rows.value.map((row) => {
  const indices: number[] = [];
  let assigned = 0;
  plan.value.forEach((entry, index) => {
    if (entry.winding_id === row.id) {
      indices.push(index + 1);
      if (Number.isInteger(entry.turns) && entry.turns > 0) assigned += entry.turns;
    }
  });
  return { id: row.id, assigned, turns: row.turns, indices,
    complete: Number.isInteger(row.turns) && row.turns > 0 && assigned === row.turns };
}));
const issues = computed(() => {
  const errors: string[] = [];
  for (const [key, label] of geometryFields) {
    const value = config.value[key];
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0)
      errors.push(`${label}请输入有限非负数值。`);
  }
  if (config.value.window_width > 0 && 2 * config.value.margin_x >= config.value.window_width)
    errors.push("左右留边合计必须小于窗口净宽。");
  if (config.value.window_height > 0 && 2 * config.value.margin_y >= config.value.window_height)
    errors.push("上下留边合计必须小于窗口净高。");
  for (const row of rows.value) {
    const entry = { ...wireDefaults, ...(config.value.overrides?.[row.id] || {}) };
    if (entry.strand_columns) continue; // Preserve old rectangular configurations until explicit conversion.
    if (!Number.isInteger(entry.parallel_bundles) || entry.parallel_bundles < 1)
      errors.push(`${row.id} 并绕束数必须为正整数。`);
    else if (Number.isInteger(row.strands) && row.strands % entry.parallel_bundles !== 0)
      errors.push(`${row.id} 并绕束数必须整除每匝总股数 ${row.strands}。`);
    if (!(Number.isFinite(entry.packing_factor) && entry.packing_factor > 0 && entry.packing_factor <= 1))
      errors.push(`${row.id} 束内填充系数应大于 0 且不超过 1。`);
    if (!(Number.isFinite(entry.flatten_ratio) && entry.flatten_ratio >= 1 && entry.flatten_ratio <= 100))
      errors.push(`${row.id} 压扁宽度倍数须在 1–100 之间。`);
    for (const key of ["outer_diameter", "bundle_diameter", "turns_per_layer"])
      if (!Number.isFinite(entry[key]) || entry[key] < 0)
        errors.push(`${row.id} 外径及每层匝数不得为负或空值。`);
    if (!Number.isInteger(entry.turns_per_layer)) errors.push(`${row.id} 每层匝数须为整数，0 表示自动。`);
  }
  if (manualMode.value) {
    if (!plan.value.length) errors.push("已启用手动排层但尚无层；请添加层或先评估后从自动方案生成。");
    if (plan.value.length > 1000) errors.push("手动方案最多允许 1000 层。");
    plan.value.forEach((entry, index) => {
      if (!Number.isInteger(entry.turns) || entry.turns < 1 || entry.turns > 10000000)
        errors.push(`第 ${index + 1} 层匝数须为 1–10⁷ 的整数。`);
      const resolved = assessmentRows.value.find((row) => row.id === entry.winding_id);
      if (resolved && entry.turns > resolved.turns_per_layer)
        errors.push(`第 ${index + 1} 层超过 ${entry.winding_id} 每层允许 ${resolved.turns_per_layer} 匝。`);
    });
    if (hasResolvedWindings.value) allocations.value.forEach((row) => {
      if (!row.complete) errors.push(`${row.id} 已分配 ${row.assigned} / ${row.turns} 匝，需完整且不重复分配。`);
    });
  }
  if (unknownIds.value.length) errors.push(`配置含当前已不存在的绕组：${unknownIds.value.join("、")}。可点击清理；未自动删除原设置。`);
  return errors;
});

watch(rows, (value) => {
  if (!value.some((row) => row.id === selected.value)) selected.value = value[0]?.id || "P";
}, { immediate: true });
watch(() => props.spec.winding_config?.layer_plan, (value) => {
  if (value?.length) manualMode.value = true;
  if (selectedLayer.value !== null && selectedLayer.value >= (value?.length || 0))
    selectedLayer.value = value?.length ? value.length - 1 : null;
}, { deep: true });
watch(() => canonical(config.value), (value) => {
  if (value === ownConfigSignature.value) ownConfigSignature.value = "";
  else {
    // Loading a different project must not reuse an earlier project's manual draft.
    manualMode.value = Boolean(plan.value.length);
    savedManualPlan.value = [];
  }
});

function updateConfig(nextConfig: Spec) {
  const next = clone(props.spec);
  next.winding_config = nextConfig;
  ownConfigSignature.value = canonical(nextConfig);
  localMessage.value = "设置已更改。请评估/刷新截面；如改动了电气匝数或线径，请先重新计算设计。";
  emit("change", next);
}
function moveWire(nextConfig:Spec){updateConfig(nextConfig);emit('preview',nextConfig);}
function geometry(key: string, event: Event) {
  const text = (event.target as HTMLInputElement).value;
  const next = clone(config.value);
  next[key] = text === "" ? null : Number(text) / 1000;
  updateConfig(next);
}
function setWire(key: string, value: any, scale = 1) {
  const next = clone(config.value);
  next.overrides ||= {};
  // Do not merge new-model defaults into an untouched old rectangular bundle.
  next.overrides[selected.value] = { ...(next.overrides[selected.value] || {}),
    [key]: value === "" ? null : typeof value === "string" && scale === 1 &&
      ["wire_type", "winding_style"].includes(key) ? value : Number(value) / scale };
  updateConfig(next);
}
function setNumericWire(key: string, event: Event, scale = 1) {
  setWire(key, (event.target as HTMLInputElement).value, scale);
}
function moveWinding(step: number) {
  const ids = rows.value.map((row) => row.id);
  const index = ids.indexOf(selected.value), target = index + step;
  if (index < 0 || target < 0 || target >= ids.length) return;
  [ids[index], ids[target]] = [ids[target]!, ids[index]!];
  updateConfig({ ...clone(config.value), order: ids });
}
function convertLegacy() {
  const next = clone(config.value);
  next.overrides[selected.value] = { ...wireDefaults,
    outer_diameter: Number(wire.value.outer_diameter) || 0 };
  updateConfig(next);
}
function toggleManual(event: Event) {
  const enable = (event.target as HTMLInputElement).checked;
  manualMode.value = enable;
  if (!enable) {
    savedManualPlan.value = clone(plan.value);
    updateConfig({ ...clone(config.value), layer_plan: [] });
  } else if (savedManualPlan.value.length) {
    selectedLayer.value = 0;
    updateConfig({ ...clone(config.value), layer_plan: clone(savedManualPlan.value) });
  }
}
function refresh() {
  localMessage.value = "";
  emit("preview", clone(config.value));
}
function useAutomatic() {
  if (!automaticReady.value) {
    localMessage.value = "请先评估当前窗口与线束，取得后端自动排层结果。";
    return;
  }
  if (manualMode.value && plan.value.length &&
    !window.confirm("将用当前自动方案替换手动逐层方案。是否继续？")) return;
  manualMode.value = true;
  selectedLayer.value = 0;
  updateConfig({ ...clone(config.value), layer_plan: clone(props.automaticPlan!), turn_positions:{} });
}
function editLayer(index: number, key: string, value: any) {
  const next = clone(config.value);
  if (key === "winding_style" && value === "") delete next.layer_plan[index][key];
  else next.layer_plan[index][key] = key === "turns" ? value === "" ? null : Number(value) : value;
  updateConfig(next);
}
function addLayer() {
  if (plan.value.length >= 1000) { localMessage.value = "手动方案最多 1000 层。"; return; }
  const next = clone(config.value);
  const index = selectedLayer.value;
  const position = index === null ? next.layer_plan.length : index + 1;
  const id = index === null ? selected.value : next.layer_plan[index]?.winding_id || selected.value;
  next.layer_plan.splice(position, 0, { winding_id: id, turns: 1, section_id:'SEC_'+crypto.randomUUID().replaceAll('-','') });
  identifyLayers(next.layer_plan);
  manualMode.value = true; selectedLayer.value = position;
  updateConfig(next);
}
function removeLayer() {
  if (selectedLayer.value === null) return;
  const next = clone(config.value);
  next.layer_plan.splice(selectedLayer.value, 1);
  selectedLayer.value = next.layer_plan.length ? Math.min(selectedLayer.value, next.layer_plan.length - 1) : null;
  updateConfig(next);
}
function moveLayer(step: number) {
  const index = selectedLayer.value;
  if (index === null) return;
  const target = index + step;
  if (target < 0 || target >= plan.value.length) return;
  const next = clone(config.value);
  [next.layer_plan[index], next.layer_plan[target]] = [next.layer_plan[target], next.layer_plan[index]];
  selectedLayer.value = target; updateConfig(next);
}
function splitLayer() {
  const index = selectedLayer.value;
  if (index === null) return;
  const entry = plan.value[index];
  if (!entry || !Number.isInteger(entry.turns) || entry.turns < 2 || plan.value.length >= 1000) {
    localMessage.value = "仅可拆分匝数不少于 2 的整数层，且总层数不得超过 1000。";
    return;
  }
  const first = Math.floor(entry.turns / 2);
  const next = clone(config.value);
  const second={...entry,turns:entry.turns-first,section_id:'SEC_'+crypto.randomUUID().replaceAll('-','')};
  next.layer_plan.splice(index, 1, { ...entry, turns: first }, second);
  identifyLayers(next.layer_plan);
  selectedLayer.value = index + 1; updateConfig(next);
}
function clearUnknown() {
  if (!window.confirm("仅清理当前不存在绕组的几何设置与排层记录，是否继续？")) return;
  const next = clone(config.value), ids = new Set(rows.value.map((row) => row.id));
  next.order = next.order.filter((id: string) => ids.has(id));
  next.overrides = Object.fromEntries(Object.entries(next.overrides).filter(([id]) => ids.has(id)));
  next.layer_plan = next.layer_plan.filter((row: Spec) => ids.has(row.winding_id));
  updateConfig(next);
}
function mm(value: any) { return value === null || value === undefined ? "" : Number((Number(value) * 1000).toPrecision(10)); }
</script>

<template>
  <section class="winding-editor" aria-labelledby="winding-editor-title">
    <header class="we-heading">
      <div><span class="we-eyebrow">T1 · 可绕制预评估</span><h3 id="winding-editor-title">窗口、等效线束与交错绕制</h3></div>
      <button type="button" class="we-primary" :disabled="previewBusy || !hasResolvedWindings" @click="refresh">
        {{ previewBusy ? "正在评估…" : "评估 / 刷新截面" }}
      </button>
    </header>
    <p class="we-note">骨架净窗口的单侧轴向 × 径向截面。所有尺寸以 mm 输入；按比例显示每束等效截面，不逐根绘制细丝。</p>
    <p v-if="!hasResolvedWindings" class="we-alert" role="status">请先完成一次有效的变压器计算，取得实际匝数、线径与总股数。自动匝数未算出前不生成排层，也不凭磁芯 Wa 猜窗口宽高。</p>
    <p v-else class="we-note">几何评估基于当前已计算绕组；如已修改电气匝数、线径、股数或输出路数，请先重新计算设计，再刷新截面。</p>

    <fieldset class="we-box"><legend>1 · 净窗口与绝缘</legend>
      <div class="we-grid">
        <label v-for="[key, label, hint] in geometryFields" :key="key" class="we-field">
          <span>{{ label }}</span><span class="we-unit-input"><input type="number" min="0" step="any" :value="mm(config[key])" :aria-label="label" @change="geometry(key, $event)" /><span>mm</span></span>
          <small>{{ hint }}</small>
        </label>
      </div>
    </fieldset>

    <fieldset class="we-box"><legend>2 · 由骨架向外的绕组顺序</legend>
      <div class="we-table-scroll"><table class="we-table">
        <thead><tr><th>选择</th><th>绕组</th><th>总匝数</th><th>单根股数 × 并绕根数</th><th>单股裸铜线径</th><th>窗口容量 / 层</th></tr></thead>
        <tbody><tr v-for="row in rows" :key="row.id" :class="{ 'we-selected': selected === row.id }" @click="selected = row.id">
          <td><input type="radio" name="winding-selection" :aria-label="`编辑 ${row.id} 绕组`" :checked="selected === row.id" @change="selected = row.id" /></td>
          <td><strong>{{ row.id }}</strong><small class="we-block">{{ row.name }}</small></td>
          <td>{{ row.turns ? fmt(row.turns, '匝') : '待计算' }}</td>
          <td>{{ row.strands ? `${fmt(row.strands, '股')} × ${row.parallel_wires||1} 根` : '待计算' }}</td>
          <td>{{ row.bare_diameter ? fmt(row.bare_diameter * 1000, 'mm') : '待计算' }}</td>
          <td>{{ assessmentRows.find((item) => item.id === row.id)?.capacity ?? '待评估' }}</td>
        </tr></tbody>
      </table></div>
      <div class="we-actions"><button type="button" :disabled="selected === rows[0]?.id" @click="moveWinding(-1)">所选绕组上移</button><button type="button" :disabled="selected === rows[rows.length - 1]?.id" @click="moveWinding(1)">所选绕组下移</button></div>
      <p class="we-note">自动排层按此顺序连续绕制；手动逐层模式以第 4 节的实体层顺序为准。</p>
    </fieldset>

    <fieldset v-if="selectedRow" class="we-box"><legend>3 · {{ selected }} 等效线束与层绕</legend>
      <div v-if="legacy" class="we-alert"><p>保留旧版矩形束 {{ wire.strand_columns }} 列设置。未自动转换，以免改变原有排布。</p><button type="button" @click="convertLegacy">转换为等效圆 / 压扁线束</button></div>
      <div class="we-grid">
        <label class="we-field"><span>线材类型</span><select :value="wire.wire_type" :disabled="legacy" @change="setWire('wire_type', ($event.target as HTMLSelectElement).value)"><option value="auto">自动 · 多股利兹 / 单股铜线</option><option value="solid">普通铜线 · 不压扁</option><option value="litz">利兹线 · 等面积压扁</option></select></label>
        <label class="we-field"><span>绕制方式</span><select :value="wire.winding_style" :disabled="legacy" @change="setWire('winding_style', ($event.target as HTMLSelectElement).value)"><option v-for="style in styles" :value="style.value">{{ style.label }}</option></select></label>
        <label class="we-field"><span>每根线内分束数</span><input type="number" min="1" max="10000000" step="1" :value="wire.parallel_bundles" :disabled="legacy" @change="setNumericWire('parallel_bundles', $event)" /><small>只划分单根线内已有股数；线圈并绕根数在左侧磁件参数中设置。</small></label>
        <label class="we-field"><span>每束股数（自动分配）</span><output>{{ perBundle === null ? '待确认总股数 / 束数' : `${perBundle} 股 / 束` }}</output><small>{{ selectedRow.strands || '待计算' }} 总股 ÷ {{ wire.parallel_bundles }} 束；不重复增加铜截面积。</small></label>
        <label class="we-field"><span>单股含漆外径</span><span class="we-unit-input"><input type="number" min="0" step="any" :value="mm(wire.outer_diameter)" @change="setNumericWire('outer_diameter', $event, 1000)" /><span>mm</span></span><small>0 = 裸铜线径 + 第 1 节含漆外径增量。</small></label>
        <label class="we-field"><span>整束未压扁外径（优先实测）</span><span class="we-unit-input"><input type="number" min="0" step="any" :value="mm(wire.bundle_diameter)" :disabled="legacy" @change="setNumericWire('bundle_diameter', $event, 1000)" /><span>mm</span></span><small>0 = 后端按单股含漆外径、每束股数与填充系数估算。</small></label>
        <label class="we-field"><span>束内填充系数</span><input type="number" min="0.000001" max="1" step="any" :value="wire.packing_factor" :disabled="legacy" @change="setNumericWire('packing_factor', $event)" /><small>默认 0.75 仅为估算，实测整束外径优先。</small></label>
        <label class="we-field"><span>利兹线压扁宽度倍数</span><input type="number" min="1" max="100" step="any" :value="wire.flatten_ratio" :disabled="legacy || !flattened" @change="setNumericWire('flatten_ratio', $event)" /><small>{{ flattened ? '默认宽 ×1.5、高 ÷1.5，截面积保持不变。' : '单股或普通铜线不压扁，实际倍数固定为 1。' }}</small></label>
        <label class="we-field"><span>每层匝数上限</span><input type="number" min="0" max="10000000" step="1" :value="wire.turns_per_layer" :disabled="legacy" @change="setNumericWire('turns_per_layer', $event)" /><small>0 = 后端按有效窗口容量自动排层；手动每层也不能超过此上限。</small></label>
      </div>
      <div v-if="currentAssessment" class="we-facts"><span>等效束宽 <strong>{{ fmt(currentAssessment.bundle_width * 1000, 'mm') }}</strong></span><span>等效束高 <strong>{{ fmt(currentAssessment.bundle_height * 1000, 'mm') }}</strong></span><span>每层允许 <strong>{{ fmt(currentAssessment.turns_per_layer, '匝') }}</strong></span><span>实际层数 <strong>{{ fmt(currentAssessment.layers, '层') }}</strong></span></div>
    </fieldset>

    <fieldset class="we-box"><legend>4 · 逐层排布与交错绕制</legend>
      <div class="we-toolbar"><label class="we-checkbox"><input type="checkbox" :checked="manualMode" @change="toggleManual" />启用手动逐层排布</label><button type="button" :disabled="!automaticReady || previewBusy" @click="useAutomatic">从已评估自动方案生成</button></div>
      <p class="we-note">同一绕组可分配到第 1、3 等不连续层。先生成自动方案、拆分层，再上下移动；也可手动添加。每层前的绝缘按紧邻的内侧层判断：同绕组用“同绕组层间绝缘”，不同绕组用“不同绕组间绝缘”。交错绕制时，请按下表的相邻关系调整对应厚度。</p>
      <p v-if="!automaticReady" class="we-note">生成自动方案前，请点击右上角“评估 / 刷新截面”；仅使用后端返回的实际排层，不推测未计算的匝数。</p>
      <template v-if="manualMode">
        <div class="we-layer-scroll"><table class="we-table we-layer-table"><thead><tr><th>选择</th><th>实体层</th><th>绕组</th><th>本层匝数</th><th>本层绕法</th><th>本层前绝缘</th><th>厚度 / mm</th></tr></thead><tbody>
          <tr v-for="(entry, index) in plan" :key="index" :class="{ 'we-selected': selectedLayer === index }" @click="selectedLayer = index">
            <td><input type="radio" name="physical-layer-selection" :aria-label="`选择第 ${index + 1} 层`" :checked="selectedLayer === index" @change="selectedLayer = index" /></td><td>L{{ index + 1 }}</td>
            <td><select :aria-label="`第 ${index + 1} 层绕组`" :value="entry.winding_id" @change="editLayer(index, 'winding_id', ($event.target as HTMLSelectElement).value)"><option v-for="row in rows" :value="row.id">{{ row.id }}</option><option v-if="!rows.some((row) => row.id === entry.winding_id)" :value="entry.winding_id">{{ entry.winding_id }} · 已不存在</option></select></td>
            <td><input type="number" min="1" max="10000000" step="1" :aria-label="`第 ${index + 1} 层匝数`" :value="entry.turns" @change="editLayer(index, 'turns', ($event.target as HTMLInputElement).value)" /></td>
            <td><select :aria-label="`第 ${index + 1} 层绕法`" :value="entry.winding_style || ''" @change="editLayer(index, 'winding_style', ($event.target as HTMLSelectElement).value)"><option value="">跟随该绕组</option><option v-for="style in styles" :value="style.value">{{ style.label }}</option></select></td>
            <td class="we-interface-label">{{ layerInsulation[index].label }}</td>
            <td>{{ layerInsulation[index].thickness == null ? '—' : mm(layerInsulation[index].thickness) }}</td>
          </tr><tr v-if="!plan.length"><td colspan="7" class="we-empty">尚未添加实体层。新层初值为 1 匝，请按实际方案修改。</td></tr>
        </tbody></table></div>
        <div class="we-actions"><button type="button" :disabled="plan.length >= 1000 || !rows.length" @click="addLayer">添加层</button><button type="button" :disabled="selectedLayer === null" @click="removeLayer">删除所选层</button><button type="button" :disabled="selectedLayer === null || selectedLayer === 0" @click="moveLayer(-1)">所选层上移</button><button type="button" :disabled="selectedLayer === null || selectedLayer === plan.length - 1" @click="moveLayer(1)">所选层下移</button><button type="button" :disabled="selectedLayer === null || plan.length >= 1000" @click="splitLayer">拆分所选层</button></div>
        <div class="we-allocations"><div v-for="row in allocations" :key="row.id" :class="{ 'we-allocation-ok': row.complete }"><strong>{{ row.id }}</strong><span>已分配 {{ row.assigned }} / {{ row.turns || '待计算' }} 匝</span><small>实体层：{{ row.indices.length ? row.indices.join('、') : '未分配' }}</small><span>{{ row.complete ? '分配完整' : '待补齐 / 调整' }}</span></div></div>
      </template>
      <p v-else class="we-note">当前为整绕组自动连续排层。关闭手动模式会保留本次编辑草稿，设计文件仅保存当前生效的自动方案；重新启用可恢复本次草稿。</p>
    </fieldset>

    <div v-if="issues.length" class="we-alert" role="status"><strong>输入与分配提示</strong><ul><li v-for="issue in issues" :key="issue">{{ issue }}</li></ul><button v-if="unknownIds.length" type="button" @click="clearUnknown">清理不存在绕组的设置</button></div>
    <div v-if="assessmentFresh && assessment?.configured" class="we-assessment" :class="{ 'we-overflow': assessment.fits === false }" role="status"><strong>{{ assessment.fits === true ? '当前几何预评估：窗口可容纳' : assessment.fits === false ? '当前几何预评估：窗口存在溢出' : '当前几何方案需修正后再评估' }}</strong><div v-if="assessment.fits === true || assessment.fits === false" class="we-facts"><span>所需径向高度 <b>{{ fmt(assessment.required_height * 1000, 'mm') }}</b></span><span>高度余量 <b>{{ fmt(assessment.height_margin * 1000, 'mm') }}</b></span><span>物理层数 <b>{{ fmt(assessment.total_layer_count, '层') }}</b></span></div><p v-for="warning in assessment.warnings" :key="warning">{{ warning }}</p></div>
    <p v-else-if="assessment" class="we-note">{{ assessmentFresh ? '请填写大于 0 的窗口净宽与净高，再进行评估。' : '配置已变化，旧几何评估不再用于显示容量。请刷新截面。' }}</p>
    <p v-if="previewError" class="we-error" role="alert">{{ previewError }}</p><p v-if="localMessage" class="we-note" role="status">{{ localMessage }}</p>
    <WindingCanvas v-if="assessment?.editable && assessment?.cross_sections?.length" :assessment="assessment" :config="config" @change="moveWire" />
    <p class="we-disclaimer">几何预评估不是量产工艺或安规结论。骨架挡墙仅作示意，不占用所填净窗口；未包含引线、交叉线、圆角和制造公差。利兹线压扁为等面积假设，须用实物外径与绝缘确认。所有设置不回写电气股数、DCR、铜损、漏感或耦合系数 kij。</p>
  </section>
</template>

<style scoped>
.winding-editor { display: grid; gap: 15px; padding: 22px; background: #fff; border: 1px solid #dce4ed; border-radius: 16px; font-size: 15px; line-height: 1.65; min-width: 0; }
.we-heading, .we-toolbar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; }
.we-heading h3 { font-size: 20px; color: #1e3859; margin: 3px 0 0; }
.we-eyebrow { color: #356ba8; font-size: 14px; font-weight: 650; }
.we-note, .we-disclaimer { color: #607188; margin: 0; font-size: 14px; line-height: 1.8; }
.we-disclaimer { border-top: 1px solid #e3e9f0; padding-top: 14px; }
.we-box { margin: 0; border: 1px solid #dce4ed; border-radius: 10px; padding: 16px; min-width: 0; }
.we-box legend { padding: 0 8px; color: #284f80; font-size: 16px; font-weight: 650; }
.we-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 15px 22px; }
.we-field { display: grid; gap: 5px; align-content: start; font-size: 15px; min-width: 0; }
.we-field > span:first-child { font-weight: 550; }
.we-field small, .we-block { color: #687a90; font-size: 14px; line-height: 1.65; }
.we-block { display: block; white-space: normal; }
.winding-editor input:not([type="checkbox"]):not([type="radio"]), .winding-editor select { width: 100%; min-width: 0; min-height: 40px; background: #fff; border: 1px solid #cdd8e5; border-radius: 6px; padding: 7px 10px; font-size: 15px; color: #243b57; }
.winding-editor input:disabled, .winding-editor select:disabled { background: #f0f3f7; color: #718198; }
.we-unit-input { display: flex; align-items: center; gap: 9px; }
.we-unit-input > span { font-size: 14px; min-width: 27px; color: #6f7f91; }
.we-field output { display: block; padding: 7px 10px; min-height: 40px; background: #f2f6fb; border-radius: 6px; color: #294f7e; }
.winding-editor button { min-height: 38px; border: 1px solid #cbd7e4; background: #fff; border-radius: 7px; padding: 8px 13px; font-size: 14px; line-height: 1.45; color: #2c4d78; }
.winding-editor button:hover:not(:disabled) { background: #eff5fd; border-color: #80a9d9; }
.winding-editor button.we-primary { color: #fff; background: #285f9f; border-color: #285f9f; font-weight: 600; }
.winding-editor button.we-primary:hover:not(:disabled) { background: #194d8b; }
.we-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.we-table-scroll, .we-layer-scroll { overflow: auto; max-width: 100%; border: 1px solid #e1e7ef; border-radius: 7px; }
.we-layer-scroll { max-height: 420px; margin-top: 12px; }
.we-table { width: 100%; border-collapse: collapse; font-size: 14px; min-width: 620px; }
.we-table th { background: #eff4f9; font-weight: 650; color: #375474; text-align: left; white-space: nowrap; }
.we-table td, .we-table th { padding: 11px 10px; border-bottom: 1px solid #e5ebf2; vertical-align: middle; }
.we-table tr:last-child td { border-bottom: none; }
.we-table tbody tr { cursor: pointer; }
.we-table tbody tr.we-selected td { background: #edf5ff; }
.we-table input[type="radio"], .we-checkbox input { width: 18px; height: 18px; accent-color: #285f9f; flex-shrink: 0; }
.we-layer-table td:nth-child(4) { min-width: 110px; width: 20%; }
.we-layer-table td:nth-child(5) { min-width: 185px; }
.we-layer-table td:nth-child(3) { min-width: 110px; }
.we-interface-label { min-width: 205px; }
.we-checkbox { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; min-height: 38px; }
.we-empty { color: #697b91; padding: 20px !important; text-align: center; cursor: default; }
.we-facts { display: flex; flex-wrap: wrap; gap: 10px 22px; background: #f1f6fc; border-radius: 7px; padding: 11px 13px; margin-top: 14px; font-size: 14px; color: #49617f; }
.we-facts strong, .we-facts b { color: #234d7e; margin-left: 5px; }
.we-allocations { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
.we-allocations > div { display: grid; grid-template-columns: auto 1fr; gap: 3px 11px; padding: 11px; background: #fff8eb; border: 1px solid #eddfbc; border-radius: 7px; color: #7a5a1d; font-size: 14px; }
.we-allocations > .we-allocation-ok { background: #eef8f4; border-color: #cfe7dc; color: #286c55; }
.we-allocations small { font-size: 14px; grid-column: 1 / -1; }
.we-alert { border: 1px solid #ead6a4; background: #fff9eb; color: #80601f; padding: 13px 15px; border-radius: 8px; font-size: 14px; }
.we-alert p { margin: 0 0 10px; }
.we-alert ul { margin: 8px 0 0; padding-left: 21px; }
.we-alert button { margin-top: 10px; }
.we-assessment { border: 1px solid #bddfce; background: #eff8f3; border-radius: 9px; padding: 14px; color: #27674d; font-size: 14px; }
.we-assessment > strong { font-size: 16px; }
.we-assessment > p { margin: 10px 0 0; }
.we-assessment.we-overflow { border-color: #efc6bd; background: #fff4ef; color: #984b35; }
.we-error { background: #fff0ed; color: #a74635; border: 1px solid #efc9c1; border-radius: 7px; padding: 12px 14px; font-size: 14px; }
@media (max-width: 850px) { .we-grid, .we-allocations { grid-template-columns: 1fr; } .winding-editor { padding: 16px; } .we-box { padding: 13px; } }
</style>
