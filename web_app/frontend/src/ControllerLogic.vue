<script setup lang="ts">
import { computed,ref,watch,onMounted } from 'vue';
import type { Spec } from './types';
const props=defineProps<{ definition:Spec; values:Spec; design:Spec; selected:string }>();
const emit=defineEmits<{ selected:[key:string] }>();
const activeKey=computed(()=>props.definition.parameters[props.selected]?props.selected:Object.keys(props.definition.parameters)[0]);
const active=computed(()=>props.definition.parameters[activeKey.value]);
const scroll=ref<HTMLElement|null>(null);
function reveal() { const el=scroll.value,node=props.definition.nodes.find((n:Spec)=>n.id===active.value.node);if(el && node)el.scrollTop=Math.max(0,(node.y-60)*el.clientWidth/props.definition.width); }
watch(()=>active.value.node,reveal,{flush:'post'});onMounted(reveal);
function value(key:string,compact=false):string {
  const meta=props.definition.parameters[key];
  const n=Number(props.values[key] ?? props.design.spice_config?.[key] ?? 0);
  if (!Number.isFinite(n)) return '编辑中…';
  if (key==='qr_zcd_delay_ns' && n===-1) return '自动估算';
  if (key==='acf_dead_ns' && n===0) return `沿用设计 ${Number(props.design.forward_dead_time || 100e-9)*1e9} ns`;
  if (compact && props.definition.short_choices[key]) return props.definition.short_choices[key][String(n)] || '编辑中…';
  if (key==='frequency_hz' && !n) return `跟随设计 ${Number(props.design.f_sw)/1000} kHz`;
  if (!n && ['kp','fz1','fp1','fz2','fp2'].includes(key)) return '沿用软件';
  if (!n && ['cs_limit','comp_voltage_max'].includes(key)) return '自动确定';
  return meta?.unit==='Hz' && Math.abs(n)>=1000 ? `${n/1000} kHz` : `${n}${meta?.unit?' '+meta.unit:''}`;
}
function pick(node:string) { const key=Object.keys(props.definition.parameters).find(k=>props.definition.parameters[k].node===node);if(key)emit('selected',key); }
function summary(row:Spec) { return row.values.map((k:string)=>`${props.definition.short_labels[k] || k} ${value(k,true)}`).join(' / '); }
const stateNote=computed(()=>{
  const n=(key:string,defaultValue=0)=>Number(props.values[key] ?? defaultValue);
  if (['ss_comp_start_v','ss_comp_end_v'].includes(props.selected) && n('soft_start_mode')!==2) return '当前软启动模式未使用此项；COMP上限缓升时生效。';
  if (props.selected==='soft_start_current_fraction' && n('soft_start_mode')!==1) return '当前软启动模式未使用此项；CS限流缓升时生效。';
  if (props.selected==='slope' && n('slope_mode',1)!==2) return '当前使用自动/设计斜坡，手动值暂不生效。';
  if (props.selected==='hiccup_off_ms' && n('short_mode')!==1) return '当前不是打嗝模式，等待时间暂不生效。';
  if (['scp_threshold_v','scp_blanking_ns','olp_enabled','olp_ms','ocp_hold_us'].includes(props.selected) && !n('short_mode')) return '当前仅逐周期限流，不执行SCP/OLP故障关断。';
  if (['fz2','fp2'].includes(props.selected)) return '第二组零极点只作用于三型；二型保留此值但不使用。';
  return '';
});
</script>
<template>
  <aside class="controller-logic" aria-label="控制器内部逻辑与参数说明">
    <h4>控制器内部逻辑与参数去向</h4>
    <div class="logic-description" aria-live="polite">
      <strong>{{ active.label }} · {{ value(activeKey) }}</strong>
      <p>{{ active.purpose }}</p><p>{{ active.meaning }}</p>
      <p v-if="stateNote" class="logic-state">{{ stateNote }}</p>
    </div>
    <p class="logic-caption">点击模块或左侧参数查看用途。框图随当前拓扑切换；外部补偿、寄生与试验单独分区。</p>
    <div class="logic-scroll" ref="scroll">
      <svg :viewBox="`0 0 ${definition.width} ${definition.height}`" role="group" aria-label="从反馈、振荡器、电流采样到PWM及GATE的控制逻辑图">
        <defs><marker id="controller-logic-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#6a85a6" /></marker></defs>
        <rect x="32" y="164" width="656" height="628" fill="#eaf2fd" stroke="#9db8da" stroke-dasharray="5 3" />
        <text x="48" y="187" class="logic-chip-title">芯片内部控制逻辑 · 通用可配置等效</text>
        <polyline v-for="(edge,i) in definition.edges" :key="i" :points="edge.map((p:number[])=>p.join(',')).join(' ')" fill="none" stroke="#6a85a6" stroke-width="1.6" marker-end="url(#controller-logic-arrow)" />
        <g v-for="node in definition.nodes" :key="node.id" role="button" tabindex="0" :aria-label="node.title" class="logic-node" @click="pick(node.id)" @keydown.enter="pick(node.id)" @keydown.space.prevent="pick(node.id)">
          <rect :x="node.x" :y="node.y" :width="node.w" :height="node.h" rx="6" :fill="active.node===node.id?'#dbeafe':node.scope==='chip'?'white':'#fff8ec'" :stroke="active.node===node.id?'#1763bb':node.scope==='chip'?'#b7c9df':'#dbbb81'" :stroke-width="active.node===node.id?2:1" />
          <text :x="node.x+12" :y="node.y+27" class="logic-node-title">{{ node.title }}</text>
          <text v-for="(line,i) in node.body" :key="i" :x="node.x+12" :y="node.y+53+Number(i)*20" class="logic-node-body">{{ line }}</text>
          <text :x="node.x+12" :y="node.y+node.h-14" class="logic-node-value">{{ summary(node) }}</text>
        </g>
      </svg>
    </div>
    <a :href="definition.source" target="_blank" rel="noopener noreferrer">芯片官方资料 · 实际引脚与逻辑以数据手册为准</a>
  </aside>
</template>
