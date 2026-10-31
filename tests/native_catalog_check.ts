import assert from 'node:assert/strict';
import fixture from './fixtures/native_catalog_reference.json';
import {design,componentEvaluation,checks} from '../web_app/frontend/src/native_engine/engine';
for(const c of fixture.cases){
 const run=design(c.spec),data=componentEvaluation(run.p,run);
 assert.deepEqual(data.rows.map(r=>r.ref).sort(),c.rows.map(r=>r.ref).sort(),c.name+' BOM refs');
 for(const expected of c.checks){const actual=data.checks.find(r=>r.ref===expected.ref&&r.metric===expected.metric)||data.checks.find(r=>r.id===expected.ref+'.'+expected.metric);assert.ok(actual,c.name+' '+JSON.stringify(expected));
  for(const key of ['value','rating','factor','limit']){const a=actual[key]??null,b=expected[key]??null;if(typeof b==='number')assert.ok(Math.abs(a-b)<=Math.max(1e-9,Math.abs(b)*.001),c.name+' '+expected.ref+'.'+key+': '+a+' vs '+b);else assert.equal(a,b);}
  assert.equal(actual.state,expected.state,c.name+' '+expected.ref+'.'+expected.metric);
 }
 const catalog=checks(run.p,run);assert.ok(catalog.some(r=>r.id.includes('temperature')||r.name.includes('温升')));assert.ok(catalog.every(r=>r.state!=='pass'||r.value!==null),'missing evidence cannot pass');
 console.log('PASS BOM/rating source parity',c.name,data.rows.length,data.checks.length);
}
const acf=fixture.cases.find(c=>c.spec.topology==='ACF-FORWARD')!;
const p={...acf.spec,parasitic_config:{mode:'transient',rp_pcb:.02,rails:{OUT1:{r_pcb:.01}}}};
const run=design(p,false),m=run.op.acf_model,tr=run.mag.transformer;
assert.ok(m.energy_balance_relative<.02);
assert.ok(Math.abs(m.R[0]-tr.R_dc_p-.02)<1e-12);
const s=run.op.acf_solution,t=s.t,bePower=(a:number[])=>a.slice(1).reduce((sum:number,v:number,i:number)=>sum+(t[i+1]-t[i])*v*v,0)/run.op.Ts;
// The implicit periodic solver's energy audit uses right-endpoint BE quadrature,
// while its displayed winding RMS uses trapezoidal quadrature.
const pcb=.02*bePower(s.i_primary)+.01*bePower(s.i_s[0]);
assert.ok(Math.abs(run.P_parasitic-pcb)<1e-10,'discrete energy loss must equal the PCB resistor integral');
const copper=tr.Fr_p*tr.R_dc_p*m.winding_rms[0]**2+tr.windings.reduce((s:number,w:any)=>s+w.Fr*w.R_dc*w.I_rms**2,0);
assert.ok(Math.abs(tr.P_cu-copper)<1e-12,'PCB dissipation must not be added to transformer copper');
console.log('PASS ACF nonzero PCB resistance: independent energy ledger; no double loss');
