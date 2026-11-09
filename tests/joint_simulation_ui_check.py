"""Real Tk orchestration checks with lightweight owned-runner substitutes."""
from contextlib import ExitStack
import copy
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
import joint_simulation_ui as ui


class JointDesktopChecks(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.errors = []
        self.root.report_callback_exception = lambda *args:self.errors.append(str(args[1]))
        self.stack = ExitStack()
        scratch = ROOT/'artifacts'/'joint-simulation-ui'
        scratch.mkdir(parents=True, exist_ok=True)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory(dir=scratch)))
        self.template = self.directory / '提取设置.json'
        self.template.write_text('{}', encoding='utf-8')
        self.exe = self.directory / 'LTspice.exe'
        self.exe.write_bytes(b'not executed')
        self.stack.enter_context(patch('spice_runtime.find_ltspice', return_value=str(self.exe)))
        self.stack.enter_context(patch('transformer_sim_ui._read_settings', return_value={
            'tool_root':str(self.directory), 'templates':{'PQ32-30':str(self.template)}}))
        self.stack.enter_context(patch('transformer_sim_ui._save_settings'))
        self.stack.enter_context(patch.object(ui, '_settings_file', return_value=self.directory/'joint-settings.json'))
        self.stack.enter_context(patch('simulation_environment._settings_file', return_value=self.directory/'environment.json'))
        self.stack.enter_context(patch('simulation_environment._model_root', return_value=self.directory/'models'))
        self.config = {'topology':'QR-FLYBACK', 'core_choice':'PQ32-30', 'L':.0008,
                       'winding_config':{'window_width':.0188, 'window_height':.0052}}
        self.applied = []
        def snapshot():
            self.assertIs(threading.current_thread(), threading.main_thread())
            return copy.deepcopy(self.config)
        def apply(config):
            self.assertIs(threading.current_thread(), threading.main_thread())
            self.applied.append(config)
            self.config = config
        self.app = SimpleNamespace(root=self.root, _config_dict=snapshot, _apply_config=apply,
                                   _export_spice_ui=lambda:None, status_var=tk.StringVar(self.root))

    def tearDown(self):
        if getattr(self.app, '_joint_simulation_dialog', None):
            self.app._joint_simulation_dialog.win.destroy()
        for task in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.after_cancel(task)
        self.root.destroy()
        self.stack.close()
        self.assertFalse(self.errors)

    def dialog(self):
        window = ui.show(self.app)
        self.assertIs(window, ui.show(self.app), '重复入口不应启动第二个窗口或任务')
        dialog = self.app._joint_simulation_dialog
        dialog.output.set(str(self.directory))
        # Existing tests continue exercising the explicit legacy contract;
        # the built-in default is checked separately below.
        dialog.legacy.set(True)
        dialog.toggle_legacy()
        self.root.update()
        return dialog

    def drain(self, dialog):
        deadline = time.monotonic()+5
        while dialog.job is not None and time.monotonic()<deadline:
            self.root.update()
            time.sleep(.01)
        self.assertIsNone(dialog.job, '模拟任务未按时完成')

    def fake_runner(self, config, **options):
        self.assertIsNot(threading.current_thread(), threading.main_thread())
        self.assertEqual(options['leakage_factor'], 1.2)
        self.assertTrue(options['prepare_reference_inputs'])
        self.assertEqual(options['project_file'], str(self.template))
        self.assertFalse(options['cancelled']())
        original = copy.deepcopy(config)
        for stage, _ in ui.STAGES:
            options['progress']({'stage':stage, 'status':'running', 'message':stage+'开始'})
            options['progress']({'stage':stage, 'status':'complete', 'message':stage+'完成'})
        report = self.directory/'联合报告.docx'
        report.write_bytes(b'fixture, not a generated Word document')
        config['L'] = .00081
        self.assertEqual(original['L'], .0008)
        return dict(directory=str(self.directory), report_path=str(report),
                    manifest_path=str(self.directory/'manifest.json'), status='complete',
                    proposed_config=config, input_id='run-input', summary='验证链完成',
                    evidence={'do_not_embed':['large values']})

    def test_frozen_worker_inputs_and_explicit_compact_adoption(self):
        self.stack.enter_context(patch.dict(sys.modules, joint_simulation=SimpleNamespace(
            run_joint_simulation=self.fake_runner)))
        dialog = self.dialog()
        dialog.run_button.invoke()
        self.assertTrue(dialog.run_button.instate(['disabled']))
        self.drain(dialog)
        self.assertEqual(self.config['L'], .0008)
        self.assertEqual(self.applied, [])
        self.assertEqual(float(dialog.bar['value']), 5)
        self.assertFalse(dialog.open_report.instate(['disabled']))
        dialog.adopt.invoke()
        self.assertEqual(self.config['L'], .00081)
        record = self.config['__joint_simulation']
        self.assertEqual(record['report_path'], str(self.directory/'联合报告.docx'))
        self.assertNotIn('proposed_config', record)
        self.assertNotIn('evidence', record)
        dialog.adopt.invoke()
        self.assertEqual(len(self.applied), 1)
        prefs = json.loads((self.directory/'joint-settings.json').read_text(encoding='utf-8'))
        self.assertEqual(prefs['leakage_factor'], 1.2)
        dialog.win.destroy()
        reopened = self.dialog()
        self.assertFalse(reopened.open_report.instate(['disabled']))
        self.assertTrue(reopened.adopt.instate(['disabled']), '历史引用不应重新采用旧结果')

    def test_builtin_default_uses_plain_environment_off_tk_thread(self):
        from simulation_environment_ui import EnvironmentPanel
        captured = []
        environment = dict(core_model='PQ32-30', elmer_home='new-machine-Elmer',
                           core_path='portable/core.step', ltspice=str(self.exe))
        def save(config, inputs):
            self.assertIsNot(threading.current_thread(), threading.main_thread())
            self.assertEqual(inputs, environment)
            return dict(inputs)
        def runner(config, **options):
            self.assertIsNot(threading.current_thread(), threading.main_thread())
            captured.append(options)
            return dict(status='complete', directory=str(self.directory), summary='built-in completed')
        self.stack.enter_context(patch.object(EnvironmentPanel, 'snapshot', return_value=copy.deepcopy(environment)))
        self.stack.enter_context(patch('simulation_environment.save_environment', side_effect=save))
        self.stack.enter_context(patch.dict(sys.modules, joint_simulation=SimpleNamespace(run_joint_simulation=runner)))
        win = ui.show(self.app)
        dialog = self.app._joint_simulation_dialog
        dialog.output.set(str(self.directory))
        self.assertFalse(dialog.legacy.get(), '默认必须是内置提取器')
        self.assertFalse(dialog.legacy_frame.winfo_ismapped())
        dialog.start()
        self.drain(dialog)
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]['tool_root'], 'builtin')
        self.assertIsNone(captured[0]['project_file'])
        self.assertEqual(captured[0]['environment'], environment)
        self.assertFalse(dialog.run_button.instate(['disabled']))

    def test_edits_during_run_cannot_be_overwritten(self):
        started = threading.Event()
        release = threading.Event()
        def runner(config, **options):
            started.set()
            release.wait(3)
            return self.fake_runner(config, **options)
        self.stack.enter_context(patch.dict(sys.modules, joint_simulation=SimpleNamespace(run_joint_simulation=runner)))
        dialog = self.dialog()
        dialog.start()
        self.assertTrue(started.wait(2))
        self.config['L'] = .001
        release.set()
        self.drain(dialog)
        dialog.apply_result()
        self.assertEqual(self.config['L'], .001)
        self.assertFalse(self.applied)
        self.assertIn('已被修改', dialog.log.get('1.0','end'))

    def test_cancel_keeps_window_until_owned_worker_stops(self):
        started = threading.Event()
        def runner(config, **options):
            started.set()
            while not options['cancelled']():
                time.sleep(.005)
            options['progress']({'stage':'field', 'status':'cancelled', 'message':'外部任务已停止'})
            return {'status':'cancelled', 'directory':str(self.directory)}
        self.stack.enter_context(patch.dict(sys.modules, joint_simulation=SimpleNamespace(run_joint_simulation=runner)))
        dialog = self.dialog()
        dialog.start()
        self.assertTrue(started.wait(2))
        dialog.close()
        self.assertTrue(dialog.win.winfo_exists())
        self.drain(dialog)
        self.assertIn('已取消',dialog.status.get())
        self.assertTrue(dialog.adopt.instate(['disabled']))
        self.assertFalse(self.applied)

    def test_failure_exposes_directory_and_keeps_stages_honest(self):
        failed = self.directory/'failed-stage'
        failed.mkdir()
        def runner(config, **options):
            options['progress']({'stage':'field', 'status':'running', 'message':'检查场输入'})
            error = ValueError('窗口容量不足')
            error.directory = str(failed)
            raise error
        self.stack.enter_context(patch.dict(sys.modules, joint_simulation=SimpleNamespace(run_joint_simulation=runner)))
        dialog = self.dialog()
        dialog.start()
        self.drain(dialog)
        self.assertEqual(dialog.stages['field'].get(), '失败')
        self.assertEqual(dialog.stages['spice'].get(), '未执行')
        self.assertIn('窗口容量不足', dialog.status.get())
        self.assertFalse(dialog.open_folder.instate(['disabled']))
        with patch.object(ui.os,'startfile') as open_folder:
            dialog.open_folder.invoke()
            open_folder.assert_called_once_with(str(failed))
        self.assertTrue(dialog.open_report.instate(['disabled']))

    def test_invalid_inputs_redirect_to_central_tools_and_allow_retry(self):
        dialog = self.dialog()
        dialog.factor.set('nan')
        dialog.start()
        self.assertIsNone(dialog.job)
        self.assertIn('不小于1',dialog.status.get())
        dialog.factor.set('1.2')
        dialog.executable.set('')
        dialog.start()
        self.assertIsNone(dialog.job)
        self.assertEqual(dialog.notebook.index(dialog.notebook.select()), 1)
        self.assertIn('LTspice',dialog.status.get())
        self.assertFalse(dialog.run_button.instate(['disabled']))

    def test_failed_result_cannot_be_adopted_even_if_it_contains_a_proposal(self):
        dialog = self.dialog()
        dialog.stages['calculation'].set('完成')
        dialog.result = {'status':'failed','proposed_config':dict(self.config,L=.002)}
        dialog.source_id = ui._input_id(self.config)
        dialog.refresh()
        self.assertTrue(dialog.adopt.instate(['disabled']))
        dialog.apply_result()
        self.assertFalse(self.applied)

    def test_real_canvas_magnetic_and_menu_entries_share_centre_and_history(self):
        from main import PowerSupplyAnalyzer
        import system_workspace as model
        from system_workspace_ui import SystemWorkspace
        self.stack.enter_context(patch.object(PowerSupplyAnalyzer,'schedule_update'))
        shell = SystemWorkspace(self.root,recovery=False)
        shell.initialize()
        original = json.loads((ROOT/'examples/90W_QR_L6565_300V.json').read_text(encoding='utf-8'))
        model.set_unit_config(shell.project,'PSU-01',original)
        shell.open_unit('PSU-01')
        app = shell.calculator
        try:
            win = app._export_joint_ui()
            self.assertEqual(win.title(),'电磁仿真，电路仿真，设计计算联合报告')
            dialog = app._joint_simulation_dialog
            app.mag_simulation_button.invoke()
            self.assertIs(app._joint_simulation_dialog,dialog)
            def menu_with_label(widget,caption):
                for child in widget.winfo_children():
                    if isinstance(child,tk.Menu):
                        for i in range((child.index('end') or 0)+1):
                            try:
                                if child.entrycget(i,'label') == caption:
                                    return child,i
                            except tk.TclError:
                                pass
                    found = menu_with_label(child,caption)
                    if found:
                        return found
                return None
            item = menu_with_label(app.root,'电磁仿真，电路仿真，设计计算联合报告…')
            self.assertIsNotNone(item)
            item[0].invoke(item[1])
            self.assertIs(app._joint_simulation_dialog,dialog)
            record = dict(directory=str(self.directory),report_path=str(self.directory/'结果.docx'),
                          manifest_path=str(self.directory/'manifest.json'),status='partial',
                          input_id='fixed',summary='单元历史')
            proposed = app._config_dict()
            proposed['__joint_simulation'] = record
            app._apply_config(proposed)
            self.assertEqual(app._config_dict()['__joint_simulation'],record)
            win.destroy()
            app.on_close()
            saved = self.directory/'系统工程.json'
            model.save_project(shell.project,saved)
            shell.project = model.load_project(saved)
            shell.open_unit('PSU-01')
            app = shell.calculator
            app._export_joint_ui()
            history = app._joint_simulation_dialog
            self.assertEqual(history.result,record)
            self.assertFalse(history.open_report.instate(['disabled']))
            self.assertTrue(history.adopt.instate(['disabled']))
            history.win.destroy()
        finally:
            if shell.calculator is not None:
                shell.calculator.on_close()

    def test_qr_field_self_inductances_survive_real_gui_canvas_roundtrip(self):
        from main import PowerSupplyAnalyzer
        import system_workspace as model
        from system_workspace_ui import SystemWorkspace
        self.stack.enter_context(patch.object(PowerSupplyAnalyzer,'schedule_update'))
        shell = SystemWorkspace(self.root,recovery=False)
        shell.initialize()
        cfg = json.loads((ROOT/'examples/90W_QR_L6565_300V.json').read_text(encoding='utf-8'))
        inductances = [.000812345678912345,.000205432198765432]
        original_k = .987654321098765
        cfg['coupling_config'] = dict(enabled=False,field_matrix_enabled=True,
            port_order=['P','OUT1'],self_inductances_H=inductances,
            k=[[1.,original_k],[original_k,1.]],source='joint-field-margin')
        model.set_unit_config(shell.project,'PSU-01',cfg)
        shell.open_unit('PSU-01')
        app = shell.calculator
        try:
            coupling = app._config_dict()['coupling_config']
            self.assertEqual(coupling['self_inductances_H'],inductances)
            self.assertTrue(coupling['field_matrix_enabled'])
            self.assertEqual(coupling['k'][0][1],original_k)
            self.assertFalse(coupling['enabled'],'QR保留谷底快速模型，不启用CCM物理周期求解')
            app.on_close()
            saved = self.directory/'场解QR系统.json'
            model.save_project(shell.project,saved)
            shell.project = model.load_project(saved)
            shell.open_unit('PSU-01')
            app = shell.calculator
            coupling = app._config_dict()['coupling_config']
            self.assertEqual(coupling['self_inductances_H'],inductances)
            self.assertEqual(coupling['port_order'],['P','OUT1'])
            self.assertTrue(coupling['field_matrix_enabled'])
            self.assertEqual(coupling['source'],'joint-field-margin')
            self.assertEqual(coupling['k'][0][1],original_k)
        finally:
            if shell.calculator is not None:
                shell.calculator.on_close()

    def test_layout_main_actions_visible_at_normal_and_compact_sizes(self):
        self.root.deiconify()
        dialog = self.dialog()
        for width,height in ((1180,830),(820,580)):
            dialog.win.geometry(f'{width}x{height}')
            self.root.update()
            for widget in (dialog.run_button,dialog.stop_button,dialog.open_report,dialog.adopt):
                self.assertGreaterEqual(widget.winfo_rootx(),dialog.win.winfo_rootx())
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),dialog.win.winfo_rootx()+dialog.win.winfo_width()+2)
                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),dialog.win.winfo_rooty()+dialog.win.winfo_height()+2)
        dialog.notebook.select(1)
        self.root.update()
        self.assertEqual(dialog.tool.get(),str(self.directory))

    def test_large_calculator_font_reflows_footer_and_stages(self):
        from main import _apply_fonts
        _apply_fonts(ttk.Style(self.root),20/13)
        self.root.deiconify()
        dialog = self.dialog()
        dialog.win.geometry('820x620')
        self.root.update()
        footer_rows = {int(button.grid_info()['row']) for button in dialog.action_buttons}
        self.assertGreater(len(footer_rows),1)
        for widget in (*dialog.action_buttons,*dialog.stage_boxes):
            self.assertGreaterEqual(widget.winfo_rootx(),dialog.win.winfo_rootx())
            self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),
                                 dialog.win.winfo_rootx()+dialog.win.winfo_width()+2)
        for widget in dialog.action_buttons:
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),
                                 dialog.win.winfo_rooty()+dialog.win.winfo_height()+2)


if __name__ == '__main__':
    unittest.main()
