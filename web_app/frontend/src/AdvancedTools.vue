<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch, inject, type ComputedRef } from 'vue';
const modalTarget=inject<HTMLElement|string>('power-modal-target','body');
const native=inject<ComputedRef<boolean>>('power-native',computed(()=>false));
import { getBlob, post, request, download } from './api';
import AdvancedNumber from './AdvancedNumber.vue';
import { frozenDesigns, type FrozenDesign } from './advancedMemory';
import { compensationInputs, type CompensationInterpretation } from './advancedInputs';
import type { Snapshot, Spec } from './types';
import { fmt, topologyNames } from './types';

const props = defineProps<{ mode: 'loop' | 'compensation' | 'efficiency' | 'review'; job: string; caseId: string; spec: Spec; dirty: boolean; busy: boolean }>();
const emit = defineEmits<{ applied: [updates: Spec] }>();
const pending = ref(false), error = ref(''), status = ref(''), action = ref(''), result = ref<Spec | null>(null), image = ref(''), imageOpen = ref(false), operationId = ref('');
let generation = 0, imageAbort: AbortController | null = null;
const ready = computed(() => !!props.job && !props.dirty && !props.busy && !pending.value);
const psr = computed(() => props.spec.feedback_mode === 'PSR-MP6005');
const compensationKeys = computed(() => (props.spec.controller_type === 'type2' || ((props.spec.controller_type || 'auto') === 'auto' && props.spec.control_mode === 'Peak Current Mode')) ? ['KP', 'fz1', 'fp1'] : ['KP', 'fz1', 'fz2', 'fp1', 'fp2']);
const outputCount = computed(() => Array.isArray(props.spec.outputs) && props.spec.outputs.length ? props.spec.outputs.length : 1);
const unavailable = computed(() => !props.job ? '请先运行计算，生成当前工程快照。' : props.dirty ? '参数已修改，请先重新计算，再运行分析。' : props.busy ? '主计算运行中，请稍候。' : '');
const fc = ref(Number(props.spec.fc_target) || 3200), pm = ref(Number(props.spec.pm_target) || 65), controller = ref(props.spec.controller_type || 'auto'), loadOutput = ref(1);
const net = ref('opamp3'), direction = ref<'fwd' | 'rev'>('fwd'), type2 = ref(false), compInputs = ref<Spec>({});
const savedInterpretation = ref<CompensationInterpretation>(props.spec.__comp?.encoding === 'si' ? 'si' : 'desktop'), compatibilityWarnings = ref<string[]>([]);
type Part = { key: string; label: string; value: number; unit: string; scale?: number };
const networks = [{ key: 'opamp3', name: '普通运放补偿网络' }, { key: 'gm3', name: '跨导运放补偿网络' }, { key: 'tl431nf', name: 'TL431 + 光耦 · 无快车道' }, { key: 'tl431f', name: 'TL431 + 光耦 · 快车道' }];
const part = (key: string, label: string, value: number, unit = 'kΩ', scale = 1000): Part => ({ key, label, value, unit, scale });
const cap = (key: string, label: string, value: number): Part => part(key, label, value, 'nF', 1e-9);
const commonOpto = [part('CTR', '光耦电流传输比 CTR', 1, '倍', 1), part('Rpullup', '光耦上拉电阻 Rpullup', 20000), cap('Copto', '光耦结电容 Copto', 2e-9)];
const forward: Record<string, Part[]> = {
  opamp3: [part('R1', '上分压电阻 R1', 10000), part('Vref', '基准电压 Vref', 2.5, 'V', 1)],
  gm3: [part('R2', '下分压电阻 R2', 10000), part('R1u', '上分压电阻 R1（二型必填）', 100000), part('gm', '跨导 gm', .002, 'mS', .001)],
  tl431nf: [part('R1', '上分压电阻 R1', 40000), part('R_LED', 'LED 限流电阻 R_LED', 1000), ...commonOpto],
  tl431f: [part('R1', '上分压电阻 R1', 40000), ...commonOpto],
};
const reverse: Record<string, Part[]> = {
  opamp3: [part('R1', '上分压电阻 R1', 10000), part('R2', '反馈串联电阻 R2', 10000), part('R3', '输入支路电阻 R3', 10000), cap('C1', '反馈串联电容 C1', 10e-9), cap('C2', '反馈并联电容 C2（0=不焊）', 10e-9), cap('C3', '输入支路电容 C3（0=二型）', 10e-9)],
  gm3: [part('gm', '跨导 gm', .002, 'mS', .001), part('R1', '上分压电阻 R1', 100000), part('R2', '下分压电阻 R2', 10000), part('R3', '阻抗串联电阻 R3', 10000), cap('C1', '并联 R1 电容 C1（0=二型）', 2.2e-9), cap('C2', '阻抗串联电容 C2', 10e-9), cap('C3', '阻抗并联电容 C3（0=不焊）', 10e-9)],
  tl431nf: [...commonOpto, part('R_LED', 'LED 限流电阻 R_LED', 1000), part('R1', '上分压电阻 R1', 40000), part('R2', 'FB→阴极电阻 R2', 40000), part('R3', 'Vout→FB 电阻 R3', 4000), cap('C1', 'FB→阴极电容 C1', 3.8e-9), cap('C2', '光耦外接电容 C2', 3.3e-9), cap('C3', 'Vout→FB 电容 C3', .4e-9)],
  tl431f: [...commonOpto, part('R_LED', 'Vout→LED 电阻 R_LED', 200, 'Ω', 1), part('R1', '上分压电阻 R1', 40000), cap('C1', 'FB→阴极电容 C1', 4e-9), part('R_pz', '第二支路电阻 R_pz', 15, 'Ω', 1), cap('C_pz', '第二支路电容 C_pz', 790e-9), cap('C2', '光耦外接电容 C2', 1e-9)],
};
const partFields = computed(() => (direction.value === 'fwd' ? forward : reverse)[net.value] || []);
function resetParts() { compInputs.value = Object.fromEntries(partFields.value.map(field => [field.key, field.value])); }
watch([net, direction], resetParts, { immediate: true, flush: 'sync' });
function restoreCompState() {
  const saved = props.spec.__comp;
  if (!saved) return;
  const label = String(saved.key || saved.topo || '');
  const key = networks.find(network => label === network.key || (network.key === 'tl431nf' ? label.includes('无快车道') : network.key === 'tl431f' ? label.includes('快车道') : network.key === 'gm3' ? label.includes('跨导') : label.includes('普通运放')))?.key;
  if (key) net.value = key;
  direction.value = saved.dir === 'rev' ? 'rev' : 'fwd';
  type2.value = !!saved.type2;
  resetParts();
  const restored = compensationInputs(saved, compInputs.value, savedInterpretation.value);
  compInputs.value = restored.values;
  compatibilityWarnings.value = restored.warnings;
}
restoreCompState();
const vars = [part('f_sw', '开关频率', 250000, 'kHz', 1000), part('L', '功率级电感 / 反激励磁电感', 8e-6, 'µH', 1e-6), part('N', '变压器匝比 Np/Ns', .5, '倍', 1), part('C_out', '输出滤波电容', 330e-6, 'µF', 1e-6), part('Rds_on', 'MOS 导通电阻', .05, 'mΩ', .001), part('Bmax', '设计最大磁通密度', .3, 'T', 1), part('Lm_forward', '正激变压器励磁电感', .0002, 'µH', 1e-6), part('C_clamp', '正激钳位电容', 100e-9, 'nF', 1e-9)];
const allowedVars = computed(() => vars.filter(item => {
  const t = props.spec.topology, multi = outputCount.value > 1;
  if (item.key === 'f_sw') return t !== 'QR-FLYBACK' && !psr.value;
  if (item.key === 'Lm_forward' || item.key === 'C_clamp') return t === 'ACF-FORWARD';
  if (item.key === 'N') return ['FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'].includes(t);
  if (item.key === 'Bmax') return !['FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD'].includes(t);
  if (item.key === 'C_out') return !multi && t !== 'ACF-FORWARD';
  if (item.key === 'Rds_on') return t !== 'ACF-FORWARD';
  if (item.key === 'L' && multi && t === 'ACF-FORWARD') return false;
  return true;
}));
const sweepVar = ref('f_sw'), minimum = ref(125000), maximum = ref(500000), points = ref(17), load = ref(1), target = ref(.9);
const sweepField = computed(() => allowedVars.value.find(item => item.key === sweepVar.value) || allowedVars.value[0] || vars[0]);
function resetBounds() { const v = Number(props.spec[sweepVar.value]) || sweepField.value.value; minimum.value = v * .5; maximum.value = v * 2; }
watch(allowedVars, available => { if (!available.some(item => item.key === sweepVar.value)) sweepVar.value = available[0]?.key || 'L'; }, { immediate: true });
watch(sweepVar, resetBounds, { immediate: true });
const optimization = ref<Spec[]>([]), iterations = ref(6), population = ref(5);
function addOptimization() {
  const field = allowedVars.value.find(item => !optimization.value.some(row => row.variable === item.key));
  if (!field || optimization.value.length >= 3) return;
  const v = Number(props.spec[field.key]) || field.value;
  optimization.value.push({ variable: field.key, minimum: v * .5, maximum: v * 2 });
}
addOptimization();
function optimizationField(row: Spec) { return vars.find(item => item.key === row.variable) || vars[0]; }
function resetOptimizationBounds(row: Spec) { const field = optimizationField(row), v = Number(props.spec[row.variable]) || field.value; row.minimum = v * .5; row.maximum = v * 2; }
const cornerMin = ref(Number(props.spec.V_in_min ?? props.spec.V_in) || 30), cornerMax = ref(Number(props.spec.V_in_max ?? props.spec.V_in) || 30), includeNominal = ref(false), fractions = ref([.1, .5, 1]);
const chosenFractions = ref([.1, .5, 1]), extraFraction = ref(.25), freezeName = ref('');
const freezePending = ref(false), freezeError = ref('');
const titles: Record<string, string> = { tune: '环路自动整定', compensate: '补偿网络设计', sweep: '效率参数扫描', find_target: '查找目标效率', optimize: '效率多变量优化', corners: '固定硬件角点分析', loop_response: '多路响应分析' };
const fieldNames: Record<string, string> = { KP: '补偿器增益 KP', fz1: '零点 fz1', fz2: '零点 fz2', fp1: '极点 fp1', fp2: '极点 fp2', fc: '穿越频率', fc_target: '目标穿越频率', pm: '相位裕度', min_pm: '全部穿越最小相位裕度', gm_db: '增益裕度', gm_infinite: '无有限增益裕度穿越', boost: '相位提升', boost_required: '所需相位提升', K: 'Venable K 因子', feasible: '目标可实现', closed_loop_stable: '闭环极点稳定', inner_spectral_radius: '周期内环谱半径', eta: '模型效率', nit: '迭代次数', evaluations: '已评估候选数', limited_budget: '受限计算预算', ok: '优化器收敛', R_lower: '下分压电阻 R_lower', fp_opto: '光耦自身极点', R_LED_max: 'LED 电阻上限', Vref: '基准电压', Vref_check: '基准电压回代', target_value: '达到目标的参数值', target_eta: '目标模型效率', fixed_hardware: '固定同一套硬件', snapshot_unchanged: '原设计快照未改变', same_requirements: '需求一致', target: '目标值', actual: '回代值', realized: '回代值', error: '误差 / 说明', match: '一致', within_tolerance: '误差在容许范围', buildable: '物理网络可实现', controller_type: '补偿器类型', comp_type: '补偿器类型', action: '分析类型', case: '输入工况', load_output: '扰动注入输出编号', feedback_output: '主反馈输出编号' };
function label(key: string) { return fieldNames[key] || vars.find(item => item.key === key)?.label || key; }
function valueText(value: any, key = ''): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') {
    const variable = vars.find(field => field.key === (key === 'target_value' ? result.value?.variable : key));
    if (variable) return fmt(value / (variable.scale || 1), variable.unit, 6);
    if (key === 'eta' || key === 'load_frac') return fmt(value * 100, '%', 5);
    if (key === 'target_eta') return fmt(value * 100, '%', 5);
    if (/^(fz[12]|fp[12]|fc|fc_target|fp_opto|frequency)$/.test(key)) return fmt(value, 'Hz', 5);
    if (/^(pm|min_pm|boost|boost_required)$/.test(key)) return fmt(value, '°', 5);
    if (/^(C\d|Copto|C_pz|C2_tot)$/.test(key)) return fmt(value * 1e9, 'nF', 5);
    if (/^R/.test(key)) return fmt(value, 'Ω', 5);
    if (key === 'gm') return fmt(value * 1e3, 'mS', 5);
    if (key === 'gm_db') return fmt(value, 'dB', 5);
    return fmt(value, '', 6);
  }
  if (Array.isArray(value)) return value.length ? value.map(item => typeof item === 'object' ? String(item?.note || item?.message || item?.name || '详细校核项') : String(item)).join('；') : '无';
  if (typeof value === 'object') return Object.entries(value).filter(([, v]) => typeof v !== 'object').map(([k, v]) => `${label(k)}：${valueText(v, k)}`).join('；') || '见下方明细';
  return String(value);
}
const scalarEntries = (source: any) => source && typeof source === 'object' ? Object.entries(source).filter(([, value]) => value === null || ['number', 'string', 'boolean'].includes(typeof value)) : [];
const resultNotes = computed(() => {
  const notes = result.value?.notes || result.value?.warnings || [];
  return Array.isArray(notes) ? notes.map(String) : [String(notes)];
});
const updates = computed(() => result.value?.spec_updates || {});
const canApply = computed(() => ready.value && Object.keys(updates.value).length > 0 && !(result.value?.feasible === false));
function clearImage() { if (image.value) URL.revokeObjectURL(image.value); image.value = ''; imageAbort?.abort(); imageAbort = null; }
function invalidate() {
  if (pending.value && operationId.value) void post(`/operations/${operationId.value}/cancel`, {}).catch(() => undefined);
  generation++; pending.value = false; result.value = null; error.value = ''; status.value = ''; operationId.value = ''; clearImage();
}
watch(() => [props.job, props.caseId, props.mode], invalidate);
watch(() => props.dirty, (dirty) => {
  if (dirty && pending.value) {
    invalidate();
    status.value = '输入已改变，已丢弃旧候选结果。';
  }
});
watch(() => props.job, () => {
  fc.value = Number(props.spec.fc_target) || 3200;
  pm.value = Number(props.spec.pm_target) || 65;
  controller.value = props.spec.controller_type || 'auto';
  cornerMin.value = Number(props.spec.V_in_min ?? props.spec.V_in) || 30;
  cornerMax.value = Number(props.spec.V_in_max ?? props.spec.V_in) || 30;
  loadOutput.value = Math.min(loadOutput.value, outputCount.value);
  optimization.value = optimization.value.filter(row => allowedVars.value.some(field => field.key === row.variable));
  if (!optimization.value.length) addOptimization();
  savedInterpretation.value = props.spec.__comp?.encoding === 'si' ? 'si' : 'desktop';
  restoreCompState();
});
onBeforeUnmount(invalidate);
async function run(kind: string, options: Spec) {
  if (!ready.value) return;
  const rev = ++generation, originJob = props.job;
  pending.value = true; result.value = null; error.value = ''; action.value = kind; clearImage(); status.value = '等待后台计算进程…';
  try {
    const op = await post<{ id: string }>(`/jobs/${originJob}/action`, { action: kind, options: { ...options, case: props.caseId } });
    if (rev !== generation) { void post(`/operations/${op.id}/cancel`, {}).catch(() => undefined); return; }
    operationId.value = op.id;
    while (rev === generation) {
      const row = await request<Spec>(`/operations/${op.id}`);
      if (rev !== generation) return;
      if (row.state === 'failed') throw new Error(row.error?.message || row.error || '分析失败');
      if (row.state === 'cancelled') throw new Error('分析已取消，未应用任何参数');
      status.value = row.message || (row.state === 'running' ? '后台计算中，可取消或继续查看其他结果…' : '排队中…');
      if (row.state === 'succeeded' || row.state === 'done') {
        result.value = row.result;
        status.value = '分析完成，工程参数尚未改变。';
        if (row.result?.has_chart) {
          imageAbort = new AbortController();
          const blob = await getBlob(`/files/${op.id}`, imageAbort.signal);
          if (rev === generation) image.value = URL.createObjectURL(blob);
        }
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 450));
    }
  } catch (e: any) { if (rev === generation && e.name !== 'AbortError') error.value = e.message; }
  finally { if (rev === generation) pending.value = false; }
}
async function cancel() {
  if (!operationId.value) return;
  try { await post(`/operations/${operationId.value}/cancel`, {}); status.value = '已请求取消，后台将在安全检查点停止。'; }
  catch (e: any) { error.value = e.message; }
}
function tune() { void run('tune', { fc: fc.value, pm: pm.value, controller_type: controller.value }); }
function compensate() {
  if (partFields.value.some(field => !Number.isFinite(Number(compInputs.value[field.key])))) { error.value = '请完整填写有限的阻容参数。'; return; }
  void run('compensate', { key: net.value, direction: direction.value, type2: type2.value, inputs: { ...compInputs.value } });
}
function sweep(kind: 'sweep' | 'find_target') {
  if (![minimum.value, maximum.value].every(Number.isFinite) || !(minimum.value > 0 && maximum.value > minimum.value)) { error.value = '扫描下限应大于 0，且上限应大于下限。'; return; }
  if (!Number.isInteger(points.value) || points.value < 5 || points.value > 41) { error.value = '扫描点数必须为 5–41 的整数，不能超出计算预算。'; return; }
  if (!Number.isFinite(load.value) || load.value < .01 || load.value > 1) { error.value = '计算负载比例须为 1%–100%。'; return; }
  if (kind === 'find_target' && (!Number.isFinite(target.value) || target.value < .01 || target.value > 1)) { error.value = '目标模型效率须为 1%–100%。'; return; }
  void run(kind, { variable: sweepVar.value, minimum: minimum.value, maximum: maximum.value, points: points.value, load_frac: load.value, ...(kind === 'find_target' ? { target_eta: target.value } : {}) });
}
function optimize() {
  if (!optimization.value.length || optimization.value.some(row => !(row.minimum > 0 && row.maximum > row.minimum)) || new Set(optimization.value.map(row => row.variable)).size !== optimization.value.length) { error.value = '请选择 1–3 个互不重复的变量，并填写正数递增范围。'; return; }
  if (!Number.isInteger(iterations.value) || iterations.value < 1 || iterations.value > 20 || !Number.isInteger(population.value) || population.value < 5 || population.value > 10) { error.value = '优化预算须为 1–20 次迭代、5–10 种群倍率。'; return; }
  if (!Number.isFinite(load.value) || load.value < .01 || load.value > 1) { error.value = '计算负载比例须为 1%–100%。'; return; }
  void run('optimize', { variables: optimization.value.map(row => row.variable), bounds: optimization.value.map(row => [row.minimum, row.maximum]), load_frac: load.value, maxiter: iterations.value, popsize: population.value, seed: 0 });
}
function corners() {
  if (!chosenFractions.value.length) { error.value = '请至少选择一个负载点。'; return; }
  void run('corners', { v_in_min: cornerMin.value, v_in_max: cornerMax.value, load_fracs: [...chosenFractions.value].sort((a, b) => a - b), include_nominal: includeNominal.value });
}
function addFraction() {
  if (!(extraFraction.value > 0 && extraFraction.value <= 1)) { error.value = '自定义负载应在 0%–100% 之间且不为 0。'; return; }
  if (fractions.value.length >= 8 && !fractions.value.includes(extraFraction.value)) { error.value = '最多设置 8 个负载点，避免角点组合计算过多。'; return; }
  fractions.value = [...new Set([...fractions.value, extraFraction.value])].sort((a, b) => a - b);
  if (!chosenFractions.value.includes(extraFraction.value)) chosenFractions.value.push(extraFraction.value);
}
function apply() { if (canApply.value) { emit('applied', JSON.parse(JSON.stringify(updates.value))); status.value = '候选参数已写入左侧输入，请重新计算以更新结果与报告。'; } }
function copyPartsToReverse() {
  const source = result.value?.parts;
  if (!source) return;
  direction.value = 'rev'; resetParts();
  for (const field of reverse[net.value] || []) if (Number.isFinite(Number(source[field.key]))) compInputs.value[field.key] = Number(source[field.key]);
}
async function freeze(slot: 'a' | 'b') {
  if (!ready.value) return;
  freezePending.value = true; freezeError.value = '';
  const identity = props.job, selectedCase = props.caseId;
  try {
    const snap = await request<Snapshot>(`/jobs/${identity}/result`);
    if (props.job !== identity || props.dirty) throw new Error('冻结期间参数已变化，请重新计算后再冻结。');
    frozenDesigns.value[slot] = { name: freezeName.value.trim() || `方案 ${slot.toUpperCase()}`, snapshot: structuredClone(snap), frozenAt: new Date().toLocaleString('zh-CN'), caseId: selectedCase };
  } catch (e: any) { freezeError.value = e.message; }
  finally { freezePending.value = false; }
}
const frozen = computed(() => frozenDesigns.value);
const requirements = (value: FrozenDesign | null) => value ? JSON.stringify([value.snapshot.spec.topology, value.snapshot.spec.V_in_min, value.snapshot.spec.V_in_max, value.snapshot.spec.V_out, value.snapshot.spec.P_out, (value.snapshot.spec.outputs || []).map((o: Spec) => [o.V_out, o.P_out])]) : '';
const comparable = computed(() => !!frozen.value.a && !!frozen.value.b && requirements(frozen.value.a) === requirements(frozen.value.b));
const metrics = [ { key: 'eta', name: '模型效率', unit: '%', scale: 100, from: 'losses' }, { key: 'P_total', name: '总损耗', unit: 'W', scale: 1, from: 'losses' }, { key: 'I_L_pk', name: '电感 / 原边峰值电流', unit: 'A', scale: 1, from: 'operating_point' }, { key: 'V_sw_max', name: 'MOS 最大电压', unit: 'V', scale: 1, from: 'operating_point' }, { key: 'ripple_pp', name: '输出低频纹波', unit: 'mV', scale: 1000, from: 'operating_point' }, { key: 'dT', name: '主磁件温升', unit: 'K', scale: 1, from: 'magnetics' }, { key: 'fc', name: '穿越频率', unit: 'Hz', scale: 1, from: 'loop' }, { key: 'min_pm', name: '全部穿越最小 PM', unit: '°', scale: 1, from: 'loop' } ];
function frozenValue(slot: 'a' | 'b', caseId: string, metric: typeof metrics[number]): number | null {
  const s = frozen.value[slot]?.snapshot.cases.find(item => item.id === caseId)?.summary as any;
  const value = s?.[metric.from]?.[metric.key];
  return value !== null && value !== undefined && Number.isFinite(Number(value)) ? Number(value) * metric.scale : null;
}
function delta(caseId: string, metric: typeof metrics[number]) { const a = frozenValue('a', caseId, metric), b = frozenValue('b', caseId, metric); return a !== null && b !== null ? b - a : null; }
const differences = computed(() => {
  if (!frozen.value.a || !frozen.value.b) return [];
  const a = frozen.value.a.snapshot.spec, b = frozen.value.b.snapshot.spec;
  return [...new Set([...Object.keys(a), ...Object.keys(b)])].filter(key => !key.startsWith('_') && JSON.stringify(a[key]) !== JSON.stringify(b[key])).map(key => ({ key, a: a[key], b: b[key] }));
});
function exportComparison() {
  download(new Blob([JSON.stringify({ schema: 'power-design.frozen-comparison.v1', a: frozen.value.a, b: frozen.value.b, same_requirements: comparable.value }, null, 2)], { type: 'application/json' }), '冻结方案对比.json');
}
</script>

