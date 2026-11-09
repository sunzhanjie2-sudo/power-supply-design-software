<script setup lang="ts">
import {computed, ref, watch, onBeforeUnmount} from 'vue';
import type {Spec} from './types';
import {fmt} from './types';
const props=defineProps<{assessment:Spec;config:Spec}>();
const emit=defineEmits<{change:[config:Spec]}>();
const svg=ref<SVGSVGElement>(), selected=ref(''), step=ref(.01), localX=ref<number|null>(null);
const draft=ref<Spec>({}), history=ref<Spec[]>([]);
const clone=(v:any)=>JSON.parse(JSON.stringify(v));
const points=computed<Spec[]>(()=>props.assessment.cross_sections||[]);
const current=computed(()=>points.value.find(p=>p.id===selected.value));
const width=computed(()=>props.config.window_width*1000), height=computed(()=>props.config.window_height*1000);
const pad=computed(()=>Math.max(.3,Math.max(width.value,height.value)*.07));
const palette=['#1558b0','#16866a','#b96b19','#8b52aa','#cb5660','#3b859e'];
const colors=computed(()=>Object.fromEntries((props.assessment.windings||[]).map((r:Spec,i:number)=>[r.id,palette[i%palette.length]])));
let drag:{client:number;start:number;old:Spec}|null=null, pending:number|null=null, frame=0;
watch(()=>props.config, c=>{if(!drag) draft.value=clone(c.turn_positions||{});},{deep:true,immediate:true});
watch(()=>props.assessment,()=>{localX.value=null;if(!points.value.some(p=>p.id===selected.value)) selected.value='';});
function center(p:Spec):number {
  return selected.value===p.id&&localX.value!==null?localX.value:(draft.value[p.section_id]?.[p.position_key]??p.x+p.width/2);
}
function bound(p:Spec,x:number):number {
  const lo=props.config.margin_x+p.width/2,hi=props.config.window_width-props.config.margin_x-p.width/2;
  return hi>=lo?Math.max(lo,Math.min(hi,x)):x;
}
function axial(event:PointerEvent):number {
  const matrix=svg.value?.getScreenCTM();
  return matrix?new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse()).x/1000:0;
}
function freeze(config:Spec):Spec {
  const next=clone(config);
  if(!next.layer_plan?.length) next.layer_plan=(props.assessment.physical_layers||[]).map((l:Spec)=>({
    section_id:l.section_id,winding_id:l.winding_id,turns:l.turns,winding_style:l.winding_style}));
  return next;
}
function remember(value:Spec) {history.value.push(clone(value));if(history.value.length>50)history.value.shift();}
function commit(p:Spec,x:number,old=props.config) {
  const next=freeze(props.config);next.turn_positions=clone(draft.value);
  (next.turn_positions[p.section_id]||={})[p.position_key]=x;
  draft.value=clone(next.turn_positions);remember(old);emit('change',next);
}
function press(event:PointerEvent,p:Spec) {
  if(event.button!==0)return;
  event.preventDefault();svg.value?.focus();svg.value?.setPointerCapture(event.pointerId);
  selected.value=p.id;localX.value=draft.value[p.section_id]?.[p.position_key]??p.x+p.width/2;
  drag={client:axial(event),start:localX.value!,old:clone(props.config)};
}
function move(event:PointerEvent) {
  if(!drag||!current.value)return;
  pending=bound(current.value,drag.start+axial(event)-drag.client);
  if(!frame)frame=requestAnimationFrame(()=>{frame=0;localX.value=pending;pending=null;});
}
function release(event:PointerEvent) {
  if(!drag||!current.value)return;
  if(frame){cancelAnimationFrame(frame);frame=0;localX.value=pending??localX.value;pending=null;}
  const old=drag;drag=null;
  if(svg.value?.hasPointerCapture(event.pointerId))svg.value.releasePointerCapture(event.pointerId);
  if(localX.value!==null&&Math.abs(localX.value-old.start)>1e-15)commit(current.value,localX.value,old.old);
}
function cancel() {if(frame)cancelAnimationFrame(frame);frame=0;pending=null;drag=null;localX.value=null;}
function undo(){cancel();const old=history.value.pop();if(old){draft.value=clone(old.turn_positions||{});emit('change',old);}}
function uniform(){cancel();remember(props.config);const next=freeze(props.config);next.turn_positions={};
  for(const l of next.layer_plan)l.winding_style='sparse';
  for(const value of Object.values(next.overrides||{}) as Spec[])value.winding_style='sparse';
  draft.value={};emit('change',next);}
function key(event:KeyboardEvent) {
  if(event.key==='Escape'){cancel();return;}
  if(event.ctrlKey&&event.key.toLowerCase()==='z'){event.preventDefault();undo();return;}
  if(!current.value||!['ArrowLeft','ArrowRight'].includes(event.key))return;
  event.preventDefault();if(!Number.isFinite(step.value)||step.value<=0)return;
  const delta=step.value/1000*(event.shiftKey?10:1)*(event.altKey ? .1 : 1)*(event.key==='ArrowLeft'?-1:1);
  const x=bound(current.value,center(current.value)+delta);localX.value=x;commit(current.value,x);
}
onBeforeUnmount(cancel);
</script>

