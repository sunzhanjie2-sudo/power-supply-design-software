"""Small desktop LDO editor; shares all equations and reports with the web UI."""
import copy
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from ldo import normalize,calculate,FIELDS,OPTIONAL
from ldo_report import fmt,STATE
CHOICES={'output_mode':{'fixed':'固定输出','adjustable':'可调输出（计算分压）'},
         'reverse_blocking':{'unknown':'待核对','yes':'具备（按芯片条件）','no':'不具备'}}

class LdoDesigner:
    def __init__(self,root,initial_config=None,on_return=None):
        self.root,self.on_return=root,on_return;self.spec=normalize(initial_config);self.result=None;self.vars={};self.items={}
        root.title('LDO 线性稳压器设计');root.geometry('1320x850');root.minsize(1000,650)
        head=ttk.Frame(root,padding=16);head.pack(fill='x')
        ttk.Label(head,text='LDO 线性稳压器 · 压差 / 损耗 / 温升',font=('Microsoft YaHei UI',18,'bold')).pack(side='left')
        ttk.Button(head,text='返回系统架构并保存',command=self.close).pack(side='right',padx=5)
        ttk.Button(head,text='计算 LDO',command=self.compute).pack(side='right',padx=5)
        self.status=tk.StringVar(value='静态线性模型；未知额定值和规格书条件留空')
        ttk.Label(root,textvariable=self.status,padding=(16,5)).pack(fill='x')
        split=ttk.Panedwindow(root,orient='horizontal');split.pack(fill='both',expand=True,padx=16,pady=8)
        left=ttk.Frame(split);split.add(left,weight=2);canvas=tk.Canvas(left,width=360,highlightthickness=0);scroll=ttk.Scrollbar(left,command=canvas.yview);canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        form=ttk.Frame(canvas,padding=12);win=canvas.create_window((0,0),window=form,anchor='nw');form.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')));canvas.bind('<Configure>',lambda e:canvas.itemconfigure(win,width=e.width))
        for k,label in [('manufacturer','厂家'),('model','型号'),('package','封装'),('notes','资料来源与条件')]:self.field(form,k,label)
        self.choice(form,'output_mode','输出类型');self.choice(form,'reverse_blocking','反向电流保护')
        for k,label in [('follow_input','跟随上游输入范围'),('thermal_verified','有效热阻已按实际PCB核对'),('enable_pin','具有 EN 引脚'),('power_good','具有 PG 引脚')]:
            v=tk.BooleanVar(value=self.spec[k]);self.vars[k]=(v,1);ttk.Checkbutton(form,text=label,variable=v).pack(anchor='w',pady=6)
        self.adjustable_frame=None
        for section,fields in FIELDS:
            group=ttk.Frame(form);group.pack(fill='x')
            if section=='可调输出分压':self.adjustable_frame=group
            ttk.Label(group,text=section,font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w',pady=(16,6))
            for k,label,unit,scale in fields:self.field(group,k,label+' / '+unit,scale)
        canvas.bind('<Enter>',lambda e:canvas.focus_set())
        canvas.bind('<MouseWheel>',lambda e:canvas.yview_scroll(-int(e.delta/120),'units'))
        right=ttk.Frame(split);split.add(right,weight=5)
        self.book=ttk.Notebook(right);self.book.pack(fill='both',expand=True)
        self.corner=self.tree('四角点结果',['工况','Vin/V','Iout/A','压差裕量/V','芯片W','效率%','结温°C'])
        self.checks=self.tree('检查与降额',['检查项','计算值','限值','状态','说明'])
        bom=ttk.Frame(self.book,padding=12);self.book.add(bom,text='器件BOM资料')
        ttk.Label(bom,text='U1 厂家/型号/封装在左侧；电容与分压电阻资料在此填写。').pack(anchor='w')
        self.bom_form=ttk.Frame(bom);self.bom_form.pack(fill='both',expand=True);self.bom_frames={}
        self.draw_bom()
        self.vars['output_mode'][0].trace_add('write',lambda *args:self.update_mode());self.update_mode()
        self.info=tk.Text(right,height=7,wrap='word',font=('Microsoft YaHei UI',11));self.info.pack(fill='x',pady=8)
        bar=ttk.Frame(right);bar.pack(fill='x')
        for kind in ('docx','xlsx','json'):ttk.Button(bar,text='导出 '+kind.upper(),command=lambda k=kind:self.report(k)).pack(side='left',padx=5)
        root.protocol('WM_DELETE_WINDOW',self.close);self.compute()

    def field(self,parent,key,label,scale=1):
        ttk.Label(parent,text=label).pack(anchor='w');v=self.spec.get(key);variable=tk.StringVar(value='' if v is None else str(v/scale) if isinstance(v,(int,float)) else v)
        self.vars[key]=(variable,scale);ttk.Entry(parent,textvariable=variable).pack(fill='x',pady=(3,9))

    def choice(self,parent,key,label):
        ttk.Label(parent,text=label).pack(anchor='w');v=tk.StringVar(value=CHOICES[key][self.spec[key]]);self.vars[key]=(v,1);ttk.Combobox(parent,textvariable=v,values=list(CHOICES[key].values()),state='readonly').pack(fill='x',pady=(3,9))

    def update_mode(self):
        active=self.vars['output_mode'][0].get() in ('adjustable',CHOICES['output_mode']['adjustable'])
        if active:self.adjustable_frame.pack(fill='x')
        else:self.adjustable_frame.pack_forget()
        for ref in ('R1','R2'):
            if active:self.bom_frames[ref].pack(fill='x',pady=5,before=self.bom_note)
            else:self.bom_frames[ref].pack_forget()

    def tree(self,title,headers):
        f=ttk.Frame(self.book);self.book.add(f,text=title);t=ttk.Treeview(f,columns=list(range(len(headers))),show='headings');sy=ttk.Scrollbar(f,command=t.yview);sx=ttk.Scrollbar(f,orient='horizontal',command=t.xview);t.configure(yscrollcommand=sy.set,xscrollcommand=sx.set);sy.pack(side='right',fill='y');sx.pack(side='bottom',fill='x');t.pack(fill='both',expand=True)
        for j,label in enumerate(headers):t.heading(j,text=label);t.column(j,width=125 if j<len(headers)-1 else 240,stretch=True)
        t.tag_configure('review',background='#fff3df');return t

    def draw_bom(self):
        for ref in ('C_IN1','C_OUT1','R1','R2'):
            f=ttk.LabelFrame(self.bom_form,text=ref,padding=8);f.pack(fill='x',pady=5);self.bom_frames[ref]=f;self.items[ref]={};saved=self.spec['component_management']['items'].get(ref,{})
            for j,(k,label) in enumerate([('manufacturer','厂家'),('model','型号'),('package','封装')]+([('voltage_V','耐压/V')] if ref.startswith('C_') else [('power_W','额定功率/W')])):
                ttk.Label(f,text=label).grid(row=0,column=j,sticky='w');v=tk.StringVar(value=saved.get(k) or '');self.items[ref][k]=v;ttk.Entry(f,textvariable=v,width=15).grid(row=1,column=j,sticky='ew',padx=3);f.columnconfigure(j,weight=1)
            if ref.startswith('C_'):
                v=tk.StringVar(value=saved.get('capacitor_type','unknown'));self.items[ref]['capacitor_type']=v;ttk.Label(f,text='电容类型').grid(row=2,column=0);ttk.Combobox(f,textvariable=v,values=['unknown','mlcc','electrolytic','film','other'],state='readonly',width=15).grid(row=2,column=1,columnspan=2,sticky='w')
        self.bom_note=ttk.Label(self.bom_form,text='固定输出不使用 R1/R2；可调输出的下电阻自动计算。电阻按20%额定功率初查。\n有效电容/ESR在左侧填写；本模块不预测瞬态纹波电流。',wraplength=650);self.bom_note.pack(anchor='w',pady=8)

    def _config_dict(self):
        p=copy.deepcopy(self.spec)
        for k,(var,scale) in self.vars.items():
            text=var.get()
            if k in CHOICES:p[k]=next((key for key,label in CHOICES[k].items() if label==text),text)
            elif k in ('manufacturer','model','package','notes'):p[k]=text
            elif isinstance(text,bool):p[k]=text
            else:p[k]=None if text=='' and k in OPTIONAL else float(text)*scale
        for ref,fields in self.items.items():
            item=p['component_management']['items'].setdefault(ref,{})
            for key,v in fields.items():item[key]=(float(v.get()) if v.get() else None) if key in ('voltage_V','power_W') else v.get()
        return normalize(p)

    def compute(self):
        try:
            r=calculate(self._config_dict());self.spec=r['spec'];self.result=r
            for t in (self.corner,self.checks):t.delete(*t.get_children())
            for c in r['corners']:self.corner.insert('', 'end',values=[c['id'],fmt(c['V_in']),fmt(c['I_out']),fmt(c['dropout_margin']),fmt(c['P_chip']),fmt(c['eta']*100 if c['eta'] is not None else None),fmt(c['T_j'])],tags=() if c['regulated'] else ('review',))
            for c in r['checks']:self.checks.insert('','end',values=[c['name'],fmt(c['value'])+c['unit'],c['comparison']+fmt(c['limit']),STATE[c['state']],c['note']],tags=() if c['state']=='pass' else ('review',))
            self.info.configure(state='normal');self.info.delete('1.0','end');self.info.insert('end','\n'.join(r['notes'])+'\n'+('R2 = '+fmt(r['divider']['R_bottom'])+' Ω' if self.spec['output_mode']=='adjustable' else '固定输出，无外部分压电阻。'));self.info.configure(state='disabled');self.status.set('已按当前输入完成四角点计算：'+STATE[r['state']]);return True
        except Exception as e:messagebox.showerror('LDO 参数',str(e),parent=self.root);return False

    def report(self,kind):
        if not self.compute():return
        path=filedialog.asksaveasfilename(parent=self.root,initialfile='LDO设计报告.'+kind,defaultextension='.'+kind,filetypes=[(kind.upper(),'*.'+kind)])
        if path:
            try:
                from ldo_report import export_report
                export_report(self.result,path);self.status.set('已导出：'+path)
            except Exception as e:messagebox.showerror('LDO 报告',str(e),parent=self.root)

    def close(self):
        if self.on_return:
            if self.on_return(self) is False:return
        self.root.destroy()
