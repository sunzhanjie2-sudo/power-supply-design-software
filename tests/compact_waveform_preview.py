"""Render test-owned compact per-output cards at GUI and print widths."""
import json
from pathlib import Path
import sys

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from design_api import load_spec
from loss_model import compute_design
from multi_output_charts import draw_output_power, output_chart_figsize
from multi_output_charts_check import multi


def run():
    output=ROOT/'_tmp_compact_waveform_qa'
    output.mkdir(exist_ok=True)
    config=load_spec(json.loads((ROOT/'examples/3_OUTPUT_COUPLED_FLYBACK.json').read_text(encoding='utf-8')))
    for name,p in [('flyback',config),('forward',multi('ACF-FORWARD'))]:
        result=compute_design(p)
        branch=dict(result['outputs'][-1],wf=result['wf']['outputs'][-1])
        for label,width in [('wide',11.2),('narrow',5.4)]:
            fig=Figure(figsize=output_chart_figsize('power',p['topology'],width),dpi=100)
            FigureCanvasAgg(fig)
            draw_output_power(fig,branch)
            fig.savefig(output/f'{name}_{label}.png',dpi=100)
    print(f'Compact chart previews: {output}')


if __name__=='__main__':
    run()
