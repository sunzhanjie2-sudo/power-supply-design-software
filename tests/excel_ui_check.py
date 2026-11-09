"""Actual Tk report chooser, Help menu and XLSX export callback."""
from pathlib import Path
import sys
import tkinter as tk
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import main

def run():
    root=tk.Tk();root.withdraw();app=main.PowerSupplyAnalyzer(root)
    try:
        menu=root.nametowidget(root.cget('menu'))
        helpmenu=root.nametowidget(menu.entrycget('Help (帮助)','menu'))
        assert [helpmenu.entrycget(i,'label') for i in range(helpmenu.index('end')+1)] == [
            '计算方法与公式说明','多路反激电源设计入门教程','自动计算参数依据']
        app.set_param('V_in_min',27.);app.set_param('V_in_max',33.)
        app.update_all()
        snapshot=main._calculate_input_report(dict(p=app._last['p']),lambda:False)
        from report_xlsx import export_input_range_xlsx
        out=Path('_tmp_excel_report_qa/gui_report.xlsx').resolve()
        with patch.object(main.filedialog,'asksaveasfilename',return_value=str(out)) as dialog, \
                patch.object(main.messagebox,'showinfo') as info, \
                patch.object(main.messagebox,'showerror') as error, \
                patch('report_xlsx.export_input_range_xlsx',wraps=export_input_range_xlsx) as exporter:
            app.export_report(recompute=False,range_result=snapshot)
            assert ('Excel 模块对照报告','*.xlsx') in dialog.call_args.kwargs['filetypes']
            assert not error.called,error.call_args
            assert info.call_args.args[0]=='Excel 设计报告'
            assert 'Sheet' in info.call_args.args[1]
            assert out.is_file() and not root.cget('cursor')
            assert exporter.call_args.kwargs['compensation_state']==app._comp_state()
            assert exporter.call_args.kwargs['mos_real_time']==app.mos_real_time.get()
        with patch('report_xlsx.export_input_range_xlsx',side_effect=RuntimeError('QA export failure')), \
                patch.object(main.filedialog,'asksaveasfilename',return_value=str(out)), \
                patch.object(main.messagebox,'showerror') as error:
            app.export_report(recompute=False,range_result=snapshot)
            assert error.called and not root.cget('cursor')
        # Native Windows dialogs may leave the initial .docx suffix behind.
        def select_excel(**kwargs):
            kwargs['typevariable'].set('Excel 模块对照报告')
            return str(out.with_name('gui_chosen_format.docx'))
        with patch.object(main.filedialog,'asksaveasfilename',side_effect=select_excel), \
                patch.object(main.messagebox,'showinfo'), \
                patch.object(main.messagebox,'showerror') as error, \
                patch('report_xlsx.export_input_range_xlsx',return_value=dict(successful_cases=2,
                    failed_cases=[],sheet_count=11,figure_count=25,check_count=60,incomplete=False)) as exporter:
            app.export_report(range_result=snapshot)
            assert not error.called,error.call_args
            assert Path(exporter.call_args.args[0]).suffix=='.xlsx'
        print('Excel UI checks passed: minimal Help, format chooser, actual export, current options, error cleanup.')
    finally:
        app._closing=True
        app._calculation_worker.close()
        for job in (app.update_timer,app._font_timer,app._initial_update_job,app._control_warmup_job):
            if job is not None: root.after_cancel(job)
        root.destroy()

if __name__=='__main__':run()
