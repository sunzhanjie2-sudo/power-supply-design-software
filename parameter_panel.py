"""Parameter presentation only: the engine's variables and JSON keys stay intact."""
import math
import re
import tkinter as tk
from tkinter import ttk

import magnetics as mag
from engineering_ui import Tooltip
from parameter_layout import GROUPS, META, SECTION_ORDER, SECTION_TITLES, applicable, visible
from device_curve_ui import DeviceCurveUI
from diode_curves import DEPRECATED_RD
from custom_core_ui import CustomCoreUI, CoreGeometryEditor
from custom_cores import CUSTOM_CORE, is_custom


ISOLATED = ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')
OPTIONAL = {'C_out2': 'cout2_enable', 'Cin2': 'cin2_enable',
            'Vf_din': 'd_in_enable', 'Vf_dout': 'd_out_enable'}
OPTION_NAMES = {'cout2_enable': '启用输出第二电容', 'cin2_enable': '启用输入第二电容',
                'd_in_enable': '启用输入防反二极管', 'd_out_enable': '启用输出防反二极管'}
OUTPUT_OWNED = {'V_out', 'P_out', 'C_out', 'Rc', 'ESL', 'C_out2', 'Rc2', 'ESL2',
                'Vf_diode', 'Rd_diode', 'Qrr', 'Vf_dout', 'Rd_dout', 'ripple_target',
                'Ns', 'd_wire_s', 'n_strand_s'}
PSR_COMPATIBILITY = {'KP', 'fz1', 'fz2', 'fp1', 'fp2'}


def display_number(value):
    return f'{value:.10g}'


def search_matches(query, text):
    if not query:
        return True
    normalized = (text+' '+text.replace('µ', 'u')).lower()
    if re.fullmatch(r'[a-z0-9_]+', query):
        return re.search(r'(?<![a-z0-9])'+re.escape(query), normalized) is not None
    return query in normalized


