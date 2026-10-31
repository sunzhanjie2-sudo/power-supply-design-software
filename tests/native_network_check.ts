import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {analyzeNetwork,normalizeNetwork} from '../web_app/frontend/src/native_engine/network';
const data=JSON.parse(readFileSync('tests/fixtures/native-network-reference.json','utf8'));
function compare(a:any,b:any,path=''){
 if(typeof a==='number'&&typeof b==='number'){assert.ok(Math.abs(a-b)<=1e-9*Math.max(1,Math.abs(b)),path+': '+a+' vs '+b);return;}
 if(Array.isArray(b)){assert.equal(a.length,b.length,path);b.forEach((v,i)=>compare(a[i],v,path+'['+i+']'));return;}
 if(b&&typeof b==='object'){assert.deepEqual(Object.keys(a).sort(),Object.keys(b).sort(),path);for(const k of Object.keys(b))compare(a[k],b[k],path+'.'+k);return;}
 assert.equal(a,b,path);
}
for(const c of data.cases){compare(analyzeNetwork(c.project),c.expected,c.name);console.log('PASS Python network reference:',c.name);}
const p=normalizeNetwork(data.cases[0].project),bad=structuredClone(p);bad.connections[0].mode='direct';assert.throws(()=>normalizeNetwork(bad),/二极管/);
const cycle=structuredClone(p);cycle.junctions=[{id:'OR',name:'OR',capacity:50}];cycle.connections.push({id:'E1',source:{kind:'junction',id:'OR',output:1},target:'OR',mode:'diode',vf:.3});assert.throws(()=>normalizeNetwork(cycle),/循环/);
const duplicate=structuredClone(p);duplicate.connections.push({...duplicate.connections[0],id:'E2'});assert.throws(()=>normalizeNetwork(duplicate),/已存在/);
const old={schema_version:'pcs.aux-workspace/1',title:'old',sources:p.sources,units:[{id:'U',name:'U',source:{kind:'bus',id:'A',output:1},spec:{V_in:24,V_out:12,P_out:5,eta_guess:.9}}]};
const migrated=normalizeNetwork(old);assert.equal(migrated.connections[0].target,'U');assert.equal(migrated.schema_version,'power.system-network/2');assert.deepEqual(migrated.loads,[]);
console.log('PASS malformed networks rejected and old source-tree migration');
