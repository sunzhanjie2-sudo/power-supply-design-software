<script setup lang="ts">
import { ref, computed, watch } from "vue";
import type { Spec } from "./types";
import { fmt } from "./types";
const props = defineProps<{ value?: Spec; rows?: Spec[]; rules?: Spec; types?: Spec; evaluation?: Spec; note?: string }>();
const emit = defineEmits<{ change: [value: Spec] }>();
const selected = ref(""), draft = ref<Spec>({}), error = ref("");
const zone = ref("I"), reason = ref(""), overrides = ref<Spec>({});
const clone = (v: any) => JSON.parse(JSON.stringify(v));
const config = computed<Spec>(() => ({ version: 1, zone: "I", items: {}, overrides: {}, override_reason: "", ...props.value }));
const row = computed(() => props.rows?.find(r => r.ref === selected.value));
const evaluated = computed(() => props.evaluation?.rows?.find((r: Spec) => r.ref === selected.value));
const stateLabels: Spec = {pass:"模型内满足",review:"超出限值",undefined:"待补充/复核",na:"仅记录资料"};
function initial(ref: string) { return {manufacturer:"",model:"",package:"",conditions:"",note:"",capacitor_type:"unknown",voltage_V:null,ripple_A:null,power_W:null,...config.value.items?.[ref]}; }
function reset() { draft.value = initial(selected.value); error.value=""; }
function choose(ref: string) {
  if (selected.value && JSON.stringify(draft.value)!==JSON.stringify(initial(selected.value)) && !window.confirm("当前器件还有未应用的修改。放弃这些修改并切换器件？")) return;
  selected.value=ref; reset();
}
watch(() => props.rows, rows => { if (!rows?.some(r=>r.ref===selected.value)) {selected.value=rows?.[0]?.ref||"";reset();} }, {immediate:true});
watch(() => props.value, () => {reset();zone.value=config.value.zone;reason.value=config.value.override_reason;overrides.value=Object.fromEntries(Object.entries(config.value.overrides).map(([k,v])=>[k,Number(v)*100]));}, {immediate:true});
function apply() {
  const next=clone(config.value), item=clone(draft.value);
  for(const key of ["voltage_V","ripple_A","power_W"]) {
    const n=item[key]; item[key]=n===""||n===null||n===undefined?null:Number(n);
    if(item[key]!==null&&(!Number.isFinite(item[key])||item[key]<=0)){error.value="额定值应为正数，未知请留空。";return;}
  }
  next.items={...next.items,[selected.value]:item}; error.value="";emit("change",next);
}
function applyPolicy() {
  const custom: Spec={};
  for(const [key,raw] of Object.entries(overrides.value)) {
    if(raw===""||raw===null||raw===undefined)continue;
    const n=Number(raw)/100;
    if(!Number.isFinite(n)||n<=0||n>1){error.value="自定义允许使用率须在 0～100% 之间。";return;}
    custom[key]=n;
  }
  if(Object.keys(custom).length&&!reason.value.trim()){error.value="请填写自定义规则的依据/原因。";return;}
  error.value="";emit("change",{...clone(config.value),zone:zone.value,overrides:custom,override_reason:reason.value});
}
function rating(ref: string) {
  const r=config.value.items?.[ref]||{};
  return [["voltage_V","V"],["ripple_A","A RMS"],["power_W","W"]].filter(([key])=>r[key]!=null).map(([key,unit])=>fmt(r[key],unit)).join(" / ")||"额定值待补充";
}
</script>

