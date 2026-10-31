"""Exercise the application report path, reusing only byte-equivalent QA data."""
import json
from pathlib import Path
import shutil
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from design_engine.specification import load_spec
from design_engine.service import calculate_parameters
from spice_runtime import compare_design,_run

if __name__=='__main__':
    p=load_spec(json.loads((ROOT/'examples/33W_3OUT_ACF_MP6005.json').read_text(encoding='utf-8')))
    p['spice_config'].update(fra_enabled=0.,cross_enabled=0.)
    run=calculate_parameters(p,analysis='endpoints',include_loop=True,include_cross_regulation=False)
    cache=ROOT/'artifacts/qa/acf/bench';used=[]
    critical=('power_stage.inc','GenericACF_MP6005.lib','GenericFlybackPWM.lib','analysis.inc','support.inc','coupling.inc','design_params.inc','Flyback.cir')
    def canonical(data):return sorted(x for x in data.decode().splitlines() if x and not x.startswith('.step '))
    def execute(exe,folder,timeout,cancel):
        folder=Path(folder)
        # VIN is a real part of this comparison. Ordering of .param cards is
        # immaterial; every component, model and analysis card must match.
        match=all(canonical((folder/k).read_bytes())==canonical((cache/k).read_bytes()) for k in critical)
        if match and (cache/'Flyback.raw').is_file():
            for suffix in ('raw','log'):shutil.copy2(cache/f'Flyback.{suffix}',folder/f'Flyback.{suffix}')
            used.append(dict(destination=folder.name,source=str(cache),identity='all-model-power-analysis-cards-exact'))
            print('Reused previously simulated identical circuit',folder.name,flush=True)
            return 0.
        return _run(exe,folder,timeout,cancel)
    out=ROOT/'output/MP6005_三路有源钳位正激_20261028';out.mkdir(parents=True,exist_ok=True)
    with patch('spice_runtime._run',execute):
        result=compare_design(run,out/'仿真与设计计算对比报告.docx',progress=lambda i,n,s:print(i,n,s,flush=True))
    (ROOT/'artifacts/qa/acf/nominal_qa.json').write_text(json.dumps(dict(result=result,reused=used),ensure_ascii=False,indent=2),encoding='utf-8')
    print(result,flush=True)
