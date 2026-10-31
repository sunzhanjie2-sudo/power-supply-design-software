"""One small scale-selection dialog, no physical-unit fields in the curve file."""
import tkinter as tk
from tkinter import ttk,messagebox
from simple_curves import to_transfer,to_charge

SCALES={'1（原数值）':1.,'10^-3（m）':1e-3,'10^-6（u）':1e-6,'10^-9（n）':1e-9,'10^-12（p）':1e-12,'10^3（k）':1e3,'10^6（M）':1e6}


def _place_dialog(dialog,owner):
    """Center on the actual application window, not Windows' last dialog origin."""
    dialog.update_idletasks()
    width=max(620,dialog.winfo_reqwidth())
    height=max(470,dialog.winfo_reqheight())
    screen_w,screen_h=dialog.winfo_screenwidth(),dialog.winfo_screenheight()
    width=min(width,max(1,screen_w-32));height=min(height,max(1,screen_h-96))
    x=owner.winfo_rootx()+(owner.winfo_width()-width)//2
    y=owner.winfo_rooty()+(owner.winfo_height()-height)//2
    x=max(16,min(x,screen_w-width-16))
    y=max(32,min(y,screen_h-height-64))
    dialog.geometry(f'{width}x{height}+{x}+{y}')


def import_simple(parent,data,kind,target=''):
    owner=parent.winfo_toplevel()
    dialog=tk.Toplevel(owner);dialog.title('简洁曲线导入 选择数量级');dialog.transient(owner)
    dialog.geometry('620x470');dialog.minsize(560,440)
    body=ttk.Frame(dialog,padding=14);body.pack(fill='both',expand=True)
    gate=kind=='gate_charge'
    diode=kind=='diode'
    guide='X=Vf 正向压降（V）；Y=If 正向电流（A）。用此曲线计算所选二极管的导通损耗。' if diode else 'X=Qg（C）；Y=Vgs（V）。' if gate else 'X=Vgs（V）；Y=Id（A）。'
    ttk.Label(body,text=(('绑定目标：'+target+'\n') if target else '')+guide+
        '\nV1.3 提取文件已乘数量级，X/Y 均选 1；旧原图数值文件才选 n/u/m 等倍率。\nCSV 只需 x,y；JSON 只需点数组。端点范围外按趋势外推并提示。',wraplength=580).pack(fill='x')
    if diode:
        ttk.Label(body,text='允许小幅描点回退：不超过 Vf 跨度 3% 时自动单调整理，并记录修正量；明显倒退仍需校核。',wraplength=580).pack(fill='x',pady=(4,0))
    box=tk.Listbox(body,height=min(5,len(data['curves'])),exportselection=False)
    for c in data['curves']:box.insert('end',c['name']+f"  {len(c['points'])} 点")
    box.pack(fill='x',pady=10);box.selection_set(0)
    limits=tk.StringVar()
    ttk.Label(body,textvariable=limits,wraplength=580).pack(fill='x',pady=(0,5))
    def show_limits(*_):
        selected=box.curselection()
        if not selected:return
        points=data['curves'][selected[0]]['points']
        limits.set(f"文件原数值范围：X {min(p[0] for p in points):.5g}–{max(p[0] for p in points):.5g}；"
                   f"Y {min(p[1] for p in points):.5g}–{max(p[1] for p in points):.5g}")
    box.bind('<<ListboxSelect>>',show_limits);show_limits()
    form=ttk.Frame(body);form.pack(fill='x')
    x=tk.StringVar(value='1（原数值）');y=tk.StringVar(value='1（原数值）')
    for r,(text,var) in enumerate((('X 数量级',x),('Y 数量级',y))):
        ttk.Label(form,text=text).grid(row=r,column=0,sticky='w',pady=5)
        ttk.Combobox(form,textvariable=var,values=list(SCALES),state='readonly',width=20).grid(row=r,column=1,sticky='w',padx=10)
    start=tk.StringVar();end=tk.StringVar()
    if gate:
        for r,(text,var) in enumerate((('平台起点 X（原数值）',start),('平台终点 X（原数值）',end)),2):
            ttk.Label(form,text=text).grid(row=r,column=0,sticky='w',pady=4)
            ttk.Entry(form,textvariable=var,width=22).grid(row=r,column=1,sticky='w',padx=10)
        def suggest(*_):
            show_limits()
            try:
                from simple_curves import cleaned_points
                from mos_gate_charge import suggest_plateau
                c=data['curves'][box.curselection()[0]]
                a,b=suggest_plateau(cleaned_points(c['points'])[0]);start.set(f'{a:.9g}');end.set(f'{b:.9g}')
            except (ValueError,IndexError):start.set('');end.set('')
        box.bind('<<ListboxSelect>>',suggest);suggest()
        ttk.Label(body,text='平台位置为建议值，可直接修改；仅填原图横轴数值，不用写单位。',wraplength=560).pack(fill='x',pady=8)
    result=[]
    def accept():
        try:
            selected=box.curselection()
            if not selected:raise ValueError('请选择一条曲线')
            curve=data['curves'][selected[0]];args=dict(x_multiplier=SCALES[x.get()],y_multiplier=SCALES[y.get()],source=data['source'])
            if gate:
                args.update(start=float(start.get()) if start.get().strip() else None,end=float(end.get()) if end.get().strip() else None)
                value=to_charge(curve,**args)
            elif diode:
                from diode_curves import from_xy
                value=from_xy(curve,**args)
            else:value=to_transfer(curve,**args)
            result.append(value);dialog.destroy()
        except (ValueError,OverflowError) as exc:messagebox.showerror('请核对导入设置',str(exc),parent=dialog)
    buttons=ttk.Frame(body);buttons.pack(side='bottom',fill='x',pady=8)
    ttk.Button(buttons,text='确认数量级并导入',command=accept).pack(side='right')
    ttk.Button(buttons,text='取消',command=dialog.destroy).pack(side='right',padx=8)
    _place_dialog(dialog,owner)
    dialog.grab_set();owner.wait_window(dialog)
    return result[0] if result else None
