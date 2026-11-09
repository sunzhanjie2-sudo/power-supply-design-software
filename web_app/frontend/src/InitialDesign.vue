<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue';
import { request } from './api';
import type { Spec } from './types';

const props = defineProps<{current: Spec; apply: (config:Spec)=>Promise<void>}>();
const emit = defineEmits<{close: []; basis: []}>();
type Options = {fields:[string,string,number,number][];values:Record<string,number>;
  modes:Record<string,string>;mode:string;locks:Spec;conduction?:string;windings?:Spec;hint?:string};
const options = ref<Options>(), values = ref<Record<string,string>>({}), mode = ref('');
const topology = ref(''), variants=ref<Record<string,Options>>({});
const conduction=ref('CCM');
const checked = ref<string[]>([]), summary = ref(''), candidate = ref<Spec|null>(null);
const error = ref(''), busy = ref(false);
const lockNames: Record<string,string> = {L:'锁定 L',inductor_dcr:'锁定 DCR',input_capacitors:'锁定输入电容组',output_capacitors:'锁定输出电容组',rail_banks:'锁定各路输出电容组'};
const abort = new AbortController();
function send(url: string,spec: Spec) {
  return request(url,{method:'POST',body:JSON.stringify({spec}),signal:abort.signal});
}
function choose(key:string) {
  const data=variants.value[key];
  topology.value=key;
  checked.value=[];
  values.value=Object.fromEntries(Object.entries(data.values).map(([k,v])=>[k,v==null?'':String(v)]));
  conduction.value=data.conduction||'CCM';
  mode.value=data.mode;
  options.value=data;
}
onMounted(async()=>{
  try {
    const data = await send('/initial-design/options',props.current);
    variants.value=data.variants;
    choose(data.topology);
  } catch(e:any) {error.value = e.message;}
});
onBeforeUnmount(()=>abort.abort());
watch([values,mode,checked,conduction],()=>{candidate.value=null; summary.value=''; error.value='';},{deep:true});
async function generate() {
  if (!options.value) return;
  error.value=''; candidate.value=null; summary.value=''; busy.value=true;
  try {
    const spec:Spec = {topology:topology.value,control_mode:mode.value,locked:{}};
    if(options.value.conduction) Object.assign(spec,{conduction:conduction.value,windings:options.value.windings||{}});
    for (const [key,,scale] of options.value.fields) {
      if(key==='il_ratio' && options.value.conduction && conduction.value==='DCM') continue;
      const raw=values.value[key].trim();
      spec[key]=raw==='' ? null : Number(raw)*scale;
      if (raw!=='' && !Number.isFinite(spec[key])) throw Error('请输入有效数值');
    }
    for(const k of checked.value) spec.locked[k]=options.value.locks[k];
    const data = await send('/initial-design',spec);
    candidate.value=data.config; summary.value=data.summary;
  } catch(e:any){error.value=e.message;} finally{busy.value=false;}
}
async function adopt() {
  if (!candidate.value) return;
  busy.value=true;
  try { await props.apply(candidate.value); }
  catch(e:any){error.value=e.message;} finally{busy.value=false;}
}
</script>
<template>
  <div class="modal-backdrop" @keydown.esc="emit('close')">
    <section class="modal" role="dialog" aria-modal="true" aria-label="按规格生成初版">
      <header><h2>按规格生成电源初版</h2><button class="button" @click="emit('close')">关闭</button></header>
      <div class="modal-body">
        <p>先校核输入与负载工况，再决定是否采用。选择与当前工程相同的拓扑时，可锁定已有器件。</p>
        <fieldset v-if="options" :disabled="busy">
          <div class="sizing-selectors">
            <label>拓扑 <select :value="topology" @change="choose(($event.target as HTMLSelectElement).value)"><option v-for="(_,k) in variants" :key="k" :value="k">{{k}}</option></select></label>
            <label>控制器参考<select v-model="mode"><option v-for="(v,k) in options.modes" :key="k" :value="k">{{v}}</option></select></label>
            <label v-if="options.conduction">额定负载导通模式<select v-model="conduction"><option>CCM</option><option>DCM</option></select></label>
          </div>
          <p v-if="options.conduction">{{options.hint}}</p>
          <div class="sizing-fields"><label v-for="[key,label] in options.fields" :key="key" v-show="key!=='il_ratio' || !options.conduction || conduction!=='DCM'">{{label}}<input v-model="values[key]" type="text" inputmode="decimal" :readonly="key==='fs' && !!options.conduction" /></label></div>
          <div class="sizing-locks"><label v-for="(_,k) in options.locks" :key="k"><input v-model="checked" type="checkbox" :value="k"/> {{lockNames[k]}} </label></div>
        </fieldset>
        <pre v-if="summary" aria-live="polite">{{summary}}</pre>
        <p v-if="error" class="error-box" role="alert">{{error}}</p>
      </div>
      <footer><button class="button" @click="emit('basis')">查看选值依据</button>
        <button class="button" :disabled="!options || busy" @click="generate">{{busy?'处理中…':'生成并校核'}}</button>
        <button class="button primary" :disabled="!candidate || busy" @click="adopt">采用此初版</button>
      </footer>
    </section>
  </div>
</template>
<style scoped>
fieldset{border:0;padding:0;margin:0}
.sizing-selectors{display:flex;flex-wrap:wrap;gap:.6rem 1rem}
.sizing-selectors label{display:grid;gap:.25rem;min-width:6rem;flex:1 1 auto}
.sizing-selectors select,.sizing-fields input{min-width:0;border:1px solid #b6c5d4;border-radius:4px;padding:.35rem .5rem;font:inherit;color:inherit;background:white}
.sizing-fields input[readonly]{background:#edf2f6}
.sizing-locks{display:flex;flex-wrap:wrap;gap:.5rem 1rem}
.sizing-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:.6rem 1rem;margin:.8rem 0}
.sizing-fields label{display:grid;gap:.2rem}
pre{white-space:pre-wrap;font:inherit;line-height:1.55}
</style>
