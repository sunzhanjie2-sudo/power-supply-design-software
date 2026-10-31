"""MOS platform selection/import controls, owned by the parameter sidebar."""
import copy
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

class MosCurveUI:
    def _mos_resolved_mode(self):
        mode=self.params['mos_miller_mode'].get()
        if mode=='auto':
            try:return 'gfs' if self.get_param('gfs')>0 else 'manual'
            except (ValueError,tk.TclError):return 'gfs'
        return mode

    def _sync_mos_curve_controls(self):
        mode=self._mos_resolved_mode()
        if 'Vgp_on' in self._param_widgets:
            self._param_widgets['Vgp_on'][0].configure(text=('开通米勒平台 Vgp,on *' if mode=='manual' else 'Qgs曲线参考平台 Vgp,ref *'))
        self._sync_manual_events()

    def _mos_mode_changed(self, *_):
        if getattr(self,'_curve_binding_busy',False):return
        # Keep programmatic/legacy source changes consistent with explicit
        # sidebar choices, without resetting other device overrides.
        if not self._building and self._device_curve_settings:
            from device_curve_sources import TRANSFER,CHARGE
            p=dict(self._curve_context(),device_curve_settings={})
            from device_curve_sources import source_for
            for target in (TRANSFER,CHARGE):
                self._device_curve_settings['overrides'][target]=source_for(p,target)
        self._sync_mos_curve_controls()
        if not self._building:
            self._filter_params()
            self.schedule_update()

    def _select_mos_curve(self, candidates):
        if len(candidates)==1:return candidates[0]
        dialog=tk.Toplevel(self.root);dialog.title('选择一条测试条件明确的曲线')
        dialog.transient(self.root)
        ttk.Label(dialog,text='不同温度或 Vds 的曲线不自动混合，请明确选择一条。',padding=10).pack(fill='x')
        box=tk.Listbox(dialog,width=90,height=min(10,len(candidates)),exportselection=False)
        box.pack(fill='both',expand=True,padx=10,pady=6)
        for c in candidates:
            condition=c.get('conditions') or '条件未声明'
            if 'Id_test_A' in c:
                temp='未声明' if c.get('Tj_C') is None else f"{c['Tj_C']:g} °C"
                condition+='；Id='+str(c.get('Id_test_A') if c.get('Id_test_A') is not None else '未声明')+' / VDD='+str(c.get('Vds_test_V') if c.get('Vds_test_V') is not None else '未声明')+' / Tj='+temp
            box.insert('end',c.get('name','MOS')+' · '+condition)
        result=[]
        def accept():
            chosen=box.curselection()
            if chosen:result.append(candidates[chosen[0]]);dialog.destroy()
        row=ttk.Frame(dialog);row.pack(fill='x',padx=10,pady=10)
        ttk.Button(row,text='使用所选曲线',command=accept).pack(side='right')
        ttk.Button(row,text='取消',command=dialog.destroy).pack(side='right',padx=8)
        from simple_curve_ui import _place_dialog
        _place_dialog(dialog,self.root)
        dialog.grab_set();self.root.wait_window(dialog)
        return result[0] if result else None

    def _import_mos_curve(self):
        path=filedialog.askopenfilename(parent=self.root,title='导入 MOS 转移曲线或带 Vgs 的输出曲线族',
            filetypes=[('曲线 CSV / JSON','*.csv *.json'),('CSV','*.csv'),('JSON','*.json')])
        if not path:return
        try:
            from mos_curves import validate_curve
            candidate=self._read_mos_input(path,'transfer')
            if candidate is None:return
            data=validate_curve(candidate)
            self._mos_miller_curve=copy.deepcopy(data)
            self._set_curve_override('Q1:transfer','curve')
        except (ValueError,OSError,UnicodeError) as exc:
            messagebox.showerror('MOS 曲线未导入',str(exc),parent=self.root)

    def _mos_charge_parameter_hidden(self,key):
        if hasattr(self,'_manual_event_vars') and self._mos_resolved_mode()=='manual' and key in ('Vgp_on','Vgp_off','Qgs'):return True
        active=self.params.get('mos_charge_mode') and self.params['mos_charge_mode'].get()=='curve'
        return bool(active and (key in ('Qg','Qg_th','Qgs','Qgd') or (key=='Vgp_on' and self._mos_current_plateau_active())))

    def _build_manual_events(self,frame,row):
        self._manual_event_vars={};self._manual_event_entries={};self._manual_loading=False
        panel=ttk.Frame(frame);panel.grid(row=row,column=0,columnspan=4,sticky='ew',pady=6)
        ttk.Label(panel,text='手动四事件：电流由对应工况计算',style='Param.TLabel').grid(row=0,column=0,columnspan=3,sticky='w')
        for col,text in enumerate(('输入 / 事件','Vgp / V','零伏至平台\nQgs / nC')):
            ttk.Label(panel,text=text,justify='center').grid(row=1,column=col,padx=3,pady=4)
        from power_stage import DEFAULT_PARAMS
        for index,(case,edge) in enumerate((('min','on'),('min','off'),('max','on'),('max','off')),2):
            ttk.Label(panel,text=('Vinmin' if case=='min' else 'Vinmax')+(' 开通' if edge=='on' else ' 关断')).grid(row=index,column=0,sticky='w',padx=2,pady=3)
            for col,key in enumerate(('Vgp','Qgs'),1):
                val=DEFAULT_PARAMS['Vgp_'+edge] if key=='Vgp' else DEFAULT_PARAMS['Qgs']*1e9
                var=tk.StringVar(value=f'{val:.7g}');self._manual_event_vars[case,edge,key]=var
                entry=ttk.Entry(panel,textvariable=var,width=8);entry.grid(row=index,column=col,padx=3,sticky='ew')
                self._manual_event_entries[case,edge,key]=entry
                var.trace_add('write',self._manual_event_changed)
        panel.columnconfigure(1,weight=1);panel.columnconfigure(2,weight=1)
        self._manual_event_note=tk.StringVar()
        ttk.Label(panel,textvariable=self._manual_event_note,wraplength=300,style='Muted.TLabel').grid(row=6,column=0,columnspan=3,sticky='ew',pady=4)
        self._register_param_extra(frame,[panel],('Vgp_on','Vgp_off','Qgs'),'MOS 手动 四事件 Vinmin Vinmax Qgs 平台',lambda:self._mos_resolved_mode()=='manual')
        self._sync_manual_events()
        return row+1

    def _sync_manual_events(self):
        if not hasattr(self,'_manual_event_vars'):return
        curve=self.params['mos_charge_mode'].get()=='curve'
        for (case,edge,key),entry in self._manual_event_entries.items():
            entry.configure(state='disabled' if curve and key=='Qgs' else 'normal')
        self._manual_event_note.set('Qgs 由栅电荷曲线按四个平台读取，表内电荷草稿不参与计算。' if curve else '四行独立生效；Qg(th)、Qgd 与总 Qg 仍为公共器件参数。对应电流见上方“四工况”核算。')

    def _manual_event_changed(self,*_):
        if self._manual_loading or self._building:return
        self.schedule_update()

    def _manual_events_value(self,strict=True):
        values={case:{edge:{} for edge in ('on','off')} for case in ('min','max')}
        for (case,edge,key),var in self._manual_event_vars.items():
            if strict and key=='Qgs' and self.params['mos_charge_mode'].get()=='curve':
                values[case][edge][key]=0.
                continue
            try:value=float(var.get())*(1e-9 if key=='Qgs' else 1.)
            except ValueError:
                if strict:raise ValueError(f'请填写 {case}/{edge} 的 '+key) from None
                value=var.get()
            values[case][edge][key]=value
        if strict:
            from mos_manual import normalize_events
            values=normalize_events(values)
        return values

    def _load_manual_events(self,cfg):
        from mos_manual import normalize_events
        from config_io import decode_config
        from power_stage import DEFAULT_PARAMS
        legacy=dict(DEFAULT_PARAMS,**decode_config(cfg))
        values=cfg.get('mos_manual_events')
        if not values:
            values={case:{edge:dict(Vgp=legacy['Vgp_'+edge],Qgs=legacy['Qgs']) for edge in ('on','off')} for case in ('min','max')}
        if not isinstance(values,dict):raise ValueError('MOS 四事件配置格式错误')
        self._manual_loading=True
        try:
            for (case,edge,key),var in self._manual_event_vars.items():
                try:raw=values[case][edge][key]
                except (KeyError,TypeError):raise ValueError('MOS 四事件配置缺少 '+case+'/'+edge+'/'+key) from None
                try:display=f"{float(raw)*(1e9 if key=='Qgs' else 1):.10g}"
                except (ValueError,TypeError,OverflowError):display=str(raw)
                var.set(display)
        finally:self._manual_loading=False

    def _import_gate_charge(self):
        path=filedialog.askopenfilename(parent=self.root,title='② 导入 Vgs–Qg 栅电荷曲线（横轴Qg，纵轴Vgs）',filetypes=[('栅电荷 CSV / JSON','*.csv *.json')])
        if not path:return
        try:
            candidate=self._read_mos_input(path,'gate_charge')
            if candidate is None:return
            self._mos_charge_curve=copy.deepcopy(candidate)
            self._set_curve_override('Q1:charge','curve')
        except (ValueError,OSError,UnicodeError) as exc:messagebox.showerror('栅电荷曲线未导入',str(exc),parent=self.root)

    def _read_mos_input(self,path,kind):
        from mos_curves import read_curve_candidates
        from mos_gate_charge import read_charge_candidates
        try:candidates=(read_charge_candidates if kind=='gate_charge' else read_curve_candidates)(path)
        except ValueError:
            from simple_curves import read_simple
            simple=read_simple(path)
            if simple is None:raise
            from simple_curve_ui import import_simple
            return import_simple(self.root,simple,kind,target='Q1 · 主开关 MOS · '+('栅电荷' if kind=='gate_charge' else '米勒平台'))
        return self._select_mos_curve(candidates)

    def _show_mos_four(self):
        from mos_four_cases import show_four_cases
        show_four_cases(self)
