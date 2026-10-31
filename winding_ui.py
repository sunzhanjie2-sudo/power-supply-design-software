"""Local, inexpensive transformer-window geometry editor on the magnetics page."""
import math
import tkinter as tk
from tkinter import ttk

from winding_layout import (DEFAULT_WINDING_CONFIG,DEFAULT_WIRE_OVERRIDE,validate_winding_config,
    transformer_windings,assess_winding_window,draw_winding_cross_section,build_automatic_layer_plan)


GEOMETRY_FIELDS=(('window_width','窗口净宽',1e3),('window_height','窗口净高',1e3),
    ('margin_x','左右留边（每侧）',1e3),('margin_y','上下留边（每侧）',1e3),
    ('diameter_allowance','含漆外径增量 Δd',1e3),('layer_insulation','层间绝缘厚度',1e3),
    ('interwinding_insulation','绕组间绝缘厚度',1e3),('wire_gap','线束与匝间净隙',1e3))

WIRE_CHOICES={'wire_type':{'自动：多股利兹 / 单股铜线':'auto','普通铜线（不压扁）':'solid','利兹线（等效压扁）':'litz'},
    'winding_style':{'疏绕：沿窗口均匀分布':'sparse','密绕：靠左':'dense_left','密绕：靠右':'dense_right'}}
WIRE_FIELDS=(('wire_type','线材类型'),('winding_style','绕制方式'),
    ('parallel_bundles','每匝并绕束数'),('turns_per_layer','每层匝数（0=自动）'),
    ('outer_diameter','单股含漆外径\nmm，0=自动'),('bundle_diameter','整束未压扁外径\nmm，0=估算'),
    ('packing_factor','束内填充系数\n0 < 系数 ≤ 1'),('flatten_ratio','利兹线压扁宽度倍数\n≥ 1'))
LAYER_STYLE_CHOICES={'跟随该绕组':None,**WIRE_CHOICES['winding_style']}