class ParameterPanelUI(DeviceCurveUI, CustomCoreUI):
    def _param_unit_choices(self, key):
        unit = META[key].unit
        options = self.unit_opts.get(key, [])
        return {prefix.replace('u', 'µ') + unit: prefix for prefix in options} if options else {unit: ''}

    def _presentation_context(self):
        topo, mode = self._topo_key(), self._ctrl_key()
        if topo == 'FLYBACK' and self.feedback_mode.get() == 'PSR-MP6005':
            mode = 'Peak Current Mode'
        return topo, mode

    def _sync_param_field(self, key, *_):
        if key in self._param_binding_busy:
            return
        self._param_binding_busy.add(key)
        try:
            spec = META[key]
            try:
                value = self.params[key].get()
            except (tk.TclError, ValueError):
                # Invalid/incomplete edits remain invalid in the engine variable.
                if self._psr_active() and key in ('f_sw', 'A_sense'):
                    value = 0  # draw the fixed effective value, never the invalid SSR draft
                else:
                    return
            if key in self._param_auto_vars:
                automatic = value == 0
                self._param_auto_vars[key].set(automatic)
                if not automatic and math.isfinite(value):
                    self._param_auto_saved[key] = (value, self.params[key+'_unit'].get())
                self._param_widgets[key][1].configure(state='readonly' if automatic else 'normal')
            text = '自动' if spec.auto and value == 0 else display_number(value * spec.display_factor)
            self._param_display_vars[key].set(text)
            if key in self._param_unit_vars:
                prefix = self.params[key+'_unit'].get()
                full = next((label for label, p in self._param_unit_choices(key).items() if p == prefix), None)
                if full is not None:
                    self._param_unit_vars[key].set(full)
            if key == 'A_sense' and self._psr_active():
                self._param_display_vars[key].set('11')
                self._param_widgets[key][1].configure(state='readonly')
            elif key == 'A_sense':
                self._param_widgets[key][1].configure(state='normal')
            if key == 'f_sw':
                if self._psr_active():
                    prefix = self.params[key+'_unit'].get()
                    self._param_display_vars[key].set(display_number(250e3 / self.units[prefix]))
                self._param_widgets[key][1].configure(state='readonly' if self._psr_active() else 'normal')
                self._param_widgets[key][2].configure(state='disabled' if self._psr_active() else 'readonly')
        finally:
            self._param_binding_busy.discard(key)

    def _param_edit(self, key, *_):
        if key in self._param_binding_busy:
            return
        raw_text = self._param_display_vars[key].get().strip()
        if key in self._param_auto_vars and self._param_auto_vars[key].get():
            return
        try:
            value = float(raw_text) / META[key].display_factor
        except ValueError:
            value = raw_text
        # Prevent canonical-to-view syncing from rewriting a partial edit such
        # as '1.' or silently turning an invalid field into its previous value.
        self._param_binding_busy.add(key)
        try:
            self.params[key].set(value)
            if key in self._param_auto_saved and isinstance(value, float) and value != 0:
                self._param_auto_saved[key] = (value, self.params[key+'_unit'].get())
        finally:
            self._param_binding_busy.discard(key)
        if META[key].auto and isinstance(value, float) and value == 0:
            self._sync_param_field(key)
        self._refresh_param_summaries()

    def _change_param_unit(self, key):
        choices = self._param_unit_choices(key)
        requested = choices.get(self._param_unit_vars[key].get())
        current = self.params[key+'_unit'].get()
        if requested is None or requested == current:
            return
        try:
            value = self.params[key].get()
        except (tk.TclError, ValueError):
            self._sync_param_field(key)
            self._param_unit_vars[key].set(next((label for label, p in choices.items() if p == current), ''))
            return
        was_building = self._building
        self._building = True
        self._param_binding_busy.add(key)
        try:
            si_value = value * self.units[current]
            self.params[key].set(si_value / self.units[requested])
            self.params[key+'_unit'].set(requested)
        finally:
            self._param_binding_busy.discard(key)
            self._building = was_building
        self._sync_param_field(key)
        self._refresh_param_summaries()
        if not was_building:
            self.schedule_update()

    def _toggle_param_auto(self, key):
        automatic = self._param_auto_vars[key].get()
        was_building = self._building
        self._building = True
        try:
            if automatic:
                try:
                    value = self.params[key].get()
                    if value != 0:
                        self._param_auto_saved[key] = (value, self.params[key+'_unit'].get())
                except (ValueError, tk.TclError):
                    pass
                self.params[key].set(0)
            else:
                saved = self._param_auto_saved.get(key)
                if saved:
                    value, prefix = saved
                    self.params[key].set(value)
                    self.params[key+'_unit'].set(prefix)
                else:
                    self.params[key].set('')
                    self._param_display_vars[key].set('')
                    self._param_widgets[key][1].configure(state='normal')
        finally:
            self._building = was_building
        self._sync_param_field(key)
        self._refresh_param_summaries()
        if not was_building:
            self.schedule_update()

    def _psr_active(self):
        return self._topo_key() == 'FLYBACK' and self.feedback_mode.get() == 'PSR-MP6005'

    def _multiple_active(self):
        return self._topo_key() in ISOLATED and self.multi_enabled.get()

    def _output_owns_parameter(self, key):
        return self._multiple_active() and (key in OUTPUT_OWNED or (key == 'L' and self._topo_key() == 'ACF-FORWARD'))

    def _scalar_parameter_active(self, key):
        """Calculation ownership, independent of search/folding/basic mode."""
        if key in DEPRECATED_RD:return False
        if key == 'MLT' and not self._standard_mlt_active():return False
        topo, mode = self._presentation_context()
        spec = META[key]
        if key == 'gfs' and self._mos_resolved_mode() != 'gfs':return False
        if key == 'mos_curve_vds' and not (self._mos_resolved_mode()=='curve' and self._mos_miller_curve.get('kind')=='output_family'):return False
        if self._mos_charge_parameter_hidden(key):return False
        if key == 'Vgp_off' and self._mos_current_plateau_active():
            return False
        if not applicable(key, topo, mode) or self._output_owns_parameter(key):
            return False
        if spec.enabled_by and not self.params[spec.enabled_by].get():
            return False
        if self._psr_active() and key in PSR_COMPATIBILITY | {'f_sw', 'A_sense'}:
            return False
        return True

    def _build_param_panel(self, parent, specifications, topology_labels, control_labels):
        self.params['mos_miller_mode']=tk.StringVar(value='auto')
        self._mos_miller_curve={}
        self.params['mos_charge_mode']=tk.StringVar(value='manual')
        self._mos_charge_curve={}
        self._diode_curves={}
        self._device_curve_settings={}
        self._curve_binding_busy=False
        self._param_display_vars, self._param_unit_vars = {}, {}
        self._param_auto_vars, self._param_auto_saved = {}, {}
        self._param_binding_busy = set()
        self._param_summary_vars, self._param_subgroups = {}, []
        self._param_extras, self._param_switches, self._param_status_vars = [], {}, {}
        self._param_group_keys = {}
        self._param_search_terms = {}
        self._cap_editors={}
        self._cap_bank_active={'input':False,'output':False}
        self._build_param_filters(parent)
        by_key = {key: (label, units) for key, label, units, _section in specifications}
        # Optional switches must exist before any summaries or filters run.
        from power_stage import DEFAULT_PARAMS
        for key in OPTION_NAMES:
            self.params[key] = tk.BooleanVar(value=DEFAULT_PARAMS.get(key, False))
        rows = {}
        for section in SECTION_ORDER:
            frame = self._add_section(parent, SECTION_TITLES[section])
            self._param_sections[section] = frame
            self._param_group_keys[section] = []
            summary = tk.StringVar()
            self._param_summary_vars[section] = summary
            label = ttk.Label(frame._section_container, textvariable=summary, style='Muted.TLabel',
                              wraplength=350, padding=(6, 0, 6, 4), justify='left')
            label.pack(fill='x', before=frame)
            frame._section_summary = label
            row = 0
            if section == 'spec':
                row = self._build_scheme_rows(frame, row, topology_labels, control_labels)
            if section == 'curves':
                row = self._build_device_curve_controls(frame, row)
            if section == 'mag':
                row = self._build_core_picker_rows(frame, row)
            if section == 'ctrl':
                row = self._build_feedback_rows(frame, row)
            if section == 'device':
                row = self._build_manual_events(frame, row)
            for title, keys in GROUPS[section]:
                group_label = ttk.Label(frame, text=title, style='TLabelframe.Label', padding=(2, 6, 2, 3))
                group_label.grid(row=row, column=0, columnspan=4, sticky='ew')
                self._param_subgroups.append((frame, group_label, keys))
                row += 1
                for key in keys:
                    if key in OPTIONAL:
                        switch_key = OPTIONAL[key]
                        check = ttk.Checkbutton(frame, text=OPTION_NAMES[switch_key], variable=self.params[switch_key],
                                                command=self._filter_params)
                        check.grid(row=row, column=0, columnspan=4, sticky='w', pady=(4, 2))
                        self._param_switches[switch_key] = check
                        self._register_param_extra(frame, [check], keys, OPTION_NAMES[switch_key]+' '+switch_key)
                        row += 1
                        status = tk.StringVar()
                        status_label = ttk.Label(frame, textvariable=status, style='Muted.TLabel', wraplength=340)
                        status_label.grid(row=row, column=0, columnspan=4, sticky='w', pady=(0, 3))
                        self._param_status_vars[switch_key] = status
                        self._register_param_extra(frame, [status_label], keys, OPTION_NAMES[switch_key]+' '+switch_key)
                        row += 1
                    label_text, units = by_key[key]
                    self._param_search_terms[key] = title
                    self._param_row(frame, row, key, label_text, units)
                    self._param_group_keys[section].append(key)
                    row += 1
            if section == 'capacitors':
                from capacitor_ui import BankEditor
                from capacitor_banks import bank
                for side,label in (('input','输入并联电容组'),('output','输出并联电容组')):
                    holder=ttk.LabelFrame(frame,text=label)
                    holder.grid(row=row,column=0,columnspan=4,sticky='ew',pady=5)
                    editor=BankEditor(holder,bank(DEFAULT_PARAMS,side),lambda s=side:self._capacitor_bank_changed(s))
                    editor.pack(fill='x',padx=3,pady=3);self._cap_editors[side]=editor
                    self._register_param_extra(frame,[holder],text=label+' C ESR ESL 电容数量 capacitors',
                        predicate=(lambda:self._multiple_active()==False) if side=='output' else None)
                    row+=1
            if section == 'stage':
                row = self._build_clamp_parameter_rows(frame, row)
                from parasitic_ui import open_editor
                button=ttk.Button(frame,text='寄生参数与吸收…（快速 / 寄生瞬态）',command=lambda:open_editor(self))
                button.grid(row=row,column=0,columnspan=4,sticky='ew',pady=6)
                self._register_param_extra(frame,[button],('N',),'寄生 振铃 Coss Cj 布线 电容 吸收 RC')
                row+=1
            if section == 'device':
                self.mos_gate_readout = tk.StringVar(value='当前 MOS 平台：待计算')
                note = ttk.Label(frame, text='导入、切换来源与四工况核算已集中到上方“器件计算方式与曲线”。曲线模式仍需填写 Rds(on)、Coss、Vth、内部栅阻及驱动参数。',
                                 style='Muted.TLabel', wraplength=350, justify='left')
                reading = ttk.Label(frame, textvariable=self.mos_gate_readout, style='Muted.TLabel', wraplength=350, justify='left')
                note.grid(row=row, column=0, columnspan=4, sticky='ew', pady=4)
                reading.grid(row=row+1, column=0, columnspan=4, sticky='ew', pady=4)
                self._register_param_extra(frame, [note, reading], ('gfs','Vgp_on','Vgp_off'), 'MOS 米勒平台 实际开通关断电流 Id Vgp 曲线 Qgs')
                row += 2
            row = self._build_output_parameter_rows(frame, row, section)
            if section == 'mag':
                note = ttk.Label(frame, text='磁损系数：Pv[mW/cm³] = k·(f/kHz)^α·B[T]^β。\n自动模式仍使用原引擎的 0=auto；不填虚构手动值。',
                                 style='Muted.TLabel', wraplength=350, justify='left')
                note.grid(row=row, column=0, columnspan=4, sticky='w', pady=4)
                self._register_param_extra(frame, [note], ('k_core', 'a_core', 'b_core'), '磁损系数 计算约定')
                row += 1
            rows[section] = row
        self._param_scheme_row = rows
        # Start with every applicable group expanded. Users can still fold
        # groups explicitly; filtering must never conceal a material model.
        for key in OPTION_NAMES:
            self.params[key].trace_add('write', lambda *_: self._filter_params())
        self.params['gfs'].trace_add('write', lambda *_: self._filter_params())
        self.params['mos_miller_mode'].trace_add('write', self._mos_mode_changed)
        self.params['mos_charge_mode'].trace_add('write', self._mos_mode_changed)
        for variable in (self.multi_enabled, self.feedback_mode, self.feedback_output):
            variable.trace_add('write', lambda *_: self._parameter_context_changed())
        self._refresh_param_rows()

    def _param_row(self, parent, row, key, original_label, units):
        spec = META[key]
        label = spec.label + (' '+spec.symbol if spec.symbol else '')
        if spec.required:
            label += ' *'
        lab = ttk.Label(parent, text=label, style='Param.TLabel', wraplength=170, justify='left')
        lab.grid(row=row, column=0, sticky='w', padx=(2, 6), pady=3)
        self.param_labels.append(lab)
        parent.columnconfigure(0, weight=1)
        display = tk.StringVar()
        self._param_display_vars[key] = display
        entry = ttk.Entry(parent, textvariable=display, width=8)
        entry.grid(row=row, column=1, sticky='ew', padx=2, pady=3)
        widgets = [lab, entry]
        shown = tk.StringVar()
        self._param_unit_vars[key] = shown
        if len(units) > 1:
            combo = ttk.Combobox(parent, textvariable=shown, values=list(self._param_unit_choices(key)), width=7, state='readonly')
            combo.grid(row=row, column=2, padx=(2, 4), pady=3)
            combo.bind('<<ComboboxSelected>>', lambda _event, k=key: self._change_param_unit(k))
            widgets.append(combo)
        else:
            unit_label = ttk.Label(parent, textvariable=shown, style='Muted.TLabel', wraplength=78, justify='left')
            unit_label.grid(row=row, column=2, sticky='w', padx=4)
            widgets.append(unit_label)
        density = key in ('d_wire_p', 'n_strand_p', 'd_wire_s', 'n_strand_s')
        side = ttk.Frame(parent) if density else parent
        if density:
            side.grid(row=row, column=3, sticky='w', padx=(3, 0), pady=3)
            widgets.append(side)
        if spec.auto:
            automatic = tk.BooleanVar(value=self.params[key].get() == 0)
            self._param_auto_vars[key] = automatic
            check = ttk.Checkbutton(side, text='自动', variable=automatic, command=lambda k=key: self._toggle_param_auto(k))
            if density:
                check.pack(anchor='w')
            else:
                check.grid(row=row, column=3, sticky='w', padx=(1, 0))
                widgets.append(check)
        if density:
            self._transformer_density_label(side, 'P' if key.endswith('_p') else 'OUT1').pack(anchor='w')
        self._param_widgets[key] = widgets
        self.params[key].trace_add('write', lambda *_, k=key: self._sync_param_field(k))
        self.params[key+'_unit'].trace_add('write', lambda *_, k=key: self._sync_param_field(k))
        display.trace_add('write', lambda *_, k=key: self._param_edit(k))
        note = original_label+'\n配置字段：'+key+'；内部前缀保持旧格式。'
        if spec.required:
            note += '\n* 当前计算模型所需，请核对规格书和工况；预设不是厂家保证值。'
        if spec.display_factor == 100:
            note += '\n显示为百分数；计算/JSON仍保存0~1比例，不更改计算模型。'
        if spec.auto:
            note += '\n自动切换保留当前手动值；加载新配置后不继承上个设计的手动缓存。'
        if key == 'Rth_transformer':
            note += '\nΔT=(全部绕组铜损+磁芯损耗)×Ri-a；默认100 K/W仅为初始假设，请按实测或热设计填写。不是局部热点热阻。'
        Tooltip(lab, note)
        Tooltip(entry, note)
        self._sync_param_field(key)

    def _register_param_extra(self, frame, widgets, keys=(), text='', predicate=None):
        self._param_extras.append((frame, widgets, tuple(keys), text, predicate))

    def _mos_current_plateau_active(self):
        return self._mos_resolved_mode() in ('curve','gfs')

    def _mark_mos_gate_stale(self):
        if hasattr(self, 'mos_gate_readout'):
            self.mos_gate_readout.set('当前 MOS 平台：待计算，旧工况值已清除。')

    def _update_mos_gate_readout(self, res):
        gate = res['semi']['switch']['gate']
        self._curve_gate_result=gate
        self.mos_gate_readout.set(gate['label']+f"\nId,on={gate['I_on']:.4g} A → Vgp,on={gate['Vgp_on']:.4g} V\n"
                                 f"Id,off={gate['I_off']:.4g} A → Vgp,off={gate['Vgp_off']:.4g} V\n"
                                 f"Qgs,on/off={gate['Qgs_on']*1e9:.4g}/{gate['Qgs_off']*1e9:.4g} nC；Qgd={gate['Qgd_on']*1e9:.4g} nC\n"
                                 f"Qg(th)={gate['Qg_th']*1e9:.4g} nC；Qg,total={gate['Qg_on']*1e9:.4g} nC"+
                                 ('\n本工况含端点趋势外推，请结合规格书/实测校核。' if gate.get('extrapolations') or gate.get('charge_extrapolations') else ''))

    def _build_scheme_rows(self, frame, row, topology_labels, control_labels):
        for name, var, values, attr in (
                ('拓扑', self.params['topology'], list(topology_labels.values()), 'topo_combo'),
                ('控制模式', self.params['control_mode'], list(control_labels.values()), 'ctrl_combo')):
            label = ttk.Label(frame, text=name, style='Param.TLabel')
            label.grid(row=row, column=0, columnspan=4, sticky='w', pady=(3, 1))
            if attr == 'ctrl_combo':
                self._param_mode_display = tk.StringVar(value=var.get())
                var = self._param_mode_display
            combo = ttk.Combobox(frame, textvariable=var, values=values, state='readonly', width=18)
            if attr == 'ctrl_combo':
                combo.bind('<<ComboboxSelected>>', lambda _e: self.params['control_mode'].set(self._param_mode_display.get()))
            combo.grid(row=row+1, column=0, columnspan=4, sticky='ew', pady=(0, 5))
            setattr(self, attr, combo)
            self._register_param_extra(frame, [label, combo], text=name+' topology control_mode')
            row += 2
        self.single_output_note = tk.StringVar()
        note = ttk.Label(frame, textvariable=self.single_output_note, style='Muted.TLabel', wraplength=350)
        note.grid(row=row, column=0, columnspan=4, sticky='ew')
        self._register_param_extra(frame, [note], text='输出配置 多绕组 outputs')
        row += 1
        label = ttk.Label(frame, text='显示工况（全部页面）', style='Param.TLabel')
        label.grid(row=row, column=0, columnspan=4, sticky='w', pady=(6, 1))
        self._input_case_display = tk.StringVar(value='Vin min · 输入下限')
        self.input_case_combo = ttk.Combobox(frame, textvariable=self._input_case_display,
            values=('Vin min · 输入下限', 'Vin max · 输入上限'), state='readonly')
        self.input_case_combo.grid(row=row+1, column=0, columnspan=4, sticky='ew', pady=(0, 4))
        self.input_case_combo.bind('<<ComboboxSelected>>', lambda _e:
            self.params['input_voltage_case'].set('max' if self._input_case_display.get().startswith('Vin max') else 'min'))
        note = ttk.Label(frame, text='同一套器件在两端电压下计算；自动磁件以 Vin min 为参考。报告包含两端完整工况，不随此选择删减。',
            style='Muted.TLabel', wraplength=350, justify='left')
        note.grid(row=row+2, column=0, columnspan=4, sticky='ew', pady=(0, 4))
        self._register_param_extra(frame, [label, self.input_case_combo, note],
            ('V_in_min', 'V_in_max'), '输入电压 工况 Vin min max 波形')
        self.params['input_voltage_case'].trace_add('write', lambda *_: self._refresh_param_summaries())
        return row + 3

    def _build_clamp_parameter_rows(self, frame, row):
        flyback = lambda: self._topo_key() in ('FLYBACK', 'QR-FLYBACK')
        header = ttk.Label(frame, text='RCD 漏感钳位', style='TLabelframe.Label', padding=(2, 6, 2, 3))
        header.grid(row=row, column=0, columnspan=4, sticky='ew')
        self._register_param_extra(frame, [header], text='RCD 钳位 漏感 snubber', predicate=flyback)
        row += 1
        self._rcd_param_widgets = {}
        for key, label, symbol in (('rcd_K', '旧版漏感系数 K（非 kij）', 'K'),
                                   ('rcd_Kc', '钳位比 Vclamp/Vreflect', 'Kc'),
                                   ('rcd_dC', '钳位电压波动比例（0–1）', 'dC')):
            caption = ttk.Label(frame, text=label, style='Param.TLabel', wraplength=165)
            caption.grid(row=row, column=0, sticky='w', padx=(2, 6), pady=3)
            self.param_labels.append(caption)
            entry = ttk.Entry(frame, textvariable=self.params[key], width=8)
            entry.grid(row=row, column=1, columnspan=3, sticky='ew', padx=2, pady=3)
            self._rcd_param_widgets[key] = (caption, entry)
            active = (lambda: flyback() and not (hasattr(self, 'coupling_enabled') and
                      self.coupling_enabled.get() and self._topo_key() == 'FLYBACK' and
                      self._effective_feedback_mode() == 'SSR')) if key == 'rcd_K' else flyback
            self._register_param_extra(frame, [caption, entry], text=f'RCD 钳位 {label} {key} {symbol}', predicate=active)
            row += 1
        return row

    def _build_core_picker_rows(self, frame, row):
        self._init_custom_core_controls()
        ttk_label = ttk.Label(frame, text='先选择材料和磁芯，再配置绕组；L/变比在②组编辑。', style='Muted.TLabel', wraplength=350)
        ttk_label.grid(row=row, column=0, columnspan=4, sticky='w', pady=3)
        self._register_param_extra(frame, [ttk_label], text='磁芯 材料 绕组')
        row += 1
        self.params['core_shape'] = tk.StringVar(value='auto')
        self.params['core_choice_L'] = tk.StringVar(value='auto')
        for name, var, choices, attr, callback, predicate in (
                ('磁芯材料', None, list(mag.STEINMETZ_MATERIALS), 'mat_combo', self.on_material_change, None),
                ('磁芯形状', self.params['core_shape'], ['auto']+mag.core_shape_list(), 'shape_combo', self.on_core_shape_change, None),
                ('磁芯型号', self.params['core_choice'], ['auto',CUSTOM_CORE]+list(mag.CORE_DB), 'core_combo', self.on_core_model_change, None),
                ('正激输出电感磁芯', self.params['core_choice_L'], ['auto',CUSTOM_CORE]+list(mag.CORE_DB), 'inductor_core_combo', None,
                 lambda: self._topo_key() == 'ACF-FORWARD' and not self._multiple_active())):
            label = ttk.Label(frame, text=name, style='Param.TLabel', wraplength=150)
            label.grid(row=row, column=0, sticky='w', pady=3)
            combo = ttk.Combobox(frame, textvariable=var, values=choices, state='readonly', width=14)
            combo.grid(row=row, column=1, columnspan=3, sticky='ew', pady=3)
            setattr(self, attr, combo)
            if attr == 'mat_combo':
                combo.set('N87')
            if callback:
                combo.bind('<<ComboboxSelected>>', lambda _event, fn=callback: fn())
            logical_key = {'mat_combo': 'material', 'shape_combo': 'core_shape',
                           'core_combo': 'core_choice', 'inductor_core_combo': 'core_choice_L'}[attr]
            self._register_param_extra(frame, [label, combo], text=name+' '+logical_key, predicate=predicate)
            row += 1
            if attr in ('core_combo','inductor_core_combo'):
                key='custom_core' if attr=='core_combo' else 'custom_core_L'
                editor=CoreGeometryEditor(frame,self._custom_core_vars[key],self._custom_core_edited,
                    '当前磁芯有效尺寸' if attr=='core_combo' else '独立输出电感有效尺寸')
                editor.frame.grid(row=row,column=0,columnspan=4,sticky='ew')
                self._custom_core_editors[key]=editor
                visible_core=(lambda:is_custom(self.params['core_choice'].get())) if key=='custom_core' else (
                    lambda:self._topo_key()=='ACF-FORWARD' and not self._multiple_active() and is_custom(self.params['core_choice_L'].get()))
                self._register_param_extra(frame,[editor.frame],text=key+' 自定义 非标准 磁芯 Ae Ve Wa MLT 尺寸 mm cm',predicate=visible_core)
                var.trace_add('write',self._custom_core_context_changed)
                row+=1
        return row

    def _build_feedback_rows(self, frame, row):
        label = ttk.Label(frame, text='补偿类型', style='Param.TLabel')
        label.grid(row=row, column=0, sticky='w', pady=3)
        self._param_controller_display = tk.StringVar(value=self.params['controller_type'].get())
        combo = ttk.Combobox(frame, textvariable=self._param_controller_display, values=('auto', 'type2', 'type3'), state='readonly', width=12)
        combo.bind('<<ComboboxSelected>>', lambda _e: self.params['controller_type'].set(self._param_controller_display.get()))
        self._param_controller_combo = combo
        combo.grid(row=row, column=1, columnspan=3, sticky='ew')
        self._register_param_extra(frame, [label, combo], text='补偿类型 controller_type 二型 三型')
        row += 1
        row = self._add_param_link(frame, row, '自动整定在环路页；SSR 保留五项零极点。MP6005 使用下方物理 COMP 参数。', '查看环路 / 自动整定', 'tab_loop')
        return row

    def _add_param_link(self, frame, row, text, caption, tab, topologies=()):
        label = ttk.Label(frame, text=text, style='Muted.TLabel', wraplength=350, justify='left')
        label.grid(row=row, column=0, columnspan=4, sticky='ew', pady=(4, 2))
        button = ttk.Button(frame, text=caption, command=lambda: self._open_parameter_tab(tab))
        button.grid(row=row+1, column=0, columnspan=4, sticky='ew', pady=(0, 3))
        predicate = (lambda: self._topo_key() in topologies) if topologies else None
        self._register_param_extra(frame, [label, button], text=text+' '+caption, predicate=predicate)
        return row + 2

    def _open_parameter_tab(self, tab):
        self._sync_topology_pages()
        target = getattr(self, tab)
        if str(self.nb.tab(target, 'state')) == 'hidden':
            self.status_var.set('此工具不适用于当前拓扑或工作区域；请查看当前拓扑与控制器核算结果。')
            return
        self.nb.select(target)
        self._refresh_visible_tab()

    def _open_outputs_from_parameters(self):
        if self._topo_key() in ISOLATED:
            self.edit_outputs()

    def _parameter_context_changed(self):
        if not hasattr(self, '_param_display_vars'):
            return
        self._refresh_param_rows()
        self._filter_params()
        if hasattr(self, 'nb') and hasattr(self, 'tab_comp'):
            self._sync_topology_pages()
        if not self._building and not self._inline_binding_busy:
            self.schedule_update()

    def _refresh_param_rows(self):
        for key in self._param_widgets:
            self._sync_param_field(key)
        topo, mode = self._presentation_context()
        label = '励磁电感 Lm' if topo in ('FLYBACK', 'QR-FLYBACK') else '输出滤波电感 Lout' if topo == 'ACF-FORWARD' else '功率电感 L'
        if topo=='FLYBACK' and hasattr(self,'coupling_enabled') and self.coupling_enabled.get() and self._effective_feedback_mode()=='SSR':
            label = '原边自感 Lp（开路测量）'
        self._param_widgets['L'][0].configure(text=label+' *')
        self._param_widgets['f_sw'][0].configure(text='频率上限 fmax *' if topo == 'QR-FLYBACK' else '开关频率 fsw *')
        self._param_widgets['N'][0].configure(text='原副边匝比 Np/Ns(OUT1) *' if self._multiple_active() else '原副边匝比 Np/Ns *')
        for _frame, header, keys in self._param_subgroups:
            if keys == ('Vf_diode', 'Rd_diode', 'Qrr'):
                header.configure(text='D1 / D2 · 固定 Vf/Qrr 共用，曲线独立' if topo == 'ACF-FORWARD' else 'D1 · 输出整流器')
        self._param_widgets['A_sense'][1].configure(state='readonly' if self._psr_active() else 'normal')
        multiple = topo in ISOLATED and self.multi_enabled.get()
        for key in ('V_out', 'P_out'):
            self._param_widgets[key][1].configure(state='readonly' if multiple else 'normal')
        self._param_mode_display.set('Peak Current Mode (峰值电流模式)' if self._psr_active() else self.params['control_mode'].get())
        self.ctrl_combo.configure(state='disabled' if self._psr_active() else 'readonly')
        self._param_controller_display.set('type2 (MP6005)' if self._psr_active() else self.params['controller_type'].get())
        self._param_controller_combo.configure(state='disabled' if self._psr_active() else 'readonly')
        self.inductor_core_combo.configure(state='disabled' if multiple and topo == 'ACF-FORWARD' else 'readonly')
        self._sync_inline_output_context()
        self._sync_mos_curve_controls()
        self._sync_device_curve_controls()
        self._refresh_param_summaries()

    def _capacitor_bank_changed(self,side):
        self._cap_bank_active[side]=True
        if not self._building:
            self._refresh_param_summaries()
            self.schedule_update()

    def _capacitor_parameters(self):
        return {side+'_capacitors':editor.get() if self._cap_bank_active[side] else None
                for side,editor in self._cap_editors.items()}

    def _load_capacitor_parameters(self,cfg):
        from capacitor_banks import bank
        from config_io import decode_config
        from power_stage import DEFAULT_PARAMS
        p=dict(DEFAULT_PARAMS,**decode_config(cfg))
        for side,editor in self._cap_editors.items():
            editor.load(bank(p,side))
            self._cap_bank_active[side]=p.get(side+'_capacitors') is not None

    def _refresh_param_summaries(self):
        if not hasattr(self, '_param_summary_vars'):
            return
        def val(key, suffix=''):
            try:
                return display_number(self.get_param(key)) + suffix
            except (ValueError, KeyError, tk.TclError):
                return '待填写'
        topo, mode = self._presentation_context()
        case = 'max' if self.params['input_voltage_case'].get() == 'max' else 'min'
        if hasattr(self, '_input_case_display'):
            self._input_case_display.set('Vin max · 输入上限' if case == 'max' else 'Vin min · 输入下限')
        range_text = val('V_in_min', 'V')+'–'+val('V_in_max', 'V')
        state = '当前' if self._snapshot_valid else '待计算'
        self.input_case_note.set(f"{state}：Vin {case} = {val('V_in', 'V')}  ·  输入范围 {range_text}")
        multiple = topo in ISOLATED and self.multi_enabled.get()
        if multiple:
            demand = f'{range_text} · {len(self.output_config)} 路输出'
            self.single_output_note.set('多输出已启用：各路需求、整流器、电容和副边绕组在本侧栏对应分组编辑。')
        else:
            demand = range_text+' → '+val('V_out', 'V')+' · '+val('P_out', 'W')
            self.single_output_note.set('单路输出；可在下方启用最多6路绕组输出。' if topo in ISOLATED else '非隔离单输出；已隐藏变压器、多绕组和钳位参数。')
        try:
            eta = display_number(self.get_param('eta_guess') * 100)+'%'
        except (ValueError, tk.TclError):
            eta = '待填写'
        summaries = {
            'spec': demand+' · 预设效率 '+eta+(' · MP6005 PWM固定250kHz，轻载另核算' if self._psr_active() else ''),
            'stage': ('励磁' if topo in ('FLYBACK', 'QR-FLYBACK') else '输出电感')+' · '+('有源钳位' if topo == 'ACF-FORWARD' else 'RCD' if topo in ('FLYBACK', 'QR-FLYBACK') else '非隔离功率级'),
            'device': '预设 / 手工参数 · 栅极电荷法（*模型必需）',
            'capacitors': f"输入 {len(self._cap_editors['input'].values) if 'input' in self._cap_editors else 2} 颗 / "+('各路输出独立配置' if multiple else f"输出 {len(self._cap_editors['output'].values) if 'output' in self._cap_editors else 2} 颗电容")+' · 可增删',
            'drive': 'Vgs '+val('Vgs', 'V')+' · 开通/关断电阻分别配置',
            'sense': ('MP6005：PCM，采样增益固定11' if self._psr_active() else '电压模式' if mode == 'Voltage Mode' else '峰值电流模式')+' · 采样电阻仍计损耗',
            'mag': '材料 / 磁芯 → 绕组 → 温升；自动与手工分开',
            'ctrl': (('PSR-MP6005' if self._psr_active() else 'SSR')+f' · OUT{self.feedback_output.get() if multiple else 1}' if topo in ISOLATED else '非隔离反馈')+' · '+('type2（MP6005）' if self._psr_active() else self._controller_key()),
        }
        for section, text in summaries.items():
            if section == 'ctrl' and 'fc_target' in self.params:
                text += ' · 目标 fc '+val('fc_target', 'Hz')+' / PM '+val('pm_target', '°')
            missing = [key for key in self._param_group_keys.get(section, []) if META[key].required and applicable(key, topo, mode)
                       and not (key == 'Vgp_off' and self._mos_current_plateau_active()) and not self._mos_charge_parameter_hidden(key)
                       and not self._output_owns_parameter(key)
                       and self._param_value_missing(key)]
            if missing:
                text += f' · {len(missing)} 项必需数值待填写'
            self._param_summary_vars[section].set(text)
        for switch_key, var in self._param_status_vars.items():
            enabled = self.params[switch_key].get()
            var.set('已启用：参与当前模型' if enabled else '已停用：保留参数，不参与当前模型')

    def _param_value_missing(self, key):
        try:
            return not math.isfinite(self.get_param(key))
        except (ValueError, KeyError, tk.TclError):
            return True

    def _filter_parameter_panel(self):
        if not hasattr(self, '_param_extras'):
            return
        Tooltip.hide_all(self.root)
        self._refresh_param_rows()
        search = self.param_search.get().strip().lower()
        topo, mode = self._presentation_context()
        flags = {key: self.params[key].get() for key in OPTION_NAMES}
        visible_keys = set()
        for key, widgets in self._param_widgets.items():
            spec = META[key]
            section = widgets[0].master
            terms = ' '.join((key, spec.label, spec.symbol, widgets[0].cget('text'), section._section_title,
                              self._param_search_terms[key], self._param_unit_vars[key].get()))
            matches = search_matches(search, terms)
            allowed = key not in DEPRECATED_RD and visible(key, topo, mode, True, flags)
            from capacitor_banks import FIELDS
            if key in FIELDS:allowed=False
            if key=='MLT' and not self._standard_mlt_active():allowed=False
            if key == 'V_in':
                allowed = False  # compatibility variable; range is the only editor
            if key == 'Vgp_off' and self._mos_current_plateau_active():
                allowed = False
            if key == 'gfs' and self._mos_resolved_mode()!='gfs':allowed=False
            if key == 'mos_curve_vds' and not (self._mos_resolved_mode()=='curve' and self._mos_miller_curve.get('kind')=='output_family'):allowed=False
            if self._mos_charge_parameter_hidden(key):allowed=False
            if self._output_owns_parameter(key):
                allowed = False
            if self._psr_active() and key in PSR_COMPATIBILITY:
                allowed = False
            allowed = allowed and matches and (section not in self._folded_sections or bool(search))
            for widget in widgets:
                widget.grid() if allowed else widget.grid_remove()
            if allowed:
                visible_keys.add(key)
        for frame, widgets, keys, text, predicate in self._param_extras:
            related = any(key in visible_keys for key in keys)
            context_ok = predicate is None or predicate()
            from capacitor_banks import FIELDS
            if keys and set(keys).issubset(FIELDS):context_ok=False
            if keys and all(self._output_owns_parameter(key) for key in keys):
                context_ok = False
            # Optional switches stay visible even when their child fields are
            # disabled. Searching never exposes disabled, unused values.
            matches = search_matches(search, text+' '+frame._section_title) or related or any(search_matches(search, key) for key in keys)
            allowed = context_ok and matches and (frame not in self._folded_sections or bool(search))
            for widget in widgets:
                widget.grid() if allowed else widget.grid_remove()
        for frame, header, keys in self._param_subgroups:
            allowed = any(key in visible_keys for key in keys)
            # A disabled optional subgroup still contains its enable switch.
            allowed = allowed or any(OPTIONAL.get(key) in self._param_switches and self._param_switches[OPTIONAL[key]].grid_info() for key in keys)
            header.grid() if allowed else header.grid_remove()
        for section in SECTION_ORDER:
            frame = self._param_sections[section]
            has_content = bool(frame.grid_slaves())
            frame.pack(fill='x') if has_content else frame.pack_forget()
            frame._section_header.configure(text=('▼ ' if has_content else '▶ ')+frame._section_title)
            frame._section_container.pack_forget()
            if not search or has_content:
                frame._section_container.pack(fill='x', pady=3)
        pending = getattr(self, '_param_layout_job', None)
        if pending is not None:
            self.root.after_cancel(pending)
        self._param_layout_job=None
        self._schedule_parameter_scrollregion()
