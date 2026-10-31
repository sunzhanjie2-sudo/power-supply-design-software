"""Owned engineering chart previews; no desktop screenshots or user windows."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
from winding_layout import assess_winding_window,draw_winding_cross_section


def run():
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    out=Path('_tmp_equivalent_winding_qa');out.mkdir(exist_ok=True)
    rows=[dict(id='P',name='原边',turns=4,strands=60,bare_diameter=.1e-3),
          dict(id='OUT1',name='副边',turns=6,strands=1,bare_diameter=.7e-3),
          dict(id='AUX',name='辅助',turns=3,strands=1,bare_diameter=.13e-3)]
    base=dict(window_width=.008,window_height=.004,diameter_allowance=.02e-3,
        layer_insulation=.08e-3,interwinding_insulation=.15e-3)
    for style in ('sparse','dense_left','dense_right'):
        cfg=dict(base,overrides={'P':dict(parallel_bundles=3,winding_style=style),
            'OUT1':dict(winding_style=style),'AUX':dict(winding_style=style)})
        assessment=assess_winding_window(rows,cfg)
        fig,ax=plt.subplots(figsize=(11,5),layout='constrained')
        draw_winding_cross_section(ax,assessment)
        fig.savefig(out/(style+'.png'),dpi=140);plt.close(fig)
    print(out.resolve())


if __name__=='__main__':run()