class WindingUI:
    def _init_winding_state(self):
        self._winding_loading=True
        self._winding_vars={}
        self._winding_overrides={}
        self._winding_order=[]
        self._winding_source=None
        self._winding_job=None
        self._winding_row_signature=None
        self._winding_assessment=None
        self._winding_selected=tk.StringVar(value='P')
        self._winding_selected.trace_add('write',self._select_winding_details)
        self._winding_binding_details=False
        self._winding_layer_plan=[]
        self._winding_plan_enabled=tk.BooleanVar(value=False)
        self._winding_plan_enabled.trace_add('write',self._toggle_winding_plan)
        self._winding_binding_plan=False
        for key,_caption,scale in GEOMETRY_FIELDS:
            value=DEFAULT_WINDING_CONFIG[key]*scale
            var=tk.StringVar(value='' if key in ('window_width','window_height') and not value else f'{value:.10g}')
            var.trace_add('write',self._schedule_winding_redraw)
            self._winding_vars[key]=var
        self._winding_loading=False

    def _winding_config(self,*,include_layer_plan=True):
        values={}
        for key,caption,scale in GEOMETRY_FIELDS:
            try:
                text=self._winding_vars[key].get().strip()
                values[key]=float(text or '0')/scale
            except (ValueError,tk.TclError):
                raise ValueError(caption+' 请填写有限非负数值（mm）') from None
        values.update(order=list(self._winding_order),overrides={},layer_plan=[])
        for key,variables in self._winding_overrides.items():
            try:
                entry={name:(variable.get() if name in WIRE_CHOICES else float(variable.get() or 0))
                    for name,variable in variables.items()}
                entry['outer_diameter']/=1e3
                entry['bundle_diameter']/=1e3
            except (ValueError,tk.TclError):
                raise ValueError(key+' 线束设置不是有效数字') from None
            # Old hand-configured rectangular bundles retain exactly their old
            # construction until the user explicitly chooses conversion.
            if entry['strand_columns']:
                entry={name:entry[name] for name in ('outer_diameter','strand_columns')}
            values['overrides'][key]=entry
        if include_layer_plan and self._winding_plan_enabled.get():
            if not self._winding_layer_plan:
                raise ValueError('已启用手动逐层排布，但尚无层；请先从自动排层生成，或添加所有绕组的层')
            for index,entry in enumerate(self._winding_layer_plan,1):
                try:
                    row=dict(winding_id=entry['winding_id'],turns=float(entry['turns']))
                except (TypeError,ValueError):
                    raise ValueError(f'第 {index} 层匝数不是有效数字') from None
                if entry.get('winding_style'):
                    row['winding_style']=entry['winding_style']
                values['layer_plan'].append(row)
        return dict(winding_config=validate_winding_config(values))

    def _load_winding_config(self,cfg):
        candidate=validate_winding_config(cfg.get('winding_config'))
        self._winding_loading=True
        try:
            for key,_caption,scale in GEOMETRY_FIELDS:
                value=candidate[key]*scale
                self._winding_vars[key].set('' if key in ('window_width','window_height') and not value else f'{value:.10g}')
            self._winding_order=list(candidate['order'])
            self._winding_layer_plan=[dict(entry,turns=str(entry['turns'])) for entry in candidate.get('layer_plan',[])]
            self._winding_plan_enabled.set(bool(self._winding_layer_plan))
            for variables in self._winding_overrides.values():
                for name,variable in variables.items():
                    variable.set(str(DEFAULT_WIRE_OVERRIDE[name]))
            for key,entry in candidate['overrides'].items():
                variables=self._winding_override_vars(key)
                for name,value in entry.items():
                    variables[name].set(f'{value*1e3:.10g}' if name in ('outer_diameter','bundle_diameter') else str(value))
            self._winding_row_signature=None
        finally:
            self._winding_loading=False
        self._select_winding_details()
        self._render_winding_plan()
        self._toggle_winding_plan()
        self._schedule_winding_redraw()

    def _winding_override_vars(self,key):
        if key not in self._winding_overrides:
            variables={name:tk.StringVar(value=str(value)) for name,value in DEFAULT_WIRE_OVERRIDE.items()}
            for variable in variables.values():
                variable.trace_add('write',self._schedule_winding_redraw)
            self._winding_overrides[key]=variables
        return self._winding_overrides[key]

    def _build_winding_tab(self,parent):
        from matplotlib.figure import Figure
        from resource_canvas import EfficientFigureCanvasTkAgg as FigureCanvasTkAgg
        from scrollable_results import ScrollableResults
        self._winding_view=ScrollableResults(parent)
        self._winding_view.pack(fill='both',expand=True)
        body=self._winding_view.content
        self._winding_labels=[]
        self._winding_wrap_width=0
        def label(**options):
            widget=ttk.Label(body,wraplength=850,justify='left',**options)
            self._winding_labels.append(widget)
            return widget
        label(text='骨架净窗口的单侧轴向 × 径向截面；每束多股线画一个等效截面，所有尺寸按同一比例绘制。不能用磁芯 Wa 直接代替窗口宽高。',
                  style='Muted.TLabel').pack(fill='x',padx=10,pady=(9,5))
        inputs=ttk.LabelFrame(body,text='窗口与绝缘设置（长度均为 mm）',padding=7)
        inputs.pack(fill='x',padx=8,pady=4)
        self._winding_geometry_frame=inputs
        self._winding_geometry_widgets=[]
        self._winding_input_columns=None
        for index,(key,caption,_scale) in enumerate(GEOMETRY_FIELDS):
            row,column=divmod(index,2)
            caption_widget=ttk.Label(inputs,text=caption,wraplength=170)
            caption_widget.grid(row=row,column=column*2,sticky='w',padx=(2,7),pady=3)
            entry=ttk.Entry(inputs,textvariable=self._winding_vars[key],width=9)
            entry.grid(row=row,column=column*2+1,sticky='ew',padx=(0,12),pady=3)
            self._winding_geometry_widgets.append((caption_widget,entry))
        for column in (1,3):
            inputs.columnconfigure(column,weight=1)
        label(text='电气参数中的股数是每匝总股数，不会因并绕束数重复增加。例：60 股分成 3 束，每束 20 股。自动模式将多股视为利兹线，单股铜线不压扁；非利兹多股线请选择普通铜线。',
                  style='Muted.TLabel').pack(fill='x',padx=10,pady=5)
        self._winding_rows_frame=ttk.LabelFrame(body,text='绕组顺序（由骨架向外）· 点选绕组后编辑下方设置',padding=5)
        self._winding_rows_frame.pack(fill='x',padx=8,pady=4)
        controls=ttk.Frame(body,padding=(8,3))
        controls.pack(fill='x')
        ttk.Button(controls,text='所选绕组上移',command=lambda:self._move_winding(-1)).pack(side='left',padx=3)
        ttk.Button(controls,text='下移',command=lambda:self._move_winding(1)).pack(side='left',padx=3)
        ttk.Button(controls,text='重新评估 / 重画',command=self._refresh_winding).pack(side='right',padx=3)
        self._build_winding_details(body,label)
        self._build_winding_plan(body,label)
        self.winding_summary=tk.StringVar(value='请先填写骨架窗口净宽与净高。')
        label(textvariable=self.winding_summary,style='Result.TLabel').pack(fill='x',padx=10,pady=6)
        plot=ttk.Frame(body,height=470)
        plot.pack(fill='x',padx=7,pady=4)
        plot.pack_propagate(False)
        self.fig_winding=Figure(figsize=(8.8,4.7),dpi=100,layout='constrained')
        self.ax_winding=self.fig_winding.subplots()
        self.canvas_winding=FigureCanvasTkAgg(self.fig_winding,master=plot)
        self.canvas_winding.get_tk_widget().pack(fill='both',expand=True)
        label(text='几何预评估，不是可量产工艺或安规判定。图中骨架挡墙仅作示意，不占用用户输入的净窗口。利兹线默认宽 ×1.5、高 ÷1.5，为等面积假设，不代表实物必然可压到此尺寸。未包含引线、交叉线、骨架圆角和工艺公差；外径与绝缘必须按实物确认。调整截面不会改变铜损、漏感或 kij。',
                  style='Muted.TLabel').pack(fill='x',padx=10,pady=(6,12))
        body.bind('<Configure>',self._resize_winding_text,add='+')
        parent.bind('<Destroy>',lambda event:self._cancel_winding_redraw() if event.widget is parent else None,add='+')
        self._refresh_winding()

    def _build_winding_details(self,body,label):
        self._winding_details_frame=ttk.LabelFrame(body,text='所选绕组 · 等效线束与层绕设置',padding=7)
        frame=self._winding_details_frame
        frame.pack(fill='x',padx=8,pady=4)
        self._winding_detail_widgets={}
        self._winding_detail_labels={}
        self._winding_detail_choices={}
        for index,(name,caption) in enumerate(WIRE_FIELDS):
            row,column=divmod(index,2)
            caption_widget=ttk.Label(frame,text=caption,wraplength=160)
            caption_widget.grid(row=row,column=column*2,sticky='w',padx=(2,6),pady=4)
            self._winding_detail_labels[name]=caption_widget
            if name in WIRE_CHOICES:
                display=tk.StringVar()
                widget=ttk.Combobox(frame,textvariable=display,values=list(WIRE_CHOICES[name]),state='readonly',width=18)
                display.trace_add('write',lambda *_args,key=name:self._set_winding_choice(key))
                self._winding_detail_choices[name]=display
            else:
                widget=ttk.Entry(frame,width=10)
            widget.grid(row=row,column=column*2+1,sticky='ew',padx=(0,8),pady=4)
            self._winding_detail_widgets[name]=widget
        for column in (1,3):
            frame.columnconfigure(column,weight=1)
        self._winding_detail_note=tk.StringVar()
        label(textvariable=self._winding_detail_note,style='Muted.TLabel').pack(fill='x',padx=10,pady=4)
        self._winding_convert_button=ttk.Button(frame,text='将旧矩形束转换为等效线束',command=self._convert_winding_bundle)
        label(text='估算整束直径 = 单股含漆外径 × √(每束股数 / 填充系数)。默认填充系数 0.75 仅为可修改的估算；已有线材规格时，优先填写整束未压扁外径。疏绕均匀分布，密绕可靠左或靠右；每层匝数可限制层内数量。',
            style='Muted.TLabel').pack(fill='x',padx=10,pady=4)
        self._select_winding_details()

    def _build_winding_plan(self,body,label):
        frame=ttk.LabelFrame(body,text='逐层与交错排布 · 实体层从骨架向外编号',padding=7)
        self._winding_plan_frame=frame
        frame.pack(fill='x',padx=8,pady=4)
        top=ttk.Frame(frame);top.pack(fill='x')
        ttk.Checkbutton(top,text='启用手动逐层排布',variable=self._winding_plan_enabled).pack(side='left')
        ttk.Button(top,text='从自动排层生成',command=self._generate_winding_plan).pack(side='right',padx=3)
        self._winding_plan_body=ttk.Frame(frame)
        self._winding_plan_body.pack(fill='x',pady=(6,0))
        content=self._winding_plan_body
        table=ttk.Frame(content);table.pack(fill='x')
        self._winding_plan_tree=ttk.Treeview(table,columns=('layer','winding','turns','style'),show='headings',height=7,selectmode='browse')
        for name,caption,width in (('layer','实体层',55),('winding','绕组',75),('turns','本层匝数',80),('style','本层绕法',165)):
            self._winding_plan_tree.heading(name,text=caption)
            self._winding_plan_tree.column(name,width=width,minwidth=45,anchor='center',stretch=name=='style')
        self._winding_plan_tree.pack(side='left',fill='both',expand=True)
        scrollbar=ttk.Scrollbar(table,orient='vertical',command=self._winding_plan_tree.yview)
        scrollbar.pack(side='right',fill='y')
        self._winding_plan_tree.configure(yscrollcommand=scrollbar.set)
        self._winding_plan_tree.bind('<<TreeviewSelect>>',self._select_winding_plan_layer)
        editor=ttk.Frame(content);editor.pack(fill='x',pady=(5,0));editor.columnconfigure(1,weight=1)
        self._winding_plan_editor_vars={name:tk.StringVar() for name in ('winding_id','turns','winding_style')}
        self._winding_plan_editor_widgets={}
        for index,(name,caption) in enumerate((('winding_id','所选层绕组'),('turns','所选层匝数'),('winding_style','所选层绕法'))):
            ttk.Label(editor,text=caption).grid(row=index,column=0,sticky='w',padx=(0,8),pady=3)
            variable=self._winding_plan_editor_vars[name]
            if name=='turns':
                widget=ttk.Entry(editor,textvariable=variable,width=12)
            else:
                widget=ttk.Combobox(editor,textvariable=variable,state='readonly',width=18,
                    values=list(LAYER_STYLE_CHOICES) if name=='winding_style' else [])
            widget.grid(row=index,column=1,sticky='ew',pady=3)
            variable.trace_add('write',lambda *_args,key=name:self._edit_winding_plan_layer(key))
            self._winding_plan_editor_widgets[name]=widget
        controls=ttk.Frame(content);controls.pack(fill='x',pady=5)
        for index,(caption,command) in enumerate((('添加层',self._add_winding_plan_layer),('删除所选层',self._delete_winding_plan_layer),
                ('所选层上移',lambda:self._move_winding_plan_layer(-1)),('所选层下移',lambda:self._move_winding_plan_layer(1)),
                ('拆分所选层',self._split_winding_plan_layer))):
            ttk.Button(controls,text=caption,command=command).grid(row=index//3,column=index%3,sticky='ew',padx=2,pady=3)
        for column in range(3):controls.columnconfigure(column,weight=1)
        self._winding_plan_note=tk.StringVar()
        label(textvariable=self._winding_plan_note,style='Muted.TLabel').pack(fill='x',padx=10,pady=4)
        label(text='同一绕组可出现在不连续的实体层。例：P 的 6 匝拆成第 1 层 3 匝与第 3 层 3 匝，中间放副边层。可先生成自动方案，拆分所选层，再上移 / 下移；所有绕组的分层匝数必须严格等于电气总匝数。相邻异绕组用绕组间绝缘，同绕组用层间绝缘。重新生成会替换手动草稿；手动模式下上方绕组顺序仅作用于重新生成自动方案。',
            style='Muted.TLabel').pack(fill='x',padx=10,pady=4)
        self._render_winding_plan()
        self._toggle_winding_plan()

    def _toggle_winding_plan(self,*_):
        if hasattr(self,'_winding_plan_body'):
            if self._winding_plan_enabled.get():
                self._winding_plan_body.pack(fill='x',pady=(6,0))
            else:
                self._winding_plan_body.pack_forget()
            self._update_winding_plan_note()
        self._schedule_winding_redraw()

    def _selected_winding_plan_index(self):
        if not hasattr(self,'_winding_plan_tree'):
            return None
        selected=self._winding_plan_tree.selection()
        if selected and selected[0].isdigit() and int(selected[0])<len(self._winding_layer_plan):
            return int(selected[0])
        return None

    def _render_winding_plan(self,selected=None):
        if not hasattr(self,'_winding_plan_tree'):
            return
        if selected is None:selected=self._selected_winding_plan_index()
        tree=self._winding_plan_tree
        tree.delete(*tree.get_children())
        for index,entry in enumerate(self._winding_layer_plan):
            style=next((label for label,value in LAYER_STYLE_CHOICES.items() if value==entry.get('winding_style')),'跟随该绕组')
            tree.insert('', 'end',iid=str(index),values=(index+1,entry['winding_id'],entry['turns'],style))
        if self._winding_layer_plan:
            selected=min(max(0,selected or 0),len(self._winding_layer_plan)-1)
            tree.selection_set(str(selected));tree.see(str(selected))
        self._select_winding_plan_layer()
        self._update_winding_plan_note()

    def _select_winding_plan_layer(self,*_):
        if not hasattr(self,'_winding_plan_editor_vars'):
            return
        index=self._selected_winding_plan_index()
        self._winding_binding_plan=True
        try:
            entry=self._winding_layer_plan[index] if index is not None else {}
            for name,variable in self._winding_plan_editor_vars.items():
                value=entry.get(name,'')
                if name=='winding_style':
                    value=next((label for label,code in LAYER_STYLE_CHOICES.items() if code==entry.get(name)),'跟随该绕组')
                variable.set(value)
                self._winding_plan_editor_widgets[name].configure(state=('normal' if name=='turns' else 'readonly') if index is not None else 'disabled')
            self._winding_plan_editor_widgets['winding_id'].configure(values=[row['id'] for row in self._ordered_winding_rows()])
        finally:
            self._winding_binding_plan=False

    def _edit_winding_plan_layer(self,name):
        if self._winding_binding_plan:
            return
        index=self._selected_winding_plan_index()
        if index is None:return
        value=self._winding_plan_editor_vars[name].get()
        entry=self._winding_layer_plan[index]
        if name=='winding_style':
            value=LAYER_STYLE_CHOICES.get(value)
            if value is None:entry.pop(name,None)
            else:entry[name]=value
        else:
            entry[name]=value
        style=next((label for label,code in LAYER_STYLE_CHOICES.items() if code==entry.get('winding_style')),'跟随该绕组')
        self._winding_plan_tree.item(str(index),values=(index+1,entry['winding_id'],entry['turns'],style))
        self._update_winding_plan_note()
        self._schedule_winding_redraw()

    def _update_winding_plan_note(self):
        if not hasattr(self,'_winding_plan_note'):
            return
        if not self._winding_plan_enabled.get():
            self._winding_plan_note.set('当前按整绕组自动连续排层；启用手动模式可将同一绕组分配到第 1、3 等不连续层。关闭手动模式会保留本次草稿，但保存时只使用自动方案。')
            return
        totals={row['id']:[0,int(row['turns']),[]] for row in self._ordered_winding_rows()}
        invalid=[]
        for index,entry in enumerate(self._winding_layer_plan,1):
            try:
                value=float(entry['turns'])
                if not math.isfinite(value) or value<=0 or int(value)!=value:raise ValueError()
                if entry['winding_id'] not in totals:raise ValueError()
                totals[entry['winding_id']][0]+=int(value)
                totals[entry['winding_id']][2].append(index)
            except (TypeError,ValueError):
                invalid.append(str(index))
        lines=[f'{key}：已分配 {assigned} / {target} 匝，实体层 '+('、'.join(map(str,layers)) if layers else '未分配')
               for key,(assigned,target,layers) in totals.items()]
        prefix=f'手动方案共 {len(self._winding_layer_plan)} 层。'
        if invalid:prefix+='待修正层：'+ '、'.join(invalid)+'。'
        self._winding_plan_note.set(prefix+'\n'+'；'.join(lines))

    def _generate_winding_plan(self):
        try:
            cfg=self._winding_config(include_layer_plan=False)['winding_config']
            plan=build_automatic_layer_plan(self._ordered_winding_rows(),cfg)
            self._winding_layer_plan=[dict(entry,turns=str(entry['turns'])) for entry in plan]
            self._winding_plan_enabled.set(True)
            self._render_winding_plan(0)
            self._refresh_winding()
        except (ValueError,TypeError) as exc:
            self._winding_plan_note.set('未生成手动方案：'+str(exc))

    def _add_winding_plan_layer(self):
        if len(self._winding_layer_plan)>=1000:
            self._winding_plan_note.set('手动方案最多支持 1000 层。');return
        rows=self._ordered_winding_rows()
        if not rows:
            self._winding_plan_note.set('尚无有效变压器绕组。');return
        index=self._selected_winding_plan_index()
        key=self._winding_layer_plan[index]['winding_id'] if index is not None else self._winding_selected.get()
        if key not in {row['id'] for row in rows}:key=rows[0]['id']
        position=index+1 if index is not None else len(self._winding_layer_plan)
        self._winding_layer_plan.insert(position,dict(winding_id=key,turns='1'))
        self._render_winding_plan(position);self._schedule_winding_redraw()

    def _delete_winding_plan_layer(self):
        index=self._selected_winding_plan_index()
        if index is None:return
        self._winding_layer_plan.pop(index)
        self._render_winding_plan(index);self._schedule_winding_redraw()

    def _move_winding_plan_layer(self,step):
        index=self._selected_winding_plan_index()
        if index is None:return
        target=index+step
        if 0<=target<len(self._winding_layer_plan):
            self._winding_layer_plan[index],self._winding_layer_plan[target]=self._winding_layer_plan[target],self._winding_layer_plan[index]
            self._render_winding_plan(target);self._schedule_winding_redraw()

    def _split_winding_plan_layer(self):
        index=self._selected_winding_plan_index()
        if index is None:return
        try:
            value=float(self._winding_layer_plan[index]['turns'])
            if not math.isfinite(value) or int(value)!=value or value<2:raise ValueError()
            if len(self._winding_layer_plan)>=1000:raise ValueError()
        except (TypeError,ValueError):
            self._winding_plan_note.set('仅能拆分匝数 ≥ 2 的整数层，且总层数不能超过 1000。');return
        turns=int(value);first=turns//2
        entry=self._winding_layer_plan[index]
        self._winding_layer_plan[index:index+1]=[dict(entry,turns=str(first)),dict(entry,turns=str(turns-first))]
        self._render_winding_plan(index+1);self._schedule_winding_redraw()

    def _select_winding_details(self,*_):
        if not hasattr(self,'_winding_detail_widgets'):
            return
        key=self._winding_selected.get()
        variables=self._winding_override_vars(key)
        legacy=variables['strand_columns'].get() not in ('','0','0.0')
        rows={row['id']:row for row in self._ordered_winding_rows()}
        row=rows.get(key)
        self._winding_details_frame.configure(text=f'{key} · 等效线束与层绕设置')
        self._winding_binding_details=True
        try:
            for name,widget in self._winding_detail_widgets.items():
                if name in WIRE_CHOICES:
                    display=next((label for label,value in WIRE_CHOICES[name].items() if value==variables[name].get()),'')
                    self._winding_detail_choices[name].set(display)
                    widget.configure(state='disabled' if legacy or row is None else 'readonly')
                else:
                    widget.configure(textvariable=variables[name],state='disabled' if row is None or legacy and name!='outer_diameter' else 'normal')
            if legacy:
                columns=self._winding_input_columns or 2
                self._winding_convert_button.grid(row=(len(WIRE_FIELDS)+columns-1)//columns,column=0,columnspan=columns*2,sticky='w',pady=4)
                self._winding_detail_note.set(f'{key} 保留旧版矩形束（{variables["strand_columns"].get()} 列），未自动改变既有方案。点击转换后才启用等效圆 / 椭圆线束。')
            else:
                self._winding_convert_button.grid_remove()
                self._update_winding_detail_note(row,variables)
        finally:
            self._winding_binding_details=False

    def _update_winding_detail_note(self,row,variables):
        if row is None:
            self._winding_detail_note.set('请先完成有效的变压器电气计算。')
            return
        try:
            bundles=float(variables['parallel_bundles'].get())
            total=int(row['strands'])
            if not math.isfinite(bundles) or bundles<1 or int(bundles)!=bundles or total%int(bundles):
                raise ValueError()
            note=f'{row["id"]}：每匝 {total} 股 ÷ {int(bundles)} 束 = 每束 {total//int(bundles)} 股；电气总铜截面积保持不变。'
        except (ValueError,ZeroDivisionError):
            note=f'{row["id"]}：并绕束数必须为正整数，并且整除每匝总股数 {int(row["strands"])}。'
        self._winding_detail_note.set(note)

    def _set_winding_choice(self,name):
        if self._winding_binding_details:
            return
        label=self._winding_detail_choices[name].get()
        value=WIRE_CHOICES[name].get(label)
        if value is not None:
            self._winding_override_vars(self._winding_selected.get())[name].set(value)

    def _convert_winding_bundle(self):
        self._winding_override_vars(self._winding_selected.get())['strand_columns'].set('0')
        self._select_winding_details()
        self._refresh_winding()

    def _resize_winding_text(self,event):
        width=max(160,event.width-24)
        if width==self._winding_wrap_width:
            return
        self._winding_wrap_width=width
        for label in self._winding_labels:
            label.configure(wraplength=width)
        self._layout_winding_inputs(width)

    def _layout_winding_inputs(self,width):
        columns=2 if width>=740 else 1
        if columns==self._winding_input_columns:
            return
        self._winding_input_columns=columns
        frames=(self._winding_geometry_frame,self._winding_details_frame)
        for frame in frames:
            for column in range(4):
                frame.columnconfigure(column,weight=1 if column%2 and column<columns*2 else 0)
        groups=(self._winding_geometry_widgets,
            [(self._winding_detail_labels[name],self._winding_detail_widgets[name]) for name,_caption in WIRE_FIELDS])
        for widgets in groups:
            for index,(caption,entry) in enumerate(widgets):
                row,column=divmod(index,columns)
                caption.grid_configure(row=row,column=column*2)
                entry.grid_configure(row=row,column=column*2+1)
        self._select_winding_details()

    def _cancel_winding_redraw(self):
        job,self._winding_job=self._winding_job,None
        if job:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass

    def _schedule_winding_redraw(self,*_):
        if self._winding_loading or getattr(self,'_closing',False):
            return
        self._cancel_winding_redraw()
        if hasattr(self,'canvas_winding'):
            self._winding_job=self.root.after(300,self._refresh_winding)

    def _ordered_winding_rows(self):
        rows=list(self._winding_source or [])
        by_id={row['id']:row for row in rows}
        order=[key for key in self._winding_order if key in by_id]
        order += [key for key in by_id if key not in order]
        return [by_id[key] for key in order]

    def _update_winding_rows(self):
        if not hasattr(self,'_winding_rows_frame'):
            return
        rows=self._ordered_winding_rows()
        signature=[(r['id'],r['turns'],r['strands'],r['bare_diameter']) for r in rows]
        if signature==self._winding_row_signature:
            return
        self._winding_row_signature=signature
        for child in self._winding_rows_frame.winfo_children():
            child.destroy()
        frame=self._winding_rows_frame
        for column,caption in enumerate(('选择 / 绕组','匝数','每匝总股数','单股裸径 mm')):
            ttk.Label(frame,text=caption,justify='center',style='Muted.TLabel').grid(row=0,column=column,sticky='w',padx=5,pady=3)
        for index,row in enumerate(rows,1):
            key=row['id']
            self._winding_override_vars(key)
            ttk.Radiobutton(frame,text=key,variable=self._winding_selected,value=key).grid(row=index,column=0,sticky='w',padx=4,pady=3)
            for column,value in ((1,int(row['turns'])),(2,int(row['strands'])),(3,f"{row['bare_diameter']*1e3:.4g}")):
                ttk.Label(frame,text=str(value)).grid(row=index,column=column,sticky='w',padx=5,pady=3)
        if not rows:
            ttk.Label(frame,text='当前没有有效变压器；非隔离拓扑不适用。').grid(row=1,column=0,columnspan=4,sticky='w',pady=6)
        frame.columnconfigure(0,weight=1)
        if rows and self._winding_selected.get() not in {row['id'] for row in rows}:
            self._winding_selected.set(rows[0]['id'])
        self._select_winding_details()
        self._select_winding_plan_layer()
        self._update_winding_plan_note()

    def _move_winding(self,step):
        rows=self._ordered_winding_rows()
        order=[r['id'] for r in rows]
        key=self._winding_selected.get()
        if key not in order:
            return
        i=order.index(key)
        j=i+step
        if 0<=j<len(order):
            order[i],order[j]=order[j],order[i]
            self._winding_order=order+[x for x in self._winding_order if x not in order]
            self._winding_row_signature=None
            self._refresh_winding()

    def _update_winding(self,op,p,res):
        # Geometry needs only resolved scalar turns / wire dimensions. Keeping
        # the full electrical result here would retain old multi-output waves
        # after another lazy page publishes a newer design.
        self._winding_source=transformer_windings(res)
        self._winding_row_signature=None
        self._refresh_winding()

    def _mark_winding_stale(self):
        if self._winding_source is not None and hasattr(self,'winding_summary'):
            note='电气参数已变化，以下仅对应上一有效计算；新计算完成后自动更新。'
            text=self.winding_summary.get()
            if not text.startswith(note):
                self.winding_summary.set(note+'\n'+text)

    def _refresh_winding(self):
        self._cancel_winding_redraw()
        if getattr(self,'_closing',False) or not hasattr(self,'canvas_winding'):
            return
        self._update_winding_rows()
        self._select_winding_details()
        self._winding_assessment=None
        try:
            cfg=self._winding_config()['winding_config']
            assessment=assess_winding_window(self._ordered_winding_rows(),cfg)
            self._winding_assessment=assessment
            draw_winding_cross_section(self.ax_winding,assessment)
            if not assessment['configured']:
                text='请填写骨架净窗口宽和高。默认留边及绝缘值仅供预估，须按实际材料和工艺修改。'
            elif not assessment['windings']:
                text='尚无有效变压器参数；请先完成电气计算。'
            else:
                prefix='当前手动逐层方案：' if cfg.get('layer_plan') else '当前指定层绕方案：'
                text=prefix+('可放下' if assessment['fits'] else '超出窗口')
                text+=f" · 所需总高 {assessment['required_height']*1e3:.4g} mm / 净窗高 {cfg['window_height']*1e3:g} mm"
                text+=f" · 高度余量 {assessment['height_margin']*1e3:+.4g} mm · 裸铜面积占比 {assessment['copper_fill']*100:.1f}%"
                def layer_summary(row):
                    indices=row.get('physical_layer_indices')
                    location='（实体层 '+ '、'.join(map(str,indices))+'）' if cfg.get('layer_plan') and indices else ''
                    per_layer='各层 '+ ' / '.join(map(str,row['layer_turns']))+' 匝' if cfg.get('layer_plan') and row.get('layer_turns') else f"{row['turns_per_layer']} 匝/层"
                    return f"{row['id']}：{row['layers']} 层{location}，{per_layer}，单束 {row['bundle_width']*1e3:.3g} × {row['bundle_height']*1e3:.3g} mm"
                text+='\n'+'；'.join(layer_summary(row) for row in assessment['windings'])
                if not assessment['fits']:
                    text+='\n'+'；'.join(assessment['warnings'][:-1])
            if self._winding_source is not None and hasattr(self,'_snapshot_valid') and not self._snapshot_valid:
                text='电气参数已变化，以下仅对应上一有效计算；新计算完成后自动更新。\n'+text
            self.winding_summary.set(text)
        except (ValueError,TypeError) as exc:
            self.ax_winding.clear()
            self.ax_winding.set_axis_off()
            self.ax_winding.text(.5,.5,'绕制输入待修正\n'+str(exc),ha='center',va='center',wrap=True,transform=self.ax_winding.transAxes,fontsize=10)
            self.winding_summary.set('未生成有效评估：'+str(exc))
        self.canvas_winding.request_draw()
        self._winding_view.sync()
