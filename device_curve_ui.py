"""One topology-aware sidebar entry for all supported semiconductor curves."""
import copy
import tkinter as tk
from tkinter import ttk, messagebox

from device_curve_sources import (TRANSFER, CHARGE, LABELS, targets, source_for,
    curve_for, inferred_settings, source_summary, validate_requests)
from diode_curves import cleanup_message
from mos_curve_ui import MosCurveUI
from diode_curve_ui import DiodeCurveUI

CHOICES = {'跟随全局': None, '固定值估算': 'fixed', '导入曲线计算': 'curve', '旧跨导兼容': 'legacy'}
COLORS = {'fixed': '#667587', 'curve': '#237544', 'missing': '#B53232', 'warning': '#A25C00'}


class DeviceCurveUI(MosCurveUI, DiodeCurveUI):
    def _curve_context(self):
        p = self._diode_context()
        try:
            gfs = self.get_param('gfs')
        except (tk.TclError, ValueError):
            gfs = 0.
        return dict(p, device_curve_settings=self._device_curve_settings,
                    mos_miller_mode=self.params['mos_miller_mode'].get(), gfs=gfs,
                    mos_charge_mode=self.params['mos_charge_mode'].get(),
                    mos_miller_curve=self._mos_miller_curve, mos_charge_curve=self._mos_charge_curve,
                    diode_curves=self._diode_curves)

    def _validate_curve_requests(self):
        validate_requests(self._curve_context())

    def _build_device_curve_controls(self, frame, row):
        frame.columnconfigure(0, weight=1)
        panel = ttk.Frame(frame)
        panel.grid(row=row, column=0, columnspan=4, sticky='ew')
        self._curve_global = tk.StringVar(value='fixed')
        ttk.Label(panel, text='器件损耗怎么计算？', style='Param.TLabel').pack(anchor='w', pady=(0, 4))
        for value, text in (('fixed', '固定值快速估算'), ('curve', '导入曲线精细计算')):
            ttk.Radiobutton(panel, text=text, value=value, variable=self._curve_global,
                            style='CurveMode.TRadiobutton', command=self._choose_global_curve_mode).pack(anchor='w', pady=2)
        ttk.Label(panel, text='可逐项覆盖；切换全局会重置逐项例外，数据保留。仅切换器件损耗来源，不等同完整电路仿真。',
                  style='Muted.TLabel', wraplength=310, justify='left').pack(fill='x', pady=4)
        self._curve_summary = tk.StringVar()
        self._curve_summary_label = ttk.Label(panel, textvariable=self._curve_summary, wraplength=310, justify='left')
        self._curve_summary_label.pack(fill='x', pady=4)
        box = ttk.Frame(panel); box.pack(fill='x')
        self._curve_tree = ttk.Treeview(box, columns=('object', 'kind', 'state'), show='headings',
                                       height=5, selectmode='browse', takefocus=True)
        for key, title, width in (('object', '器件 / 输出', 90), ('kind', '所需曲线', 100), ('state', '来源 / 状态', 112)):
            self._curve_tree.heading(key, text=title)
            self._curve_tree.column(key, width=width, minwidth=60)
        for tag, color in COLORS.items():
            self._curve_tree.tag_configure(tag, foreground=color)
        scroll = ttk.Scrollbar(box, command=self._curve_tree.yview)
        self._curve_tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); self._curve_tree.pack(fill='x')
        self._curve_tree.bind('<<TreeviewSelect>>', lambda _e: self._curve_selection_note())
        self._curve_detail = tk.StringVar()
        ttk.Label(panel, textvariable=self._curve_detail, wraplength=310, justify='left',
                  style='Muted.TLabel').pack(fill='x', pady=5)
        ttk.Label(panel, text='此项计算来源（可覆盖全局）', style='Param.TLabel').pack(anchor='w')
        self._curve_row_source = tk.StringVar(value='跟随全局')
        self._curve_source_combo = ttk.Combobox(panel, textvariable=self._curve_row_source,
                                               values=tuple(CHOICES)[:3], state='readonly')
        self._curve_source_combo.pack(fill='x')
        self._curve_source_combo.bind('<<ComboboxSelected>>', self._choose_row_curve_source)
        actions = ttk.Frame(panel); actions.pack(fill='x', pady=(5, 0))
        ttk.Button(actions, text='导入 / 替换所选…', command=self._import_selected_curve).pack(side='left', expand=True, fill='x')
        self._curve_preview_button = ttk.Button(actions, text='预览曲线…', command=self._preview_selected_curve)
        self._curve_preview_button.pack(side='left', padx=(4, 0))
        actions = ttk.Frame(panel); actions.pack(fill='x', pady=4)
        self._curve_unbind_button = ttk.Button(actions, text='解除绑定', command=self._unbind_selected_curve)
        self._curve_unbind_button.pack(side='left', expand=True, fill='x')
        self._curve_reuse_button = ttk.Button(actions, text='复用到其他二极管…', command=self._reuse_diode_curve)
        self._curve_reuse_button.pack(side='left', padx=(4, 0))
        ttk.Button(panel, text='查看 MOS Vinmin / Vinmax 四工况…', command=self._show_mos_four).pack(fill='x', pady=3)
        ttk.Label(panel, text='文件仍只需 x,y 数值；导入时确认 X/Y 数量级。切换方式不删除曲线或手动值。\n'
                  '绿色=曲线已校验并启用；灰色=固定值或已停用；橙色=整理/外推；红色=待导入。',
                  style='Muted.TLabel', wraplength=310, justify='left').pack(fill='x', pady=4)
        def fit(event):
            width = max(180, event.width - 8)
            for child in panel.winfo_children():
                if isinstance(child, ttk.Label): child.configure(wraplength=width)
        panel.bind('<Configure>', fit)
        self._register_param_extra(frame, [panel], text='曲线 导入 计算方式 固定值 精细 MOS 二极管 Q1 Vgs Id Qg Vf If CSV JSON')
        self._curve_signature = None
        return row + 1

    def _ensure_curve_settings(self):
        if not self._device_curve_settings:
            self._device_curve_settings = inferred_settings(self._curve_context())

    def _sync_curve_source_params(self):
        if not self._device_curve_settings: return
        self._curve_binding_busy = True
        try:
            p = self._curve_context()
            self.params['mos_miller_mode'].set({'fixed':'manual', 'curve':'curve', 'legacy':'gfs'}[source_for(p, TRANSFER)])
            self.params['mos_charge_mode'].set('curve' if source_for(p, CHARGE) == 'curve' else 'manual')
        finally:
            self._curve_binding_busy = False

    def _curve_sources_changed(self):
        self._sync_curve_source_params()
        self._curve_signature = None
        self._filter_params()
        if not self._building: self.schedule_update()

    def _choose_global_curve_mode(self):
        # Clicking either choice deliberately resets all per-row exceptions.
        self._device_curve_settings = dict(mode=self._curve_global.get(), overrides={})
        self._curve_sources_changed()

    def _set_curve_override(self, target, source):
        self._ensure_curve_settings()
        overrides = self._device_curve_settings['overrides']
        if source is None: overrides.pop(target, None)
        else: overrides[target] = source
        self._curve_sources_changed()

    def _choose_row_curve_source(self, _event=None):
        row = self._selected_curve_row()
        if row: self._set_curve_override(row['target'], CHOICES[self._curve_row_source.get()])

    def _selected_curve_row(self):
        selection = self._curve_tree.selection()
        return next((row for row in getattr(self, '_curve_rows', []) if selection and row['target'] == selection[0]), None)

    def _curve_warning(self, row, curve):
        messages = [cleanup_message(curve)] if row['target'] not in (TRANSFER, CHARGE) else []
        if getattr(self, '_snapshot_valid', False):
            if row['target'] in (TRANSFER, CHARGE):
                gate = getattr(self, '_curve_gate_result', {})
                key = 'extrapolations' if row['target'] == TRANSFER else 'charge_extrapolations'
                if gate.get(key): messages.append('当前工况使用端点趋势外推，请校核。')
            else:
                messages += getattr(self, '_diode_result_models', {}).get(row['target'], {}).get('extrapolations', [])
        return '；'.join(message for message in messages if message)

    def _sync_device_curve_controls(self):
        if not hasattr(self, '_curve_tree') or not hasattr(self, '_inline_output_vars'): return
        p = self._curve_context()
        self._curve_rows = targets(p)
        settings = self._device_curve_settings or inferred_settings(p)
        self._curve_global.set(settings['mode'])
        rows = []
        missing = 0
        for row in self._curve_rows:
            target = row['target']; source = source_for(p, target); curve = curve_for(p, target)
            if source == 'curve' and not curve:
                tag, state = 'missing', '待导入'; missing += 1
            elif source == 'curve':
                tag = 'warning' if self._curve_warning(row, curve) else 'curve'
                state = '曲线 · 需校核' if tag == 'warning' else '曲线已启用'
            else:
                tag, state = 'fixed', LABELS[source] + (' · 已存曲线' if curve else '')
            obj = row['ref']
            if row.get('rail'): obj += f" / OUT{row['rail']}"
            kind = ('Id–Vds' if curve.get('kind')=='output_family' else 'Id–Vgs') if target == TRANSFER else 'Vgs–Qg' if target == CHARGE else 'If–Vf'
            rows.append((target, obj, kind, state, tag))
        signature = tuple(rows)
        if signature != self._curve_signature:
            selection = self._curve_tree.selection()
            self._curve_tree.delete(*self._curve_tree.get_children())
            for target, obj, kind, state, tag in rows:
                self._curve_tree.insert('', 'end', iid=target, values=(obj, kind, state), tags=(tag,))
            if rows:
                target = selection[0] if selection and selection[0] in self._curve_tree.get_children() else rows[0][0]
                self._curve_tree.selection_set(target)
            self._curve_signature = signature
        text = source_summary(p)
        if missing: text += f'\n待导入：{missing} 项。请补齐曲线，或逐项改用固定值后再计算。'
        self._curve_summary.set(text)
        self._curve_summary_label.configure(foreground=COLORS['missing' if missing else 'warning' if '混合' in text else 'curve' if settings['mode']=='curve' else 'fixed'])
        self._param_summary_vars['curves'].set(text.split('\n')[0])
        self._curve_selection_note()

    def _curve_selection_note(self):
        row = self._selected_curve_row()
        if not row: return
        p = self._curve_context(); target = row['target']; curve = curve_for(p, target); source = source_for(p, target)
        settings = self._device_curve_settings or inferred_settings(p)
        override = settings['overrides'].get(target)
        self._curve_source_combo.configure(values=tuple(CHOICES) if override == 'legacy' else tuple(CHOICES)[:3])
        self._curve_row_source.set(next((label for label, value in CHOICES.items() if value == override), '跟随全局'))
        axes = row['axes']
        if target == TRANSFER and curve.get('kind') == 'output_family': axes = '旧输出曲线族：X=Vds / V；Y=Id / A；按 Vgs 分组'
        text = f"{row['ref']} · {row['role']}\n{axes}\n当前来源：{LABELS[source]}"
        if curve:
            points = curve.get('points', []) or [pt for trace in curve.get('traces', []) for pt in trace['points']]
            text += f"\n{'使用' if source == 'curve' else '已存但不使用'}：{curve.get('name','未命名曲线')} · {len(points)} 点"
            if points:
                text += f"\nX 范围 {min(pt[0] for pt in points):.5g}–{max(pt[0] for pt in points):.5g}；Y 范围 {min(pt[1] for pt in points):.5g}–{max(pt[1] for pt in points):.5g}（上述基本单位）"
            warning = self._curve_warning(row, curve)
            if warning and source == 'curve': text += '\n' + warning
            origin = curve.get('source', {}).get('filename') or curve.get('import_file', {}).get('filename')
            if origin: text += '\n文件：' + str(origin)
            if curve.get('conditions'): text += '\n条件：' + str(curve['conditions'])
        elif source == 'curve': text += '\n尚未导入，不会自动改用固定值。'
        else: text += '\n手动数值在下方 MOS / 对应输出路 / 防反器件参数组编辑。'
        if target == CHARGE:
            text += '\n曲线读取 Qgs、Qgd、Qg(th) 与总 Qg；四事件复用所选参考曲线，并非按电流重建 Qgd。'
        elif target == TRANSFER:
            text += '\n由电流反查栅压，只是动态米勒平台的静态近似。'
        else:
            text += '\n正向特性只用于导通损耗；工作点/换流仍用固定 Vf，Qrr 仍单独输入。'
            model = getattr(self, '_diode_result_models', {}).get(target)
            if model and getattr(self, '_snapshot_valid', False):
                text += f"\n当前 Pcond={model['P_cond']:.5g} W；If,pk={model['I_max']:.5g} A。"
        self._curve_detail.set(text)
        self._curve_preview_button.configure(state='normal' if curve else 'disabled')
        self._curve_unbind_button.configure(state='normal' if curve else 'disabled')
        self._curve_reuse_button.configure(state='normal' if curve and target not in (TRANSFER, CHARGE) else 'disabled')

    def _import_selected_curve(self):
        row = self._selected_curve_row()
        if not row: return
        if row['target'] == TRANSFER: self._import_mos_curve()
        elif row['target'] == CHARGE: self._import_gate_charge()
        else: self._import_diode_curve()

    def _unbind_selected_curve(self):
        row = self._selected_curve_row()
        if not row: return
        target = row['target']
        if not messagebox.askyesno('解除曲线绑定', f"解除 {row['ref']} · {row['role']} 的曲线并明确改用固定值。手动草稿保留，原文件不会删除。继续？", parent=self.root): return
        self._ensure_curve_settings()
        if target == TRANSFER: self._mos_miller_curve = {}
        elif target == CHARGE: self._mos_charge_curve = {}
        else: self._diode_curves.pop(target, None)
        self._set_curve_override(target, 'fixed')

    def _preview_selected_curve(self):
        row = self._selected_curve_row()
        if not row: return
        curve = curve_for(self._curve_context(), row['target'])
        if not curve: return
        old=getattr(self,'_device_curve_preview',None)
        if old is not None and old.winfo_exists(): old.destroy()
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from simple_curve_ui import _place_dialog
        dialog = tk.Toplevel(self.root); dialog.title(row['ref'] + ' · ' + curve.get('name', '曲线预览'))
        self._device_curve_preview=dialog
        dialog.transient(self.root); dialog.geometry('660x460')
        ttk.Label(dialog, text=row['role']+'；'+row['axes']+'；数据已换算至基本单位', padding=8).pack(fill='x')
        figure = Figure(figsize=(6.3, 3.6), dpi=100, tight_layout=True); ax = figure.subplots()
        series = curve.get('traces') or [curve]
        for trace in series:
            ax.plot([pt[0] for pt in trace['points']], [pt[1] for pt in trace['points']], '.-', markersize=3)
        if row['target'] == CHARGE: ax.set(xlabel='Qg / C', ylabel='Vgs / V')
        elif row['target'] == TRANSFER: ax.set(xlabel='Vds / V' if curve.get('kind')=='output_family' else 'Vgs / V', ylabel='Id / A')
        else: ax.set(xlabel='Vf / V', ylabel='If / A')
        ax.grid(alpha=.25)
        ax.set_xscale(curve.get('x_scale','linear')); ax.set_yscale(curve.get('y_scale','linear'))
        canvas = FigureCanvasTkAgg(figure, master=dialog); canvas.get_tk_widget().pack(fill='both', expand=True); canvas.draw_idle()
        def release(event):
            if event.widget is dialog:
                figure.clear()
                self._device_curve_preview=None
        dialog.bind('<Destroy>',release,add='+')
        ttk.Button(dialog, text='关闭', command=dialog.destroy).pack(pady=6)
        _place_dialog(dialog, self.root)

    def _reuse_diode_curve(self):
        row = self._selected_curve_row()
        if not row or row['target'] in (TRANSFER, CHARGE): return
        curve = self._diode_curves.get(row['target'])
        if not curve: return
        from simple_curve_ui import _place_dialog
        dialog = tk.Toplevel(self.root); dialog.title('显式选择曲线复用目标'); dialog.transient(self.root)
        ttk.Label(dialog, text=f"来源 {row['ref']}：{curve['name']}\n请仅选择同型号、同温度/测试条件的二极管；已有绑定会被替换。",
                  wraplength=400, padding=10).pack(fill='x')
        choices = {}
        for other in self._curve_rows:
            target = other['target']
            if target in (TRANSFER, CHARGE, row['target']): continue
            var = tk.BooleanVar(value=False); choices[target] = var
            ttk.Checkbutton(dialog, text=other['ref']+' · '+other['role'], variable=var).pack(anchor='w', padx=12, pady=2)
        def accept():
            selected = [target for target, var in choices.items() if var.get()]
            if not selected: return
            if not messagebox.askyesno('确认复用', '将复制到 '+ '、'.join(selected)+' 并启用曲线计算。继续？', parent=dialog): return
            self._ensure_curve_settings()
            for target in selected:
                self._diode_curves[target] = copy.deepcopy(curve)
                self._device_curve_settings['overrides'][target] = 'curve'
            self._curve_sources_changed(); dialog.destroy()
        ttk.Button(dialog, text='复制并启用所选', command=accept).pack(side='right', padx=10, pady=10)
        ttk.Button(dialog, text='取消', command=dialog.destroy).pack(side='right', pady=10)
        _place_dialog(dialog, self.root)
