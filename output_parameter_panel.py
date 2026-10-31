"""Inline, topology-aware editors for isolated outputs and MP6005 PSR.

The engine and JSON continue to use SI values.  The left panel is the only
editable source; result notebooks never contain a second configuration form.
"""
import copy
import math
import json
import tkinter as tk
from tkinter import ttk

import magnetics as mag
from isolated_fields import FIELDS
from isolated_outputs import ISOLATED, RAIL_KEYS, output_specs
from mp6005 import DEFAULTS
from winding_coupling import default_coupling_config, resolve_winding_model, validate_coupling_config
from custom_cores import CUSTOM_CORE, is_custom
from custom_core_ui import CoreGeometryEditor


OUTPUT_GROUPS = {
    'spec': ('name', 'V_out', 'P_out', 'P_out_min', 'ripple_target'),
    'stage': ('L',),
    'device': ('Vf_diode', 'Rd_diode', 'Qrr'),
    'capacitors': ('C_out', 'Rc', 'ESL', 'cout2_enable', 'C_out2', 'Rc2', 'ESL2',
                   'd_out_enable', 'Vf_dout', 'Rd_dout'),
    'mag': ('Ns', 'd_wire_s', 'n_strand_s', 'core_choice_L'),
}
BOOL_LABELS = {'cout2_enable': '启用并联输出电容 B', 'd_out_enable': '启用输出防反二极管'}
OPTION_OWNER = {'C_out2': 'cout2_enable', 'Rc2': 'cout2_enable', 'ESL2': 'cout2_enable',
                'Vf_dout': 'd_out_enable', 'Rd_dout': 'd_out_enable'}
FORWARD_ONLY = {'L', 'core_choice_L', 'custom_core_L'}


