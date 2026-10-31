"""Re-evaluate an existing real LTspice FRA archive; never rerun or alter it."""
import argparse
import json
import math
from pathlib import Path
import sys
import zipfile
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from design_engine.service import calculate_parameters
from plants import build_loop_models
from spice_studies import analytical_loop,qr_measured_point
from spice_analysis import loop_metrics
from spice_comparison_report import write_report


def review(source,destination):
    source=Path(source);destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(source) as z:files={n:z.read(n) for n in z.namelist()}
    evidence=json.loads(files['comparison.json']);design_key=next(n for n in files if n.endswith('/design.json'))
    params=json.loads(files[design_key]);run=calculate_parameters(params,analysis='endpoints',include_loop=True,include_cross_regulation=False)
    for record in evidence['cases']:
        if record['fault_test'] or not record.get('complete') or not record['loop'].get('available'):continue
        case=next(c for c in run.runtime_bundle()['cases'] if c['voltage']==record['voltage'])
        loop=record['loop'];f=loop['simulation']['plant']['f'];old=loop['design']
        loop['before_qr_correction']=old
        loop['design']=analytical_loop(case,record['controller'],f)
        point=qr_measured_point(case,record)
        loop['measured_reconstruction']=analytical_loop(case,record['controller'],f,measured=point)
        models,_=build_loop_models(case['p'],case['result']['op'])
        loop['original']=loop_metrics(f,np.asarray(models[2](2j*np.pi*np.asarray(f))).ravel())
        sim=loop['simulation'];old_diff=old['plant']['db'][0]-sim['plant']['db'][0]
        new_diff=max(abs(a-b) for a,b in zip(loop['design']['plant']['db'],sim['plant']['db']))
        loop['diagnosis']=(f'本报告沿用 2026-10-27 实际 LTspice 仿真与 FRA 原始证据，仅重新计算模型。'
            f'原 BCM 峰值控制支路误用电压模式 Gvd/Vm；首频功率级偏差 {old_diff:+.2f} dB。'
            f'修正后设计点功率级全测频带最大幅值差 {new_diff:.2f} dB；原配置补偿与仿真覆盖补偿分别显示。')
        loop['evidence_reuse']='原 2026-10-27 仿真数据与日志未更改；2026-10-28 更新计算模型并重建报告。'
    evidence['analysis_revision']='QR peak-current variable-period 2026-10-28; original LTspice evidence reused'
    report=destination/'QR环路差异复核报告.docx';write_report(report,evidence)
    files['comparison.json']=json.dumps(evidence,ensure_ascii=False,allow_nan=False,indent=2).encode()
    files[report.name]=report.read_bytes()
    files['QR环路修正说明.md']=(ROOT/'docs/QR_L6565_SPICE.md').read_bytes()
    with zipfile.ZipFile(destination/'QR环路差异复核证据.zip','w',zipfile.ZIP_DEFLATED) as z:
        for n,data in files.items():z.writestr(n,data)
    print(report)
    for c in evidence['cases']:
        if c['loop'].get('measured_reconstruction'):
            for key in ('design','measured_reconstruction','simulation'):
                x=c['loop'][key]['loop'];print(key,'fc',x['fc'],'pm',x['pm'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('destination');a=p.parse_args();review(a.source,a.destination)
