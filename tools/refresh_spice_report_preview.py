"""Reflow an existing real-evidence report; never runs or fabricates simulation.

Prepare charts with the app Python, then pass --reuse-charts under the bundled
document runtime. Simulator logs and .meas records are copied unchanged.
"""
import argparse
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile,ZIP_DEFLATED
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('archive',type=Path)
    charts=parser.add_mutually_exclusive_group()
    charts.add_argument('--reuse-charts',action='store_true')
    charts.add_argument('--redraw-charts',action='store_true',help='Redraw archived evidence without recalculating design overlays.')
    args=parser.parse_args()
    with ZipFile(args.archive) as z:files={name:z.read(name) for name in z.namelist()}
    evidence=json.loads(files['comparison.json']);path=args.archive.with_suffix('.docx');images=None
    if args.reuse_charts:
        with ZipFile(path) as z:
            images=[z.read(n) for n in sorted((n for n in z.namelist() if n.startswith('word/media/image')),
                key=lambda n:int(re.search(r'image(\d+)',n)[1]))]
    elif not args.redraw_charts:
        from runtime_resources import configure_numeric_threads
        configure_numeric_threads()
        from design_engine.service import calculate_parameters
        import numpy as np
        # Only re-evaluate design overlays, never change simulator evidence.
        source=next(files[n] for n in files if n.endswith('/design.json'))
        run=calculate_parameters(json.loads(source),analysis='endpoints',include_loop=False,include_cross_regulation=False)
        for record in evidence['cases']:
            if not record['complete'] or not record.get('design_switching'):continue
            case=next(c for c in run.runtime_bundle()['cases'] if c['voltage']==record['voltage'])
            wf=case['result']['wf'];qr=case['p'].get('topology')=='QR-FLYBACK'
            frequency=case['result']['op']['f_sw'] if qr else case['p']['f_sw']
            origin=record['periodicity']['cycles'][0]['start_s'] if qr and record['periodicity']['cycles'] else 0.
            phase=np.mod(np.asarray(record['switching']['time'])-origin,1/frequency)
            record['design_switching']['i_p']=np.interp(phase,wf['t'],wf.get('i_primary',wf['i_sw'])).tolist()
    from spice_comparison_report import write_report
    write_report(path,evidence,chart_images=images)
    files[path.name]=path.read_bytes();files['comparison.json']=json.dumps(evidence,ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8')
    pending=args.archive.with_suffix('.pending.zip')
    with ZipFile(pending,'w',ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
    pending.replace(args.archive);print(path)


if __name__=='__main__':main()
