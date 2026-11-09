"""Exercise the field-report UI and canvas round-trip without invoking the external solver."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from main import PowerSupplyAnalyzer
import system_workspace as model
from system_workspace_ui import SystemWorkspace
from transformer_sim_ui import _matching_template, show


def find(parent, kind, caption=None):
    for widget in parent.winfo_children():
        if isinstance(widget, kind) and (caption is None or str(widget.cget('text')) == caption):
            return widget
        match = find(widget, kind, caption)
        if match is not None:
            return match
    return None


class FieldReportDesktop(unittest.TestCase):
    def test_reference_preparation_is_off_thread_and_needs_confirmation(self):
        root = tk.Tk()
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as temp, ExitStack() as mocks:
                folder = Path(temp)
                original = folder / '同型号.json'
                original.write_text('{}')
                new = folder / '新提取设置.json'
                new.write_text('{}')
                config = {'core_choice':'PQ32-30'}
                summaries = []
                def prepare(config, *, project_file, output_directory, cancelled):
                    self.assertNotEqual(threading.current_thread(), threading.main_thread())
                    self.assertEqual(project_file, str(original))
                    self.assertFalse(cancelled())
                    return {'config':dict(config, winding_config={'window_width':.010}),
                            'project_file':new, 'summary':'测试骨架窗口 10 mm，层序 P1/S1，线性 DMR44，标称气隙，同向。'}
                def decide(title, summary, **options):
                    self.assertEqual(threading.current_thread(), threading.main_thread())
                    summaries.append(summary)
                    return len(summaries) == 2
                applied = []
                app = SimpleNamespace(root=root, _config_dict=lambda:dict(config), _apply_config=applied.append,
                                      status_var=tk.StringVar(root))
                mocks.enter_context(patch.dict(sys.modules, transformer_sim_reference=SimpleNamespace(prepare_reference=prepare)))
                mocks.enter_context(patch('transformer_sim_ui.messagebox.askyesno',side_effect=decide))
                mocks.enter_context(patch('transformer_sim_ui._settings_file',return_value=folder/'prefs.json'))
                mocks.enter_context(patch('transformer_sim_ui._read_settings',return_value=dict(
                    tool_root=temp, output_directory=temp,templates={'PQ32-30':str(original)})))
                win = show(app)
                win.withdraw()
                go = find(win,ttk.Button,'从同型号磁芯准备参考设置…')
                entries = [w for w in win.winfo_children()[0].winfo_children() if isinstance(w,ttk.Entry)]
                for iteration in range(2):
                    go.invoke()
                    deadline = time.monotonic() + 5
                    while go.instate(['disabled']) and time.monotonic() < deadline:
                        root.update()
                        time.sleep(.01)
                    self.assertEqual(len(summaries), iteration+1)
                    self.assertIn('标称气隙',summaries[-1])
                    self.assertEqual(len(applied), iteration)
                    self.assertEqual(entries[1].get(), str(new if iteration else original))
                self.assertIn('winding_config',applied[0])
                self.assertFalse(find(win,ttk.Button,'一键仿真并生成报告').instate(['disabled']))
                win.destroy()
        finally:
            root.destroy()

    def test_failed_run_retains_log_directory_without_trusting_project_tool(self):
        root = tk.Tk()
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as temp, ExitStack() as mocks:
                folder = Path(temp)
                project_file = folder/'提取设置.json'
                project_file.write_text('{}')
                attempt = folder/'failed-attempt'
                attempt.mkdir()
                settings_file = folder/'settings.json'
                record = {'tool_root':'untrusted-from-json', 'project_file':'project-hint-only'}
                cfg = {'core_choice':'PQ32-30', '__transformer_simulation':record}
                app = SimpleNamespace(root=root, _config_dict=lambda:cfg)
                def fail(*_, **kwargs):
                    exc = ValueError('气隙不匹配')
                    exc.directory = str(attempt)
                    raise exc
                mocks.enter_context(patch.dict(sys.modules, transformer_simulation=SimpleNamespace(run_transformer_simulation=fail)))
                mocks.enter_context(patch.dict('os.environ', POWER_DESIGN_TRANSFORMER_TOOL=''))
                mocks.enter_context(patch('transformer_sim_ui._settings_file', return_value=settings_file))
                win = show(app)
                win.withdraw()
                body = next(iter(win.winfo_children()))
                entries = [w for w in body.winfo_children() if isinstance(w,ttk.Entry)]
                self.assertEqual(entries[0].get(), '')
                self.assertEqual(entries[1].get(), '')
                self.assertIn(record['project_file'], find(win,tk.Text).get('1.0','end'))
                for entry, value in zip(entries, [temp,str(project_file),temp]):
                    entry.delete(0,'end')
                    entry.insert(0,value)
                go = find(win,ttk.Button,'一键仿真并生成报告')
                go.invoke()
                end = time.monotonic() + 5
                while go.instate(['disabled']) and time.monotonic() < end:
                    root.update()
                    time.sleep(.01)
                log = find(win,tk.Text).get('1.0','end')
                self.assertIn('气隙不匹配',log)
                self.assertIn(str(attempt),log)
                self.assertTrue(find(win,ttk.Button,'采用参数并重算').instate(['disabled']))
                self.assertFalse(find(win,ttk.Button,'运行目录').instate(['disabled']))
                with patch('transformer_sim_ui.os.startfile') as open_folder:
                    find(win,ttk.Button,'运行目录').invoke()
                    open_folder.assert_called_once_with(str(attempt))
                self.assertEqual(json.loads(settings_file.read_text(encoding='utf-8'))['tool_root'],temp)
                win.destroy()
        finally:
            root.destroy()

    def test_match_only_unambiguous_core(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def project(name, cad):
                path = root/'项目库'/name/'01_提取设置'/'提取设置.json'
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({'core':{'path':cad}}), encoding='utf-8')
                return str(path)
            one = project('QR', 'PQ3230_half.step')
            project('other', 'PQ32301.step')
            self.assertEqual(_matching_template(temp,'PQ32-30',{}), one)
            project('second', 'PQ32-30_variant.step')
            self.assertEqual(_matching_template(temp,'PQ32-30',{}), '')
            self.assertEqual(_matching_template(temp,'PQ32-30',dict(tool_root=temp, templates={'PQ32-30':one})), one)

    def test_confirm_apply_then_save_and_reopen_canvas(self):
        root = tk.Tk()
        root.withdraw()
        errors = []
        root.report_callback_exception = lambda *args: errors.append(str(args[1]))
        try:
            with tempfile.TemporaryDirectory() as temp, ExitStack() as mocks:
                folder = Path(temp)
                template = folder/'模板.json'
                template.write_text('{}')
                report = folder/'场解.html'
                report.write_text('field')
                comparison = folder/'对比.html'
                comparison.write_text('comparison')
                seen = []
                record = {'report_path':str(report), 'comparison_path':str(comparison), 'directory':temp}
                def run(config, *, progress, cancelled, **params):
                    seen.append(threading.current_thread() is not threading.main_thread())
                    progress('测试场解进度')
                    return dict(record, proposed_config=config, notes=['完成测试'])
                def apply(config, result):
                    return dict(config, __transformer_simulation=record)
                mocks.enter_context(patch.dict(sys.modules, transformer_simulation=SimpleNamespace(
                    run_transformer_simulation=run, apply_transformer_simulation=apply)))
                mocks.enter_context(patch('transformer_sim_ui._settings_file', return_value=folder/'settings.json'))
                mocks.enter_context(patch('transformer_sim_ui._read_settings', return_value=dict(tool_root=temp,
                    output_directory=temp, templates={'PQ32-30':str(template)})))
                mocks.enter_context(patch('transformer_sim_ui.messagebox.askyesno', side_effect=[False,True]))
                mocks.enter_context(patch.object(PowerSupplyAnalyzer, 'schedule_update'))
                shell = SystemWorkspace(root, recovery=False)
                shell.initialize()
                raw = json.loads((ROOT/'examples/90W_QR_L6565_300V.json').read_text(encoding='utf-8'))
                model.set_unit_config(shell.project, 'PSU-01',raw)
                shell.open_unit('PSU-01')
                app = shell.calculator
                show(app)  # Standalone field dialog remains available inside the new centre.
                win = find(app.root, tk.Toplevel)
                self.assertIsNotNone(win)
                self.assertEqual(win.title(),'变压器仿真与设计闭环')
                win.withdraw()
                go = find(win,ttk.Button,'一键仿真并生成报告')
                accept = find(win,ttk.Button,'采用参数并重算')
                go.invoke()
                end = time.monotonic() + 8
                while go.instate(['disabled']) and time.monotonic() < end:
                    root.update()
                    time.sleep(.015)
                self.assertEqual(seen,[True])
                self.assertFalse(accept.instate(['disabled']), find(win,tk.Text).get('1.0','end'))
                accept.invoke()
                self.assertNotIn('__transformer_simulation',app._config_dict())
                accept.invoke()
                self.assertEqual(app._config_dict()['__transformer_simulation'],record)
                win.destroy()
                app.on_close()
                dest=folder/'系统工程.json'
                model.save_project(shell.project,dest)
                shell.project=model.load_project(dest)
                shell.open_unit('PSU-01')
                reopened = shell.calculator
                self.assertEqual(reopened._config_dict()['__transformer_simulation'],record)
                show(reopened)
                history = find(reopened.root,tk.Toplevel)
                self.assertFalse(find(history,ttk.Button,'闭环对比').instate(['disabled']))
                self.assertTrue(find(history,ttk.Button,'采用参数并重算').instate(['disabled']))
                history.destroy()
                reopened.on_close()
                self.assertFalse(errors,errors)
        finally:
            for task in root.tk.splitlist(root.tk.call('after','info')):
                root.after_cancel(task)
            root.destroy()


if __name__ == '__main__':
    unittest.main(verbosity=2)
