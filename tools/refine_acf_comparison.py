"""Recalculate predictions against immutable, electrically identical LTspice evidence."""
import copy
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile,ZIP_DEFLATED
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    from runtime_resources import configure_numeric_threads
    configure_numeric_threads()
    import numpy as np
    from design_engine.service import calculate_parameters
    from spice_export import project_files,export_project
    from spice_runtime import _comparison_rows,TransientRaw
    from spice_studies import analytical_loop,finalize_cross
    from spice_analysis import steady_quality
    from power_stage import compute_operating_point
    from isolated_outputs import output_specs
    from spice_comparison_report import write_report

    original=ROOT/'output/MP6005_三路有源钳位正激_20261028/仿真与设计计算对比报告.zip'
    out=ROOT/'output/ACF_计算精度复核_20261028';out.mkdir(parents=True,exist_ok=True)
    with ZipFile(original) as z:archive={k:z.read(k) for k in z.namelist()}
    evidence=json.loads(archive['comparison.json'])
    p=json.loads((ROOT/'examples/33W_3OUT_ACF_MP6005.json').read_text(encoding='utf-8'))
    run=calculate_parameters(p,analysis='endpoints',include_loop=True,include_cross_regulation=False)
    bundle=run.runtime_bundle();files=project_files(p,bundle=bundle);meta=json.loads(files['manifest.json'])
    if any(c.get('error') or c.get('loop_error') for c in bundle['cases']):raise RuntimeError('端点快照/环路失败')
    evidence['calculation_revision_note']='本版用独立物理周期计算替换原标称近似。LTspice 测量、FRA 复数数据和角点实测值原样保留；功率级、两两互感、两份器件库及所有电气参数与原仿真逐项一致。此次重算计算侧，没有重跑或改写仿真数据。'
    evidence['precision_summary']=[];audit=[]
    parse=lambda data:{x.split('=',1)[0]:x.split('=',1)[1].strip() for x in data.decode('ascii').splitlines() if x.startswith('.param ')}
    for record in evidence['cases']:
        vin=record['voltage'];case=next(c for c in bundle['cases'] if c['voltage']==vin);res=case['result'];op=res['op']
        label=record['id'];prior=copy.deepcopy(record['rows'])
        record['previous_calculation']=dict(rows=prior,loop=copy.deepcopy(record['loop']['design']))
        for name in ('power_stage.inc','coupling.inc','GenericACF_MP6005.lib','GenericFlybackPWM.lib'):
            if files[name]!=archive[label+'/'+name]:raise RuntimeError('电路不等价：'+name)
        before=parse(archive[label+'/design_params.inc']);after=parse(files['design_params.inc']);after['.param VIN']=str(vin)
        if any(float(v)!=float(before.get(k,'nan')) for k,v in after.items()):raise RuntimeError('电气参数不等价')
        record['calculation_model']={k:op['acf_model'][k] for k in ('kind','revision','assumptions','mesh','current_mesh_verified','normalized_residual','energy_balance_relative')}
        # The 30 V original nominal temporary RAW was deliberately not retained.
        # Its cross scan has exactly the same fixed full-load excitation until
        # 25 ms, so use that independently captured pre-step window for this
        # low-frequency guard only. Native nominal .meas stays untouched.
        folder=ROOT/'artifacts/qa/acf'/('bench' if vin==20 else 'cross_30_b')
        raw=TransientRaw(folder/'Flyback.raw')
        try:record['steady_before_step']=steady_quality(raw,op['f_sw'],.025,len(op['outputs']))
        finally:raw.close()
        record['steady_before_step']['source']=str(folder/'Flyback.raw')
        record['rows'],record['nominal_comparable']=_comparison_rows(case,record['measurements'],meta,record['periodicity'],record['steady_before_step'])
        if not record['nominal_comparable']:raise RuntimeError('新稳态准入未通过：'+label)
        record['loop']['original']=record['previous_calculation']['loop']['loop']
        record['loop']['design']=analytical_loop(case,record['controller'],record['loop']['simulation']['loop']['f'])
        record['loop']['diagnosis']='本版计算按同一物理周期解和导出斜坡重建；修订前曲线仅作历史对照。计算保持理想门极边沿、刚性直流电容端与采样包络近似，不用实测点校正增益。'
        wf=res['wf'];st=record['switching'];phase=np.mod(np.asarray(st['time']),op['Ts'])
        record['design_switching']={key:np.interp(phase,wf['t'],wf[source]).tolist() for key,source in [('i_p','i_primary'),('v_sw','v_sw')]}
        for branch,child,childop in zip(record['branches'],wf['outputs'],op['output_ops']):
            branch.update(design_current=np.interp(phase,wf['t'],child['i_s']).tolist(),
                design_ripple=np.interp(phase,wf['t'],child['vout_ripple']).tolist(),design_ripple_pp=child['ripple_pp'],
                design_choke=np.interp(phase,wf['t'],child['iL']).tolist(),
                choke_design_rms=childop['I_L_rms'],choke_design_peak=childop['I_L_pk'],choke_design_valley=childop['I_L_min'])
        for r in record['cross']['records']:
            r['previous_design']=r.get('design');q=copy.deepcopy(case['p']);q['_fixed_transformer']=record['hardware']
            for rail,w in zip(q['outputs'],r['powers']):rail.update(P_out=w,P_out_min=min(rail['P_out_min'],w))
            q['P_out']=sum(r['powers'])
            point=op if r['powers']==[r['P_out'] for r in output_specs(case['p'])] else compute_operating_point(q)
            r.update(design=[c['V_out'] for c in point['output_ops']],design_error=None,
                design_point=dict(duty=point['D'],modes=[c['mode'] for c in point['output_ops']],
                    residual=point['acf_model']['normalized_residual'],mesh=point['acf_model']['mesh'],
                    current_mesh_verified=point['acf_model']['current_mesh_verified']))
            print(vin,r['id'],'calc',r['design'],'actual',r['simulation'],flush=True)
        record['cross']['design_note']=op['acf_model']['assumptions']+'角点电压网格与高频电流网格分别核查，后者敏感时电流仅供参考。'
        finalize_cross(record['cross'],output_specs(case['p']),record['feedback_output'])
        if not record['cross']['complete']:raise RuntimeError('交叉角点不完整')
        watched=['门极导通占空比','原边电流 RMS','OUT2 输出平均电压','OUT3 输出平均电压','OUT2 副边电流 RMS','OUT3 副边电流 RMS']
        for old,new in zip(prior,record['rows']):
            if new['metric'] in watched:
                evidence['precision_summary'].append(dict(voltage=vin,metric=new['metric'],before=old['design'],after=new['design'],simulation=new['simulation']))
        audit.append(dict(voltage=vin,all_electrical_parameters_identical=True,models_and_power_stage_identical=True,
            steady=record['steady_before_step'],max_cross_voltage_error_percent=max(abs(a/b-1)*100 for r in record['cross']['records'] for a,b in zip(r['design'],r['simulation'])),
            rms_sensitive_corners=[r['id'] for r in record['cross']['records'] if not r['design_point']['current_mesh_verified']]))
    evidence['prediction_revision']='acf-periodic-MNA-v1'
    archive['previous_comparison.json']=archive['comparison.json']
    archive['comparison.json']=json.dumps(evidence,ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8')
    archive['prediction_audit.json']=json.dumps(audit,ensure_ascii=False,indent=2).encode('utf-8')
    doc=out/'计算与仿真精度复核报告.docx';write_report(doc,evidence)
    # Replace the Word entry, preserve every actual log/complex RAW verbatim.
    for name in list(archive):
        if name.endswith('.docx'):del archive[name]
    archive[doc.name]=doc.read_bytes()
    with ZipFile(out/'计算与仿真精度复核报告.zip','w',ZIP_DEFLATED) as z:
        for name,data in archive.items():z.writestr(name,data)
    (out/'prediction_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'33W 三路有源钳位正激 MP6005.json').write_bytes((ROOT/'examples/33W_3OUT_ACF_MP6005.json').read_bytes())
    export_project(out/'LTspice_三路有源钳位正激.zip',p,bundle=bundle)
    print('Completed',out,flush=True)


if __name__=='__main__':main()
