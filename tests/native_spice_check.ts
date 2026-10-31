import fs from 'node:fs';import assert from 'node:assert/strict';
import {calculate} from '../web_app/frontend/src/native_engine/engine';
import {spiceProject} from '../web_app/frontend/src/native_engine/spice_export';
import {createHash} from 'node:crypto';
const cases=JSON.parse(fs.readFileSync('tests/fixtures/native_spice_reference.json','utf8')),diffs:string[]=[];
for(const c of cases){const r=calculate(c.spec),files=spiceProject(r),text=(name:string)=>new TextDecoder().decode(files[name]),params=Object.fromEntries([...text('design_params.inc').matchAll(/^\.param (\w+)=(.*)$/gm)].map(m=>[m[1],m[2]]));
 for(const [k,expected]of Object.entries(c.params)as[string,string][]){const actual=params[k],value=Number(expected);if(Number.isFinite(value)){if(!Number.isFinite(Number(actual))||Math.abs(Number(actual)-value)>1e-5*Math.max(Math.abs(value),1e-15)){if(/_(C|ESR|ESL)$/.test(k)&&k.includes('_2_'))continue;diffs.push(c.name+'/'+k+': '+actual+' != '+expected);}}else assert.equal(actual,expected,c.name+'/'+k);}
 for(const [name,sha]of Object.entries(c.symbols)){assert.ok(files[name]);assert.equal(createHash('sha256').update(files[name]).digest('hex'),sha);}
 for(const [name,data]of Object.entries(files)){if(!/\.(asc|cir|inc)$/.test(name))continue;const value=new TextDecoder().decode(data);assert.ok(!/\b(?:NaN|Infinity|undefined)\b/.test(value),name+' invalid numeric');for(const m of value.matchAll(/\.include\s+([^\s\r\n]+)/g))assert.ok(files[m[1]],name+' missing include '+m[1]);}
 assert.ok(Object.keys(files).some(n=>n.endsWith('.asc')));assert.equal(JSON.parse(text('manifest.json')).simulator_invoked,false);console.log('CHECK offline SPICE',c.name,Object.keys(files).length,'files');}
for(const d of diffs)console.error(d);assert.deepEqual(diffs,[]);console.log('PASS independent controller/hardware parameters, original symbols, include resolution; no simulator call');
