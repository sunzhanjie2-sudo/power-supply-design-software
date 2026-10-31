"""Run the product's full, auditable comparison/report path for one example."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from design_engine.service import calculate_parameters
from design_engine.specification import load_spec
from spice_runtime import compare_design
from tools.validate_nonisolated import NAMES

if __name__=='__main__':
    n=int(sys.argv[1]);p=load_spec(json.loads((ROOT/'examples'/NAMES[n]).read_text(encoding='utf-8')))
    base=ROOT/'artifacts/qa/nonisolated_20261029_reports';base.mkdir(exist_ok=True)
    r=calculate_parameters(p,analysis='endpoints',include_loop=True,include_cross_regulation=False)
    result=compare_design(r,base/(NAMES[n][:-5]+'.docx'),executable=r'D:\LTSPCIE\LTspice.exe',progress=lambda d,t,m:print(d,t,m,flush=True))
    print(json.dumps(result,ensure_ascii=False),flush=True)
