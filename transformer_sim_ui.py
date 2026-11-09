"""Desktop entry for field extraction from the current calculator unit."""
import copy
import json
import os
from pathlib import Path
import queue
import re
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ui_preferences import preferences_path


def _settings_file():
    return preferences_path().with_name('transformer-solver.json')


def _read_settings():
    try:
        data = json.loads(_settings_file().read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_settings(settings):
    path = _settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         suffix='.tmp', delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            json.dump(settings, stream, ensure_ascii=False, indent=2)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _core_name(config):
    value = config.get('core_choice', '')
    return str(value.get('v', '') if isinstance(value, dict) else value)


def _matching_template(tool_root, core_name, settings):
    if not tool_root or not core_name:
        return ''
    root = Path(tool_root)
    templates = settings.get('templates', {})
    if settings.get('tool_root') == tool_root and isinstance(templates, dict):
        saved = templates.get(core_name)
        if isinstance(saved, str) and saved and Path(saved).is_file():
            return saved
    # Suggest only an unambiguous CAD model from the adjacent bounded project catalog.
    # The worker still validates the exact winding sections, material and geometry.
    catalog = root / '项目库'
    if not catalog.is_dir() and root.name == '变压器耦合参数提取工具':
        catalog = root.parent / '项目库'
    key = re.sub(r'[-_/\s]', '', core_name).casefold()
    if not key:
        return ''
    matches = []
    for project in catalog.glob('*/01_提取设置/提取设置.json'):
        try:
            data = json.loads(project.read_text(encoding='utf-8-sig'))
            core_file = Path(data['core']['path']).stem
        except (OSError, ValueError, KeyError, TypeError):
            continue
        compact = re.sub(r'[-_/\s]', '', core_file).casefold()
        if re.match(re.escape(key) + r'(?!\d)', compact):
            matches.append(project)
    return str(matches[0]) if len(matches) == 1 else ''


class _SimulationDialog:
    def __init__(self, app, config):
        self.app = app
        self.win = win = tk.Toplevel(app.root)
        win.title('变压器仿真与设计闭环')
        win.transient(app.root)
        win.grab_set()
        self.settings = _read_settings()
        self.core = _core_name(config)
        self.job = None
        previous = config.get('__transformer_simulation')
        self.result = previous if isinstance(previous, dict) else {}
        self.directory = self.result.get('directory')
        self.applied = True
        self.queue = queue.Queue()
        self.poll_id = None
        self.path_controls = []

        frame = ttk.Frame(win, padding=12)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)
        ttk.Label(frame, text=f'当前变压器 · {self.core}', font='TkHeadingFont').grid(
            row=0, columnspan=3, sticky='w', pady=(0, 6))
        ttk.Label(frame, text='以当前匝数和排线导出几何。提取设置提供磁芯实体、材料、坐标和接线，'
                             '请核对是否与本单元一致。', wraplength=600).grid(
            row=1, columnspan=3, sticky='w', pady=(0, 8))
        root_path = self.settings.get('tool_root') or os.environ.get('POWER_DESIGN_TRANSFORMER_TOOL', '')
        self.tool = tk.StringVar(win, root_path)
        self.template = tk.StringVar(win, _matching_template(root_path, self.core, self.settings))
        self.output = tk.StringVar(win, self.settings.get('output_directory') or str(Path.home() / '变压器仿真报告'))
        for row, (label, var, pick) in enumerate((
                ('本机提取工具目录', self.tool, self.pick_tool),
                ('提取设置 JSON', self.template, self.pick_template),
                ('报告保存目录', self.output, self.pick_output)), start=2):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', padx=(0, 8))
            entry = ttk.Entry(frame, textvariable=var, width=50)
            entry.grid(row=row, column=1, sticky='ew', pady=3)
            button = ttk.Button(frame, text='选择…', command=pick)
            button.grid(row=row, column=2, padx=(6, 0))
            self.path_controls.extend((entry, button))
        self.log = tk.Text(frame, width=64, height=8, wrap='word', state='disabled',
                           font='TkDefaultFont')
        self.log.grid(row=5, column=0, columnspan=2, sticky='nsew', pady=(10, 6))
        scroll = ttk.Scrollbar(frame, command=self.log.yview)
        scroll.grid(row=5, column=2, sticky='nsw', pady=(10, 6))
        self.log.configure(yscrollcommand=scroll.set)
        bar = ttk.Frame(frame)
        bar.grid(row=6, columnspan=3, sticky='ew')
        self.report = ttk.Button(bar, text='场仿真报告', command=lambda:self.open_report('report_path'))
        self.compare = ttk.Button(bar, text='闭环对比', command=lambda:self.open_report('comparison_path'))
        self.folder = ttk.Button(bar, text='运行目录', command=lambda:self.open_path(self.directory, directory=True))
        for btn in (self.report, self.compare, self.folder):
            btn.pack(side='left', padx=(0, 4))
        self.prepare = ttk.Button(bar, text='从同型号磁芯准备参考设置…',
                                  command=lambda:self.start(prepare=True))
        self.prepare.pack(side='right')
        actions = ttk.Frame(frame)
        actions.grid(row=7, columnspan=3, sticky='ew', pady=(5, 0))
        self.apply = ttk.Button(actions, text='采用参数并重算', command=self.apply_result)
        self.stop = ttk.Button(actions, text='停止', command=self.cancel)
        self.run = ttk.Button(actions, text='一键仿真并生成报告', command=self.start)
        self.apply.pack(side='left')
        for btn in (self.run, self.stop):
            btn.pack(side='right', padx=(4, 0))
        self.refresh()
        if self.result:
            self.write('此单元已保存一次参数采用记录。可查阅当时的场仿真报告和闭环对比。')
            if self.result.get('project_file'):
                self.write('上次使用的提取设置：' + str(self.result['project_file']))
            if not root_path and self.result.get('tool_root'):
                self.write('上次使用的工具目录：' + str(self.result['tool_root']) + '。请在本机重新选择。')
        else:
            self.write('首次选择本机工具及提取设置后，后续可直接仿真。每次运行单独保存，完成后可核对结果再采用参数。')
        if not all((config.get('winding_config') or {}).get(k) for k in ('window_width','window_height')):
            self.write('尚缺骨架净窗口尺寸。选好同型号模板后，可点击“从同型号磁芯准备参考设置…”预览参考排线和接线。')
        win.protocol('WM_DELETE_WINDOW', self.close)
        win.bind('<Destroy>', self.destroyed, add='+')

    def pick_tool(self):
        path = filedialog.askdirectory(parent=self.win, title='选择寄生参数提取研究目录或提取工具目录')
        if path:
            self.tool.set(path)
            self.template.set(_matching_template(path, self.core, self.settings))

    def pick_template(self):
        catalog = Path(self.tool.get()) / '项目库'
        path = filedialog.askopenfilename(parent=self.win, title='选择匹配本变压器的提取设置',
                initialdir=str(catalog) if catalog.is_dir() else None, filetypes=[('提取设置', '*.json')])
        if path:
            self.template.set(path)

    def pick_output(self):
        path = filedialog.askdirectory(parent=self.win, title='选择报告保存目录')
        if path:
            self.output.set(path)

    def write(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', str(text).strip() + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def refresh(self):
        busy = self.job is not None
        for widget in (*self.path_controls, self.run, self.prepare):
            widget.state(['disabled'] if busy else ['!disabled'])
        self.stop.state(['!disabled'] if busy and not self.job.is_set() else ['disabled'])
        for button, key in ((self.report, 'report_path'), (self.compare, 'comparison_path')):
            button.state(['!disabled'] if self.result.get(key) and not busy else ['disabled'])
        self.folder.state(['!disabled'] if self.directory and not busy else ['disabled'])
        applicable = bool(self.result.get('proposed_config')) and not self.applied and not busy
        self.apply.state(['!disabled'] if applicable else ['disabled'])

    def start(self, *, prepare=False):
        if self.job is not None:
            return
        paths = [v.get().strip() for v in (self.tool, self.template, self.output)]
        tool, template, output = paths
        if not all(paths) or not Path(tool).is_dir() or not Path(template).is_file():
            self.write('请先选择本机提取工具目录、有效的提取设置 JSON 和报告保存目录。')
            return
        try:
            config = copy.deepcopy(self.app._config_dict())
        except (ValueError, tk.TclError) as exc:
            self.write('请检查当前单元输入：' + str(exc))
            return
        templates = dict(self.settings.get('templates') or {}) if self.settings.get('tool_root') == tool else {}
        templates[self.core] = template
        self.settings = dict(tool_root=tool, templates=templates, output_directory=output)
        try:
            _save_settings(self.settings)
        except OSError as exc:
            self.write('本次可以运行，本机路径设置保存失败：' + str(exc))
        self.job = cancel = threading.Event()
        if not prepare:
            self.result = {}
            self.directory = output
        self.refresh()
        self.write('正在按本单元匝数准备参考窗口、层序和接线…' if prepare else '正在冻结当前单元并检查仿真输入…')
        mailbox = self.queue
        def work():
            try:
                if prepare:
                    from transformer_sim_reference import prepare_reference
                    prepared = prepare_reference(config, project_file=template, output_directory=output,
                                                 cancelled=cancel.is_set)
                    mailbox.put(('reference', (prepared, config)))
                    return
                from transformer_simulation import run_transformer_simulation
                result = run_transformer_simulation(config, tool_root=tool, project_file=template,
                    output_directory=output, cancelled=cancel.is_set,
                    progress=lambda message:mailbox.put(('progress', message)))
                mailbox.put(('done', result))
            except Exception as exc:
                mailbox.put(('error', (str(exc) or type(exc).__name__, getattr(exc, 'directory', None))))
        threading.Thread(target=work, name='transformer-field-report', daemon=True).start()
        self.poll_id = self.win.after(80, self.poll)

    def poll(self):
        self.poll_id = None
        for _ in range(60):
            try:
                kind, data = self.queue.get_nowait()
            except queue.Empty:
                break
            if kind == 'progress':
                self.write(data)
                continue
            cancelled = self.job.is_set()
            self.job = None
            if kind == 'error' and data[1]:
                self.directory = data[1]
            if cancelled and kind in ('error','reference'):
                self.write('已停止本次任务。')
            elif kind == 'error':
                self.write('本次未完成：' + data[0])
                self.write('如缺少窗口、层序或接线与模板不符，可从同型号磁芯准备参考设置，核对后重新仿真。')
            elif kind == 'reference':
                self.adopt_reference(*data)
            else:
                self.result = data
                self.applied = False
                self.directory = data['directory']
                field = data.get('record', {}).get('field', {})
                if 'primary_self_H' in field and 'primary_short_H' in field:
                    self.write('原边开路自感 %.4g µH；全部副边短路折算漏感 %.4g µH。' %
                               (field['primary_self_H'] * 1e6, field['primary_short_H'] * 1e6))
                for note in data.get('notes') or []:
                    self.write(note)
            if self.directory:
                self.write('运行文件位置：' + str(self.directory))
            self.refresh()
            return
        self.poll_id = self.win.after(100, self.poll)

    def adopt_reference(self, prepared, original_config):
        summary = str(prepared['summary'])
        self.write(summary)
        self.write('生成的参考设置：' + str(prepared['project_file']))
        if not messagebox.askyesno('采用参考绕制与建模设置', summary +
                '\n\n请核对骨架窗口、每层绕组和匝数、材料、气隙，以及各段同向串联的假设。'
                '\n是否将上面的参考设置写入当前单元，作为这次仿真的输入？',
                default='no', parent=self.win):
            self.write('已保留原设计和原提取设置。')
            return
        try:
            if self.app._config_dict() != original_config:
                raise ValueError('准备参考设置后设计参数已变化，请重新准备。')
            self.app._apply_config(prepared['config'])
        except (ValueError, OSError, KeyError, tk.TclError) as exc:
            self.write('无法采用参考设置：' + str(exc))
            return
        self.result = {}
        self.applied = True
        self.template.set(str(prepared['project_file']))
        self.directory = str(Path(prepared['project_file']).parent)
        self.write('已采用所列参考假设。点击“一键仿真并生成报告”运行当前单元。')
        self.app.status_var.set('参考绕制与建模设置已应用，可运行场解或返回画布保存工程。')

    def cancel(self):
        if self.job is not None:
            self.job.set()
            self.write('正在停止本次任务…')
            self.refresh()

    def open_report(self, key):
        self.open_path(self.result.get(key))

    def open_path(self, value, *, directory=False):
        path = Path(value or '')
        if not path.is_absolute() or path.drive.startswith('\\\\'):
            self.write('请选择本机磁盘上的报告或运行目录。')
            return
        if not (path.is_dir() if directory else path.suffix.lower() in ('.html', '.pdf') and path.is_file()):
            self.write('找不到本地报告或运行目录：' + str(path))
            return
        try:
            os.startfile(str(path.resolve()))
        except OSError as exc:
            self.write('打开报告失败：' + str(exc))

    def apply_result(self):
        if self.applied or not self.result.get('proposed_config'):
            return
        if not messagebox.askyesno('采用场解参数',
                '将闭环对比中的候选参数写入当前单元并重新计算？\n返回画布后，点击“保存系统工程”可保存到文件。',
                parent=self.win):
            return
        try:
            from transformer_simulation import apply_transformer_simulation
            config = apply_transformer_simulation(self.app._config_dict(), self.result)
            self.app._apply_config(config)
        except (ValueError, OSError, KeyError, tk.TclError) as exc:
            self.write('无法采用本次结果：' + str(exc))
            return
        self.applied = True
        self.refresh()
        self.write('场解参数与报告记录已写入当前单元，正在按新参数重算。')
        self.app.status_var.set('变压器仿真参数已采用，可返回画布并保存系统工程。')

    def close(self):
        if self.job is not None:
            self.cancel()
            return
        self.win.destroy()

    def destroyed(self, event):
        if event.widget is self.win:
            if self.job is not None:
                self.job.set()
            if self.poll_id is not None:
                self.win.after_cancel(self.poll_id)


def show(app):
    try:
        config = app._config_dict()
    except (ValueError, tk.TclError) as exc:
        messagebox.showerror('请检查当前单元输入', str(exc), parent=app.root)
        return None
    return _SimulationDialog(app, config).win
