"""A scrollable editor for acceptance evidence; callbacks own project saving.

Reading this page only projects supplied snapshots. The refresh button is the
only path that asks the application to prepare a new dual-endpoint calculation.
"""
import copy
from datetime import datetime, timezone
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox

from engineering_acceptance import (CASE_IDS, SOURCES, STATE_LABELS, input_fingerprint,
                                    manual_measurement, normalize, report_snapshot)
from scrollable_results import ScrollableResults

ISSUE_LABELS = {'open': '待整改', 'in_progress': '整改中', 'closed': '已关闭',
                'stale': '关闭证据失效', 'undefined': '缺关闭证据'}


def _fmt(value, suffix=''):
    return '—' if value is None else f'{value:.5g}{suffix}'


class AcceptancePanel(ttk.Frame):
    def __init__(self, parent, *, get_spec, on_apply, on_refresh=None,
                 get_range_result=None, get_joint_record=None, get_spice_evidence=None,
                 on_import_evidence=None):
        super().__init__(parent)
        self.get_spec, self.on_apply, self.on_refresh = get_spec, on_apply, on_refresh
        self.get_range_result = get_range_result or (lambda: None)
        self.get_joint_record = get_joint_record or (lambda: None)
        self.get_spice_evidence = get_spice_evidence or (lambda: None)
        self.on_import_evidence = on_import_evidence
        self.snapshot, self.selected = None, None
        self.summary = tk.StringVar(value='等待已完成计算快照；本页不会自动求解。')
        self.message = tk.StringVar(value='修改后点击对应应用按钮，再保存设计/系统工程。')
        self.scroll = ScrollableResults(self)
        self.scroll.pack(fill='both', expand=True)
        host = self.scroll.content
        self.heading = ttk.Label(host, text='工程验证与验收', font=('Microsoft YaHei', 16, 'bold'), padding=(8, 10))
        self.heading.pack(fill='x')
        toolbar = ttk.Frame(host, padding=8)
        self.toolbar = toolbar
        toolbar.pack(fill='x')
        self.refresh_button = ttk.Button(toolbar, text='刷新 Vinmin / Vinmax 计算', command=self.request_refresh)
        self.toolbar_buttons = [self.refresh_button,
            ttk.Button(toolbar, text='更新已完成证据显示', command=self.refresh),
            ttk.Button(toolbar, text='导入仿真证据…', command=self.import_evidence)]
        for column, button in enumerate(self.toolbar_buttons):
            button.grid(row=0, column=column, sticky='w', padx=(0, 8), pady=3)
        ttk.Label(host, textvariable=self.summary, padding=8, wraplength=1050).pack(fill='x')
        ttk.Label(host, text='缺失、旧输入证据和未完成仿真均不算通过；手工实测需注明来源与测试条件。数值按表列单位输入。',
                  padding=8, wraplength=1050).pack(fill='x')
        self.tree = self._tree(host, ('name', 'target', 'Vinmin_values', 'Vinmin_state', 'Vinmax_values', 'Vinmax_state'),
            ('指标 / 单位', '目标', 'Vinmin', '状态', 'Vinmax', '状态'), height=6)
        self._matrix_style = 'Acceptance' + str(id(self)) + '.Treeview'
        self.tree.configure(style=self._matrix_style)
        self.tree.bind('<<TreeviewSelect>>', self._selected)
        self.detail = ttk.LabelFrame(host, text='选中指标 · 目标与证据', padding=10)
        self.detail.pack(fill='x', padx=8, pady=8)
        self.detail_title = tk.StringVar(value='选择上表指标。')
        ttk.Label(self.detail, textvariable=self.detail_title, wraplength=1050).grid(row=0, column=0, columnspan=4, sticky='ew', pady=4)
        self.case_detail = {}
        self._detail_case_labels = []
        detail_compare = ttk.Frame(self.detail)
        detail_compare.grid(row=1, column=0, columnspan=4, sticky='ew', pady=6)
        for index, case_id in enumerate(CASE_IDS):
            variable = tk.StringVar(value=case_id + ' · 等待选择')
            self.case_detail[case_id] = variable
            label = ttk.Label(detail_compare, textvariable=variable, padding=8, wraplength=450, justify='left')
            label.grid(row=0, column=index, sticky='nsew', padx=4)
            self._detail_case_labels.append(label)
            detail_compare.columnconfigure(index, weight=1, uniform='case')
        self.target = {key: tk.StringVar() for key in ('comparison', 'limit', 'lower', 'upper', 'note')}
        self.target['comparison'].set('<=')
        ttk.Label(self.detail, text='目标关系').grid(row=2, column=0, sticky='w')
        ttk.Combobox(self.detail, textvariable=self.target['comparison'], values=('<=', '>=', '<', '>', 'range'), state='readonly', width=10).grid(row=2, column=1, sticky='ew', padx=4)
        ttk.Label(self.detail, text='阈值（range时填上下限）').grid(row=2, column=2, sticky='w')
        ttk.Entry(self.detail, textvariable=self.target['limit'], width=14).grid(row=2, column=3, sticky='ew', padx=4)
        for col, key, title in ((0, 'lower', '允许下限'), (2, 'upper', '允许上限')):
            ttk.Label(self.detail, text=title).grid(row=3, column=col, sticky='w', pady=4)
            ttk.Entry(self.detail, textvariable=self.target[key], width=14).grid(row=3, column=col+1, sticky='ew', padx=4)
        ttk.Label(self.detail, text='依据/说明').grid(row=4, column=0, sticky='w')
        ttk.Entry(self.detail, textvariable=self.target['note']).grid(row=4, column=1, columnspan=3, sticky='ew', padx=4)
        required = ttk.Frame(self.detail)
        required.grid(row=5, column=0, columnspan=4, sticky='ew', pady=6)
        ttk.Label(required, text='判定必需来源：').pack(side='left')
        self.required = {key: tk.BooleanVar(value=True) for key in SOURCES}
        for key, label in zip(SOURCES, ('计算', '仿真', '实测录入')):
            ttk.Checkbutton(required, text=label, variable=self.required[key]).pack(side='left', padx=5)
        self.enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(required, text='启用指标', variable=self.enabled).pack(side='left', padx=12)
        ttk.Button(self.detail, text='应用目标到当前工程', command=self.apply_target).grid(row=6, column=0, columnspan=4, sticky='ew', pady=6)
        self.measurement = {}
        for index, case_id in enumerate(CASE_IDS):
            frame = ttk.LabelFrame(self.detail, text=case_id + ' · 手工实测录入', padding=8)
            frame.grid(row=7+index, column=0, columnspan=4, sticky='ew', pady=5)
            fields = {key: tk.StringVar() for key in ('value', 'source', 'conditions', 'evidence_ref', 'note')}
            self.measurement[case_id] = fields
            for line, (key, title) in enumerate((('value', '实测值'), ('source', '来源/仪器或记录'),
                    ('conditions', '测试条件/接法/温度/带宽'), ('evidence_ref', '证据文件/编号'), ('note', '备注'))):
                ttk.Label(frame, text=title).grid(row=line, column=0, sticky='w', pady=2)
                ttk.Entry(frame, textvariable=fields[key]).grid(row=line, column=1, sticky='ew', padx=6, pady=2)
            frame.columnconfigure(1, weight=1)
        self.confirm_measurement = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.detail, text='确认本次录入', variable=self.confirm_measurement).grid(row=9, column=0, sticky='nw', pady=5)
        self.measurement_confirm_note = ttk.Label(self.detail,
            text='对应当前硬件、Vin工况及上述测试条件。旧证据不会自动重新生效；软件不证明仪器校准。', wraplength=700)
        self.measurement_confirm_note.grid(row=9, column=1, columnspan=3, sticky='ew', padx=4, pady=5)
        ttk.Button(self.detail, text='保存两端实测录入到当前工程', command=self.apply_measurements).grid(row=10, column=0, columnspan=4, sticky='ew', pady=6)
        self.detail.columnconfigure(1, weight=1)
        self.detail.columnconfigure(3, weight=1)
        self.notes = tk.StringVar()
        ttk.Label(host, textvariable=self.notes, padding=8, wraplength=1050).pack(fill='x')
        self.issue_tree = self._tree(host, ('title', 'status', 'owner', 'evidence'), ('问题/整改项', '有效状态', '负责人', '关闭证据'), height=6)
        self._issue_style = 'AcceptanceIssue' + str(id(self)) + '.Treeview'
        self.issue_tree.configure(style=self._issue_style)
        self.issue_tree.bind('<<TreeviewSelect>>', self._issue_selected)
        issue_box = ttk.LabelFrame(host, text='问题整改记录 · 新增或更新', padding=10)
        issue_box.pack(fill='x', padx=8, pady=8)
        self.issue = {key: tk.StringVar() for key in ('id', 'title', 'description', 'action', 'owner', 'status', 'evidence')}
        self.issue['status'].set(ISSUE_LABELS['open'])
        for line, (key, title) in enumerate((('id', '记录编号（空白自动生成）'), ('title', '问题标题'),
                ('description', '现象/原因'), ('action', '整改措施'), ('owner', '负责人'), ('status', '状态'), ('evidence', '验证/关闭证据'))):
            ttk.Label(issue_box, text=title).grid(row=line, column=0, sticky='w', pady=3)
            if key == 'status':
                widget = ttk.Combobox(issue_box, textvariable=self.issue[key], values=tuple(ISSUE_LABELS[k] for k in ('open', 'in_progress', 'closed')), state='readonly')
            else:
                widget = ttk.Entry(issue_box, textvariable=self.issue[key])
            widget.grid(row=line, column=1, sticky='ew', padx=6, pady=3)
        issue_box.columnconfigure(1, weight=1)
        self.confirm_issue = tk.BooleanVar(value=False)
        ttk.Checkbutton(issue_box, text='关闭时确认整改证据对应当前输入', variable=self.confirm_issue).grid(row=7, column=0, columnspan=2, sticky='w', pady=4)
        buttons = ttk.Frame(issue_box)
        buttons.grid(row=8, column=0, columnspan=2, sticky='ew')
        ttk.Button(buttons, text='新增空白整改项', command=self.new_issue).pack(side='left', padx=4, pady=6)
        ttk.Button(buttons, text='应用整改记录到当前工程', command=self.apply_issue).pack(side='left', padx=4, pady=6)
        ttk.Label(host, textvariable=self.message, padding=10, wraplength=1050).pack(fill='x')
        self.bind('<Configure>', self._reflow, add='+')
        self._last_matrix_layout = None

    @staticmethod
    def _tree(parent, columns, headings, height):
        frame = ttk.Frame(parent)
        frame.pack(fill='x', padx=8, pady=4)
        tree = ttk.Treeview(frame, columns=columns, show='headings', height=height)
        for key, title in zip(columns, headings):
            tree.heading(key, text=title)
            tree.column(key, width=220 if key in ('name', 'title', 'evidence') else 155 if key.endswith('delta') or key.endswith('state') else 110,
                        minwidth=80, anchor='w', stretch=False)
        sy = ttk.Scrollbar(frame, command=tree.yview)
        sx = ttk.Scrollbar(frame, command=tree.xview, orient='horizontal')
        sy.pack(side='right', fill='y')
        sx.pack(side='bottom', fill='x')
        tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        tree.pack(fill='x')
        for tag, color in (('pass', '#167144'), ('review', '#b42318'), ('undefined', '#966214'), ('stale', '#b54708'), ('na', '#64748b')):
            tree.tag_configure(tag, foreground=color)
        return tree

    def _reflow(self, _event=None):
        width = max(300, self.winfo_width()-50)
        font = tkfont.nametofont('TkDefaultFont')
        marker = (width, font.actual('size'), font.metrics('linespace'))
        row, column, occupied = 0, 0, 0
        for button in self.toolbar_buttons:
            requested = font.measure(button.cget('text'))+34
            if occupied and occupied+requested > width:
                row, column, occupied = row+1, 0, 0
            button.grid_configure(row=row, column=column)
            column, occupied = column+1, occupied+requested
        if getattr(self, '_last_matrix_layout', None) != marker:
            self._last_matrix_layout = marker
            style = ttk.Style(self)
            self.heading.configure(font=(font.actual('family'), max(16, abs(font.actual('size'))+2), 'bold'))
            row_height = font.metrics('linespace')*3+12
            style.configure(self._matrix_style, rowheight=row_height, font='TkDefaultFont')
            self.tree.configure(height=max(3, min(6, 430//row_height)))
            style.configure(self._matrix_style + '.Heading', font=(font.actual('family'), max(10, round(abs(font.actual('size'))*.85)), 'bold'))
            style.configure(self._issue_style, rowheight=font.metrics('linespace')+12, font='TkDefaultFont')
            style.configure(self._issue_style + '.Heading', font=(font.actual('family'), max(10, round(abs(font.actual('size'))*.85)), 'bold'))
            for column, sample in (('title', '整改问题标题'), ('status', 'in_progress'), ('owner', '负责人'), ('evidence', '验证证据编号/文件')):
                minimum = font.measure(sample)+22
                self.issue_tree.column(column, width=max(120, minimum), minwidth=minimum, stretch=True)
            proportions = (.22, .14, .20, .12, .20, .12)
            samples = ('电感/原边电流', '>= 0.999', '仿 -1234.5', '待补证据', '仿 -1234.5', '待补证据')
            for column, fraction, sample in zip(self.tree['columns'], proportions, samples):
                minimum = font.measure(sample) + 22
                self.tree.column(column, width=max(minimum, int(width*fraction)), minwidth=minimum, stretch=False)
            if self.snapshot:
                for row in self.snapshot['rows']:
                    if self.tree.exists(row['id']):
                        self.tree.set(row['id'], 'name', self._wrap_cell((row['name'] or row['id']) + (' / ' + row['unit'] if row['unit'] else ''), 'name'))
                        target = (f"{_fmt(row['lower'])} … {_fmt(row['upper'])}" if row['comparison'] == 'range' else row['comparison'] + ' ' + _fmt(row['limit']))
                        self.tree.set(row['id'], 'target', self._wrap_cell(target, 'target'))
                        for case_id in CASE_IDS:
                            title = {'pass': '满足*', 'review': '需整改', 'undefined': '待补证据', 'stale': '已失效', 'na': '不适用'}[row['cases'][case_id]['status']]
                            self.tree.set(row['id'], case_id+'_state', self._wrap_cell(title, case_id+'_state'))
        for widget in self.scroll.content.winfo_children():
            if isinstance(widget, ttk.Label):
                widget.configure(wraplength=width)
        if hasattr(self, 'detail'):
            for widget in self.detail.winfo_children():
                if isinstance(widget, ttk.Label):
                    widget.configure(wraplength=max(150, width//2))
        for label in self._detail_case_labels:
            label.configure(wraplength=max(130, width//2-50))
        self.measurement_confirm_note.configure(wraplength=max(180, width-font.measure('确认本次录入')-70))

    def _wrap_cell(self, text, column):
        font = tkfont.nametofont('TkDefaultFont')
        width = max(30, self.tree.column(column, 'width') - 12)
        lines, current = [], ''
        for char in text:
            if current and font.measure(current+char) > width:
                lines.append(current)
                current = ''
                if len(lines) == 3:
                    lines[-1] = lines[-1][:-1] + '…'
                    return '\n'.join(lines)
            current += char
        return '\n'.join(lines+[current])

    def request_refresh(self):
        if self.on_refresh is None:
            self.message.set('当前宿主没有接入后台刷新；请先完成双端计算。')
            return
        self.message.set('已请求显式后台刷新；运行与取消由主程序管理。')
        self.on_refresh()

    def import_evidence(self):
        if self.on_import_evidence is None:
            self.message.set('当前宿主没有接入证据导入；可从联合任务取得匹配配置的仿真记录。')
            return
        self.on_import_evidence()
        self.refresh()

    def refresh(self):
        previous = self.snapshot
        try:
            self.snapshot = report_snapshot(self.get_spec(), self.get_range_result(), self.get_joint_record(), self.get_spice_evidence())
        except Exception as exc:
            self.summary.set('当前验收输入未就绪：' + str(exc))
            self.snapshot, self.selected = None, None
            self.tree.delete(*self.tree.get_children())
            for case_id, variable in self.case_detail.items():
                variable.set(case_id + ' · 当前输入无有效匹配；不沿用上次通过结论。')
            return
        current = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for row in self.snapshot['rows']:
            target = (f"{_fmt(row['lower'])} … {_fmt(row['upper'])}" if row['comparison'] == 'range'
                      else row['comparison'] + ' ' + _fmt(row['limit']))
            values = [self._wrap_cell((row['name'] or row['id']) + (' / ' + row['unit'] if row['unit'] else ''), 'name'), self._wrap_cell(target, 'target')]
            states = []
            for case_id in CASE_IDS:
                case = row['cases'][case_id]
                short_state = {'pass': '满足*', 'review': '需整改', 'undefined': '待补证据', 'stale': '已失效', 'na': '不适用'}[case['status']]
                values.extend(('计 ' + _fmt(case['calculation']) + '\n仿 ' + _fmt(case['simulation']) + '\n录 ' + _fmt(case['measurement']), self._wrap_cell(short_state, case_id+'_state')))
                states.append(case['status'])
            tag = next((state for state in ('review', 'stale', 'undefined', 'pass', 'na') if state in states), 'undefined')
            self.tree.insert('', 'end', iid=row['id'], values=values, tags=(tag,))
        counts = self.snapshot['summary']['counts']
        self.summary.set('结论：' + self.snapshot['summary']['label'] + '。 ' +
            ' / '.join(label + str(counts[s]) for s, label in (('pass', '满足'), ('review', '需整改'), ('undefined', '待补'), ('stale', '失效'))) +
            f"；未闭环整改 {self.snapshot['summary']['unresolved_issues']} 项。")
        self.notes.set('\n'.join(self.snapshot['evidence_notes']))
        self.issue_tree.delete(*self.issue_tree.get_children())
        for issue in self.snapshot['issues']:
            self.issue_tree.insert('', 'end', iid=issue['id'], values=(issue['title'], ISSUE_LABELS.get(issue['effective_status'], issue['effective_status']), issue['owner'], issue['evidence']),
                tags=('pass' if issue['effective_status'] == 'closed' else 'stale' if issue['effective_status'] == 'stale' else 'review',))
        if current and self.tree.exists(current[0]):
            self.tree.selection_set(current)
            if (not previous or previous['config'] != self.snapshot['config'] or
                    previous['input_fingerprint'] != self.snapshot['input_fingerprint']):
                self._selected(force=True)
            else:
                self._update_case_details(next(r for r in self.snapshot['rows'] if r['id'] == current[0]))
        elif self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])
            self._selected()
        self.scroll._schedule_sync()
        self._reflow()

    def _selected(self, _event=None, force=False):
        ids = self.tree.selection()
        if not ids or not self.snapshot:
            return
        if ids[0] == self.selected and not force:
            return  # preserve an unapplied editor draft during a data refresh
        self.selected = ids[0]
        row = next(r for r in self.snapshot['rows'] if r['id'] == self.selected)
        self.detail_title.set((row['name'] or row['id']) + ' · 单位 ' + (row['unit'] or '比例/无量纲') +
            ' · 仅选计算作为必需来源时，不能宣称已完成仿真或实测。')
        for key, variable in self.target.items():
            value = row.get(key)
            variable.set('' if value is None else str(value))
        self.enabled.set(row['enabled'])
        for key, variable in self.required.items():
            variable.set(key in row['required_sources'])
        for case_id, fields in self.measurement.items():
            record = row['cases'][case_id].get('measurement_record') or {}
            for key, variable in fields.items():
                value = record.get(key, '')
                variable.set('' if value is None else str(value))
        self.confirm_measurement.set(False)
        self._update_case_details(row)

    def _update_case_details(self, row):
        for case_id in CASE_IDS:
            case = row['cases'][case_id]
            lines = [case_id + ' · Vin ' + _fmt(case['V_in']) + ' V',
                '仿真/计算偏差 ' + _fmt(case['delta_simulation'], '%') + '；录入/计算偏差 ' + _fmt(case['delta_measurement'], '%')]
            for source, label in zip(SOURCES, ('计算', '仿真', '录入')):
                lines.append(label + '：' + STATE_LABELS[case['states'][source]] + '；余量 ' + _fmt(case['margins'][source]))
                lines.append('来源：' + (case['sources'][source] or '未提供'))
            if case['reason'] or case['calculation_error']:
                lines.append(case['reason'] or case['calculation_error'])
            self.case_detail[case_id].set('\n'.join(lines))

    def apply_config(self, config):
        config = normalize(config)
        result = self.on_apply(copy.deepcopy(config))
        if result is False:
            return False
        self.message.set('已应用到当前工程；请使用“保存设计/保存系统工程”写入文件。未启动电气重算。')
        self.refresh()
        return True

    @staticmethod
    def _entry_number(text):
        return None if not text.strip() else float(text)

    def apply_target(self):
        if not self.selected or not self.snapshot:
            return False
        try:
            row = next(r for r in self.snapshot['criteria'] if r['id'] == self.selected)
            target = copy.deepcopy(row)
            target.update({key: variable.get() for key, variable in self.target.items()})
            for key in ('limit', 'lower', 'upper'):
                target[key] = self._entry_number(target[key])
            target.update(enabled=self.enabled.get(), required_sources=[key for key, var in self.required.items() if var.get()])
            config = normalize(self.get_spec().get('engineering_acceptance'))
            config['criteria'] = [c for c in config['criteria'] if c['id'] != self.selected] + [target]
            return self.apply_config(config)
        except (ValueError, TypeError) as exc:
            messagebox.showerror('请检查验收目标', str(exc), parent=self.winfo_toplevel())
            return False

    def apply_measurements(self):
        if not self.selected or not self.snapshot:
            return False
        try:
            if not self.confirm_measurement.get():
                raise ValueError('请先确认录入对应当前硬件与测试条件；旧证据不会自动重新绑定。')
            p = self.get_spec()
            config = normalize(p.get('engineering_acceptance'))
            added = []
            for case_id, fields in self.measurement.items():
                values = {key: variable.get().strip() for key, variable in fields.items()}
                if not values['value']:
                    continue  # an empty other endpoint does not delete its history
                if not values['source'] or not values['conditions']:
                    raise ValueError(case_id + ' 的实测必须填写来源及测试条件')
                added.append(manual_measurement(p, self.selected, case_id, self._entry_number(values.pop('value')), **values))
            if not added:
                raise ValueError('至少填写一个输入端点的实测值')
            ids = {m['id'] for m in added}
            config['measurements'] = [m for m in config['measurements'] if m['id'] not in ids] + added
            result = self.apply_config(config)
            self.confirm_measurement.set(False)
            return result
        except (ValueError, TypeError) as exc:
            messagebox.showerror('请检查实测录入', str(exc), parent=self.winfo_toplevel())
            return False

    def new_issue(self):
        for key, variable in self.issue.items():
            variable.set(ISSUE_LABELS['open'] if key == 'status' else '')
        self.confirm_issue.set(False)

    def _issue_selected(self, _event=None):
        ids = self.issue_tree.selection()
        if not ids or not self.snapshot:
            return
        row = next(i for i in self.snapshot['issues'] if i['id'] == ids[0])
        for key, variable in self.issue.items():
            variable.set(ISSUE_LABELS[row['status']] if key == 'status' else row.get(key) or '')
        self.confirm_issue.set(False)

    def apply_issue(self):
        try:
            p = self.get_spec()
            config = normalize(p.get('engineering_acceptance'))
            row = {key: variable.get().strip() for key, variable in self.issue.items()}
            row['status'] = {label: key for key, label in ISSUE_LABELS.items()}.get(row['status'], row['status'])
            if not row['title']:
                raise ValueError('请填写问题标题')
            if row['status'] == 'closed' and (not self.confirm_issue.get() or not row['evidence']):
                raise ValueError('关闭整改项需要验证证据并确认它对应当前输入')
            row.update(id=row['id'] or 'ISSUE-' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f'),
                input_fingerprint=input_fingerprint(p), updated_at=datetime.now(timezone.utc).isoformat())
            config['issues'] = [i for i in config['issues'] if i['id'] != row['id']] + [row]
            result = self.apply_config(config)
            self.issue['id'].set(row['id'])
            self.confirm_issue.set(False)
            return result
        except (ValueError, TypeError) as exc:
            messagebox.showerror('请检查整改记录', str(exc), parent=self.winfo_toplevel())
            return False
