"""Small reusable geometry editor; numeric quantities are serialized in SI."""
import json
import math
import tkinter as tk
from tkinter import ttk

from custom_cores import CUSTOM_CORE, DIMENSIONS, DISPLAY_UNITS, is_custom


class CoreGeometryEditor:
    def __init__(self,parent,variable,on_change,title):
        self.variable=variable;self.on_change=on_change;self.busy=False
        self.frame=ttk.Frame(parent,padding=(8,3,4,6))
        self.frame.columnconfigure(0,weight=1)
        ttk.Label(self.frame,text=title,style='TLabelframe.Label',wraplength=330).grid(row=0,column=0,columnspan=3,sticky='w')
        self.values={};self.units={};self._selected_units={}
        ttk.Label(self.frame,text='磁芯名称（可选）',style='Param.TLabel').grid(row=1,column=0,sticky='w')
        self.name=tk.StringVar()
        ttk.Entry(self.frame,textvariable=self.name,width=14).grid(row=1,column=1,columnspan=2,sticky='ew',pady=3)
        for row,(key,(label,choices)) in enumerate(DIMENSIONS.items(),2):
            self.values[key]=tk.StringVar();self.units[key]=tk.StringVar()
            ttk.Label(self.frame,text=label,style='Param.TLabel',wraplength=170).grid(row=row,column=0,sticky='w',pady=3)
            ttk.Entry(self.frame,textvariable=self.values[key],width=10).grid(row=row,column=1,sticky='ew',padx=3)
            combo=ttk.Combobox(self.frame,textvariable=self.units[key],values=list(choices)[:2],state='readonly',width=5)
            combo.grid(row=row,column=2,sticky='w',padx=3)
            combo.bind('<<ComboboxSelected>>',lambda _e,k=key:self.change_unit(k))
            self.values[key].trace_add('write',lambda *_:self.edit())
        self.name.trace_add('write',lambda *_:self.edit())
        ttk.Label(self.frame,text='填写厂家有效参数，不是外形包络长宽高。\nAe/Ve/Wa/MLT 均必填；MLT 在此填写后优先使用，不再用标准芯匝长覆盖。',
                  style='Muted.TLabel',wraplength=330,justify='left').grid(row=6,column=0,columnspan=3,sticky='ew',pady=(4,0))
        self.variable.trace_add('write',lambda *_:self.load())
        self.load()

    def load(self):
        if self.busy:return
        self.busy=True
        try:
            data=json.loads(self.variable.get() or '{}')
            if not isinstance(data,dict):data={}
            self.name.set(data.get('name',''))
            display=data.get('display_units',{})
            if not isinstance(display,dict):display={}
            for key,(_label,choices) in DIMENSIONS.items():
                unit=display.get(key,DISPLAY_UNITS[key])
                if unit not in list(choices)[:2]:unit=DISPLAY_UNITS[key]
                value=data.get(key,'')
                if isinstance(value,dict):
                    source=value.get('u')
                    value=value.get('v','')
                    if source in choices and isinstance(value,(int,float)):value*=choices[source]
                if isinstance(value,(int,float)) and not isinstance(value,bool):value=f'{value/choices[unit]:.12g}'
                self.units[key].set(unit);self._selected_units[key]=unit
                self.values[key].set('' if value is None else value)
        finally:self.busy=False

    def edit(self):
        if self.busy:return
        data={'name':self.name.get()[:48],'display_units':{k:v.get() for k,v in self.units.items()}}
        for key,(_label,choices) in DIMENSIONS.items():
            raw=self.values[key].get().strip()
            try:
                value=float(raw)*choices[self.units[key].get()]
                data[key]=value if math.isfinite(value) else raw
            except (ValueError,KeyError):data[key]=raw if raw else None
        self.busy=True
        try:self.variable.set(json.dumps(data,ensure_ascii=False,allow_nan=False))
        finally:self.busy=False
        self.on_change()

    def change_unit(self,key):
        new=self.units[key].get();old=self._selected_units[key]
        if new==old:return
        choices=DIMENSIONS[key][1]
        try:
            raw=float(self.values[key].get())
            if not math.isfinite(raw):raise ValueError
        except ValueError:
            self.units[key].set(old)
            return
        self.busy=True
        try:
            self.values[key].set(f'{raw*choices[old]/choices[new]:.12g}')
            self._selected_units[key]=new
        finally:self.busy=False
        self.edit()


class CustomCoreUI:
    def _init_custom_core_controls(self):
        self._custom_core_vars={key:tk.StringVar(value='{}') for key in ('custom_core','custom_core_L')}
        self._custom_core_editors={}
        self._custom_core_filtering=False

    def _custom_core_context_changed(self,*_):
        if self._building or self._custom_core_filtering or not hasattr(self,'_param_subgroups'):return
        self._custom_core_filtering=True
        try:self._filter_params()
        finally:self._custom_core_filtering=False

    def _custom_core_edited(self):
        if not self._building:self.schedule_update()

    def _custom_core_parameters(self):
        return {key:json.loads(value.get() or '{}') for key,value in self._custom_core_vars.items()}

    def _load_custom_core_config(self,cfg):
        from config_io import decode_config
        decoded=decode_config(cfg)
        for key,var in self._custom_core_vars.items():
            data=decoded.get(key,{})
            if not isinstance(data,dict):raise ValueError(key+' 必须为磁芯尺寸字典')
            var.set(json.dumps(data,ensure_ascii=False))

    def _standard_mlt_active(self):
        if not is_custom(self.params['core_choice'].get()):return True
        if self._topo_key()!='ACF-FORWARD':return False
        if not self._multiple_active():return not is_custom(self.params['core_choice_L'].get())
        try:
            count=self._read_output_count()
            return any(not is_custom(self._inline_output_vars[i]['core_choice_L'].get()) for i in range(count))
        except ValueError:return True
