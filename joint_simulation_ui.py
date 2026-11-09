"""One desktop launch centre for magnetic, calculation and circuit evidence.

The Tk thread snapshots inputs and consumes a mailbox. The worker owns only
plain data and a cancellation event; it never reads widgets or changes a unit.
"""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import queue
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ui_preferences import preferences_path


STAGES = (('prepare', '输入检查'), ('field', '变压器场仿真'),
          ('calculation', '裕量回填与计算'), ('spice', '电路仿真'), ('report', '联合报告'))


def _settings_file():
    return preferences_path().with_name('joint-simulation.json')


def _read_settings():
    try:
        value = json.loads(_settings_file().read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_settings(value):
    path = _settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     suffix='.tmp', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _input_id(config):
    from design_engine.contracts import content_hash
    return content_hash({k: v for k, v in config.items()
                         if k not in ('__transformer_simulation', '__joint_simulation')})


def _readable(value):
    return str(value.get('v', '') if isinstance(value, dict) else value)


class JointSimulationDialog:
    """Single instance per calculator, with explicit adopt-after-run semantics."""

    def __init__(self, app, config):
        from spice_runtime import find_ltspice
        from transformer_sim_ui import _core_name, _matching_template
        from transformer_sim_ui import _read_settings as field_settings
        self.app = app
        self.settings = _read_settings()
        self.field_settings = field_settings()
        self.core = _core_name(config)
        self.win = win = tk.Toplevel(app.root)
        win.title('电磁仿真，电路仿真，设计计算联合报告')
        win.transient(app.root)
        width = max(650, min(1180, win.winfo_screenwidth() - 70))
        height = max(450, min(830, win.winfo_screenheight() - 100))
        win.geometry(f'{width}x{height}')
        win.minsize(min(780, width), min(540, height))
        self.job = None
        self.poll_id = None
        self.mailbox = queue.Queue()
        history = config.get('__joint_simulation')
        self.result = copy.deepcopy(history) if isinstance(history, dict) else {}
        self.directory = self.result.get('directory')
        self.source_config = None
        self.applied = bool(self.result)
        self.controls = []
        self.stages = {}
        self.closed = False
        self.layout_job = None

        tool = self.field_settings.get('tool_root') or os.environ.get('POWER_DESIGN_TRANSFORMER_TOOL', '')
        self.tool = tk.StringVar(win, tool)
        self.template = tk.StringVar(win, _matching_template(tool, self.core, self.field_settings))
        self.output = tk.StringVar(win, self.settings.get('output_directory') or
                                  str(Path.home() / '联合仿真报告'))
        self.factor = tk.StringVar(win, str(self.settings.get('leakage_factor', 1.2)))
        self.executable = tk.StringVar(win, find_ltspice() or '')
        self.prepare_missing = tk.BooleanVar(win, self.settings.get('prepare_reference_inputs', True))
        self.status = tk.StringVar(win, '首次登记本机 Elmer、磁芯模型及 LTspice；以后可直接开始。')
        self.legacy = tk.BooleanVar(win, False)

        frame = ttk.Frame(win, padding=14)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        heading = ttk.Frame(frame)
        heading.grid(row=0, column=0, sticky='ew')
        self.heading = ttk.Label(heading, text='电磁仿真，电路仿真，设计计算联合报告',
                                 font='TkHeadingFont', wraplength=1000, justify='left')
        self.heading.pack(side='left',fill='x',expand=True)
        self.design = ttk.Label(frame, text=self.describe(config), wraplength=980,
                                style='Muted.TLabel', justify='left')
        self.design.grid(row=1, column=0, sticky='ew', pady=(7, 12))
        self.notebook = tabs = ttk.Notebook(frame)
        tabs.grid(row=2, column=0, sticky='nsew')
        from scrollable_results import ScrollableResults
        run_tab = ttk.Frame(tabs)
        run_scroll = ScrollableResults(run_tab)
        run_scroll.pack(fill='both', expand=True)
        run_page = run_scroll.content
        run_page.columnconfigure(1, weight=1)
        run_page.rowconfigure(6, weight=1)
        tools_page = ttk.Frame(tabs)
        tabs.add(run_tab, text='联合运行与结果')
        tabs.add(tools_page, text='工具与模型 · 集中配置')

        ttk.Label(run_page, text='报告保存目录').grid(row=0, column=0, sticky='w', padx=(0, 10))
        output_entry = ttk.Entry(run_page, textvariable=self.output)
        output_entry.grid(row=0, column=1, sticky='ew')
        output_pick = ttk.Button(run_page, text='选择目录…', command=self.pick_output)
        output_pick.grid(row=0, column=2, padx=(8, 0))
        self.controls.extend((output_entry, output_pick))
        policy = ttk.LabelFrame(run_page, text='参数回填策略', padding=10)
        policy.grid(row=1, column=0, columnspan=3, sticky='ew', pady=10)
        policy.columnconfigure(2, weight=1)
        ttk.Label(policy, text='漏感工程裕量 / 倍').grid(row=0, column=0, sticky='w')
        factor = ttk.Spinbox(policy, textvariable=self.factor, from_=1, to=3,
                             increment=.1, width=7)
        factor.grid(row=0, column=1, padx=10)
        self.controls.append(factor)
        self.policy_text = ttk.Label(policy, wraplength=940, justify='left', text=
            '默认1.2倍为项目经验余量，可修改。先校验自感/互感矩阵，再按原边全部其他绕组短路的漏感倍数映射耦合参数，'
            '保留自感并检查矩阵有效性；不会把 k 直接乘倍数。'
            '\n自动回填只作用于本次导出的设计副本。完成后可选择采用到当前单元。')
        self.policy_text.grid(row=1, column=0, columnspan=3, sticky='ew', pady=(7, 0))

        self.stage_frame = stages = ttk.Frame(run_page)
        self.stage_boxes = []
        stages.grid(row=2, column=0, columnspan=3, sticky='ew', pady=(0, 7))
        for i, (key, label) in enumerate(STAGES):
            stages.columnconfigure(i, weight=1, uniform='stage')
            box = ttk.LabelFrame(stages, text=f'{i+1:02d} {label}', padding=(8, 6))
            box.grid(row=0, column=i, sticky='nsew', padx=(0, 5 if i < 4 else 0))
            value = tk.StringVar(win, '等待')
            ttk.Label(box, textvariable=value).pack(anchor='w')
            self.stages[key] = value
            self.stage_boxes.append(box)
        self.bar = ttk.Progressbar(run_page, mode='determinate', maximum=len(STAGES))
        self.bar.grid(row=3, column=0, columnspan=3, sticky='ew', pady=(0, 8))
        self.message = ttk.Label(run_page, textvariable=self.status, wraplength=980,
                                 justify='left')
        self.message.grid(row=4, column=0, columnspan=3, sticky='ew')
        ttk.Label(run_page, text='运行记录', style='Muted.TLabel').grid(
            row=5, column=0, columnspan=3, sticky='w', pady=(10, 4))
        self.log = tk.Text(run_page, height=9, wrap='word', state='disabled',
                           font='TkDefaultFont', borderwidth=1, relief='solid')
        self.log.grid(row=6, column=0, columnspan=2, sticky='nsew')
        scroll = ttk.Scrollbar(run_page, command=self.log.yview)
        scroll.grid(row=6, column=2, sticky='nsw')
        self.log.configure(yscrollcommand=scroll.set)

        scroll_tools = ScrollableResults(tools_page)
        scroll_tools.pack(fill='both', expand=True)
        tools = scroll_tools.content
        tools.columnconfigure(1, weight=1)
        from simulation_environment_ui import EnvironmentPanel
        self.environment = EnvironmentPanel(tools, config)
        self.environment.grid(row=0, columnspan=3, sticky='ew', padx=8, pady=8)
        self.executable = self.environment.executable
        self.controls.extend(self.environment.controls)
        compatibility = ttk.Checkbutton(tools, text='兼容已有外部提取器与旧提取设置（新电脑无需启用）',
                                         variable=self.legacy, command=self.toggle_legacy)
        compatibility.grid(row=1, columnspan=3, sticky='w', padx=10, pady=8)
        self.controls.append(compatibility)
        self.legacy_frame = legacy = ttk.LabelFrame(tools, text='已有外部工程的兼容路径', padding=8)
        legacy.grid(row=2, columnspan=3, sticky='ew', padx=10)
        legacy.columnconfigure(1, weight=1)
        for row, label, variable, command in (
                (1, '变压器提取工具目录', self.tool, self.pick_tool),
                (2, '同型号磁芯提取设置 JSON', self.template, self.pick_template),
                (3, 'LTspice 可执行程序', self.executable, self.pick_executable)):
            ttk.Label(legacy, text=label, wraplength=220).grid(row=row, column=0, sticky='w', padx=8, pady=6)
            entry = ttk.Entry(legacy, textvariable=variable)
            entry.grid(row=row, column=1, sticky='ew', pady=8)
            button = ttk.Button(legacy, text='选择…', command=command)
            button.grid(row=row, column=2, padx=10, pady=8)
            self.controls.extend((entry, button))
        check = ttk.Checkbutton(legacy, variable=self.prepare_missing,
            text='自动准备缺失的参考输入')
        check.grid(row=4, columnspan=3, sticky='w', padx=10, pady=(12, 3))
        self.controls.append(check)
        self.tool_hint = ttk.Label(tools, wraplength=930, justify='left', text=
            '默认使用随程序携带的提取内核；提取设置 JSON 由当前设计自动生成，不需要另一个工具目录。'
            '已有窗口、匝数、层序、手调位置、接线、磁材和气隙优先保留；缺少几何定位会明确提示。'
            '\n场仿真或稳态检查未通过时，报告会明确标记失败/部分完成，不以旧结果冒充本次结果。')
        self.tool_hint.grid(row=3, columnspan=3, sticky='ew', padx=10, pady=(6, 15))
        actions = ttk.LabelFrame(tools, text='独立调试入口', padding=10)
        actions.grid(row=4, columnspan=3, sticky='ew', padx=10, pady=(4, 12))
        field = ttk.Button(actions, text='旧提取设置 / 独立调试…', command=self.open_field)
        field.pack(side='left', padx=(0, 10))
        circuit = ttk.Button(actions, text='控制器设置 / 单独电路仿真…', command=self.open_circuit)
        circuit.pack(side='left')
        self.controls.extend((field, circuit))
        self.toggle_legacy()

        self.footer = footer = ttk.Frame(frame)
        footer.grid(row=3, column=0, sticky='ew', pady=(12, 0))
        self.open_report = ttk.Button(footer, text='打开联合报告', command=lambda:self.open_path(self.result.get('report_path')))
        self.open_folder = ttk.Button(footer, text='打开运行目录', command=lambda:self.open_path(self.directory, directory=True))
        self.adopt = ttk.Button(footer, text='采用结果到当前单元', command=self.apply_result)
        self.run_button = ttk.Button(footer, text='开始联合仿真并导出', command=self.start)
        self.stop_button = ttk.Button(footer, text='取消任务', command=self.cancel)
        self.action_buttons = (self.run_button, self.stop_button, self.open_report, self.open_folder, self.adopt)
        self.refresh()
        self.write('只需一次开始：输入检查 → 场解 → 带裕量参数复算 → 电路仿真 → 联合 Word 报告。')
        if self.result:
            self.write('已载入本单元保存的联合报告记录。该记录是历史证据，重新运行会建立独立目录。')
        win.bind('<Configure>', self.resize, add='+')
        stages.bind('<Configure>', self.schedule_reflow, add='+')
        footer.bind('<Configure>', self.schedule_reflow, add='+')
        self.schedule_reflow()
        win.bind('<Destroy>', self.destroyed, add='+')
        win.protocol('WM_DELETE_WINDOW', self.close)

    def describe(self, config):
        return ('当前单元：' + _readable(config.get('topology', '未选择拓扑')) +
                '  ·  磁芯 ' + (self.core or '未选择') +
                '  ·  芯片与补偿沿用当前工程。Vin min / Vin max 按同一套回填后硬件验证。')

    def resize(self, event):
        if event.widget is self.win:
            width = max(420, event.width - 85)
            for label in (self.heading, self.design, self.message, self.policy_text, self.tool_hint):
                label.configure(wraplength=width)
            self.schedule_reflow()

    def schedule_reflow(self, _event=None):
        if not self.closed and self.layout_job is None:
            self.layout_job = self.win.after_idle(self.reflow)

    def reflow(self):
        self.layout_job = None
        if self.closed:
            return
        for parent, widgets, maximum in ((self.stage_frame,self.stage_boxes,5),
                                          (self.footer,self.action_buttons,5)):
            available = max(400,parent.winfo_width())
            cell = max(w.winfo_reqwidth() for w in widgets)+12
            columns = max(1,min(maximum,int(available//cell)))
            # Clear old column weights so font changes never leave empty columns.
            for col in range(maximum):
                parent.columnconfigure(col,weight=1 if col<columns else 0,uniform='joint-row')
            for i,widget in enumerate(widgets):
                widget.grid(row=i//columns,column=i%columns,sticky='ew',padx=(0,6),pady=3)

    def pick_output(self):
        path = filedialog.askdirectory(parent=self.win, title='选择联合报告保存目录')
        if path:
            self.output.set(path)

    def toggle_legacy(self):
        if self.legacy.get():
            self.legacy_frame.grid()
        else:
            self.legacy_frame.grid_remove()

    def pick_tool(self):
        from transformer_sim_ui import _matching_template
        path = filedialog.askdirectory(parent=self.win, title='选择变压器提取工具目录或研究根目录')
        if path:
            self.tool.set(path)
            self.template.set(_matching_template(path, self.core, self.field_settings))

    def pick_template(self):
        path = filedialog.askopenfilename(parent=self.win, title='选择同型号磁芯提取设置',
                                          filetypes=[('提取设置 JSON', '*.json')])
        if path:
            self.template.set(path)

    def pick_executable(self):
        from spice_runtime import set_ltspice
        path = filedialog.askopenfilename(parent=self.win, title='选择 LTspice 程序',
                                          filetypes=[('LTspice', '*.exe')])
        if path:
            try:
                set_ltspice(path)
                self.executable.set(path)
            except ValueError as exc:
                self.write(str(exc))

    def save_local_settings(self):
        from transformer_sim_ui import _save_settings as save_field_settings
        if self.legacy.get():
            tool = self.tool.get().strip()
            templates = dict(self.field_settings.get('templates') or {}) if self.field_settings.get('tool_root') == tool else {}
            templates[self.core] = self.template.get().strip()
            self.field_settings = dict(self.field_settings, tool_root=tool, templates=templates)
            save_field_settings(self.field_settings)
        self.settings = dict(output_directory=self.output.get().strip(),
                             leakage_factor=float(self.factor.get()),
                             prepare_reference_inputs=self.prepare_missing.get())
        _save_settings(self.settings)

    def write(self, message):
        self.log.configure(state='normal')
        self.log.insert('end', str(message).strip() + '\n')
        # Bound the live widget, while the engine preserves the full on-disk log.
        lines = int(self.log.index('end-1c').split('.')[0])
        if lines > 600:
            self.log.delete('1.0', f'{lines-500}.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def refresh(self):
        busy = self.job is not None
        for widget in (*self.controls, self.run_button):
            widget.state(['disabled'] if busy else ['!disabled'])
        self.stop_button.state(['!disabled'] if busy and not self.job.is_set() else ['disabled'])
        self.open_report.state(['!disabled'] if not busy and self.result.get('report_path') else ['disabled'])
        self.open_folder.state(['!disabled'] if not busy and self.directory else ['disabled'])
        self.adopt.state(['!disabled'] if not busy and not self.applied and self.adoptable() else ['disabled'])

    def adoptable(self):
        return (bool(self.result.get('proposed_config')) and
                self.result.get('status') in ('complete','completed','partial') and
                self.stages['calculation'].get() == '完成')

    def start(self):
        if self.job is not None:
            return
        try:
            factor = float(self.factor.get())
            if not math.isfinite(factor) or factor < 1:
                raise ValueError('漏感裕量应为不小于1的有限倍数；1表示不增加工程余量。')
            tool, template, output, exe = [variable.get().strip() for variable in (
                self.tool, self.template, self.output, self.executable)]
            portable = not self.legacy.get()
            environment = None
            if not portable and (not tool or not Path(tool).is_dir() or not template or not Path(template).is_file()):
                self.notebook.select(1)
                raise ValueError('请在“工具与模型”选择本机提取工具和同型号磁芯的提取设置。')
            if not exe or not Path(exe).is_file():
                self.notebook.select(1)
                raise ValueError('请在“工具与模型”选择 LTspice 可执行程序。')
            if not output:
                raise ValueError('请选择联合报告保存目录。')
            config = copy.deepcopy(self.app._config_dict())
            from transformer_sim_ui import _core_name
            self.core = _core_name(config)
            self.design.configure(text=self.describe(config))
            if portable:
                self.notebook.select(1)
                self.environment.set_config(config)
                environment = self.environment.snapshot(require_spice=True)
                tool, template = 'builtin', None
            source_id = _input_id(config)
            prepare = bool(self.prepare_missing.get())
        except (ValueError, OSError, tk.TclError) as exc:
            self.status.set('尚未开始：' + str(exc))
            self.write(self.status.get())
            return
        try:
            self.save_local_settings()
        except OSError as exc:
            self.write('本机配置未能保存，本次仍可运行：' + str(exc))
        self.source_config = config
        self.source_id = source_id
        self.result = {}
        self.applied = False
        self.directory = output
        self.job = cancel = threading.Event()
        for value in self.stages.values():
            value.set('等待')
        self.bar['value'] = 0
        self.status.set('正在冻结输入并检查工具…')
        self.notebook.select(0)
        self.refresh()
        mailbox = self.mailbox
        def work():
            try:
                current_environment = environment
                if current_environment is not None:
                    from simulation_environment import save_environment
                    try:
                        current_environment = save_environment(config, current_environment)
                    except OSError as exc:
                        mailbox.put(('progress', {'stage':'prepare', 'message':'本机配置未能保存，本次继续使用已选路径：' + str(exc)}))
                from joint_simulation import run_joint_simulation
                options = dict(tool_root=tool, project_file=template,
                    output_directory=output, leakage_factor=factor, executable=exe,
                    prepare_reference_inputs=prepare, cancelled=cancel.is_set,
                    progress=lambda event:mailbox.put(('progress', event)))
                if current_environment is not None:
                    options['environment'] = current_environment
                result = run_joint_simulation(config, **options)
                mailbox.put(('done', result))
            except Exception as exc:
                mailbox.put(('error', (str(exc) or type(exc).__name__,
                                       getattr(exc, 'directory', None))))
        threading.Thread(target=work, name='joint-simulation-report', daemon=True).start()
        self.poll_id = self.win.after(80, self.poll)

    def progress(self, event):
        if not isinstance(event, dict):
            self.status.set(str(event))
            self.write(event)
            return
        stage, state = event.get('stage'), event.get('status', 'running')
        if stage == 'margin':
            stage = 'calculation'
            # Mapping is part of recalculation, never its successful conclusion.
            if state in ('complete', 'completed'):
                state = 'running'
        if stage in self.stages:
            self.stages[stage].set({'running':'运行中', 'complete':'完成', 'completed':'完成',
                'partial':'部分完成', 'failed':'失败', 'cancelled':'已取消', 'skipped':'未执行',
                'pending':'等待'}.get(state, str(state)))
            self.bar['value'] = sum(value.get() == '完成' for value in self.stages.values())
        message = event.get('message')
        if message:
            self.status.set(str(message))
            self.write(message)

    def poll(self):
        self.poll_id = None
        for _ in range(100):
            try:
                kind, data = self.mailbox.get_nowait()
            except queue.Empty:
                break
            if kind == 'progress':
                self.progress(data)
                continue
            requested_cancel = self.job is not None and self.job.is_set()
            self.job = None
            if kind == 'error':
                if data[1]:
                    self.directory = data[1]
                self.status.set(('已取消；已保存的运行文件保留。' if requested_cancel else '本次未完成：' + data[0]))
                for value in self.stages.values():
                    if value.get() == '运行中':
                        value.set('已取消' if requested_cancel else '失败')
            else:
                self.result = data
                self.directory = data.get('directory', self.directory)
                state = data.get('status', 'partial')
                if state in ('complete', 'completed'):
                    self.status.set(('任务已完成，取消请求晚于完成；' if requested_cancel else '') +
                                    '联合报告已生成；结果已用于导出副本，当前单元尚未改写。')
                elif state == 'cancelled' or requested_cancel:
                    self.status.set('已取消；已完成阶段及诊断记录保留，不代表完整验证通过。')
                else:
                    self.status.set('联合报告已保存，存在失败或未覆盖项目，请查看报告结论。')
                summary = data.get('summary')
                if summary:
                    self.write(summary if isinstance(summary, str) else json.dumps(summary, ensure_ascii=False))
            for value in self.stages.values():
                if value.get() == '等待':
                    value.set('未执行')
            self.write(self.status.get())
            if self.directory:
                self.write('运行目录：' + str(self.directory))
            self.refresh()
            return
        if self.job is not None and not self.closed:
            self.poll_id = self.win.after(100, self.poll)

    def cancel(self):
        if self.job is not None:
            self.job.set()
            self.status.set('正在停止当前步骤；不会继续启动后续阶段…')
            self.write(self.status.get())
            self.refresh()

    def apply_result(self):
        if self.job is not None or self.applied or not self.adoptable():
            return
        try:
            if _input_id(self.app._config_dict()) != self.source_id:
                raise ValueError('当前单元在任务开始后已被修改。为保留修改，本次结果不直接覆盖；请打开导出工程核对。')
            proposed = copy.deepcopy(self.result['proposed_config'])
            proposed['__joint_simulation'] = {
                key: copy.deepcopy(self.result[key]) for key in (
                    'directory', 'report_path', 'manifest_path', 'status', 'input_id', 'summary')
                if key in self.result}
            self.app._apply_config(proposed)
        except (ValueError, OSError, KeyError, tk.TclError) as exc:
            self.write('未采用：' + str(exc))
            self.status.set('未覆盖当前单元；导出报告和工程仍可查阅。')
            return
        self.applied = True
        self.status.set('已采用带裕量场解参数到当前单元并重算；返回画布后可保存系统工程。')
        if hasattr(self.app, 'status_var'):
            self.app.status_var.set(self.status.get())
        self.write(self.status.get())
        self.refresh()

    def open_field(self):
        if self.job is not None:
            return
        try:
            self.save_local_settings()
        except (OSError, ValueError):
            pass
        from transformer_sim_ui import show
        show(self.app)

    def open_circuit(self):
        if self.job is None:
            self.app._export_spice_ui()

    def open_path(self, value, *, directory=False):
        path = Path(value or '')
        if not path.is_absolute() or path.drive.startswith('\\\\'):
            self.write('请选择本机磁盘上的报告或目录。')
            return
        if not (path.is_dir() if directory else path.is_file() and path.suffix.lower() in ('.docx', '.html', '.pdf')):
            self.write('找不到报告或目录：' + str(path))
            return
        try:
            os.startfile(str(path.resolve()))
        except OSError as exc:
            self.write('无法打开：' + str(exc))

    def close(self):
        if self.job is not None:
            self.cancel()
            return
        self.win.destroy()

    def destroyed(self, event):
        if event.widget is self.win:
            self.closed = True
            if self.job is not None:
                self.job.set()
            if self.poll_id is not None:
                try:
                    self.win.after_cancel(self.poll_id)
                except tk.TclError:
                    pass
                self.poll_id = None
            if self.layout_job is not None:
                try:
                    self.win.after_cancel(self.layout_job)
                except tk.TclError:
                    pass
                self.layout_job = None
            if getattr(self.app, '_joint_simulation_dialog', None) is self:
                self.app._joint_simulation_dialog = None


def show(app):
    previous = getattr(app, '_joint_simulation_dialog', None)
    if previous is not None and previous.win.winfo_exists():
        previous.win.deiconify()
        previous.win.lift()
        return previous.win
    try:
        config = copy.deepcopy(app._config_dict())
    except (ValueError, tk.TclError) as exc:
        messagebox.showerror('请检查当前单元输入', str(exc), parent=app.root)
        return None
    dialog = JointSimulationDialog(app, config)
    app._joint_simulation_dialog = dialog
    return dialog.win