<template>
  <section class="card component-management">
    <div class="card-heading"><h3>关键器件 BOM 与降额管理</h3><span class="pill">按位号独立保存</span></div>
    <p class="hint">厂家、型号、封装和额定值在这里统一维护。多路输出的整流器件、电容各自独立；隐藏器件资料保留在设计 JSON 中，不参与当前拓扑检查。</p>
    <details class="policy"><summary>降额规则：{{ config.zone }} 区 · 查看 / 自定义</summary>
      <p class="hint">{{ note }}</p>
      <label>规范分区（定义须确认）<select v-model="zone"><option>I</option><option>II</option></select></label>
      <div class="table-wrap"><table class="data-table"><thead><tr><th>规则</th><th>I 区</th><th>II 区</th><th>自定义允许使用率 %</th><th>来源位置</th></tr></thead>
        <tbody><tr v-for="(rule,key) in rules" :key="key"><td>{{rule[0]}}</td><td>{{rule[1]===null?'未列':fmt(rule[1]*100,'%')}}</td><td>{{rule[2]===null?'未列':fmt(rule[2]*100,'%')}}</td><td><input v-model="overrides[key]" type="number" min="0.01" max="100" step="any" placeholder="留空采用规范" /></td><td>{{rule[3]}}</td></tr></tbody></table></div>
      <label>自定义依据 / 原因<input v-model="reason" placeholder="采用自定义比例时必填" /></label>
      <button class="button" @click="applyPolicy">应用降额规则</button>
    </details>
    <p class="notice">{{ evaluation ? '当前已计算工况的初筛。每个检查项独立判定，不代表整颗器件或全边界验证通过。' : '尚无匹配当前资料的计算结果。请应用器件资料后重新计算，不能用旧快照的结论代替。' }}</p>
    <div class="table-wrap bom-list"><table class="data-table"><thead><tr><th>位号</th><th>用途 / 输出归属</th><th>厂家</th><th>型号</th><th>封装</th><th>额定值</th><th>初筛</th></tr></thead><tbody>
      <tr v-for="r in rows" :key="r.ref" :class="{active:r.ref===selected}" @click="choose(r.ref)"><td><button class="text-button" @click.stop="choose(r.ref)">{{r.ref}}</button></td><td>{{r.role}}</td><td>{{config.items[r.ref]?.manufacturer||'待填'}}</td><td>{{config.items[r.ref]?.model||'待填'}}</td><td>{{config.items[r.ref]?.package||'待填'}}</td><td>{{rating(r.ref)}}</td><td>{{evaluation?.rows?.find((x:Spec)=>x.ref===r.ref)?.status||'待计算'}}</td></tr>
    </tbody></table></div>
    <form v-if="row" class="component-editor" @submit.prevent="apply">
      <h3>{{selected}} · {{row.role}}</h3>
      <div class="editor-fields">
        <label>厂家<input v-model="draft.manufacturer" /></label><label>型号<input v-model="draft.model" /></label><label>封装<input v-model="draft.package" /></label>
        <label v-if="['mos','diode','capacitor'].includes(row.kind)">{{row.kind==='mos'?'MOS Vds 耐压 / V':row.kind==='diode'?'二极管 Vrrm / V':'电容耐压 / V'}}<input v-model="draft.voltage_V" type="number" min="0" step="any" placeholder="未知留空" /></label>
        <label v-if="row.kind==='capacitor'">纹波电流能力 / A RMS<input v-model="draft.ripple_A" type="number" min="0" step="any" placeholder="按实际频率/温度修正" /></label>
        <label v-if="row.kind==='capacitor'">电容类型<select v-model="draft.capacitor_type"><option v-for="(title,key) in types" :value="key">{{title}}</option></select></label>
        <label v-if="row.kind==='resistor'">额定功耗 / W<input v-model="draft.power_W" type="number" min="0" step="any" placeholder="单颗电阻额定功率" /></label>
        <label>额定条件 / 规格书来源<input v-model="draft.conditions" placeholder="温度、频率、版本等" /></label><label>备注<input v-model="draft.note" /></label>
      </div>
      <div v-if="error" class="error-box">{{error}}</div>
      <button type="submit" class="button primary">应用当前器件</button>
      <p class="hint">这里只录入 BOM 与额定值，不会自动替换 Rds(on)、Qg、ESR 或导入曲线。非完整采购 BOM，数量按当前模型的单颗参考器件统计。</p>
    </form>
    <div v-if="evaluated" class="table-wrap"><table class="data-table"><thead><tr><th>检查项</th><th>实际应力</th><th>额定值</th><th>使用率</th><th>允许因数</th><th>允许应力</th><th>结论 / 限制</th></tr></thead><tbody><tr v-for="c in evaluated.checks" :key="c.id"><td>{{c.name}}</td><td>{{fmt(c.value,c.unit)}}</td><td>{{fmt(c.rating,c.unit)}}</td><td>{{c.utilization===null?'—':fmt(c.utilization*100,'%')}}</td><td>{{c.factor===null?'未列':fmt(c.factor*100,'%')}}</td><td>{{fmt(c.limit,c.unit)}}</td><td><strong :class="{'over-limit':c.state==='review'}">{{stateLabels[c.state]}}</strong><p class="hint">{{c.note}}</p><small>{{c.source}}</small></td></tr></tbody></table></div>
  </section>
</template>

<style scoped>
.component-management { display:grid;gap:16px; }
.component-management input,.component-management select { width:100%;min-width:100px;min-height:40px;padding:9px 11px;border:1px solid #cbd7e6;border-radius:7px;background:#fff;color:var(--ink);font:inherit; }
.component-management input::placeholder {color:#8090a4;}
.component-management input:focus,.component-management select:focus {outline:2px solid #98bce9;outline-offset:1px;}
.bom-list {max-height:390px;overflow:auto;}
.bom-list th {position:sticky;top:0;background:var(--surface,#fff);z-index:1;}
.bom-list tr.active {background:#e7f1ff;color:#17365d;}
.bom-list tr {cursor:pointer;}
.editor-fields {display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;margin:16px 0;}
label {display:grid;gap:7px;}
.policy {padding:14px;border:1px solid #ccd9e7;border-radius:10px;display:grid;gap:12px;}
.policy summary {cursor:pointer;font-weight:700;}
.over-limit {color:#b3261e;}
</style>
