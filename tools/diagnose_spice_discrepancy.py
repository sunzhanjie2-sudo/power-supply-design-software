"""Read-only v3 diagnosis; creates isolated tests, never edits user designs."""
import argparse
import copy
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def source():
    archive=ROOT/'releases/Windows-x64/20261024-spice-comparison-v3/LTspiceExamples/多路反激_全面仿真对比.zip'
    with ZipFile(archive) as z:
        evidence=json.loads(z.read('comparison.json'));case=evidence['cases'][0]
        files={n.split('/',1)[1]:z.read(n) for n in z.namelist() if n.startswith(case['id']+'/')}
    return case,files


def calculate():
    from runtime_resources import configure_numeric_threads
    configure_numeric_threads()
    from design_engine.service import calculate_parameters
    from power_stage import compute_operating_point
    case,files=source();original=json.loads(files['design.json'])
    p=calculate_parameters(original,analysis='endpoints',include_loop=False,include_cross_regulation=False).runtime_bundle()['cases'][0]['p']
    if compute_operating_point(p).get('voltage_convention'):
        raise RuntimeError('历史 v3 归因脚本不适用于已修正的节点模型；请读取 artifacts/qa/spice-discrepancy-20261025 中的原始记录。')
    results=[]
    for label,din,dout in [('current_calculator',False,False),('add_input_drop',True,False),('add_output_drop',False,True),('add_both_drops',True,True)]:
        q=copy.deepcopy(p)
        if din:q['V_in']-=q['Vf_din'] if q.get('d_in_enable') else 0.
        if dout:
            main=int(q['feedback_output'])-1;r=q['outputs'][main]
            old=r['V_out']+r['Vf_diode'];new=old+(r['Vf_dout'] if r.get('d_out_enable') else 0)
            # Hold the original ideal clamp voltage constant. Folding the
            # output DC drop into VF is equivalent in a stiff-capacitor DC
            # solve, but does not constitute a final loss/ripple code fix.
            q['Kc']*=old/new
            for r in q['outputs']:r['Vf_diode']+=r['Vf_dout'] if r.get('d_out_enable') else 0.
        op=compute_operating_point(q)
        row=dict(label=label,D=op['D'],voltage=[r['V_out'] for r in op['output_ops']],
            average=[r['I_out'] for r in op['output_ops']],rms=[r['I_s_rms'] for r in op['output_ops']],
            peak=[r['I_d_pk'] for r in op['output_ops']],energy_residual=op['coupled_model']['energy_balance_W'])
        results.append(row);print(row,flush=True)
    out=ROOT/'artifacts/qa/spice-discrepancy-20261025';out.mkdir(parents=True,exist_ok=True)
    (out/'calculator-isolation.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')


def prepare(stage):
    case,files=source()
    for name,keys in [('bypass_all_output',['D_OUT1_EN','D_OUT2_EN','D_OUT3_EN']),
                      ('bypass_input_and_output',['D_IN_EN','D_OUT1_EN','D_OUT2_EN','D_OUT3_EN']),
                      ('bypass_only_out3',['D_OUT3_EN'])]:
        folder=stage/name;folder.mkdir(parents=True,exist_ok=True)
        for filename,data in files.items():
            if Path(filename).suffix not in ('.cir','.inc','.lib'):continue
            if filename=='design_params.inc':
                text=data.decode('ascii')
                for key in keys:text=re.sub(r'(?m)^\.param '+key+r'=[^\r\n]*',f'.param {key}=0',text)
                text=re.sub(r'(?m)^\.param TSTOP=[^\r\n]*','.param TSTOP=.012',text)
                data=text.encode('ascii')
            (folder/filename).write_bytes(data)
        lines=['.options threads=2 method=gear reltol=.003 plotwinsize=300 plotreltol=1e-4 plotvntol=1e-5 plotabstol=1e-7',
            '.tran 0 .012 0 100n','.save V(gate) V(sense) V(fault) V(sgnd) I(LP)',
            '.meas tran fault_max MAX V(fault) FROM .0112 TO .01196',
            '.meas tran primary_rms RMS I(LP) FROM .0112 TO .01196']
        for i in range(1,4):
            lines.extend([f'.save V(out{i}) V(cap{i}) I(LS{i})',
                f'.meas tran out{i}_before AVG V(out{i},sgnd) FROM .0112 TO .01196',
                f'.meas tran cap{i}_before AVG V(cap{i},sgnd) FROM .0112 TO .01196',
                f'.meas tran out{i}_winding_avg AVG I(LS{i}) FROM .0112 TO .01196',
                f'.meas tran out{i}_winding_rms RMS I(LS{i}) FROM .0112 TO .01196',
                f'.meas tran out{i}_winding_peak MAX I(LS{i}) FROM .0112 TO .01196'])
        (folder/'analysis.inc').write_text('\n'.join(lines)+'\n',encoding='ascii')
    print(stage)


def collect(stage):
    from runtime_resources import configure_numeric_threads
    configure_numeric_threads()
    from spice_runtime import read_log,TransientRaw
    from spice_analysis import cycle_quality
    records=[];failures=[]
    for receipt_file in stage.glob('*runs.json'):
        receipt=json.loads(receipt_file.read_text(encoding='utf-8'))
        for run in receipt['runs']['items']:
            if run['status']!='produced':
                failures.append(dict(circuit=run['circuit'],job=receipt['job_id'],status=run['status']));continue
            measured,_,errors,warnings=read_log(run['log']);assert not errors,errors
            raw=TransientRaw(run['raw'])
            try:
                assert abs(raw.time[-1]-.012)<1e-12
                quality=cycle_quality(raw,250000,.0112,.01196)
                assert quality['stable'] and measured['fault_max']<.5,quality
            finally:raw.close()
            row=dict(circuit=run['circuit'],job=receipt['job_id'],measurements=measured,
                periodicity=quality,log=run['log'],warnings=warnings)
            records.append(row)
            print(run['circuit'],{k:measured[k] for k in ('out3_before','cap3_before','out3_winding_avg','out3_winding_rms','out3_winding_peak')})
    out=ROOT/'artifacts/qa/spice-discrepancy-20261025';out.mkdir(parents=True,exist_ok=True)
    (out/'spice-isolation.json').write_text(json.dumps(dict(records=records,excluded=failures),ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['calculate','prepare','collect']);parser.add_argument('--stage',type=Path)
    args=parser.parse_args()
    if args.action=='calculate':calculate()
    elif args.action=='prepare':prepare(args.stage)
    else:collect(args.stage)
