<script setup lang="ts">
import {computed,ref} from 'vue';
const props=defineProps<{spec:Record<string,any>;side?:string;value?:any}>();
const emit=defineEmits<{change:[value:Record<string,number>[]]}>();
const count=ref('');
const rows=computed(()=>{
  if(Array.isArray(props.value))return props.value;
  const p=props.spec;
  if(props.side==='input')return [{C:p.Cin1,ESR:p.Rcin1,ESL:p.ESLin1},...(p.cin2_enable?[{C:p.Cin2,ESR:p.Rcin2,ESL:p.ESLin2}]:[])];
  return [{C:p.C_out,ESR:p.Rc,ESL:p.ESL},...(p.cout2_enable?[{C:p.C_out2,ESR:p.Rc2,ESL:p.ESL2}]:[])];
});
function resize(n:number){
  if(!Number.isInteger(n)||n<1)return;
  const old=rows.value;
  emit('change',Array.from({length:n},(_,i)=>({...old[Math.min(i,old.length-1)]})));
  count.value='';
}
function edit(i:number,key:string,value:number){
  const next=rows.value.map((row:any)=>({...row}));next[i][key]=value;emit('change',next);
}
function remove(i:number){if(rows.value.length>1)emit('change',rows.value.filter((_:any,j:number)=>i!==j));}
</script>
<template>
  <div class="bank">
    <div class="bank-actions"><strong>{{side==='input'?'输入':'输出'}}并联电容 · {{rows.length}} 颗</strong><button type="button" @click="resize(rows.length+1)">增加</button></div>
    <div class="bank-actions"><input v-model="count" type="number" min="1" step="1" :placeholder="String(rows.length)" aria-label="电容数量" /><button type="button" @click="resize(Number(count))">设置数量</button></div>
    <div class="cap-list"><table><thead><tr><th>序号</th><th>C / µF</th><th>ESR / mΩ</th><th>ESL / nH</th><th></th></tr></thead><tbody>
      <tr v-for="(row,i) in rows" :key="i"><td>{{Number(i)+1}}</td>
        <td v-for="[key,scale] in [['C',1e-6],['ESR',1e-3],['ESL',1e-9]]" :key="String(key)"><input type="number" min="0" step="any" :aria-label="`C${Number(i)+1} ${key}`" :value="Number(row[String(key)])/Number(scale)" @change="edit(Number(i),String(key),Number(($event.target as HTMLInputElement).value)*Number(scale))" /></td>
        <td><button type="button" :disabled="rows.length===1" @click="remove(Number(i))">删除</button></td>
      </tr>
    </tbody></table></div><small>同一端口全部并联；各颗参数独立，逐颗计算分流与损耗。</small>
  </div>
</template>
<style scoped>
.bank{margin:8px 0;padding:8px;border:1px solid #aabccc;border-radius:6px}.bank-actions{display:flex;align-items:center;gap:8px;margin-bottom:6px}.bank-actions strong{flex:1}.bank-actions input{width:65px}.cap-list{max-height:230px;overflow:auto}table{width:100%;border-collapse:collapse}th,td{padding:3px;font-size:13px}td input{width:100%;min-width:52px;box-sizing:border-box;padding:4px}small{display:block;margin-top:6px}button{cursor:pointer;padding:4px 7px}
</style>
