"""Exercise actual GUI export/help callbacks without dialogs or external apps."""
import json
from pathlib import Path
import sys
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docx import Document
from input_range_report import export_input_range_docx
import main


def run():
    folder = Path('_tmp_report_qa').resolve()
    folder.mkdir(exist_ok=True)
    output = folder / 'GUI_export_check.docx'
    root = tk.Tk()
    root.withdraw()
    app = main.PowerSupplyAnalyzer(root)
    try:
        cfg = json.loads(Path('examples/40W_ACF_FORWARD.json').read_text(encoding='utf-8'))
        app._apply_config(cfg)
        app.params['target_eta'].set(.89)
        app.set_param('eta_guess', .85)
        app.set_param('fc_target', 2800)
        app.params['pm_target'].set(58)
        app.comp_type.set(dict(app.COMP_TOPOS)['tl431f'])
        app.comp_dir.set('fwd'); app._on_comp_dir_change()
        app.comp_vars['Copto'].set(.1); app.comp_vars['Copto_unit'].set('n')
        with patch.object(main.filedialog, 'asksaveasfilename', return_value=str(output)) as dialog, \
                patch.object(main.messagebox, 'showinfo') as info, \
                patch.object(main.messagebox, 'showerror') as error, \
                patch('input_range_report.export_input_range_docx', wraps=export_input_range_docx) as exporter:
            app.export_report()
            assert dialog.call_args.kwargs['defaultextension'] == '.docx'
            assert not error.called, str(error.call_args)
            assert info.called
            assert exporter.call_args.kwargs['mos_real_time'] is False
            assert exporter.call_args.kwargs['compensation_state'] == app._comp_state()
        doc = Document(output)
        assert len(doc.inline_shapes) == 25  # paired overview + both complete 12-figure cases
        assert [c['id'] for c in exporter.call_args.args[1]['cases']] == ['Vinmin','Vinmax']
        cells = '\n'.join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
        assert '89.0%' in cells and '2.8 kHz / 58 °' in cells
        assert '85.00%' in cells
        assert '光耦结电容 C_opto' in cells and '100 pF' in cells
        assert '6.2  补偿电路计算关系与回代核验' in '\n'.join(p.text for p in doc.paragraphs)
        assert app.get_params()['eta_guess'] == .85
        assert app._last['op']['eta_guess'] == .85
        assert app._last['p']['target_eta'] == .89, 'review targets must share the numerical snapshot'
        assert not root.cget('cursor')
        assert '已导出' in app.status_var.get()
        app.mos_real_time.set(True)
        real_output=folder/'GUI_real_time_export_check.docx'
        with patch.object(main.filedialog, 'asksaveasfilename', return_value=str(real_output)), \
                patch.object(main.messagebox, 'showinfo'), \
                patch.object(main.messagebox, 'showerror') as error, \
                patch('input_range_report.export_input_range_docx', wraps=export_input_range_docx) as exporter:
            app.export_report()
            assert not error.called, str(error.call_args)
            assert exporter.call_args.kwargs['mos_real_time'] is True
        assert '真实时间轴（ns）' in '\n'.join(p.text for p in Document(real_output).paragraphs)
        # No shell association is launched during tests.
        with patch.object(main.os, 'startfile') as launch, \
                patch.object(main.messagebox, 'showerror') as error:
            app.open_calculation_reference()
            assert launch.called and not error.called
            assert Path(launch.call_args.args[0]).name == '计算方法与公式说明.docx'
        with patch('input_range_report.export_input_range_docx', side_effect=RuntimeError('QA export failure')), \
                patch.object(main.filedialog, 'asksaveasfilename', return_value=str(output)), \
                patch.object(main.messagebox, 'showerror') as error:
            app.export_report()
            assert error.called and not root.cget('cursor')
        print('GUI report/help checks passed: Word default, current compensation state/reference, both MOS axis modes, help target, error cleanup.')
    finally:
        app._closing = True
        for job in (app.update_timer, app._font_timer, app._initial_update_job, app._control_warmup_job):
            if job is not None:
                root.after_cancel(job)
        root.destroy()


if __name__ == '__main__':
    run()
