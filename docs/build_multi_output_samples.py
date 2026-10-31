"""Generate the reviewed SSR and MP6005 sample reports with bundled Python."""
from pathlib import Path
import sys
import json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from design_api import load_spec
from analysis_workflows import evaluate,corners
from report_docx import export_design_docx


def build():
    for filename,output in [('6_OUTPUT_FLYBACK_SSR.json','6路反激_SSR_设计评审报告.docx'),
                            ('MP6005_PSR_FLYBACK.json','MP6005_PSR_多输出设计评审报告.docx')]:
        p=load_spec(json.loads((Path('examples')/filename).read_text(encoding='utf-8')))
        snap=evaluate(p)
        grid=corners(p,load_fracs=(.1,.5,1.))
        result=export_design_docx(Path('reports')/output,p,snap['op'],snap['wf'],snap['res'],snap['models'],
                                  loop_error=snap['loop_error'],corners=grid)
        print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__': build()