<template>
  <section class="wire-canvas">
    <header><h4>5 · 逐匝位置微调</h4><div class="wire-tools">
      <button type="button" @click="uniform">一键均匀排布</button>
      <button type="button" :disabled="!history.length" @click="undo">撤销位置调整</button>
      <label>键盘步长 <input v-model.number="step" type="number" min="0.000001" step="any" aria-label="逐匝移动步长" /> mm</label>
    </div></header>
    <p>点击一匝线后左右拖动，或在画布中用 ← / → 移动；Shift ×10、Alt ÷10，Ctrl+Z 撤销。位置在松开鼠标后保存，拖动不重跑电气计算。</p>
    <svg ref="svg" tabindex="0" role="application" aria-label="可调整绕组截面"
      :viewBox="`${-pad} ${-pad} ${width+2*pad} ${height+2*pad}`"
      @pointermove="move" @pointerup="release" @pointercancel="cancel" @keydown="key">
      <g :transform="`translate(0,${height}) scale(1,-1)`">
        <rect x="0" y="0" :width="width" :height="height" fill="#f1f4f8" stroke="#415975" stroke-width=".02" />
        <rect :x="config.margin_x*1000" :y="config.margin_y*1000" :width="width-config.margin_x*2000"
          :height="height-config.margin_y*2000" fill="white" stroke="#8798ac" stroke-width=".012" stroke-dasharray=".06 .03" />
        <rect v-for="layer in assessment.physical_layers" :key="layer.section_id" :x="config.margin_x*1000"
          :y="layer.y*1000" :width="width-config.margin_x*2000" :height="layer.height*1000"
          :fill="colors[layer.winding_id]" fill-opacity=".08" :stroke="colors[layer.winding_id]" stroke-opacity=".25" stroke-width=".01" />
        <component :is="p.profile_type==='rectangle'?'rect':'ellipse'" v-for="p in points" :key="p.id" :data-wire-id="p.id" :aria-label="`${p.section_id} 第${p.turn}匝 并绕束${p.bundle}`"
          :x="(center(p)-p.width/2)*1000" :y="p.y*1000" :width="p.width*1000" :height="p.height*1000"
          :cx="center(p)*1000" :cy="(p.y+p.height/2)*1000" :rx="p.width*500" :ry="p.height*500"
          :fill="selected===p.id?'#dceeff':'white'" :stroke="p.conflict?'#b42318':selected===p.id?'#e17b16':colors[p.winding_id]"
          :stroke-width="selected===p.id ? .035 : .018" @pointerdown="press($event,p)">
          <title>{{ p.section_id }} · 第 {{ p.turn }} 匝 · 并绕束 {{ p.bundle }} · X={{ fmt(center(p)*1000,'mm') }}</title>
        </component>
      </g>
    </svg>
    <p class="wire-selection" role="status">{{ current?`${current.section_id} · 第 ${current.turn} 匝 · 并绕束 ${current.bundle}，中心 X=${fmt(center(current)*1000,'mm',6)}`:'尚未选择线圈；首次移动会固定当前分层方案。' }}</p>
    <div class="wire-legend"><span v-for="row in assessment.windings" :key="row.id" :style="{color:colors[row.id]}">● {{ row.id }} · {{ row.turns }} 匝 × {{ row.parallel_wires||1 }} 根</span></div>
    <p v-for="issue in assessment.position_issues" :key="issue" class="wire-error">{{ issue }}</p>
  </section>
</template>

<style scoped>
.wire-canvas{border:1px solid #dce4ed;border-radius:10px;padding:16px;min-width:0}
header{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px}h4{margin:0;color:#284f80;font-size:17px}
.wire-tools{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.wire-tools label{display:flex;gap:6px;align-items:center;color:#4a627f;font-size:14px}.wire-tools input{width:80px!important}
button{border:1px solid #cad7e5;border-radius:7px;background:white;padding:9px 12px;color:#294c77;font-size:14px}button:disabled{opacity:.5}input{border:1px solid #cad7e5;border-radius:6px;padding:8px;font-size:14px}
svg{display:block;width:100%;height:420px;max-height:65vh;background:#f8fafc;border-radius:8px;outline-offset:3px;touch-action:none;user-select:none}
svg:focus{outline:2px solid #2b72bd}[data-wire-id]{cursor:ew-resize}p{font-size:14px;line-height:1.7;color:#66768a;margin:12px 0}.wire-selection{color:#244d7c;font-weight:600}
.wire-legend{display:flex;gap:18px;flex-wrap:wrap;font-size:14px}.wire-error{color:#b42318;font-weight:600}
</style>
