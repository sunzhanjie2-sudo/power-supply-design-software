"""Scrollable editor; committing is atomic and cancel leaves drafts untouched."""
import copy
import tkinter as tk
from tkinter import ttk, messagebox
from parasitics import FIELDS, RAIL_FIELDS, normalize, resolved, NOTE


def open_editor(app):
    try:p=app.get_params(check_curve_sources=False)
    except Exception as e:messagebox.showerror('请先完成参数',str(e));return
    raw=copy.deepcopy(getattr(app,'_parasitic_config',{}));count=len(p.get('outputs') or [None])
    cfg=resolved(p,count)
    win=tk.Toplevel(app.root);win.title('寄生参数与吸收 · 同步计算 / 报告 / LTspice')
    win.geometry('860x720');win.minsize(680,420);win.transient(app.root)
    mode=tk.StringVar(value=cfg['mode']);vars={};rail_vars={}
    head=ttk.Frame(win,padding=12);head.pack(fill='x')
    ttk.Label(head,text='寄生参数与吸收',font=('Microsoft YaHei UI',15,'bold')).pack(anchor='w')
    ttk.Radiobutton(head,text='快速计算：沿用原有波形，不增加局部振铃求解',variable=mode,value='fast').pack(anchor='w',pady=3)
    ttk.Radiobutton(head,text='寄生瞬态：反激局部 RLC 估算 / 正激物理周期',variable=mode,value='transient').pack(anchor='w',pady=3)
    ttk.Label(head,text=NOTE,wraplength=800,justify='left').pack(fill='x',pady=5)
    # Footer is outside the scrolling body, always reachable on small displays.
    foot=ttk.Frame(win,padding=12);foot.pack(side='bottom',fill='x')
    outer=ttk.Frame(win);outer.pack(fill='both',expand=True)
    canvas=tk.Canvas(outer,highlightthickness=0);bar=ttk.Scrollbar(outer,command=canvas.yview)
    bar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True);canvas.configure(yscrollcommand=bar.set)
    body=ttk.Frame(canvas,padding=12);item=canvas.create_window(0,0,window=body,anchor='nw')
    body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
    def wheel(e):canvas.yview_scroll(-int(e.delta/120),'units')
    win.bind('<MouseWheel>',wheel)
    def rows(frame,fields,data,store):
        for i,(key,(label,unit,scale,default)) in enumerate(fields.items()):
            if key in ('coss_aux','cj_free') and p['topology']!='ACF-FORWARD':continue
            value=data.get(key,default)
            store[key]=tk.StringVar(value=f'{value*scale:.8g}')
            ttk.Label(frame,text=label,wraplength=465).grid(row=i,column=0,sticky='w',pady=5,padx=5)
            ttk.Entry(frame,textvariable=store[key],width=15).grid(row=i,column=1,pady=5,padx=6)
            ttk.Label(frame,text=unit).grid(row=i,column=2,sticky='w')
        frame.columnconfigure(0,weight=1)
    group=ttk.LabelFrame(body,text='共享原边 / Q1 / Q2',padding=8);group.pack(fill='x',pady=4)
    # Explicit effective Coss prevents an old QR export-only override lingering.
    rows(group,FIELDS,cfg,vars)
    for i,row in enumerate(cfg['rails'],1):
        rectifier=f'D_O{i}' if p.get('outputs') else 'D1（仿真 D_O1）'
        frame=ttk.LabelFrame(body,text=f'OUT{i} · 整流 {rectifier}'+(f' / 续流 D_F{i}' if p['topology']=='ACF-FORWARD' else ''),padding=8)
        frame.pack(fill='x',pady=6);rail_vars[f'OUT{i}']={};rows(frame,RAIL_FIELDS,row,rail_vars[f'OUT{i}'])
    def commit():
        try:
            data={k:float(v.get())/FIELDS[k][2] for k,v in vars.items()}
            # Keep inactive outputs' drafts, but show only existing rails.
            data['rails']=copy.deepcopy(raw.get('rails',{}))
            for ref,entry in rail_vars.items():data['rails'][ref]={k:float(v.get())/RAIL_FIELDS[k][2] for k,v in entry.items()}
            data['mode']=mode.get();data=normalize(data)
            if data['mode']=='transient' and p['topology']=='ACF-FORWARD' and not p.get('coupling_config',{}).get('enabled'):
                raise ValueError('正激寄生瞬态请先在左侧磁件配置中启用两两 kij 物理周期计算')
            if data['mode']=='transient' and p.get('feedback_mode','SSR')!='SSR':raise ValueError('当前寄生瞬态支持 SSR，请先切换反馈模式')
        except (ValueError,TypeError) as e:messagebox.showerror('请检查寄生参数',str(e),parent=win);return
        app._parasitic_config=data;app.schedule_update();win.destroy()
    ttk.Button(foot,text='应用并重新计算',command=commit).pack(side='right',padx=6)
    ttk.Button(foot,text='取消',command=win.destroy).pack(side='right',padx=6)
    ttk.Label(foot,text='参数单位在每行右侧；保存工程时一起保存。').pack(side='left')
    return win