<template>
  <section class="advanced-tools">
    
    <div v-if="unavailable" class="at-notice">{{ unavailable }} 以下分析始终基于已计算快照，不会混用未计算的输入。</div>

    <section v-if="mode === 'loop'" class="card at-card">
      <header class="at-heading"><div><h3>Venable K 因子自动整定</h3><p>选择当前 {{ caseId }} 工况设计补偿器；先检查候选结果，再显式写入参数。</p></div><span class="at-badge">{{ psr ? 'MP6005 物理 COMP 网络' : 'SSR 外环' }}</span></header>
      <div class="at-grid">
        <AdvancedNumber v-model="fc" label="目标穿越频率 fc" unit="kHz" :scale="1000" :min="0" />
        <AdvancedNumber v-model="pm" label="目标相位裕度 PM" unit="°" :min="1" :max="89" />
        <label class="at-field"><span>补偿器类型</span><select v-model="controller"><option value="auto">自动（沿用原版控制模式规则）</option><option value="type2">二型补偿</option><option value="type3">三型补偿</option></select></label>
      </div>
      <div class="at-actions"><button class="primary" :disabled="!ready" @click="tune">计算候选补偿参数</button></div>
      <p class="at-limit">沿用 EXE 的整定算法。耦合多路模型需检查周期内环与闭环稳定性；过高目标频率、相位提升不足或不适用的模型会明确提示，不会静默写回。最终仍需实机 FRA 与负载阶跃验证。</p>
      <div v-if="outputCount > 1" class="at-subsection"><h4>多路输出闭环响应</h4><div class="at-actions"><label class="at-inline">负载扰动注入路<select v-model.number="loadOutput"><option v-for="n in outputCount" :key="n" :value="n">OUT{{ n }}</option></select></label><button :disabled="!ready" @click="run('loop_response', { load_output: loadOutput })">计算各路响应</button></div><p class="at-limit">只有主反馈路闭环调节；其他输出仅显示参考跟踪和所选负载电流扰动响应，不能等同于独立稳压环。</p></div>
    </section>

    <section v-if="mode === 'compensation'" class="card at-card">
      <header class="at-heading"><div><h3>补偿电路参数与参考图</h3><p>四类参考网络跟随当前环路类型；标准二型只使用KP、fz1、fp1并保留高频极点。支持阻容反推与回代。</p></div></header>
      <div v-if="psr" class="at-notice">MP6005 使用独立的 Rcomp / Ccomp / Cpole 物理网络，不使用 SSR 的四种参考电路。请在 PSR 参数区编辑，或在环路页运行 MP6005 整定。</div>
      <div v-if="spec.__comp" class="at-compatibility"><label class="at-field"><span>已导入补偿配置的数值解释</span><select v-model="savedInterpretation" @change="restoreCompState"><option value="desktop">按桌面格式：保存数值 × 单位前缀（默认）</option><option value="si">旧文件数值已是 SI：前缀仅作标签</option></select></label><p class="at-limit">未标记的文件按桌面正式格式读取，例如 20 + k → 20 kΩ。不根据大小猜测单位；仅当确认旧文件的数值已经是 SI 时，主动选择第二项。切换会重新恢复该文件的补偿表单；网页新保存的补偿参数统一使用 SI 数值与空前缀。</p><p v-for="warning in compatibilityWarnings" :key="warning" class="at-error">{{ warning }}</p></div>
      <div class="at-grid">
        <label class="at-field"><span>参考网络</span><select v-model="net"><option v-for="network in networks" :key="network.key" :value="network.key">{{ network.name }}</option></select></label>
        <label class="at-field"><span>计算方向</span><select v-model="direction"><option value="fwd">正向：KP / fz / fp → 阻容</option><option value="rev">反向：阻容 → KP / fz / fp</option></select></label>
        <label class="at-checkbox"><input v-model="type2" type="checkbox" :disabled="direction === 'rev' || psr || !['opamp3', 'gm3'].includes(net)" />旧版简化（不含高频极点；正向默认跟随环路类型）</label>
      </div>
      <div class="at-targets"><span v-for="key in compensationKeys" :key="key">{{ key }} <strong>{{ valueText(spec[key], key) }}</strong></span></div>
      <h4>{{ direction === 'fwd' ? '给定初始阻容，其余由已计算快照中的零极点求解' : '完整物理网络参数（不焊的简化支路电容填 0）' }}</h4>
      <div class="at-grid"><AdvancedNumber v-for="field in partFields" :key="field.key" v-model="compInputs[field.key]" :label="field.label" :unit="field.unit" :scale="field.scale || 1" :min="0" :disabled="psr" /></div>
      <div class="at-actions"><button class="primary" :disabled="!ready || psr" @click="compensate">{{ direction === 'fwd' ? '计算阻容并显示电路图' : '反推零极点并显示电路图' }}</button><button v-if="result?.parts && action === 'compensate' && direction === 'fwd'" @click="copyPartsToReverse">将计算阻容带入反向表单</button></div>
      <p class="at-limit">二型简化支路保留原版定义，不另行改变零极点个数。TL431 快车道的高频增益地板与光耦固有极点可能使理想目标不可实现，请以回代校核和可实现性提示为准。电路连接与器件位号沿用桌面版，参考图采用统一界面配色。</p>
    </section>

    <template v-if="mode === 'efficiency'">
      <section class="card at-card">
        <header class="at-heading"><div><h3>效率参数扫描与目标查找</h3><p>当前 {{ caseId }} · 扫描设计变量，不覆盖已有计算结果。</p></div></header>
        <div class="at-grid">
          <label class="at-field"><span>扫描变量</span><select v-model="sweepVar"><option v-for="field in allowedVars" :key="field.key" :value="field.key">{{ field.label }}</option></select></label>
          <AdvancedNumber v-model="minimum" label="扫描下限" :unit="sweepField.unit" :scale="sweepField.scale" :min="0" />
          <AdvancedNumber v-model="maximum" label="扫描上限" :unit="sweepField.unit" :scale="sweepField.scale" :min="0" />
          <label class="at-field"><span>扫描点数（5–41）</span><input v-model.number="points" type="number" min="5" max="41" step="1" /></label>
          <AdvancedNumber v-model="load" label="计算负载比例" unit="%" :scale=".01" :min=".01" :max="1" />
          <AdvancedNumber v-model="target" label="目标模型效率" unit="%" :scale=".01" :min="0" :max="1" />
        </div>
        <div class="at-actions"><button class="primary" :disabled="!ready" @click="sweep('sweep')">运行参数扫描</button><button :disabled="!ready" @click="sweep('find_target')">扫描并查找目标效率</button></div>
        <p class="at-limit">沿用 EXE 的损耗模型；扫描允许重新设计候选磁件，并非固定 BOM 的角点评估。多路支路电容与功率需在各路配置中修改；MP6005 不扫描固定开关频率。模型效率不包含全部辅助、EMI、布局与温度损耗，不保证实测效率。</p>
      </section>
      <section class="card at-card">
        <header class="at-heading"><div><h3>有界多变量效率优化</h3><p>最多 3 个变量，采用小预算搜索。候选仅用于探索，应用后需重新检查全部设计约束。</p></div><button :disabled="optimization.length >= 3 || pending" @click="addOptimization">增加优化变量</button></header>
        <div class="at-table-wrap"><table><thead><tr><th>优化变量</th><th>下限</th><th>上限</th><th>操作</th></tr></thead><tbody><tr v-for="(row, index) in optimization" :key="index"><td><select v-model="row.variable" @change="resetOptimizationBounds(row)"><option v-for="field in allowedVars" :key="field.key" :value="field.key">{{ field.label }}</option></select></td><td><AdvancedNumber v-model="row.minimum" label="" :unit="optimizationField(row).unit" :scale="optimizationField(row).scale" :min="0" /></td><td><AdvancedNumber v-model="row.maximum" label="" :unit="optimizationField(row).unit" :scale="optimizationField(row).scale" :min="0" /></td><td><button @click="optimization.splice(index, 1)">移除</button></td></tr></tbody></table></div>
        <div class="at-grid at-small-grid"><label class="at-field"><span>最大迭代数（1–20）</span><input v-model.number="iterations" type="number" min="1" max="20" /></label><label class="at-field"><span>种群倍率（5–10）</span><input v-model.number="population" type="number" min="5" max="10" /></label></div>
        <div class="at-actions"><button class="primary" :disabled="!ready || !optimization.length" @click="optimize">搜索较高模型效率的候选方案</button></div>
        <p class="at-limit">使用与上方相同的负载比例。搜索优先倾向 CCM，但不是所有器件选型、饱和、温升、稳定性约束的全局可行性证明；达到迭代预算也不代表找到全局最优。</p>
      </section>
    </template>

    <template v-if="mode === 'review'">
      <section class="card at-card">
        <header class="at-heading"><div><h3>固定硬件角点评估</h3><p>冻结同一套磁芯、匝数、线径与股数，评估不同输入和负载，不在角点自动重新选芯。</p></div></header>
        <div class="at-grid"><AdvancedNumber v-model="cornerMin" label="输入电压下限" unit="V" :min="0" /><AdvancedNumber v-model="cornerMax" label="输入电压上限" unit="V" :min="0" /><label class="at-checkbox"><input v-model="includeNominal" type="checkbox" />包含当前标称电压点</label></div>
        <div class="at-actions"><span>负载点</span><label v-for="fraction in fractions" :key="fraction" class="at-checkbox"><input v-model="chosenFractions" type="checkbox" :value="fraction" />{{ fmt(fraction * 100, '%') }}</label></div>
        <div class="at-actions"><AdvancedNumber v-model="extraFraction" label="自定义负载点" unit="%" :scale=".01" :min=".01" :max="1" /><button @click="addFraction">加入负载点</button><button class="primary" :disabled="!ready || !chosenFractions.length" @click="corners">运行固定硬件角点</button></div>
        <p class="at-limit">各路负载按同一比例缩放，此处不替代非反馈路交叉调整率的独立轻载/重载组合。失败角点将保留错误，不以相邻有效数据替代。允许的输入范围必须覆盖当前计算工况。</p>
      </section>
      <section class="card at-card">
        <header class="at-heading"><div><h3>冻结 A / B 方案对比</h3><p>冻结计算快照与 snapshot_id，切换工程或重新计算后仍保留；只保存在本页浏览器内存，刷新会清除。</p></div></header>
        <div class="at-actions"><label class="at-field at-name"><span>当前方案名称</span><input v-model="freezeName" placeholder="例如：PQ20 / 250kHz / 三路输出" maxlength="80" /></label><button :disabled="!ready || freezePending" @click="freeze('a')">冻结当前为 A</button><button :disabled="!ready || freezePending" @click="freeze('b')">冻结当前为 B</button><button :disabled="!frozen.a && !frozen.b" @click="exportComparison">导出对比快照 JSON</button></div>
        <p v-if="freezeError" class="at-error">{{ freezeError }}</p>
        <div class="at-freezes"><div v-for="slot in (['a', 'b'] as const)" :key="slot"><strong>{{ slot.toUpperCase() }} · {{ frozen[slot]?.name || '尚未冻结' }}</strong><template v-if="frozen[slot]"><span>{{ topologyNames[frozen[slot]!.snapshot.spec.topology] || frozen[slot]!.snapshot.spec.topology }} · {{ frozen[slot]!.frozenAt }}</span><code>{{ frozen[slot]!.snapshot.snapshot_id }}</code><button @click="frozenDesigns[slot] = null">清除 {{ slot.toUpperCase() }}</button></template></div></div>
        <div v-if="frozen.a && frozen.b" class="at-comparison"><p :class="comparable ? 'at-success' : 'at-notice'">{{ comparable ? 'A / B 输入、输出需求一致，可比较设计取舍。' : '两方案拓扑或输入/输出需求不同，以下数字不可直接评判优劣。' }}</p><div v-for="caseKey in ['Vinmin', 'Vinmax']" :key="caseKey" class="at-table-wrap"><h4>{{ caseKey }} 同名工况对比</h4><table><thead><tr><th>指标</th><th>A · {{ frozen.a.name }}</th><th>B · {{ frozen.b.name }}</th><th>差值 B − A</th></tr></thead><tbody><tr v-for="metric in metrics" :key="metric.key"><td>{{ metric.name }}</td><td>{{ fmt(frozenValue('a', caseKey, metric), metric.unit, 5) }}</td><td>{{ fmt(frozenValue('b', caseKey, metric), metric.unit, 5) }}</td><td>{{ fmt(delta(caseKey, metric), metric.unit, 5) }}</td></tr></tbody></table></div><details v-if="differences.length"><summary>查看 {{ differences.length }} 项输入差异</summary><div class="at-table-wrap"><table><thead><tr><th>参数</th><th>A</th><th>B</th></tr></thead><tbody><tr v-for="difference in differences" :key="difference.key"><td>{{ label(difference.key) }}</td><td>{{ valueText(difference.a, difference.key) }}</td><td>{{ valueText(difference.b, difference.key) }}</td></tr></tbody></table></div></details></div>
      </section>
    </template>

    <section v-if="pending || error || result" class="card at-card at-results" aria-live="polite">
      <header class="at-heading"><div><h3>{{ titles[action] || '分析' }} · 结果</h3><p>{{ status }}</p></div><button v-if="pending && operationId" @click="cancel">取消后台分析</button></header>
      <p v-if="pending" class="at-pending"><span class="spinner" />{{ status }}</p><p v-if="error" role="alert" class="at-error">{{ error }}</p>
      <template v-if="result">
        <div v-if="result.feasible === false || result.buildable === false" class="at-notice">{{ result.feasible === false ? '当前目标不可实现，不能写入整定参数。' : '参考物理网络未完全实现理想目标，请先处理回代差异与提示。' }}</div>
        <div class="at-targets"><span v-for="[key, value] in scalarEntries(result).filter(([key]) => !['has_chart', 'media_type', 'action'].includes(key))" :key="key">{{ label(key) }} <strong>{{ valueText(value, key) }}</strong></span></div>
        <template v-for="section in ['design', 'achieved', 'parts', 'targets', 'realized', 'best']" :key="section"><div v-if="result[section] && scalarEntries(result[section]).length" class="at-table-wrap"><h4>{{ ({ design: '候选整定设计', achieved: '候选环路校验', parts: '物理器件参数', targets: '目标零极点', realized: '阻容回代结果', best: '优化候选参数' } as any)[section] }}</h4><table><thead><tr><th>参数</th><th>计算值</th></tr></thead><tbody><tr v-for="[key, value] in scalarEntries(result[section])" :key="key"><td>{{ label(key) }}</td><td>{{ valueText(value, key) }}</td></tr></tbody></table></div></template>
        <div v-if="result.checks" class="at-table-wrap"><h4>一致性与可实现性校核</h4><table v-if="Array.isArray(result.checks)"><thead><tr><th>校核项</th><th>目标</th><th>回代</th><th>一致性</th><th>说明</th></tr></thead><tbody><tr v-for="(check, index) in result.checks" :key="index"><td>{{ label(check.name || check.key || check.id || `校核 ${index + 1}`) }}</td><td>{{ valueText(check.target, check.name) }}</td><td>{{ valueText(check.actual, check.name) }}</td><td>{{ check.ok === undefined ? '—' : check.ok ? '一致' : '需复核' }}</td><td>{{ check.note || '—' }}</td></tr></tbody></table><table v-else><thead><tr><th>校核项</th><th>结果 / 说明</th></tr></thead><tbody><tr v-for="[key, value] in Object.entries(result.checks)" :key="key"><td>{{ label(key) }}</td><td>{{ valueText(value, key) }}</td></tr></tbody></table></div>
        <div v-if="result.rows?.length" class="at-table-wrap"><h4>扫描数据 · {{ sweepField.label }}</h4><table><thead><tr><th>参数值（{{ sweepField.unit }}）</th><th>模型效率</th></tr></thead><tbody><tr v-for="(row, index) in result.rows" :key="index"><td>{{ fmt(row.value / (sweepField.scale || 1), '', 6) }}</td><td>{{ row.eta === null ? '该点计算失败' : fmt(row.eta * 100, '%', 5) }}</td></tr></tbody></table></div>
        <div v-if="result.corners?.length" class="at-table-wrap"><h4>全部角点（{{ result.corners.length }} 个）</h4><table><thead><tr><th>编号</th><th>Vin / V</th><th>负载</th><th>状态</th><th>η</th><th>峰值电流 / A</th><th>MOS 电压 / V</th><th>纹波 / mV</th><th>温升 / K</th><th>最小 PM / °</th><th>需复核项</th></tr></thead><tbody><tr v-for="row in result.corners" :key="row.id"><td>{{ row.id }}</td><td>{{ fmt(row.V_in) }}</td><td>{{ fmt(row.load_frac * 100, '%') }}</td><td>{{ row.skipped ? '失败' : row.mode }}</td><td>{{ fmt(row.eta * 100, '%') }}</td><td>{{ fmt(row.I_L_pk) }}</td><td>{{ fmt(row.V_sw_max) }}</td><td>{{ fmt(row.ripple_pp * 1000) }}</td><td>{{ fmt(row.dT) }}</td><td>{{ fmt(row.min_pm) }}</td><td>{{ row.error || row.failed_checks?.join('、') || '—' }}</td></tr></tbody></table></div>
        <div v-if="result.worst" class="at-table-wrap"><h4>最坏值与对应角点</h4><table><thead><tr><th>指标</th><th>最坏值</th><th>对应工况</th></tr></thead><tbody><tr v-for="[key, value] in Object.entries(result.worst)" :key="key"><td>{{ ({ min_eta: '最低模型效率', max_I_L_pk: '最大峰值电流 / A', max_ripple_pp: '最大低频纹波 / V', max_V_sw_max: '最高 MOS 电压 / V', max_dT: '最大温升 / K', max_B_pk: '最大磁通密度 / T', min_pm: '最小相位裕度 / °', DCM_at_loads: '进入 DCM 的负载比例' } as any)[key] || key }}</td><td>{{ valueText(value, key === 'min_eta' ? 'eta' : key) }}</td><td>{{ result.worst_cases?.[key] ? `${result.worst_cases[key].id} · ${fmt(result.worst_cases[key].V_in, 'V')} · ${fmt(result.worst_cases[key].load_frac * 100, '%')}` : '—' }}</td></tr></tbody></table></div>
        <div v-if="Array.isArray(result.dc_load)" class="at-table-wrap"><h4>直流交叉负载响应 · ΔVout / ΔIload（V/A）</h4><table><thead><tr><th>观察输出</th><th v-for="(rail, index) in result.outputs" :key="rail.id">注入 {{ rail.id || `OUT${index + 1}` }}</th></tr></thead><tbody><tr v-for="(row, rowIndex) in result.dc_load" :key="rowIndex"><th>{{ result.outputs?.[rowIndex]?.id || `OUT${rowIndex + 1}` }}</th><td v-for="(value, colIndex) in row" :key="colIndex">{{ fmt(value, '', 5) }}</td></tr></tbody></table></div>
        <div v-if="resultNotes.length" class="at-notes"><p v-for="(note, index) in resultNotes" :key="index">{{ note }}</p></div>
        <div v-if="image" class="at-chart"><button class="at-chart-button" @click="imageOpen = true">放大图表 / 电路参考图</button><img :src="image" :alt="titles[action] + '图表'" @click="imageOpen = true" /></div>
        <div v-if="Object.keys(updates).length" class="at-apply"><p>以上为候选结果，当前工程未自动改变。写入后需重新计算，才会更新图表、检查项和报告。</p><button class="primary" :disabled="!canApply" @click="apply">{{ action === 'compensate' && direction === 'fwd' ? '保存补偿电路配置到工程' : '将候选参数写入输入区' }}</button></div>
      </template>
    </section>
    <Teleport :to="modalTarget"><div v-if="imageOpen && image" class="modal-backdrop" @click.self="imageOpen = false"><section class="modal at-image-modal"><header><h3>{{ titles[action] }} · {{ caseId }}</h3><button @click="imageOpen = false">关闭</button></header><img :src="image" :alt="titles[action]" /></section></div></Teleport>
  </section>
