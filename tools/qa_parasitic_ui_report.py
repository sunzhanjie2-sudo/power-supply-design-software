"""Owned Tk editor, same report blocks, actual Excel and shared charts."""
from pathlib import Path
import copy
import json
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()


def main():
    import tkinter as tk
    from tkinter import ttk
    from unittest.mock import patch
    import main as desktop
    from parasitic_ui import open_editor
    root=tk.Tk();root.attributes('-alpha',0)
    try:
        with patch.object(desktop.PowerSupplyAnalyzer,'schedule_update',return_value=None):
            app=desktop.PowerSupplyAnalyzer(root)
            for task in root.tk.splitlist(root.tk.call('after','info')):root.after_cancel(task)
            window=open_editor(app);window.geometry('680x420');root.update()
            def visit(w):
                for child in w.winfo_children():yield child;yield from visit(child)
            button=next(w for w in visit(window) if isinstance(w,ttk.Button) and w.cget('text')=='应用并重新计算')
            assert button.winfo_rooty()+button.winfo_height()<=window.winfo_rooty()+window.winfo_height()
            button.invoke();assert app._parasitic_config
            cfg=app._config_dict();app._apply_config(copy.deepcopy(cfg))
            assert app.get_params()['parasitic_config']==cfg['parasitic_config']
            window=open_editor(app);window.destroy()
            print('Owned small-window footer/save/load/cancel passed',flush=True)
    finally:
        for task in root.tk.splitlist(root.tk.call('after','info')):
            try:root.after_cancel(task)
            except tk.TclError:pass
        root.destroy()
    from design_engine.specification import load_spec
    from design_engine.service import calculate_parameters
    from web_app.presentation import present
    from web_app.charts import render
    from docx_layout import new_document
    from parasitic_report import add_report
    from report_xlsx import export_input_range_xlsx,_capture_document
    from matplotlib import rc_context
    from power_charts import POWER_CHART_STYLE
    p=load_spec(json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf-8')))
    p['parasitic_config']={'mode':'transient','snub_r_primary':22.,'snub_c_primary':80e-12,
        'rails':{'OUT1':{'cj':55e-12},'OUT2':{'cj':40e-12},'OUT3':{'cj':30e-12}}}
    run=calculate_parameters(p,analysis='endpoints',include_loop=False,include_cross_regulation=False)
    data=present(run)
    assert all(row['parasitics']['edges'] for row in data['display'])
    assert all('t' not in z for row in data['display'] for z in row['parasitics']['edges'])
    folder=ROOT/'artifacts/qa/parasitics_20261029';bundle=run.runtime_bundle()
    result=bundle['cases'][0]['result']
    doc=new_document('寄生参数与局部换流核查','产品报告新增模块 · 排版核对','寄生参数核查')
    with rc_context(POWER_CHART_STYLE):add_report(doc,p,result)
    doc.save(folder/'parasitic_section.docx')
    blocks=_capture_document(doc)['power']
    assert any(b['kind']=='image' for section in blocks.values() for b in section)
    render(run,folder/'local_ringing.png','Vinmin','parasitics')
    print('Shared report and web chart passed',flush=True)
    info=export_input_range_xlsx(folder/'parasitic_endpoints.xlsx',bundle)
    from openpyxl import load_workbook
    wb=load_workbook(folder/'parasitic_endpoints.xlsx');sheet=wb['03 功率级与开关波形']
    text=' '.join(str(c.value) for row in sheet for c in row if c.value is not None)
    assert '寄生参数' in text and 'Vinmin' in text and 'Vinmax' in text
    wb.close()
    (folder/'ui_report_verification.json').write_text(json.dumps(dict(small_window_footer=True,save_load=True,
        compact_metadata=True,excel=info),ensure_ascii=False,indent=2),encoding='utf-8')
    print('Actual endpoint XLSX new module passed',flush=True)


if __name__=='__main__':main()