class OutputParameterPanel:
    def _init_inline_output_state(self):
        self._inline_cap_editors={}
        self._inline_cap_active={}
        from power_stage import DEFAULT_PARAMS
        self.output_count = tk.StringVar(value='1')
        self._inline_binding_busy = True
        self._inline_output_vars = []
        self._inline_last_max = {}
        self._inline_output_widgets = {}
        self._inline_custom_core_editors = {}
        self._inline_psr_vars = {}
        self._inline_psr_widgets = {}
        self._inline_output_dirty = False
        self._inline_psr_dirty = False
        self._inline_psr_snapshot = {}
        self._inline_output_snapshot = []
        self._inline_count_known = 1
        self._inline_voltage_reference = 1
        self._transformer_density_vars = {}
        self._transformer_dcr_vars = {}
        self._inline_feedback_display = tk.StringVar(value='SSR')
        self.coupling_enabled = tk.BooleanVar(value=False)
        self.coupling_config = default_coupling_config(1)
        self._coupling_vars = {}
        self._coupling_dcr_vars = {}
        self._coupling_widgets = {}
        self._coupling_dirty = False
        for i in range(7):
            # These are readouts, never a second editable resistance source.
            variable = tk.StringVar(value='待计算')
            self._coupling_dcr_vars[i] = variable
            for j in range(i + 1, 7):
                variable = tk.StringVar(value='0.995')
                variable.trace_add('write', lambda *_: self._inline_coupling_edited(False))
                self._coupling_vars[i, j] = variable
        self.coupling_enabled.trace_add('write', lambda *_: self._inline_coupling_edited(True))
        for i in range(6):
            variables = {}
            for key in ('name',) + RAIL_KEYS:
                if key in BOOL_LABELS:
                    variable = tk.BooleanVar(value=DEFAULT_PARAMS[key])
                else:
                    variable = tk.StringVar(value='')
                variable.trace_add('write', lambda *_, n=i, k=key: self._inline_output_edited(n, k))
                variables[key] = variable
            self._inline_output_vars.append(variables)
        for key in DEFAULTS:
            variable = tk.StringVar()
            variable.trace_add('write', lambda *_, k=key: self._inline_psr_edited(k))
            self._inline_psr_vars[key] = variable
        self.output_count.trace_add('write', self._inline_count_edited)
        self.multi_enabled.trace_add('write', self._inline_multi_changed)
        self._reset_inline_output_forms(DEFAULT_PARAMS, [])
        self._sync_inline_psr_values()
        self._inline_binding_busy = False

    @staticmethod
    def _inline_number(value):
        return f'{float(value):.12g}'

    def _output_template(self, base=None, index=0):
        from power_stage import DEFAULT_PARAMS
        data = dict(DEFAULT_PARAMS)
        if base is not None:
            data.update(base)
        if base is None and hasattr(self, 'params'):
            for key in RAIL_KEYS:
                try:
                    if key == 'custom_core_L':
                        if hasattr(self,'_custom_core_vars'):data[key]=self._custom_core_parameters()[key]
                    elif key in BOOL_LABELS or key == 'core_choice_L':
                        data[key] = self.params[key].get()
                    else:
                        data[key] = self.get_param(key)
                except (KeyError, ValueError, tk.TclError):
                    pass
        row = {key: copy.deepcopy(data[key]) for key in RAIL_KEYS}
        capacitors=data.get('output_capacitors')
        if base is None and getattr(self,'_cap_bank_active',{}).get('output'):
            capacitors=self._cap_editors['output'].get()
        if capacitors is not None:row['output_capacitors']=copy.deepcopy(capacitors)
        row['P_out_min'] = row['P_out']
        row['name'] = f'OUT{index + 1}'
        if index:
            row.update(Ns=self._new_output_turns(data), d_wire_s=0., P_out=0., P_out_min=0.)
        return row

    def _new_output_turns(self, base):
        """New rails start at the reference turns, not a hidden old voltage.

        Imported zero-turn legacy rows are deliberately not changed here:
        their stored voltage is needed once by the backend migration.
        """
        try:
            index = max(0, self.feedback_output.get() - 1)
            value = float(self._inline_output_vars[index]['Ns'].get())
            if math.isfinite(value) and value > 0 and value == int(value):
                return int(value)
        except (IndexError, KeyError, ValueError, tk.TclError):
            pass
        transformer = (((getattr(self, '_last', None) or {}).get('res') or {}).get('mag') or {}).get('transformer') or {}
        windings = transformer.get('windings', [])
        for winding in windings:
            if winding.get('id') == self.feedback_output.get():
                return max(1, int(winding['Ns']))
        for value in (transformer.get('Ns'), base.get('Ns')):
            if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
                return max(1, round(value))
        return max(1, round(float(base.get('Np') or 1) / max(float(base.get('N') or 1), 1e-30)))

    def _set_inline_output_row(self, index, data):
        if index in self._inline_cap_editors:
            from capacitor_banks import bank
            self._inline_cap_editors[index].load(bank(data))
            self._inline_cap_active[index]=data.get('output_capacitors') is not None
        for key, variable in self._inline_output_vars[index].items():
            value = data[key]
            if key == 'custom_core_L':
                variable.set(json.dumps(value or {},ensure_ascii=False))
            elif key in BOOL_LABELS or key in ('name', 'core_choice_L'):
                variable.set(value)
            else:
                variable.set(self._inline_number(value / FIELDS[key][2]))
        self._inline_last_max[index]=self._inline_output_vars[index]['P_out'].get()

    def _reset_inline_output_forms(self, base, rails):
        previous = self._inline_binding_busy
        self._inline_binding_busy = True
        try:
            for i in range(6):
                data = self._output_template(base, i)
                if i < len(rails):
                    data.update(rails[i])
                self._set_inline_output_row(i, data)
            self.output_count.set(str(max(1, len(rails))))
            self._inline_count_known = max(1, len(rails))
            self._inline_voltage_reference = self.feedback_output.get()
            self._inline_output_snapshot = copy.deepcopy(self.output_config)
            self._inline_output_dirty = False
        finally:
            self._inline_binding_busy = previous

    def _sync_inline_psr_values(self):
        previous = self._inline_binding_busy
        self._inline_binding_busy = True
        try:
            for key, variable in self._inline_psr_vars.items():
                variable.set(self._inline_number(self.psr_config[key] / FIELDS[key][2]))
            self._inline_psr_dirty = False
            self._inline_psr_snapshot = copy.deepcopy(self.psr_config)
        finally:
            self._inline_binding_busy = previous

    def _inline_multi_changed(self, *_):
        if self._inline_binding_busy:
            return
        if self.multi_enabled.get() and not self.output_config and not self._inline_output_dirty:
            # Seed the first inline design from the currently edited single
            # output, not from stale startup defaults.
            self._reset_inline_output_forms(self._output_template(), [])
        self._inline_request_update()

    def _inline_output_edited(self, index, key):
        if self._inline_binding_busy:
            return
        if key=='P_out':
            values=self._inline_output_vars[index]
            if values['P_out_min'].get()==self._inline_last_max.get(index):
                self._inline_binding_busy=True
                try:values['P_out_min'].set(values['P_out'].get())
                finally:self._inline_binding_busy=False
            self._inline_last_max[index]=values['P_out'].get()
        self._inline_output_dirty = True
        if key in ('Ns','Vf_diode','Vf_dout','d_out_enable') or (key == 'V_out' and index + 1 == self.feedback_output.get()):
            self._preview_inline_output_voltages()
        self._inline_request_update(refilter=key in BOOL_LABELS or key == 'core_choice_L')

    def _preview_inline_output_voltages(self, reference=None):
        """Cheap turns-only preview, independent of the debounced solver.

        A new feedback selection must inherit the latest ratio voltage, not
        the previous solved display. Partial/automatic turns stay untouched;
        canonical backend results resolve those cases after validation.
        """
        if self._inline_binding_busy or not self._inline_multiple_active():
            return
        try:
            count = self._read_output_count()
            selected = self.feedback_output.get() if reference is None else reference
            if not 1 <= selected <= count:
                return
            source = self._inline_output_vars[selected - 1]
            voltage = float(source['V_out'].get())
            turns = float(source['Ns'].get())
            if not math.isfinite(voltage) or voltage <= 0 or not math.isfinite(turns) or turns <= 0 or int(turns) != turns:
                return
        except (ValueError, tk.TclError):
            return
        previous = self._inline_binding_busy
        self._inline_binding_busy = True
        try:
            for index in range(count):
                if index + 1 == selected:
                    continue
                try:
                    secondary = float(self._inline_output_vars[index]['Ns'].get())
                    from voltage_nodes import ratio_voltage
                    def preview(values):
                        return dict(V_out=float(values['V_out'].get()),Vf_diode=float(values['Vf_diode'].get()),
                            Vf_dout=float(values['Vf_dout'].get()),d_out_enable=values['d_out_enable'].get())
                    derived = ratio_voltage(preview(source),preview(self._inline_output_vars[index]),secondary/turns)
                    if (not math.isfinite(secondary) or secondary <= 0 or int(secondary) != secondary
                            or not math.isfinite(derived) or derived <= 0):
                        continue
                except (ValueError, tk.TclError):
                    continue
                self._inline_output_vars[index]['V_out'].set(self._inline_number(derived))
        finally:
            self._inline_binding_busy = previous

    def _inline_psr_edited(self, key):
        if self._inline_binding_busy:
            return
        self._inline_psr_dirty = True
        self._inline_request_update(refilter=False)

    def _inline_count_edited(self, *_):
        if self._inline_binding_busy:
            return
        self._inline_output_dirty = True
        try:
            count = self._read_output_count()
            if self.feedback_output.get() > count:
                self.feedback_output.set(count)
            if count > self._inline_count_known:
                previous = self._inline_binding_busy
                self._inline_binding_busy = True
                try:
                    turns = self._new_output_turns(self._output_template())
                    for index in range(self._inline_count_known, count):
                        if index >= len(self.output_config):
                            self._inline_output_vars[index]['Ns'].set(str(turns))
                finally:
                    self._inline_binding_busy = previous
            self._inline_count_known = count
        except (ValueError, tk.TclError):
            pass
        self._preview_inline_output_voltages()
        self._inline_request_update()

    def _inline_request_update(self, refilter=True):
        if getattr(self, '_building', True):
            return
        if refilter and hasattr(self, '_param_extras'):
            self._filter_params()
        self.schedule_update()

    def _read_output_count(self):
        try:
            number = float(self.output_count.get())
            if not math.isfinite(number) or int(number) != number or not 1 <= number <= 6:
                raise ValueError
        except (ValueError, tk.TclError):
            raise ValueError('启用输出路数必须为 1–6 的整数') from None
        return int(number)

    def _inline_multiple_active(self):
        return self._topo_key() in ISOLATED and self.multi_enabled.get()

    def _inline_output_visible(self, index, key=None):
        if key in ('Rd_diode','Rd_dout'):return False
        if not self._inline_multiple_active():
            return False
        try:
            count = self._read_output_count()
        except ValueError:
            # Keep currently entered fields available while count is incomplete.
            count = max(1, len(self.output_config))
        if index >= count or (key in FORWARD_ONLY and self._topo_key() != 'ACF-FORWARD'):
            return False
        owner = OPTION_OWNER.get(key)
        return owner is None or self._inline_output_vars[index][owner].get()

    def _read_inline_outputs(self, base):
        if not self._inline_multiple_active():
            return []
        if not self._inline_output_dirty and self.output_config != self._inline_output_snapshot:
            self._reset_inline_output_forms(base, self.output_config)
        count = self._read_output_count()
        feedback = self.feedback_output.get()
        rows = []
        for i in range(count):
            data = self._output_template(base, i)
            if i < len(self.output_config):
                data.update(self.output_config[i])
            for key, variable in self._inline_output_vars[i].items():
                if key == 'custom_core_L':
                    data[key]=json.loads(variable.get() or '{}')
                    continue
                if key in ('Rd_diode','Rd_dout'):
                    data[key]=0.
                    continue
                if key == 'V_out' and i + 1 != feedback:
                    # A derived, readonly voltage must not validate or drive a
                    # design, even if an old draft contains incomplete text.
                    continue
                # A flyback has no output choke. Preserve its stored forward
                # values without allowing hidden inputs to change its model.
                if key in FORWARD_ONLY and base['topology'] != 'ACF-FORWARD':
                    self._retain_valid_hidden_output(data, key, variable)
                    continue
                owner = OPTION_OWNER.get(key)
                if owner and not self._inline_output_vars[i][owner].get():
                    self._retain_valid_hidden_output(data, key, variable)
                    continue
                if key in BOOL_LABELS:
                    data[key] = bool(variable.get())
                elif key in ('name', 'core_choice_L'):
                    data[key] = variable.get()[:24]
                else:
                    try:
                        value = float(variable.get()) * FIELDS[key][2]
                        if not math.isfinite(value):
                            raise ValueError
                    except (ValueError, tk.TclError):
                        raise ValueError(f'OUT{i + 1} · {FIELDS[key][0]} 必须填写有限数值') from None
                    # A redraw/save must not round an unchanged SI value
                    # through its human-readable display unit (e.g. 220 uF).
                    stored = data.get(key)
                    if isinstance(stored, (int, float)) and variable.get() == self._inline_number(stored / FIELDS[key][2]):
                        value = stored
                    data[key] = value
            if self._inline_cap_active.get(i):data['output_capacitors']=self._inline_cap_editors[i].get()
            rows.append(data)
        # Validate all visible edits before replacing the canonical design.
        resolved = output_specs(dict(base, outputs=rows, feedback_output=feedback,
                                     feedback_mode=self._effective_feedback_mode()))
        rows = [{key: value for key, value in rail.items() if key != 'id'} for rail in resolved]
        previous = self._inline_binding_busy
        self._inline_binding_busy = True
        try:
            for i, data in enumerate(rows):
                for key in ('V_out', 'Ns'):
                    self._inline_output_vars[i][key].set(self._inline_number(data[key] / FIELDS[key][2]))
        finally:
            self._inline_binding_busy = previous
        self.output_config = copy.deepcopy(rows)
        self._inline_output_snapshot = copy.deepcopy(rows)
        self._inline_output_dirty = False
        return rows

    @staticmethod
    def _retain_valid_hidden_output(data, key, variable):
        """Keep valid inactive edits in saved JSON; ignore incomplete ones.

        A fast topology/enable switch must not discard a valid edit made just
        before the scheduled calculation, nor let an unused invalid edit
        prevent calculation in the new topology.
        """
        if key == 'core_choice_L':
            data[key] = variable.get()
            return
        try:
            stored = data.get(key)
            if isinstance(stored, (int, float)) and variable.get() == OutputParameterPanel._inline_number(stored / FIELDS[key][2]):
                return
            value = float(variable.get()) * FIELDS[key][2]
            if math.isfinite(value) and value >= 0 and (key not in ('L', 'C_out2') or value > 0):
                data[key] = value
        except (ValueError, tk.TclError):
            pass

    def _read_inline_psr(self):
        if not self._inline_psr_dirty and self.psr_config != self._inline_psr_snapshot:
            self._sync_inline_psr_values()
        if self._topo_key() != 'FLYBACK' or self.feedback_mode.get() != 'PSR-MP6005':
            # Same inactive-edit rule as output chokes: valid work is saved,
            # but hidden incomplete MP6005 inputs do not block SSR.
            for key, variable in self._inline_psr_vars.items():
                try:
                    value = float(variable.get()) * FIELDS[key][2]
                    positive = key in ('psr_aux_target', 'psr_RfbH', 'psr_Rcomp', 'psr_Ccomp', 'psr_Cpole', 'psr_Vcc')
                    if math.isfinite(value) and value >= 0 and (not positive or value > 0) and (key != 'psr_Na' or int(value) == value):
                        self.psr_config[key] = value
                except (ValueError, tk.TclError):
                    pass
            self._inline_psr_snapshot = copy.deepcopy(self.psr_config)
            return copy.deepcopy(self.psr_config)
        candidate = {}
        for key, variable in self._inline_psr_vars.items():
            try:
                value = float(variable.get()) * FIELDS[key][2]
                if not math.isfinite(value) or value < 0:
                    raise ValueError
            except (ValueError, tk.TclError):
                raise ValueError(f'MP6005 · {FIELDS[key][0]} 必须填写有限非负值') from None
            if key in ('psr_aux_target', 'psr_RfbH', 'psr_Rcomp', 'psr_Ccomp', 'psr_Cpole', 'psr_Vcc') and value <= 0:
                raise ValueError(f'MP6005 · {FIELDS[key][0]} 必须大于 0')
            if key == 'psr_Na' and int(value) != value:
                raise ValueError('MP6005 辅助绕组必须为整数匝数，0 表示自动')
            candidate[key] = value
        self.psr_config = candidate
        self._inline_psr_dirty = False
        self._inline_psr_snapshot = copy.deepcopy(candidate)
        return copy.deepcopy(candidate)

    def _effective_feedback_mode(self):
        return self.feedback_mode.get() if self._topo_key() == 'FLYBACK' else 'SSR'

    def _coupling_supported(self):
        return self._topo_key() in ('FLYBACK','ACF-FORWARD') and self._effective_feedback_mode() == 'SSR'

    def _coupling_winding_count(self):
        if self._inline_multiple_active():
            try:
                return self._read_output_count() + 1
            except ValueError:
                return max(2, len(self.output_config) + 1)
        return 2

    def _coupling_field_visible(self, i, j=None):
        return (self._coupling_supported() and self.coupling_enabled.get()
                and i < self._coupling_winding_count()
                and (j is None or j < self._coupling_winding_count()))

    def _inline_coupling_edited(self, refilter=False):
        if self._inline_binding_busy:
            return
        self._coupling_dirty = True
        self._inline_request_update(refilter=refilter)

    def _set_inline_coupling_config(self, config, count):
        """A new design clears all previous hidden winding-pair drafts."""
        data = default_coupling_config(count)
        data.update(copy.deepcopy(config or {}))
        # Empty lists are the backwards-compatible unconfigured defaults.
        defaults = default_coupling_config(count)
        data['k'] = data.get('k') or defaults['k']
        data['dcr'] = data.get('dcr') or defaults['dcr']
        previous = self._inline_binding_busy
        self._inline_binding_busy = True
        try:
            for (i, j), variable in self._coupling_vars.items():
                variable.set(self._inline_number(data['k'][i][j] if j <= count else .995))
            for variable in self._coupling_dcr_vars.values():
                variable.set('待计算')
            self.coupling_enabled.set(data['enabled'])
            self.coupling_config = data
            self._coupling_dirty = False
        finally:
            self._inline_binding_busy = previous

    def _read_inline_coupling(self, p):
        """Visible invalid fields block; inactive drafts never poison a model."""
        count = len(p.get('outputs', [])) or 1
        size = count + 1
        active = self._coupling_supported() and self.coupling_enabled.get()
        candidate = default_coupling_config(count)
        candidate['enabled'] = bool(self.coupling_enabled.get())
        try:
            for (i, j), variable in self._coupling_vars.items():
                if j >= size:
                    continue
                try:
                    value = float(variable.get())
                except (ValueError, tk.TclError):
                    raise ValueError(f'k(P,OUT{j}) 必须填写有限数值' if i == 0 else f'k(OUT{i},OUT{j}) 必须填写有限数值') from None
                candidate['k'][i][j] = candidate['k'][j][i] = value
            # DCR is resolved from the current turns, MLT, copper resistivity,
            # diameter and parallel strands by the backend. Never parse its
            # readonly UI text or an old editable draft here.
            if active:
                resolve_winding_model(dict(p, coupling_config=candidate), p.get('outputs'))
            else:
                validate_coupling_config(candidate,count)
        except ValueError:
            if active:
                raise
            # Keep a previously valid same-size design.  New output rows get
            # fresh defaults, not a malformed padded or truncated matrix.
            stored = self.coupling_config
            if len(stored.get('k', [])) == size:
                candidate = copy.deepcopy(stored)
            else:
                candidate = default_coupling_config(count)
        else:
            self.coupling_config = copy.deepcopy(candidate)
            self._coupling_dirty = False
        candidate['enabled'] = bool(active)
        return candidate

    def _build_inline_coupling_rows(self, frame, row):
        supported = self._coupling_supported
        heading = ttk.Label(frame, text='绕组两两耦合 / 漏感（实验模型）',
                            style='TLabelframe.Label', padding=(2, 8, 2, 3))
        heading.grid(row=row, column=0, columnspan=4, sticky='ew')
        self._inline_extra(frame, [heading], '绕组 耦合 漏感 kij mutual coupling', supported)
        row += 1
        check = ttk.Checkbutton(frame, text='启用两两 kij 物理周期计算（反激／正激）', variable=self.coupling_enabled)
        check.grid(row=row, column=0, columnspan=4, sticky='w', pady=3)
        self._coupling_enable_widget = check
        self._inline_extra(frame, [check], '绕组 耦合 漏感 kij coupling_config enabled', supported)
        row += 1
        note = ttk.Label(frame, text='SSR 反激与有源钳位正激：用于计算器物理周期求解及 LTspice 变压器。正激同时求解钳位和逐路输出电感。QR / PSR 暂不支持。kij 不是旧版 RCD K。',
                         style='Muted.TLabel', wraplength=350, justify='left')
        note.grid(row=row, column=0, columnspan=4, sticky='ew', pady=4)
        self._inline_extra(frame, [note], '绕组 耦合 漏感 kij 模型限制 SSR', supported)
        row += 1
        unavailable = ttk.Label(frame, text='已保留绕组耦合草稿；当前 QR / PSR 模型不支持该求解，耦合输入已隐藏。切回 SSR 反激或有源钳位正激后恢复。',
                                style='Muted.TLabel', wraplength=350, justify='left')
        unavailable.grid(row=row, column=0, columnspan=4, sticky='ew', pady=4)
        self._inline_extra(frame, [unavailable], '绕组 耦合 漏感 kij 模型限制 SSR',
                           lambda: self._topo_key() in ISOLATED and not supported() and self.coupling_enabled.get())
        row += 1
        hint = ttk.Label(frame, text='反激 Lp 使用励磁 L；正激 Lp 使用 Lm_forward，不能用输出电感。Lii=Lp/(Np/Nsi)²；DCR 由几何计算。同名端按各拓扑连接。全部 kij=1 为理想模型。',
                         style='Muted.TLabel', wraplength=350, justify='left')
        hint.grid(row=row, column=0, columnspan=4, sticky='ew', pady=4)
        self._inline_extra(frame, [hint], '绕组 自感 Lp Lii 同名端 匝数 Np Ns kij',
                           lambda: supported() and self.coupling_enabled.get())
        row += 1
        for (i, j), variable in self._coupling_vars.items():
            left, right = 'P' if i == 0 else f'OUT{i}', f'OUT{j}'
            caption = ttk.Label(frame, text=f'{left} ↔ {right} · kij', style='Param.TLabel', wraplength=170)
            caption.grid(row=row, column=0, sticky='w', padx=(2, 6), pady=3)
            self.param_labels.append(caption)
            entry = ttk.Entry(frame, textvariable=variable, width=8)
            entry.grid(row=row, column=1, sticky='ew', padx=2, pady=3)
            unit = ttk.Label(frame, text='0 ≤ k ≤ 1', style='Muted.TLabel')
            unit.grid(row=row, column=2, columnspan=2, sticky='w', padx=4)
            widgets = [caption, entry, unit]
            self._coupling_widgets[i, j] = widgets
            self._inline_extra(frame, widgets, f'{left} {right} 绕组 耦合 漏感 kij coupling',
                               lambda n=i, m=j: self._coupling_field_visible(n, m))
            row += 1
        return row

    def _inline_extra(self, frame, widgets, text, predicate):
        self._register_param_extra(frame, widgets, text=text, predicate=predicate)

    def _inline_field(self, frame, row, index, key):
        variable = self._inline_output_vars[index][key]
        predicate = lambda n=index, k=key: self._inline_output_visible(n, k)
        identifier = f'OUT{index + 1}'
        if key in BOOL_LABELS:
            label = BOOL_LABELS[key]
            check = ttk.Checkbutton(frame, text=f'{identifier} · {label}', variable=variable)
            check.grid(row=row, column=0, columnspan=4, sticky='w', pady=3)
            widgets = [check]
        else:
            label, unit = ('名称', '') if key == 'name' else FIELDS[key][:2]
            caption = f'{identifier} · {label}'
            lab = ttk.Label(frame, text=caption, style='Param.TLabel', wraplength=170, justify='left')
            lab.grid(row=row, column=0, sticky='w', padx=(2, 6), pady=3)
            self.param_labels.append(lab)
            if key == 'core_choice_L':
                entry = ttk.Combobox(frame, textvariable=variable, values=['auto',CUSTOM_CORE] + list(mag.CORE_DB), state='readonly', width=12)
            else:
                entry = ttk.Entry(frame, textvariable=variable, width=8)
            entry.grid(row=row, column=1, columnspan=2 if key in ('name', 'core_choice_L') else 1,
                       sticky='ew', padx=2, pady=3)
            widgets = [lab, entry]
            if unit and key != 'core_choice_L':
                unit_label = ttk.Label(frame, text=unit, style='Muted.TLabel')
                unit_label.grid(row=row, column=2, sticky='w', padx=4)
                widgets.append(unit_label)
            if key in ('d_wire_s', 'n_strand_s'):
                readout = self._transformer_density_label(frame, f'OUT{index + 1}')
                readout.grid(row=row, column=3, sticky='w', padx=(3, 0), pady=3)
                widgets.append(readout)
        self._inline_output_widgets[index, key] = widgets
        text = f'{identifier} {key} {label} 多路输出' + (' 正激电感' if key in FORWARD_ONLY else '')
        self._inline_extra(frame, widgets, text, predicate)
        if key == 'core_choice_L':
            editor=CoreGeometryEditor(frame,self._inline_output_vars[index]['custom_core_L'],
                lambda n=index:self._inline_output_edited(n,'custom_core_L'),f'OUT{index+1} 独立电感磁芯尺寸')
            editor.frame.grid(row=row+1,column=0,columnspan=4,sticky='ew')
            self._inline_custom_core_editors[index]=editor
            self._inline_output_widgets[index,'custom_core_L']=[editor.frame]
            active=lambda n=index:self._inline_output_visible(n,'core_choice_L') and is_custom(self._inline_output_vars[n]['core_choice_L'].get())
            self._inline_extra(frame,[editor.frame],f'OUT{index+1} 自定义 非标准 磁芯 Ae Ve Wa MLT mm cm custom_core_L',active)
            return row+2
        return row + 1

    def _build_output_parameter_rows(self, frame, row, section):
        if section == 'spec':
            check = ttk.Checkbutton(frame, text='启用隔离多绕组输出（最多 6 路）', variable=self.multi_enabled)
            check.grid(row=row, column=0, columnspan=4, sticky='w', pady=(8, 3))
            self._inline_multi_check = check
            self._inline_extra(frame, [check], '多绕组 多路输出 outputs', lambda: self._topo_key() in ISOLATED)
            row += 1
            label = ttk.Label(frame, text='启用输出路数', style='Param.TLabel')
            label.grid(row=row, column=0, sticky='w', pady=3)
            spin = ttk.Spinbox(frame, from_=1, to=6, textvariable=self.output_count, width=6)
            spin.grid(row=row, column=1, columnspan=2, sticky='ew', pady=3)
            self._inline_count_picker = spin
            self._inline_extra(frame, [label, spin], '输出路数 outputs count 1 6', self._inline_multiple_active)
            row += 1
        if section == 'ctrl':
            row = self._build_inline_feedback_rows(frame, row)
        if section == 'mag':
            row = self._build_transformer_dcr_row(frame, row, 0,
                                                lambda: self._topo_key() in ISOLATED)
            row = self._build_transformer_dcr_row(frame, row, 1,
                                                lambda: self._topo_key() in ISOLATED and not self._inline_multiple_active())
        for index in range(6):
            keys = OUTPUT_GROUPS.get(section, ())
            if not keys:
                continue
            heading = ttk.Label(frame, text=f'OUT{index + 1} · 独立' + {'spec':'输出需求', 'stage':'输出电感', 'device':'整流器', 'capacitors':'电容与防反', 'mag':'副边绕组'}[section],
                                style='TLabelframe.Label', padding=(2, 8, 2, 3))
            heading.grid(row=row, column=0, columnspan=4, sticky='ew')
            self._inline_extra(frame, [heading], f'OUT{index + 1} 各路输出 '+' '.join(keys),
                               lambda n=index, s=section: self._inline_output_visible(n) and (s != 'stage' or self._topo_key() == 'ACF-FORWARD'))
            row += 1
            if section == 'device':
                self._inline_output_widgets[index, '_rectifier_heading'] = [heading]
            if section == 'capacitors':
                from capacitor_ui import BankEditor
                from capacitor_banks import bank
                def changed(n=index):
                    self._inline_cap_active[n]=True
                    self._inline_output_dirty=True
                    self._inline_request_update(False)
                editor=BankEditor(frame,bank(self._output_template(index=index)),changed)
                editor.grid(row=row,column=0,columnspan=4,sticky='ew',pady=4)
                self._inline_cap_editors[index]=editor
                self._inline_extra(frame,[editor],f'OUT{index+1} 电容数量 C ESR ESL',lambda n=index:self._inline_output_visible(n))
                row+=1
            for key in keys:
                if section=='capacitors' and key in ('C_out','Rc','ESL','cout2_enable','C_out2','Rc2','ESL2'):continue
                row = self._inline_field(frame, row, index, key)
            if section == 'mag':
                row = self._build_transformer_dcr_row(frame, row, index + 1,
                                                     lambda n=index: self._inline_output_visible(n))
        if section == 'mag':
            row = self._build_inline_coupling_rows(frame, row)
        return row

    def _build_inline_feedback_rows(self, frame, row):
        label = ttk.Label(frame, text='隔离反馈方式', style='Param.TLabel')
        label.grid(row=row, column=0, sticky='w', pady=3)
        combo = ttk.Combobox(frame, textvariable=self._inline_feedback_display, values=('SSR', 'PSR-MP6005'), state='readonly', width=14)
        combo.grid(row=row, column=1, columnspan=3, sticky='ew')
        combo.bind('<<ComboboxSelected>>', lambda _e: self.feedback_mode.set(self._inline_feedback_display.get()))
        self._inline_feedback_picker = combo
        self._inline_extra(frame, [label, combo], 'SSR PSR MP6005 feedback_mode 隔离反馈', lambda: self._topo_key() == 'FLYBACK')
        row += 1
        label = ttk.Label(frame, text='主反馈 / PSR 基准 OUT', style='Param.TLabel', wraplength=170)
        label.grid(row=row, column=0, sticky='w', pady=3)
        self.param_labels.append(label)
        self.feedback_pick = ttk.Combobox(frame, textvariable=self.feedback_output, values=(1,), state='readonly', width=5)
        self.feedback_pick.grid(row=row, column=1, columnspan=2, sticky='ew')
        self.feedback_pick.bind('<<ComboboxSelected>>', lambda _e: self.schedule_update())
        self._inline_extra(frame, [label, self.feedback_pick], '主反馈 PSR 基准 OUT feedback_output', self._inline_multiple_active)
        row += 1
        note = ttk.Label(frame, text='MP6005：固定频率反激；PWM 参考 250 kHz。辅助绕组与实物 COMP 网络在本组编辑。', style='Muted.TLabel', wraplength=350, justify='left')
        note.grid(row=row, column=0, columnspan=4, sticky='ew', pady=5)
        self._inline_extra(frame, [note], 'MP6005 PSR 辅助绕组 COMP', lambda: self._topo_key() == 'FLYBACK' and self.feedback_mode.get() == 'PSR-MP6005')
        row += 1
        for key, variable in self._inline_psr_vars.items():
            title, unit, _scale = FIELDS[key]
            label = ttk.Label(frame, text='MP6005 · ' + title, style='Param.TLabel', wraplength=170, justify='left')
            label.grid(row=row, column=0, sticky='w', padx=(2, 6), pady=3)
            self.param_labels.append(label)
            entry = ttk.Entry(frame, textvariable=variable, width=8)
            entry.grid(row=row, column=1, sticky='ew', padx=2, pady=3)
            unit_label = ttk.Label(frame, text=unit, style='Muted.TLabel')
            unit_label.grid(row=row, column=2, sticky='w', padx=4)
            widgets = [label, entry, unit_label]
            self._inline_psr_widgets[key] = widgets
            self._inline_extra(frame, widgets, 'MP6005 PSR ' + key + ' ' + title,
                               lambda: self._topo_key() == 'FLYBACK' and self.feedback_mode.get() == 'PSR-MP6005')
            row += 1
        return row

    def _sync_inline_output_context(self):
        selected = self.feedback_output.get()
        previous = self._inline_voltage_reference
        if selected != previous:
            # Preserve the former reference while refreshing the prospective
            # feedback target. This also covers a rapid switch before solve.
            self._preview_inline_output_voltages(reference=previous)
            self._inline_voltage_reference = selected
        for index in range(6):
            widgets = self._inline_output_widgets.get((index, 'V_out'), [])
            if len(widgets) >= 2:
                reference = index + 1 == self.feedback_output.get()
                widgets[0].configure(text=f'OUT{index + 1} · ' + ('稳压目标电压' if reference else '匝比估算电压'))
                widgets[1].configure(state='normal' if reference else 'readonly')
            widgets = self._inline_output_widgets.get((index, 'Ns'), [])
            if widgets:
                widgets[0].configure(text=f'OUT{index + 1} · ' + ('副边匝数，0=自动' if index + 1 == self.feedback_output.get() else '副边匝数（决定电压）'))
            for heading in self._inline_output_widgets.get((index, '_rectifier_heading'), []):
                heading.configure(text=f'OUT{index + 1} · '+('整流/续流共用参数 Vf/Qrr，曲线分别绑定' if self._topo_key() == 'ACF-FORWARD' else '独立整流器'))
        if hasattr(self, '_inline_feedback_picker'):
            self._inline_feedback_display.set(self._effective_feedback_mode())
        if hasattr(self, 'feedback_pick'):
            try:
                count = self._read_output_count() if self._inline_multiple_active() else 1
            except ValueError:
                count = max(1, len(self.output_config))
            self.feedback_pick.configure(values=tuple(range(1, count + 1)))
        if hasattr(self, '_isolated_result_book'):
            self._sync_isolated_result_tabs()

    def _transformer_density_label(self, frame, winding):
        from engineering_ui import Tooltip
        variable = self._transformer_density_vars.get(winding)
        if variable is None:
            variable = self._transformer_density_vars[winding] = tk.StringVar(value='J 待计算')
        label = ttk.Label(frame, textvariable=variable, style='Muted.TLabel', justify='left')
        Tooltip(label, '实际 RMS 电流密度：J = Irms / (并绕股数 × 单股铜截面积)。\n不使用平均电流；绝缘层不计入导电铜面积。参数改变后等待当前工况重新计算。')
        return label

    def _build_transformer_dcr_row(self, frame, row, index, predicate):
        from engineering_ui import Tooltip
        name = 'P' if index == 0 else f'OUT{index}'
        variable = self._coupling_dcr_vars[index]
        self._transformer_dcr_vars[name] = variable
        caption = ttk.Label(frame, text=f'{name} · DCR（自动）', style='Param.TLabel', wraplength=170)
        caption.grid(row=row, column=0, sticky='w', padx=(2, 6), pady=3)
        self.param_labels.append(caption)
        value = ttk.Label(frame, textvariable=variable, style='Muted.TLabel')
        value.grid(row=row, column=1, sticky='w', padx=2, pady=3)
        unit = ttk.Label(frame, text='mΩ', style='Muted.TLabel')
        unit.grid(row=row, column=2, sticky='w', padx=4)
        widgets = [caption, value, unit]
        Tooltip(value, '自动直流铜阻：Rdc = ρ × MLT × 匝数 / (并绕股数 × πd²/4)。\nMLT、线径为自动时使用当前磁芯/绕组预设计值；不再读取旧版手工 DCR。')
        self._coupling_widgets['dcr', index] = widgets
        self._inline_extra(frame, widgets, f'{name} 绕组 自动 电阻 DCR MLT 线径 并绕', predicate)
        return row + 1

    def _mark_transformer_readouts_stale(self):
        """Never present previous-design current density as a live result."""
        for variable in getattr(self, '_transformer_density_vars', {}).values():
            variable.set('J 待更新')
        for variable in getattr(self, '_transformer_dcr_vars', {}).values():
            variable.set('待更新')

    def _update_transformer_electrical_readouts(self, p, res):
        """Render actual RMS J and geometry DCR without mutating user inputs."""
        transformer = (res.get('mag') or {}).get('transformer') or {}
        self._mark_transformer_readouts_stale()
        if p.get('topology') not in ISOLATED or not transformer.get('ok'):
            for variable in self._transformer_density_vars.values():
                variable.set('J 不适用' if p.get('topology') not in ISOLATED else 'J 未计算')
            for variable in self._transformer_dcr_vars.values():
                variable.set('—')
            return

        def present(name, density, resistance):
            variable = self._transformer_density_vars.get(name)
            if variable is not None and isinstance(density, (int, float)) and math.isfinite(density):
                variable.set(f'J {density / 1e6:.3g} A/mm²')
            variable = self._transformer_dcr_vars.get(name)
            if variable is not None and isinstance(resistance, (int, float)) and math.isfinite(resistance):
                variable.set(f'{resistance * 1e3:.4g}')

        present('P', transformer.get('J_actual_p'), transformer.get('R_dc_p'))
        if transformer.get('windings'):
            for i, winding in enumerate(transformer['windings'], 1):
                present(f"OUT{winding.get('id', i)}", winding.get('J_actual'), winding.get('R_dc'))
        else:
            present('OUT1', transformer.get('J_actual_s'), transformer.get('R_dc_s'))
        if not self._inline_multiple_active():
            return
        # These are nominal turns estimates, deliberately not the physical
        # coupled solver's cross-regulated actual output voltages.
        rails = (res.get('op') or {}).get('outputs', [])
        previous = self._inline_binding_busy
        self._inline_binding_busy = True
        try:
            for index, rail in enumerate(rails[:6]):
                if index + 1 != self.feedback_output.get():
                    self._inline_output_vars[index]['V_out'].set(self._inline_number(rail['V_out']))
        finally:
            self._inline_binding_busy = previous

    def _focus_inline_section(self, section):
        frame = self._param_sections[section]
        self.param_search.set('')
        self._folded_sections.discard(frame)
        self._filter_params()
        self.root.update_idletasks()
        total = max(1, self.left_inner.winfo_height())
        self.left_canvas.yview_moveto(max(0, frame._section_container.winfo_y() - 4) / total)
        return frame