</template>

<style scoped>
.advanced-tools{display:grid;gap:20px;font-size:15px;line-height:1.65;color:#334155}.at-card{padding:24px;min-width:0}.at-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;margin-bottom:20px}.at-heading h3{font-size:20px;line-height:1.4;margin:0 0 5px;color:#0f172a}.at-heading p{margin:0;color:#64748b;font-size:15px}.at-badge{background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;border-radius:6px;padding:5px 9px;font-size:14px;white-space:nowrap}.at-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin-bottom:20px}.at-small-grid{max-width:650px;grid-template-columns:repeat(2,minmax(0,1fr));margin-top:18px}.at-field{display:grid;gap:7px;min-width:0}.at-field>span{font-size:15px}.advanced-tools input:not([type=checkbox]),.advanced-tools select{min-height:40px;max-width:100%;min-width:0;border:1px solid #cbd5e1;background:#fff;border-radius:8px;padding:7px 10px;font:inherit;color:#0f172a}.advanced-tools input:focus,.advanced-tools select:focus{outline:2px solid #93c5fd;outline-offset:1px}.advanced-tools button{min-height:38px;border:1px solid #cbd5e1;background:#fff;padding:7px 13px;border-radius:8px;color:#334155;font:inherit;font-size:15px;cursor:pointer}.advanced-tools button:hover:not(:disabled){background:#f1f5f9;border-color:#94a3b8}.advanced-tools button.primary{background:#1d4ed8;border-color:#1d4ed8;color:#fff}.advanced-tools button.primary:hover:not(:disabled){background:#1e40af}.advanced-tools button:disabled{opacity:.48;cursor:not-allowed}.at-actions{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin:16px 0}.at-checkbox{display:flex;gap:8px;align-items:center;min-height:40px;font-size:15px}.advanced-tools input[type=checkbox]{accent-color:#2563eb;width:18px;height:18px;flex:none}.at-inline{display:flex;gap:10px;align-items:center}.at-limit{font-size:14px;color:#64748b;margin:14px 0 0}.at-notice{background:#fffbeb;color:#92400e;border:1px solid #fde68a;border-radius:9px;padding:13px 15px;font-size:15px}.at-notice+.at-grid{margin-top:20px}.at-subsection{margin-top:24px;border-top:1px solid #e2e8f0;padding-top:20px}.advanced-tools h4{font-size:17px;color:#0f172a;margin:20px 0 12px}.at-targets{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}.at-targets>span{font-size:14px;border:1px solid #e2e8f0;background:#f8fafc;padding:8px 10px;border-radius:6px;display:flex;gap:10px;align-items:center}.at-targets strong{font-size:15px;font-weight:600;color:#0f172a}.at-table-wrap{max-width:100%;overflow-x:auto;margin-top:18px}.advanced-tools table{width:100%;border-collapse:collapse;text-align:left;font-size:15px}.advanced-tools th{color:#475569;background:#f8fafc;font-weight:600}.advanced-tools th,.advanced-tools td{padding:12px 13px;border-bottom:1px solid #e2e8f0;vertical-align:top}.advanced-tools td:first-child{color:#334155}.advanced-tools th{white-space:nowrap}.at-error{color:#b91c1c;background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px 15px;overflow-wrap:anywhere}.at-pending{display:flex;align-items:center;gap:12px;color:#1d4ed8}.at-notes{border-left:3px solid #93c5fd;padding:1px 15px;background:#f8fafc;margin:18px 0;font-size:14px}.at-chart{margin-top:22px}.at-chart img{width:100%;height:auto;background:white;cursor:zoom-in}.at-chart-button{display:block;margin:0 0 10px auto}.at-apply{border-top:1px solid #dbeafe;margin-top:22px;padding-top:18px}.at-apply p{color:#475569;font-size:14px}.at-name{flex:1;min-width:240px}.at-freezes{display:grid;grid-template-columns:1fr 1fr;gap:15px;margin:20px 0}.at-freezes>div{padding:18px;border:1px solid #dbeafe;border-radius:9px;background:#f8fafc;display:grid;gap:8px;min-width:0}.at-freezes strong{font-size:17px;color:#0f172a}.at-freezes span{font-size:14px;color:#64748b}.at-freezes code{font:12px/1.6 Consolas,monospace;overflow-wrap:anywhere}.at-freezes button{justify-self:start}.at-success{color:#166534;background:#f0fdf4;border:1px solid #bbf7d0;padding:12px 15px;border-radius:8px}.advanced-tools summary{cursor:pointer;font-size:15px;padding:15px 0;color:#1d4ed8}.at-image-modal{max-width:1400px;width:95vw;padding:20px}.at-image-modal>header{display:flex;align-items:center;justify-content:space-between;gap:12px}.at-image-modal img{width:100%;height:auto;max-height:80vh;object-fit:contain;background:white}
.at-freezes code{font-size:14px}.at-compatibility{background:#f8fafc;border:1px solid #e2e8f0;border-radius:9px;padding:16px;margin:18px 0}.at-compatibility .at-field{max-width:620px}
@media(max-width:1100px){.at-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.at-heading{flex-wrap:wrap}.at-freezes{grid-template-columns:1fr}}@media(max-width:600px){.at-card{padding:18px}.at-grid{grid-template-columns:1fr}.at-small-grid{grid-template-columns:1fr}.at-heading h3{font-size:19px}.at-actions{align-items:stretch}.at-actions>button{flex:1;min-width:150px}.advanced-tools th,.advanced-tools td{padding:10px}.at-targets>span{font-size:14px}.at-badge{white-space:normal}}
</style>
