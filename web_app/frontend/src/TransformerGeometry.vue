<script setup lang="ts">
import { ref } from 'vue';
import { request } from './api';
import type { Spec } from './types';

const props=defineProps<{config:Spec,assessment?:Spec|null,canExport:boolean,exporting:boolean}>();
const emit=defineEmits<{apply:[profile:Spec];download:[]}>();
const opened=ref(false), text=ref(''), error=ref(''), z=ref(''),radius=ref(''),source=ref('');
const file=ref<HTMLInputElement|null>(null);
function check(body:Spec) {return request('/geometry/profile',{method:'POST',body:JSON.stringify(body)});}
async function edit(){
  error.value='';
  try {
    const profile=await check({profile:props.config?.model_3d??null,layers:(props.assessment?.physical_layers||[]).map(
      (s:Spec)=>({section_id:s.section_id,winding_id:s.winding_id,turns:s.turns}))});
    text.value=JSON.stringify(profile,null,2);
    z.value=profile.frame?.z0_m==null?'':String(profile.frame.z0_m*1000);
    radius.value=profile.frame?.r0_m_if_circular==null?'':String(profile.frame.r0_m_if_circular*1000);
    source.value=profile.bobbin?.source||'';opened.value=true;
  } catch(e:any){error.value=e.message;}
}
async function save(){
  try {const profile=await check({profile:JSON.parse(text.value)});emit('apply',profile);opened.value=false;error.value='';}
  catch(e:any){error.value=e.message;}
}
async function circle(){
  try {
    const obj=JSON.parse(text.value);
    if(!z.value.trim()||!radius.value.trim()||!source.value.trim()) throw Error('请填写 Z 起点、内半径及尺寸来源');
    obj.frame={z0_m:Number(z.value)/1000,r0_m_if_circular:Number(radius.value)/1000};
    if(!Object.values(obj.frame).every(Number.isFinite)) throw Error('骨架基准需填写有限数值');
    obj.bobbin={...obj.bobbin,winding_route_type:'circular',source:source.value.trim(),status:'assumed',
      winding_path_xy_m:null,rounded_rectangle_m:null};
    text.value=JSON.stringify(await check({profile:obj}),null,2);error.value='';
  } catch(e:any){error.value=e.message;}
}
async function load(event:Event){
  const f=(event.target as HTMLInputElement).files?.[0];if(!f)return;
  try {text.value=JSON.stringify(await check({profile:JSON.parse(await f.text())}),null,2);error.value='';}
  catch(e:any){error.value=e.message;} finally {(event.target as HTMLInputElement).value='';}
}
</script>
<template>
  <section class="card tg">
    <div class="card-heading"><h3>变压器三维建模数据</h3>
      <button class="button" type="button" @click="edit">三维建模设置…</button>
      <button class="button primary" type="button" :disabled="!canExport || exporting" @click="emit('download')">导出三维建模数据…</button>
    </div>
    <p class="card-note">请先计算当前工程。包内含双端快照、逐匝坐标及等比例截面。缺少骨架基准或接线时可先导出二维数据。</p>
    <div v-if="opened" class="tg-editor">
      <div class="tg-circle"><label>窗口起点 Z / mm<input v-model="z"></label><label>内侧半径 / mm<input v-model="radius"></label>
        <label>尺寸来源<input v-model="source"></label><button class="button" @click="circle">填入圆形假设</button></div>
      <label>建模配置 JSON（SI，未知值保留 null）<textarea v-model="text" rows="15" spellcheck="false"></textarea></label>
      <div class="tg-buttons"><button class="button" @click="file?.click()">导入设置 JSON…</button>
        <input ref="file" type="file" accept=".json" hidden @change="load">
        <button class="button" @click="opened=false">取消</button><button class="button primary" @click="save">应用到当前工程</button></div>
    </div>
    <p v-if="error" role="alert" class="error-box">{{error}}</p>
  </section>
</template>
<style scoped>
.tg-editor label{display:grid;gap:.3rem}.tg-editor textarea{width:100%;box-sizing:border-box;font-family:monospace}
.tg-circle,.tg-buttons{display:flex;flex-wrap:wrap;gap:.7rem;align-items:end;margin:.6rem 0}
.tg-circle input{max-width:12rem}.tg .card-heading{flex-wrap:wrap}
</style>
