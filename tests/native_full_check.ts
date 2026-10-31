import assert from 'node:assert/strict';
import fs from 'node:fs';
import {design} from '../web_app/frontend/src/native_engine/engine';
import {plant} from '../web_app/frontend/src/native_engine/loop';
import {compensation} from '../web_app/frontend/src/native_engine/compensation';
import {solveEdge} from '../web_app/frontend/src/native_engine/parasitics';
import {frequencySystem} from '../web_app/frontend/src/native_engine/state_space';
const fixture=JSON.parse(fs.readFileSync('tests/fixtures/native_full_reference.json','utf8')),errors:string[]=[];
const near=(a:any,b:any,k:string,tol=1e-5)=>{if(b===null)return;if(typeof b==='number'&&(!Number.isFinite(a)||Math.abs(a-b)>tol*Math.max(Math.abs(b),1e-8)))errors.push(`${k}: ${a} != ${b}`);};
for(const c of fixture.compensation){const d=compensation(c.p,c.op,c.state);for(const field of ['parts','realized'])for(const [k,v]of Object.entries(c.expected[field]))if(typeof v==='number')near(d[field][k],v,c.name+'/'+field+'/'+k,1e-10);assert.equal(d.buildable,c.expected.buildable);console.log('PASS compensation',c.name);}
for(const [i,c]of fixture.edges.entries()){const d=solveEdge(c.params);for(const [k,v]of Object.entries(c.expected))if(typeof v==='number')near(d[k],v,'RLC'+i+'/'+k,.001);assert.equal(d.clamped,c.expected.clamped);console.log('PASS local RLC',i);}
for(const c of fixture.designs){const start=performance.now();const r=design(c.spec),e=c.expected;for(const [k,v]of Object.entries(e.op))near(r.op[k],v,c.name+'/'+k,.0003);e.outputs.forEach((q:any,i:number)=>{for(const [k,v]of Object.entries(q))near(r.op.output_ops[i][k],v,c.name+'/OUT'+i+'/'+k,.0003);});if(e.psr)for(const [k,v]of Object.entries(e.psr))if(typeof v==='number')near(r.psr![k],v,c.name+'/PSR/'+k,.00001);for(const [k,v]of Object.entries(e.losses))near(r[k as keyof typeof r],v,c.name+'/loss/'+k,.001);if(e.gain){const g=plant(r.p,r.op).gain;[1,10,100,1000,10000].forEach((f,i)=>g(f).forEach((v,j)=>near(v,e.gain[i][j],c.name+'/gain/'+f+'/'+j,.001)));}console.log('CHECK design',c.name,Math.round(performance.now()-start)+'ms');}
for(const e of errors)console.error(e);assert.deepEqual(errors,[]);console.log('PASS full migration independent physical references');
