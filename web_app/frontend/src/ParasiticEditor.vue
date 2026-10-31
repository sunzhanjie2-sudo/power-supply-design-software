<script setup lang="ts">
import { computed } from 'vue';
import type { Spec } from './types';
const props=defineProps<{spec:Spec; schema:Spec}>();
const emit=defineEmits<{change:[value:Spec]}>();
const config=computed(()=>props.spec.parasitic_config || {});
const count=computed(()=>props.spec.outputs?.length || 1);
function change(key:string,value:any,rail?:string){
  const next=structuredClone(config.value);
  if(rail){next.rails ||= {};next.rails[rail] ||= {};next.rails[rail][key]=value;}
  else next[key]=value;
  emit('change',next);
}
function value(key:string,field:Spec,rail?:string){
  let number=rail?config.value.rails?.[rail]?.[key]:config.value[key];
  if(number===undefined && ['cj','cj_free','cj_default'].includes(key)) number=config.value.cj_default ?? (props.spec.spice_config?.diode_cj_pf ?? 20)*1e-12;
  return (number ?? field.default)*field.scale;
}
const fields=computed(()=>Object.entries(props.schema.fields).filter(([key])=>key!=='coss_aux'||props.spec.topology==='ACF-FORWARD') as [string,Spec][]);
const railFields=computed(()=>Object.entries(props.schema.rail_fields).filter(([key])=>key!=='cj_free'||props.spec.topology==='ACF-FORWARD') as [string,Spec][]);
</script>
<template>
  <div class="parasitic-editor">
    <label class="field"><strong>计算方式</strong><select :value="config.mode || 'fast'" @change="change('mode',($event.target as HTMLSelectElement).value)">
      <option value="fast">快速计算 · 沿用原有波形</option><option value="transient">寄生瞬态 · 反激局部估算 / 正激物理周期</option>
    </select></label>
    <p class="hint">{{ schema.note }}</p>
    <p class="hint" v-if="spec.topology==='ACF-FORWARD'">正激细算须先启用两两 kij 物理周期；已有振铃不再叠加另一条估算曲线。</p>
    <p class="hint" v-if="spec.topology==='QR-FLYBACK'">Q1 填 0 时沿用旧 QR 有效漏极电容；不存在旧设置时使用器件 Coss。填写有效值后计算与导出共用。</p>
    <h4>原边 / Q1 / Q2</h4>
    <label v-for="[key,field] in fields" :key="key" class="parasitic-field"><span>{{ field.label }}</span>
      <input type="number" min="0" step="any" :value="value(key,field)" @change="change(key,Number(($event.target as HTMLInputElement).value)/field.scale)"/><span>{{ field.unit }}</span>
    </label>
    <template v-for="i in count" :key="i"><h4>OUT{{ i }} · {{ spec.outputs?.length ? '整流 D_O'+i : '整流 D1（仿真 D_O1）' }}<span v-if="spec.topology==='ACF-FORWARD'"> / 续流 D_F{{ i }}</span></h4>
      <label v-for="[key,field] in railFields" :key="key" class="parasitic-field"><span>{{ field.label }}</span>
        <input type="number" min="0" step="any" :value="value(key,field,'OUT'+i)" @change="change(key,Number(($event.target as HTMLInputElement).value)/field.scale,'OUT'+i)"/><span>{{ field.unit }}</span>
      </label>
    </template>
  </div>
</template>
<style scoped>
.parasitic-field{display:grid;grid-template-columns:minmax(0,1fr) 90px 35px;gap:6px;align-items:center;margin:8px 0;font-size:14px}.parasitic-field input{min-width:0;width:100%}.parasitic-editor h4{margin:16px 0 10px}.parasitic-editor select{width:100%;margin-top:8px}
</style>
