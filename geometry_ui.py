"""Desktop controls for the transformer CAD export. All Tk access stays on the UI thread."""
import copy
import json
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def edit_profile(app):
    from transformer_geometry_contract import profile_template,validate_profile
    from transformer_geometry import strict_json
    layers=(app._winding_assessment or {}).get('physical_layers') or []
    profile=app._geometry_profile or profile_template(layers)
    win=tk.Toplevel(app.root)
    win.title('变压器三维建模设置')
    win.transient(app.root)
    win.grab_set()
    win.columnconfigure(0,weight=1);win.rowconfigure(2,weight=1)
    ttk.Label(win,text='本设置随工程保存。JSON 长度为 m，针脚、同名端与绕向按实物或绕线图填写；未知值保留 null。',
              wraplength=670,padding=8).grid(row=0,columnspan=2,sticky='ew')
    quick=ttk.LabelFrame(win,text='圆形骨架基准（快速填写）',padding=6)
    quick.grid(row=1,columnspan=2,sticky='ew',padx=8)
    inputs={}
    for i,(k,label) in enumerate((('z0_m','净窗口起点 Z / mm'),('r0_m_if_circular','内侧半径 / mm'),('source','尺寸来源'))):
        frame=profile.get('frame',{})
        value=profile.get('bobbin',{}).get('source') if k=='source' else frame.get(k)
        val=tk.StringVar(win,'' if value is None else str(value if k=='source' else value*1000))
        ttk.Label(quick,text=label).grid(row=0,column=i,sticky='w',padx=4)
        ttk.Entry(quick,textvariable=val,width=19).grid(row=1,column=i,sticky='ew',padx=4)
        inputs[k]=val
    editor=tk.Text(win,width=81,height=23,wrap='none',undo=True)
    editor.grid(row=2,column=0,sticky='nsew',padx=(8,0),pady=8)
    scroll=ttk.Scrollbar(win,command=editor.yview);scroll.grid(row=2,column=1,sticky='ns',pady=8)
    editor.configure(yscrollcommand=scroll.set)
    def show(value):
        editor.delete('1.0','end');editor.insert('1.0',json.dumps(value,ensure_ascii=False,indent=2))
    show(profile)
    def read():
        value=strict_json(editor.get('1.0','end-1c').encode('utf8'))
        validate_profile(value)
        return value
    def circle():
        try:
            value=read()
            value['frame']=dict(z0_m=float(inputs['z0_m'].get())/1000,
                                r0_m_if_circular=float(inputs['r0_m_if_circular'].get())/1000)
            value.setdefault('bobbin',{}).update(winding_route_type='circular',status='assumed',
                    source=inputs['source'].get().strip(),winding_path_xy_m=None,rounded_rectangle_m=None)
            validate_profile(value);show(value)
        except ValueError as exc: messagebox.showerror('请核对骨架尺寸和来源',str(exc),parent=win)
    ttk.Button(quick,text='填入圆形假设',command=circle).grid(row=1,column=3,padx=4)
    def load():
        path=filedialog.askopenfilename(parent=win,title='导入三维建模设置',filetypes=[('建模配置','*.json')])
        if not path:return
        try:
            value=strict_json(Path(path).read_bytes());validate_profile(value);show(value)
        except (OSError,ValueError) as exc: messagebox.showerror('无法读取建模设置',str(exc),parent=win)
    def apply():
        try: app._geometry_profile=read()
        except ValueError as exc:
            messagebox.showerror('请检查建模设置',str(exc),parent=win);return
        app.status_var.set('三维建模设置已应用，可导出或保存工程。');win.destroy()
    buttons=ttk.Frame(win,padding=8);buttons.grid(row=3,columnspan=2,sticky='ew')
    ttk.Button(buttons,text='导入设置 JSON…',command=load).pack(side='left')
    ttk.Button(buttons,text='应用到当前工程',command=apply).pack(side='right')
    ttk.Button(buttons,text='取消',command=win.destroy).pack(side='right',padx=6)
    return win


def export_package(app):
    try: config=copy.deepcopy(app._config_dict())
    except (ValueError,tk.TclError) as exc:
        messagebox.showerror('请检查当前工程',str(exc),parent=app.root);return
    dest=filedialog.asksaveasfilename(parent=app.root,title='导出三维建模数据',defaultextension='.zip',
            initialfile='T1-三维建模数据.zip',filetypes=[('变压器建模数据包','*.zip')])
    if not dest:return
    source=getattr(app,'_geometry_source',None)
    return start_export(app,dest,config,source)


def start_export(app,dest,config,source):
    from calculation_scheduler import CalculationCancelled
    win=tk.Toplevel(app.root);win.title('导出三维建模数据');win.transient(app.root);win.grab_set()
    cancel=threading.Event();messages=queue.Queue()
    progress=ttk.Label(win,text='正在冻结输入端点、解析绕组并绘制截面…',padding=20)
    progress.pack()
    ttk.Button(win,text='取消',command=cancel.set).pack(pady=(0,12))
    win.protocol('WM_DELETE_WINDOW',cancel.set)
    win.bind('<Destroy>',lambda e:cancel.set() if e.widget==win else None)
    def run():
        try:
            from design_engine.service import calculate
            from transformer_geometry import export_geometry_package
            calculated=calculate(config,analysis='endpoints',include_loop=False,include_efficiency=False,
                                 include_cross_regulation=False,cancelled=cancel.is_set)
            result=export_geometry_package(calculated,dest,config,original_bytes=source[1] if source else None,
                original_name=source[0] if source else None,cancelled=cancel.is_set)
            messages.put(('ok',result))
        except CalculationCancelled: messages.put(('cancel',None))
        except Exception as exc: messages.put(('error',str(exc)))
    def poll():
        try: status,result=messages.get_nowait()
        except queue.Empty:
            win.after(100,poll);return
        win.destroy()
        if status=='cancel': app.status_var.set('三维建模数据导出已取消。');return
        if status=='error':
            messagebox.showerror('三维建模导出失败',result,parent=app.root);return
        msg=f"已导出 {result['sections']} 个物理段、{result['bundles']} 个线束截面。"
        msg+=('已具备名义三维绕组路径。' if result['ready']['geometry_3d'] else '当前为部分数据，待补项见 missing_fields。')
        app.status_var.set(msg)
        messagebox.showinfo('三维建模数据',msg+'\n'+str(dest),parent=app.root)
    threading.Thread(target=run,daemon=True).start()
    win.after(75,poll)
    return win
