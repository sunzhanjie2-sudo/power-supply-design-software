"""One desktop editor for all active designators, identity and ratings."""
import copy
import tkinter as tk
from tkinter import ttk, messagebox

from component_management import (normalize_management, evaluate_components, CAP_TYPES,
                                  RULES, SOURCE_NOTE, rating_text, check_text)


class ComponentManager(ttk.Frame):
    def __init__(self, parent, context, changed):
        super().__init__(parent, padding=8)
        self.context, self.changed = context, changed
        self.config_data = normalize_management()
        self.current = None
        self.loading = False
        self.draft = {}
        self.pack(fill='both', expand=True)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        top = ttk.Frame(self); top.grid(row=0, column=0, sticky='ew')
        ttk.Label(top, text='关键器件 BOM 与降额初筛', font=('Microsoft YaHei', 12, 'bold')).pack(side='left')
        ttk.Button(top, text='降额规则 / 自定义…', command=self.edit_policy).pack(side='right')
        self.summary = tk.StringVar()
        summary_label=ttk.Label(self, textvariable=self.summary, wraplength=1080)
        summary_label.grid(row=1, column=0, sticky='ew', pady=5)
        box = ttk.Frame(self); box.grid(row=2, column=0, sticky='nsew')
        box.columnconfigure(0, weight=1); box.rowconfigure(0, weight=1)
        cols = ('ref', 'role', 'manufacturer', 'model', 'package', 'rating', 'status')
        self.tree = ttk.Treeview(box, columns=cols, show='headings', height=8)
        for key,label,width in zip(cols, ('位号','器件 / 输出归属','厂家','型号','封装','额定值','初筛状态'), (90,220,130,160,120,250,145)):
            self.tree.heading(key, text=label); self.tree.column(key, width=width, minwidth=75, stretch=True)
        self.tree.grid(row=0, column=0, sticky='nsew')
        sy = ttk.Scrollbar(box, command=self.tree.yview); sy.grid(row=0,column=1,sticky='ns')
        sx = ttk.Scrollbar(box, orient='horizontal', command=self.tree.xview); sx.grid(row=1,column=0,sticky='ew')
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.tag_configure('review', foreground='#b3261e')
        self.tree.tag_configure('undefined', foreground='#996100')
        self.tree.bind('<<TreeviewSelect>>', self.select)
        detail = ttk.LabelFrame(self, text='选中器件资料（额定值按单颗填写，空白表示未知）', padding=7)
        detail.grid(row=3, column=0, sticky='ew', pady=6)
        for c in (1,3,5): detail.columnconfigure(c, weight=1)
        labels = [('manufacturer','厂家'),('model','型号'),('package','封装'),
                  ('voltage_V','耐压 / V'),('ripple_A','纹波能力 / A RMS'),('power_W','额定功耗 / W'),
                  ('conditions','额定条件 / 来源'),('note','备注')]
        self.editors = {}
        self._form_pairs = []
        self.voltage_caption = tk.StringVar(value='耐压 / V')
        for index,(key,label) in enumerate(labels):
            r,c = divmod(index,3); self.draft[key] = tk.StringVar()
            caption = ttk.Label(detail, text=label, textvariable=self.voltage_caption if key=='voltage_V' else '')
            caption.grid(row=r,column=2*c,sticky='w',padx=(0,5),pady=3)
            entry = ttk.Entry(detail, textvariable=self.draft[key], width=18)
            entry.grid(row=r,column=2*c+1,sticky='ew',padx=(0,12),pady=3)
            self.editors[key] = entry
            self._form_pairs.append((caption,entry))
        self.cap_type = tk.StringVar(value=CAP_TYPES['unknown'])
        cap_caption=ttk.Label(detail, text='电容类型'); cap_caption.grid(row=2,column=4,sticky='w')
        self.cap_select = ttk.Combobox(detail, textvariable=self.cap_type, values=list(CAP_TYPES.values()),state='readonly',width=19)
        self.cap_select.grid(row=2,column=5,sticky='ew',padx=(0,12))
        self._form_pairs.append((cap_caption,self.cap_select))
        self.selected_label = tk.StringVar(value='先在上表选择器件')
        self._form_footer=ttk.Frame(detail)
        ttk.Label(self._form_footer, textvariable=self.selected_label).pack(side='left',fill='x',expand=True)
        ttk.Button(self._form_footer, text='应用当前器件', command=self.apply_item).pack(side='right')
        self._form_columns=None
        def reflow(event):
            columns=3 if event.width>=850 else 2
            if columns==self._form_columns:return
            self._form_columns=columns
            for c in range(6):detail.columnconfigure(c,weight=1 if c<columns*2 and c%2 else 0)
            for i,(label,entry) in enumerate(self._form_pairs):
                r,c=divmod(i,columns)
                label.grid_configure(row=r,column=2*c)
                entry.grid_configure(row=r,column=2*c+1)
            self._form_footer.grid(row=math.ceil(len(self._form_pairs)/columns),column=0,columnspan=columns*2,sticky='ew',pady=4)
        import math
        detail.bind('<Configure>',reflow)
        text_host=ttk.Frame(self);text_host.grid(row=4,column=0,sticky='ew')
        self.detail = tk.Text(text_host, height=6, wrap='word', font=('Microsoft YaHei',10), relief='flat')
        self.detail.pack(side='left',fill='both',expand=True)
        sy=ttk.Scrollbar(text_host,command=self.detail.yview);sy.pack(side='right',fill='y')
        self.detail.configure(yscrollcommand=sy.set)
        footnote=ttk.Label(self, text='资料随设计 JSON 保存。耐压/额定功率不改变原损耗模型；更换型号后仍须核对电气参数与曲线。', wraplength=1080)
        footnote.grid(row=5,column=0,sticky='ew',pady=4)
        def wrap(event):
            width=max(250,event.width-20)
            summary_label.configure(wraplength=width);footnote.configure(wraplength=width)
        self.bind('<Configure>',wrap)
        self.rows = {}

    def refresh(self, preserve=False):
        p,res = self.context()
        candidate = normalize_management(p.get('component_management'))
        if candidate == self.config_data and self.current and hasattr(self,'loaded_item'):
            try: preserve = preserve or self._candidate_item()!=self.loaded_item
            except ValueError: preserve = True
        self.config_data = candidate
        data = evaluate_components(p,res)
        current = self.current
        self.loading = True
        self.tree.delete(*self.tree.get_children())
        self.rows = {r['ref']:r for r in data['rows']}
        for row in data['rows']:
            self.tree.insert('', 'end', iid=row['ref'], values=(row['ref'],row['role'],row.get('manufacturer') or '待填',
                row.get('model') or '待填',row.get('package') or '待填',rating_text(row),row['status']),tags=(row['state'],))
        self.summary.set(f"{data['zone']} 区 · {len(data['rows'])} 个器件/参考项 · 超限 {data['counts']['review']} 项 · 待补充/复核 {data['counts']['undefined']} 项。仅当前显示电压/负载，报告覆盖两输入端点。")
        self.loading = False
        if current in self.rows:
            self.tree.selection_set(current)
            self._show(current, reload=not preserve)
        elif self.rows:
            self.current = None
            ref = next(iter(self.rows)); self.tree.selection_set(ref); self._show(ref)

    def mark_stale(self):
        """Invalidate displayed verdicts immediately without discarding drafts."""
        for ref in self.tree.get_children():
            self.tree.set(ref,'status','待重新计算')
        self.summary.set('电气参数已更改，旧初筛已失效；等待重新计算。尚未应用的器件资料仍保留在编辑框内。')
        if self.current in self.rows:
            self.selected_label.set(self.current+' · '+self.rows[self.current]['role']+' · 待重新计算')
        self.detail.configure(state='normal');self.detail.delete('1.0','end')
        self.detail.insert('1.0','当前参数尚无有效应力结果；不能使用上次计算的通过结论。')
        self.detail.configure(state='disabled')

    def _candidate_item(self):
        item = {key:var.get().strip() for key,var in self.draft.items()}
        for key in ('voltage_V','ripple_A','power_W'):
            text = item[key]
            try: item[key] = float(text) if text else None
            except ValueError: raise ValueError('额定值请输入数字，支持 1e-3；未知请留空') from None
        item['capacitor_type'] = next(k for k,v in CAP_TYPES.items() if v==self.cap_type.get())
        return item

    def apply_item(self):
        if not self.current: return False
        try:
            candidate = copy.deepcopy(self.config_data)
            candidate['items'][self.current] = self._candidate_item()
            candidate = normalize_management(candidate)
            self.changed(candidate)
            self.refresh()
            return True
        except (ValueError,TypeError) as exc:
            messagebox.showerror('请核对器件资料',str(exc),parent=self)
            return False

    def select(self, _event=None):
        if self.loading or not self.tree.selection(): return
        ref = self.tree.selection()[0]
        if ref == self.current: return
        if self.current:
            try: dirty = self._candidate_item() != self.loaded_item
            except ValueError: dirty = True
            if dirty:
                choice = messagebox.askyesnocancel('未应用的器件资料', '是否先应用当前器件的修改？',parent=self)
                if choice is None or (choice and not self.apply_item()):
                    self.loading=True; self.tree.selection_set(self.current); self.loading=False
                    return
        self._show(ref)

    def _show(self, ref, reload=True):
        self.current = ref
        row = self.rows[ref]
        self.voltage_caption.set('MOS Vds / V' if row['kind']=='mos' else '二极管 Vrrm / V' if row['kind']=='diode' else '电容耐压 / V')
        if reload:
            for key,var in self.draft.items():
                val = row.get(key)
                var.set('' if val is None else f'{val:g}' if isinstance(val,(int,float)) else val)
            self.cap_type.set(CAP_TYPES.get(row.get('capacitor_type'), CAP_TYPES['unknown']))
            self.loaded_item = self._candidate_item()
        for key in ('voltage_V','ripple_A','power_W'):
            enabled = key == 'voltage_V' and row['kind'] in ('mos','diode','capacitor') or key=='ripple_A' and row['kind']=='capacitor' or key=='power_W' and row['kind']=='resistor'
            self.editors[key].configure(state='normal' if enabled else 'disabled')
        self.cap_select.configure(state='readonly' if row['kind']=='capacitor' else 'disabled')
        self.selected_label.set(ref+' · '+row['role']+' · '+row['status'])
        lines = [check_text(c)+'\n'+c['source']+'；'+c['note'] for c in row['checks']]
        if row['identity_missing']: lines.insert(0, '待补充：'+'、'.join(row['identity_missing']))
        if not row['checks']: lines.append('仅记录器件资料，本版未建立此器件的额定应力检查。')
        self.detail.configure(state='normal'); self.detail.delete('1.0','end')
        self.detail.insert('1.0','\n\n'.join(lines)); self.detail.configure(state='disabled')

    def edit_policy(self):
        win = tk.Toplevel(self); win.title('降额规则与依据'); win.transient(self.winfo_toplevel())
        win.geometry('900x710'); win.minsize(760,650)
        body = ttk.Frame(win,padding=12); body.pack(fill='both',expand=True)
        body.columnconfigure(1,weight=1)
        ttk.Label(body,text=SOURCE_NOTE,wraplength=840).grid(row=0,column=0,columnspan=4,sticky='ew',pady=5)
        zone = tk.StringVar(value=self.config_data['zone'])
        ttk.Label(body,text='规范分区（定义须自行确认）').grid(row=1,column=0,sticky='w')
        ttk.Combobox(body,textvariable=zone,values=('I','II'),state='readonly',width=8).grid(row=1,column=1,sticky='w')
        ttk.Label(body,text='规则').grid(row=2,column=0,sticky='w')
        ttk.Label(body,text='I / II 区允许使用率').grid(row=2,column=1,sticky='w')
        ttk.Label(body,text='自定义 %（空白=规范）').grid(row=2,column=2,sticky='w')
        variables = {}
        for i,(key,rule) in enumerate(RULES.items(),3):
            ttk.Label(body,text=rule[0]).grid(row=i,column=0,sticky='w',pady=3)
            ttk.Label(body,text=' / '.join('未列' if x is None else f'{x:.0%}' for x in rule[1:3])).grid(row=i,column=1,sticky='w')
            variables[key] = tk.StringVar(value='' if key not in self.config_data['overrides'] else f"{100*self.config_data['overrides'][key]:g}")
            ttk.Entry(body,textvariable=variables[key],width=12).grid(row=i,column=2,sticky='w')
        r = 3+len(RULES)
        ttk.Label(body,text='自定义依据 / 原因').grid(row=r,column=0,sticky='w',pady=8)
        reason = tk.StringVar(value=self.config_data['override_reason'])
        ttk.Entry(body,textvariable=reason).grid(row=r,column=1,columnspan=2,sticky='ew')
        ttk.Label(body,text='MOS 窄尖峰放宽仅适用于宽度 < min(1µs, Ts/50)。未满足时按稳态因数；没有宽度/反压模型的项目保留待复核。',wraplength=840).grid(row=r+1,column=0,columnspan=3,sticky='ew',pady=8)
        def apply():
            try:
                candidate = copy.deepcopy(self.config_data)
                candidate.update(zone=zone.get(),override_reason=reason.get(),overrides={k:float(v.get())/100 for k,v in variables.items() if v.get().strip()})
                candidate = normalize_management(candidate)
                self.changed(candidate); self.refresh(preserve=True); win.destroy()
            except (ValueError,TypeError) as exc: messagebox.showerror('规则无效',str(exc),parent=win)
        buttons = ttk.Frame(body); buttons.grid(row=r+2,column=0,columnspan=3,sticky='e',pady=8)
        ttk.Button(buttons,text='取消',command=win.destroy).pack(side='right',padx=6)
        ttk.Button(buttons,text='应用规则',command=apply).pack(side='right')
