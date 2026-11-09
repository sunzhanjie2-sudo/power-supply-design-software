"""Shared, non-blocking desktop settings for the bundled field runtime.

Machine executable paths are separate from the portable core-model profile.
The parent owns scrolling and the actual joint/field job; this panel only
captures plain values, persists settings and checks the local environment.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk


CORE_MODES = {
    'assembled': '已装配磁芯（CAD 已含实际气隙）',
    'half_center_gap': '单个半芯 · 中柱磨隙后镜像装配',
    'half_spacer': '单个半芯 · 整面垫片后镜像装配',
}
MESH_PROFILES = {'coarse': '粗网格', 'standard': '标准网格', 'fine': '细网格'}


class EnvironmentPanel(ttk.Frame):
    """Reusable settings panel; all Tcl calls remain in the Tk thread."""

    def __init__(self, parent, config, initial=None):
        super().__init__(parent)
        import simulation_environment as environment
        self._config = copy.deepcopy(config)
        self.controls = []
        self._labels = []
        self._closed = False
        self._poll_id = None
        self._layout_id = None
        self._checking = False
        self._mailbox = queue.Queue()
        self._values = {}
        self._vectors = {}
        self._source = {}
        self.columnconfigure(0, weight=1)
        title = ttk.Label(self, text='提取内核已随设计软件携带，无需另外安装变压器提取程序。',
                          font='TkHeadingFont', wraplength=800, justify='left')
        title.grid(row=0, column=0, sticky='ew', padx=10, pady=(10, 3))
        self._labels.append(title)
        note = ttk.Label(self, text='首次在本机指定 Elmer 和 LTspice；磁芯模型可保存或导出为配置包。'
                         '匝数、线径、层序、材料和接线从当前设计生成，“提取设置 JSON”由程序自动建立。',
                         wraplength=800, justify='left')
        note.grid(row=1, column=0, sticky='ew', padx=10, pady=(0, 10))
        self._labels.append(note)

        machine = self._section(2, '01  本机求解软件')
        self._path_row(machine, 0, 'Elmer 安装目录', 'elmer_home', self.pick_elmer)
        self._path_row(machine, 1, 'LTspice 可执行程序', 'ltspice', self.pick_spice)
        self.executable = self._values['ltspice']
        self._hint(machine, 2, 'Elmer 目录应含 bin/ElmerSolver.exe 和 bin/ElmerGrid.exe。'
                   '更换电脑后重新定位这两个软件；CAD 与模型配置可直接携带。')

        model = self._section(3, '02  当前磁芯模型')
        self.model_label = ttk.Label(model, font='TkHeadingFont', wraplength=700)
        self.model_label.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 5))
        self._labels.append(self.model_label)
        self._path_row(model, 1, '磁芯实体 STEP / BREP', 'core_path', self.pick_core)
        self._choice_row(model, 2, '磁芯装配方式', 'core_mode', CORE_MODES.values())
        self._choice_row(model, 3, 'BREP 文件单位', 'brep_unit', ('mm', 'm'))
        self._number_row(model, 4, '中柱半径 / mm', 'center_leg_radius_m')
        self._number_row(model, 5, '气隙中心 Z / mm', 'gap_center_z_m')
        self._text_row(model, 6, 'CAD / 装配依据', 'core_source')
        self._hint(model, 7, 'STEP 使用文件内单位；BREP 使用所选单位。单半芯必须按 Z 方向及镜像面建模；'
                   '中柱磨隙模式需填写中柱半径。不能把任意姿态的 STEP 当作已校准模型。')

        geometry = self._section(4, '03  坐标与求解设置')
        self._number_row(geometry, 0, '绕组内侧基准 r0 / mm', 'r0_m')
        self._number_row(geometry, 1, '绕组轴向起点 z0 / mm', 'z0_m')
        self._vector_row(geometry, 2, 'CAD 平移 X / Y / Z · mm', 'translation_mm')
        self._vector_row(geometry, 3, 'CAD 转角 X / Y / Z · °', 'rotation_deg')
        self._choice_row(geometry, 4, '网格档位', 'mesh_profile', MESH_PROFILES.values())
        self._number_row(geometry, 5, '空气域半径 / mm', 'air_radius_m')
        self._number_row(geometry, 6, '单次求解超时 / s', 'timeout_s')
        self._hint(geometry, 7, 'r0、z0 优先来自当前变压器建模设置；缺失时需按骨架与 CAD 坐标补齐。'
                   '总气隙与磁导率采用当前设计。网格档位不是收敛验证结论。')

        actions = ttk.Frame(self)
        actions.grid(row=5, column=0, sticky='ew', padx=10, pady=(5, 7))
        self._action_widgets = []
        self.check_button = self._button(actions, '检查运行环境', self.check)
        self._button(actions, '保存本机与模型配置', self.save)
        self._button(actions, '导入模型配置包…', self.import_model)
        self._button(actions, '导出模型配置包…', self.export_model)
        self._button(actions, '导入旧提取设置…', self.import_legacy)
        self.status = tk.StringVar(self, '配置未检查。检查通过后可在上一页开始仿真。')
        self.status_label = ttk.Label(self, textvariable=self.status, wraplength=800, justify='left')
        self.status_label.grid(row=6, column=0, sticky='ew', padx=10, pady=(0, 8))
        self._labels.append(self.status_label)
        self._actions = actions
        self._set_values(initial if initial is not None else environment.load_environment(config))
        self.bind('<Configure>', self._schedule_layout, add='+')
        self.bind('<Destroy>', self._destroyed, add='+')
        self._schedule_layout()

    def _section(self, row, text):
        box = ttk.LabelFrame(self, text=text, padding=10)
        box.grid(row=row, column=0, sticky='ew', padx=10, pady=(0, 10))
        box.columnconfigure(1, weight=1)
        return box

    def _label(self, frame, row, text):
        label = ttk.Label(frame, text=text, wraplength=220, justify='left')
        label.grid(row=row, column=0, sticky='w', padx=(0, 10), pady=5)
        return label

    def _path_row(self, frame, row, label, key, command):
        self._text_row(frame, row, label, key, span=1)
        button = ttk.Button(frame, text='选择…', command=command)
        button.grid(row=row, column=2, padx=(7, 0), pady=5)
        self.controls.append(button)

    def _text_row(self, frame, row, label, key, span=2):
        self._label(frame, row, label)
        variable = self._values[key] = tk.StringVar(self)
        entry = ttk.Entry(frame, textvariable=variable, width=32)
        entry.grid(row=row, column=1, columnspan=span, sticky='ew', pady=5)
        self.controls.append(entry)

    def _number_row(self, frame, row, label, key):
        self._label(frame, row, label)
        variable = self._values[key] = tk.StringVar(self)
        entry = ttk.Entry(frame, textvariable=variable, width=18)
        entry.grid(row=row, column=1, sticky='w', pady=5)
        self.controls.append(entry)

    def _choice_row(self, frame, row, label, key, values):
        self._label(frame, row, label)
        variable = self._values[key] = tk.StringVar(self)
        choice = ttk.Combobox(frame, textvariable=variable, values=tuple(values), state='readonly', width=32)
        choice.grid(row=row, column=1, columnspan=2, sticky='ew', pady=5)
        self.controls.append(choice)

    def _vector_row(self, frame, row, label, key):
        self._label(frame, row, label)
        box = ttk.Frame(frame)
        box.grid(row=row, column=1, columnspan=2, sticky='ew', pady=5)
        variables = self._vectors[key] = []
        for i in range(3):
            box.columnconfigure(i, weight=1)
            variable = tk.StringVar(self)
            variables.append(variable)
            entry = ttk.Entry(box, textvariable=variable, width=8)
            entry.grid(row=0, column=i, sticky='ew', padx=(0 if i == 0 else 5, 0))
            self.controls.append(entry)

    def _hint(self, frame, row, text):
        hint = ttk.Label(frame, text=text, wraplength=780, justify='left')
        hint.grid(row=row, column=0, columnspan=3, sticky='ew', pady=(5, 0))
        self._labels.append(hint)

    def _button(self, parent, text, command):
        button = ttk.Button(parent, text=text, command=command)
        self.controls.append(button)
        self._action_widgets.append(button)
        return button

    def _schedule_layout(self, event=None):
        if self._closed or event is not None and event.widget is not self:
            return
        if self._layout_id is None:
            self._layout_id = self.after_idle(self._layout)

    def _layout(self):
        self._layout_id = None
        if self._closed:
            return
        width = self.winfo_width()
        if width < 10:
            width = 850
        for label in self._labels:
            label.configure(wraplength=max(260, width - 65))
        total = max(1, sum(button.winfo_reqwidth() + 8 for button in self._action_widgets))
        columns = min(len(self._action_widgets), max(1, int((width - 20) / (total / len(self._action_widgets)))))
        for i, button in enumerate(self._action_widgets):
            button.grid(row=i // columns, column=i % columns, sticky='ew', padx=(0, 7), pady=4)
        for i in range(len(self._action_widgets)):
            self._actions.columnconfigure(i, weight=1 if i < columns else 0)

    def _set_values(self, values):
        values = copy.deepcopy(values or {})
        self._source = values
        for key, variable in self._values.items():
            value = values.get(key)
            if key == 'core_mode':
                value = CORE_MODES.get(value or 'assembled', value)
            elif key == 'mesh_profile':
                value = MESH_PROFILES.get(value or 'standard', value)
            elif key == 'brep_unit':
                value = value or 'mm'
            elif key in ('r0_m', 'z0_m', 'center_leg_radius_m', 'gap_center_z_m', 'air_radius_m'):
                value = '' if value is None else f'{float(value) * 1000:.10g}'
            variable.set('' if value is None else str(value))
        for key, variables in self._vectors.items():
            vector = values.get(key) or [0., 0., 0.]
            for i, variable in enumerate(variables):
                variable.set(str(vector[i]) if i < len(vector) else '')
        import simulation_environment as environment
        self.model_label.configure(text='当前磁芯：' + environment.core_name(self._config))

    def set_config(self, config):
        import simulation_environment as environment
        old = environment.core_name(self._config)
        self._config = copy.deepcopy(config)
        if environment.core_name(config) != old:
            self._set_values(environment.load_environment(config))
            self.status.set('当前磁芯已切换，请检查对应 CAD 模型和装配设置。')

    @staticmethod
    def _number(text, label, *, optional=False):
        if not text.strip() and optional:
            return None
        try:
            value = float(text)
        except (TypeError, ValueError):
            raise ValueError(label + '需要填写数值。') from None
        if not math.isfinite(value):
            raise ValueError(label + '需要有限数值。')
        return value

    def snapshot(self, require_spice=True):
        """Return immutable-by-convention input data without starting any job."""
        import simulation_environment as environment
        result = copy.deepcopy(self._source)
        for key, variable in self._values.items():
            result[key] = variable.get().strip()
        if result['core_path'] != self._source.get('core_path'):
            result.pop('core_sha256', None)
            result.pop('cad_verified', None)
        reverse = {v: k for k, v in CORE_MODES.items()}
        result['core_mode'] = reverse.get(result['core_mode'], result['core_mode'])
        reverse = {v: k for k, v in MESH_PROFILES.items()}
        result['mesh_profile'] = reverse.get(result['mesh_profile'], result['mesh_profile'])
        if result['core_mode'] not in CORE_MODES:
            raise ValueError('请选择磁芯装配方式。')
        if result['mesh_profile'] not in MESH_PROFILES or result['brep_unit'] not in ('mm', 'm'):
            raise ValueError('请选择网格档位和 BREP 单位。')
        for key, title in [('r0_m', '绕组内侧基准 r0'), ('z0_m', '绕组轴向起点 z0'),
                           ('center_leg_radius_m', '中柱半径'), ('gap_center_z_m', '气隙中心 Z'),
                           ('air_radius_m', '空气域半径')]:
            value = self._number(result[key], title, optional=key in ('r0_m', 'z0_m', 'center_leg_radius_m'))
            result[key] = None if value is None else value / 1000
        result['timeout_s'] = self._number(result['timeout_s'], '单次求解超时')
        if result['timeout_s'] <= 0 or result['air_radius_m'] <= 0:
            raise ValueError('求解超时与空气域半径必须大于零。')
        for key, variables in self._vectors.items():
            result[key] = [self._number(v.get(), 'CAD 平移 / 转角') for v in variables]
        result['core_model'] = environment.core_name(self._config)
        if require_spice and not result['ltspice']:
            raise ValueError('请选择本机 LTspice 可执行程序。')
        return result

    def pick_elmer(self):
        path = filedialog.askdirectory(parent=self.winfo_toplevel(), title='选择含 bin 的 Elmer 安装目录')
        if path:
            self._values['elmer_home'].set(path)
            self.status.set('Elmer 路径已修改，请检查环境并保存配置。')

    def pick_spice(self):
        path = filedialog.askopenfilename(parent=self.winfo_toplevel(), title='选择 LTspice 可执行程序',
                                          filetypes=[('LTspice', '*.exe')])
        if path:
            self.executable.set(path)

    def pick_core(self):
        path = filedialog.askopenfilename(parent=self.winfo_toplevel(), title='选择磁芯实体模型',
            filetypes=[('磁芯实体', '*.step *.stp *.brep'), ('全部文件', '*.*')])
        if path:
            self._values['core_path'].set(path)
            # A different CAD file has no inherited geometric certification.
            self._source.pop('core_sha256', None)
            self._source.pop('cad_verified', None)
            self.status.set('已选择新 CAD。请核对装配方式、单位、姿态和坐标；不会沿用旧模型的校验结论。')

    def save(self):
        import simulation_environment as environment
        try:
            values = self.snapshot(require_spice=False)
            saved = environment.save_environment(self._config, values)
            if isinstance(saved, dict):
                self._set_values(saved)
            self.status.set('已保存本机路径和当前磁芯模型配置。换电脑时导出模型配置包，并重新定位求解软件。')
            return saved
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status.set('配置未保存：' + str(exc))
            return None

    def check(self, require_spice=True):
        if self._checking or self._closed:
            return
        try:
            values = self.snapshot(require_spice=require_spice)
        except (ValueError, tk.TclError) as exc:
            self.status.set('尚未检查：' + str(exc))
            return
        self._checking = True
        self.check_button.state(['disabled'])
        self.status.set('正在检查本机求解软件与内置运行库…')
        mailbox = self._mailbox
        def work():
            try:
                import simulation_environment as environment
                result = environment.check_environment(values, require_spice=require_spice, probe=True)
                mailbox.put(('result', result))
            except Exception as exc:
                mailbox.put(('error', str(exc) or type(exc).__name__))
        threading.Thread(target=work, name='simulation-environment-check', daemon=True).start()
        self._poll_id = self.after(70, self._poll)

    def _poll(self):
        self._poll_id = None
        if self._closed:
            return
        try:
            kind, value = self._mailbox.get_nowait()
        except queue.Empty:
            self._poll_id = self.after(70, self._poll)
            return
        self._checking = False
        self.check_button.state(['!disabled'])
        if kind == 'error':
            self.status.set('环境检查未通过：' + value)
            return
        lines = ['环境检查通过，可开始输入校验与仿真。' if value.get('ok') else '环境检查未通过，请处理以下项目。']
        for check in value.get('checks', []):
            lines.append(('✓ ' if check.get('ok') else '需处理 · ') + str(check.get('name', '')) +
                         '：' + str(check.get('message', '')))
        lines.append('环境检查不替代 CAD 尺寸/绕组空间检查或仿真收敛验证。')
        self.status.set('\n'.join(lines))

    def import_model(self):
        path = filedialog.askopenfilename(parent=self.winfo_toplevel(), title='导入可携带的磁芯模型配置包',
                                          filetypes=[('模型配置包', '*.zip')])
        if not path:
            return
        import simulation_environment as environment
        try:
            values = environment.import_model_package(path, environment.core_name(self._config))
            # A model pack does not overwrite this computer's executable paths.
            values = dict(self.snapshot(require_spice=False), **values)
            self._set_values(values)
            self.status.set('模型配置包已导入；请核对当前磁芯和坐标，然后保存配置。')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status.set('模型配置包未导入：' + str(exc))

    def export_model(self):
        import simulation_environment as environment
        try:
            values = self.snapshot(require_spice=False)
        except (ValueError, tk.TclError) as exc:
            self.status.set('尚未导出：' + str(exc))
            return
        path = filedialog.asksaveasfilename(parent=self.winfo_toplevel(), title='导出磁芯模型配置包',
            defaultextension='.zip', initialfile=environment.core_name(self._config) + '-仿真模型.zip',
            filetypes=[('模型配置包', '*.zip')])
        if not path:
            return
        try:
            environment.export_model_package(values, path, environment.core_name(self._config))
            self.status.set('模型与装配配置已打包：' + str(path) + '\n不包含本机 Elmer / LTspice 路径。')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status.set('模型包未导出：' + str(exc))

    def import_legacy(self):
        path = filedialog.askopenfilename(parent=self.winfo_toplevel(), title='将旧提取设置迁移为磁芯配置',
                                          filetypes=[('旧提取设置', '*.json')])
        if not path:
            return
        import simulation_environment as environment
        try:
            values = environment.from_legacy_template(path)
            values = dict(self.snapshot(require_spice=False), **values)
            expected = environment.core_name(self._config)
            if values.get('core_model') and values['core_model'] != expected:
                raise ValueError('旧设置磁芯型号与当前设计不一致。')
            self._set_values(values)
            self.status.set('旧设置已迁移；仅保留磁芯与求解配置。绕组、磁材及接线仍以当前设计为准。')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status.set('旧设置未导入：' + str(exc))

    def _destroyed(self, event):
        if event.widget is not self or self._closed:
            return
        self._closed = True
        for key in ('_poll_id', '_layout_id'):
            ident = getattr(self, key)
            if ident is not None:
                try:
                    self.after_cancel(ident)
                except tk.TclError:
                    pass
                setattr(self, key, None)
