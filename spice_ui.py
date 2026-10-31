"""Grouped controller settings and owned simulation/comparison operations."""
import copy
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from spice_export import SETTINGS,CHOICES,setting_group,ordered_setting_keys,normalize_settings,mp6005_preset,export_project


def comparison_feedback(result):
    """A diagnostic report is not a successfully simulated comparison."""
    counts=(f"瞬态完成 {result['successful']}/{result['total']}；"
        f"有效 FRA {result['fra_successful']}/{result['fra_total']}；"
        f"完整交叉调整率 {result['cross_successful']}/{result['cross_total']}。\n")
    if not result['successful']:
        return 'warning','仿真未完成','所有工况均未完成，已保存诊断报告与工程 ZIP。\n'+counts+'报告中没有有效仿真对比数据，请查看各工况日志与失败原因。\n'
    if result['incomplete']:
        return 'warning','对比部分完成','已保存报告与同名工程 ZIP。\n'+counts+'存在未完成或待复核项目，请查看报告状态和原因。\n'
    return 'info','对比已完成','Word 报告与同名仿真工程 ZIP 已输出。\n'+counts


def open_export_dialog(parent,parameters,apply_settings,*,get_parameters=None,initial_tab=None):
    qr=parameters.get('topology')=='QR-FLYBACK'
    forward=parameters.get('topology')=='ACF-FORWARD'
    noniso=parameters.get('topology') in ('BUCK','BOOST')
    from nonisolated import profile,preset,is_enabled,reference_settings
    if noniso and not is_enabled(parameters):
        parameters=copy.deepcopy(parameters)
        parameters['spice_config']=preset(profile(parameters)['id'])
    from acf_spice import preset as acf_preset
    from qr_spice_settings import applicable_keys,l6565_preset
    keys=applicable_keys(parameters.get('topology'))
    if parameters.get('parasitic_config'):
        keys=[k for k in keys if k not in ('diode_cj_pf','qr_cds_pf')]
    if parameters.get('topology') not in ('FLYBACK','QR-FLYBACK','ACF-FORWARD','BUCK','BOOST') or parameters.get('feedback_mode','SSR')!='SSR':
        messagebox.showinfo('LTspice 闭环','支持固定频率反激、有源钳位正激 SSR 与单路 QR 反激 SSR。',parent=parent);return
    window=tk.Toplevel(parent);window.title('通用电源控制器配置与仿真对比')
    window.geometry(f'{min(1580,parent.winfo_screenwidth()-60)}x{min(920,parent.winfo_screenheight()-100)}');window.transient(parent)
    window.minsize(1000,620)
    window.columnconfigure(0,weight=1);window.rowconfigure(2,weight=1)
    ttk.Label(window,text=profile(parameters)['name'] if noniso else '准谐振反激 · L6565 逻辑参考 / ZCD / CS' if qr else '有源钳位正激 · MP6005 / GATE / SYNC / 死区' if forward else '反激控制器 · 频率 / 软启动 / Vcs / 短路逻辑',font=('',15,'bold')).grid(row=0,column=0,sticky='w',padx=14,pady=12)
    toolbar=ttk.Frame(window,padding=(14,0));toolbar.grid(row=1,column=0,sticky='ew')
    settings=normalize_settings(parameters.get('spice_config'));variables={};groups={};traces=[]
    body=ttk.Panedwindow(window,orient='horizontal');body.grid(row=2,column=0,sticky='nsew',padx=14,pady=10)
    left=ttk.Frame(body,width=780);left.columnconfigure(0,weight=1);left.rowconfigure(0,weight=1)
    ttk.Style(window).configure('Controller.TNotebook.Tab',font=('',10),padding=(6,7))
    notebook=ttk.Notebook(left,style='Controller.TNotebook');notebook.grid(row=0,column=0,sticky='nsew')
    from spice_logic_ui import ControllerLogicPanel
    logic=ControllerLogicPanel(body,values=lambda:{k:v.get() for k,v in variables.items()},design=parameters)
    body.add(left,weight=6);body.add(logic,weight=5)
    from scrollable_results import ScrollableResults
    for group in dict.fromkeys(setting_group(k) for k in keys):
        page=ttk.Frame(notebook);notebook.add(page,text=group)
        scroll=ScrollableResults(page);scroll.pack(fill='both',expand=True)
        scroll.content.columnconfigure(1,weight=1)
        groups[group]=[scroll.content,0,page]
    for key in keys:
        _,lo,hi,label,unit=SETTINGS[key]
        form,index,_=groups[setting_group(key)];groups[setting_group(key)][1]+=1
        row,col=index,0
        ttk.Label(form,text=label+(' / '+unit if unit else ''),wraplength=320).grid(row=row,column=col,sticky='w',padx=(8,10),pady=10)
        variable=tk.StringVar(value=f'{settings[key]:g}');variables[key]=variable
        if key in CHOICES:
            labels=[f'{value} · {text}' for value,text in CHOICES[key].items()]
            variable.set(next(s for s in labels if s.startswith(str(int(settings[key]))+' ·')))
            widget=ttk.Combobox(form,textvariable=variable,values=labels,state='readonly',width=29)
        else:widget=ttk.Entry(form,textvariable=variable,width=20)
        widget.grid(row=row,column=col+1,sticky='ew',padx=(0,18),pady=10)
        widget.bind('<FocusIn>',lambda _e,k=key:logic.select(k),add='+')
        traces.append((variable,variable.trace_add('write',lambda *_:logic.refresh())))
    def remove_traces(event):
        if event.widget is window:
            for variable,trace in traces:
                try:variable.trace_remove('write',trace)
                except tk.TclError:pass
            traces.clear()
    window.bind('<Destroy>',remove_traces,add='+')
    def show_group(_event=None):
        group=notebook.tab(notebook.select(),'text')
        logic.select(next(k for k in keys if setting_group(k)==group))
    notebook.bind('<<NotebookTabChanged>>',show_group,add='+')
    if initial_tab in groups:notebook.select(groups[initial_tab][2])
    def read():return normalize_settings(dict(settings,**{k:float(v.get().split(' ·')[0]) for k,v in variables.items()}))
    def put(value):
        for key,number in value.items():
            if key in variables:variables[key].set((str(int(number))+' · '+CHOICES[key][int(number)]) if key in CHOICES else f'{number:g}')
    def apply_only():
        try:
            apply_settings(read())
            status.set('参数已应用；更换原型后请重新检查环路整定。仅导出工程不运行仿真；对比报告会运行 LTspice。')
        except (ValueError,tk.TclError) as exc:messagebox.showerror('请检查控制器参数',str(exc),parent=window)
    def fill_reference():
        try:
            chosen=read()
            if noniso:
                number=int(chosen['niso_profile']) or profile(parameters)['id']
                put(reference_settings(number,chosen))
            elif qr:
                put(l6565_preset())
            elif forward:
                put(acf_preset())
            else:
                put(mp6005_preset())
            status.set('已填入控制器参考值；保留 DCR、软启动、补偿与测试设置。请应用到计算器。' if noniso else '已填入参考值，请应用到计算器。')
        except (ValueError,tk.TclError) as exc:messagebox.showerror('请检查控制器参数',str(exc),parent=window)
    ttk.Button(toolbar,text='应用到计算器',command=apply_only).pack(side='right')
    ttk.Button(toolbar,text='填入控制器参考值' if noniso else '填入 L6565 QR 参考配置' if qr else '填入 MP6005 正激参考配置' if forward else '填入 MP6005 SSR 参考配置',command=fill_reference).pack(side='left')
    ttk.Button(toolbar,text='恢复全部默认' if noniso else '恢复 QR 参考默认' if qr else '恢复通用默认',command=lambda:put(preset(profile(parameters)['id']) if noniso else l6565_preset() if qr else normalize_settings())).pack(side='left',padx=8)
    ttk.Label(toolbar,text='原创可配置模型，不含独立原厂模型验证' if noniso else 'ZCD 事件驱动；不是 L6565 完整硅模型' if qr else '参考值可改；不是 MP6005 完整芯片模型',style='Muted.TLabel').pack(side='left',padx=10)
    if parameters.get('parasitic_config'):
        ttk.Label(toolbar,text='Coss / Cj 请在左侧“寄生参数与吸收”统一修改',style='Muted.TLabel').pack(side='left')
    from spice_runtime import find_ltspice,set_ltspice
    executable=tk.StringVar(value=find_ltspice() or '尚未检测到 LTspice')
    runtime=ttk.Frame(window,padding=(14,0));runtime.grid(row=3,column=0,sticky='ew')
    ttk.Label(runtime,textvariable=executable,wraplength=830).pack(side='left',fill='x',expand=True)
    def choose():
        filename=filedialog.askopenfilename(parent=window,title='选择 LTspice.exe',filetypes=[('LTspice 程序','*.exe')])
        if not filename:return
        try:set_ltspice(filename);executable.set(filename)
        except ValueError as exc:messagebox.showerror('LTspice 路径',str(exc),parent=window)
    ttk.Button(runtime,text='选择 LTspice.exe…',command=choose).pack(side='right')
    ttk.Label(window,text=('单路无交叉调整率。默认快速闭环不验证结电容尖峰；LM5022 限流包含斜坡。Boost 关闭 MOS 不会切断输入至输出的短路通路。' if noniso else 'QR：f_sw 为设计频率上限；ZCD 决定实际周期。异常 CS 锁存至 VCC 欠压；理想供电不模拟自动打嗝。' if qr else 'Vcs 为原始采样端阈值，实际峰值含消隐与延时超调。保护后重启会复位软启动；340 ms 打嗝若超过观察时间，不宣称已观察到重启。'),wraplength=1040).grid(row=4,column=0,sticky='w',padx=14,pady=8)
    status=tk.StringVar(value='已加载示例时可直接导出。仅导出 ASC 工程不运行仿真；运行对比报告会依次仿真输入端点及 FRA，可取消。')
    bar=ttk.Frame(window,padding=14);bar.grid(row=5,column=0,sticky='ew')
    ttk.Label(bar,textvariable=status,wraplength=490).pack(side='left',fill='x',expand=True)
    cancellation=threading.Event()
    def start(compare=False):
        try:chosen=read();p=copy.deepcopy(get_parameters() if get_parameters else parameters)
        except (ValueError,tk.TclError) as exc:messagebox.showerror('请检查设置',str(exc),parent=window);return
        if compare and not find_ltspice():messagebox.showerror('尚未检测到 LTspice','请先选择 LTspice.exe。',parent=window);return
        path=filedialog.asksaveasfilename(parent=window,title='仿真与设计计算对比报告' if compare else '导出 LTspice 工程',
            defaultextension='.docx' if compare else '.zip',filetypes=[('Word 对比报告','*.docx')] if compare else [('LTspice 工程','*.zip')],
            initialfile='仿真与设计计算对比报告.docx' if compare else parameters['topology']+'_LTspice.zip' if noniso else '有源钳位正激_LTspice.zip' if forward else '反激闭环_LTspice.zip')
        if not path:return
        apply_settings(chosen);p['spice_config']=chosen;cancellation.clear()
        for button in (export_button,compare_button):button.configure(state='disabled')
        cancel_button.configure(state='normal');latest=['正在后台准备…'];status.set(latest[0])
        started=time.monotonic()
        executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='spice-operation')
        def operation():
            if not compare:return export_project(path,p)
            from design_engine.service import calculate_parameters
            from spice_runtime import compare_design
            run=calculate_parameters(p,analysis='endpoints',include_loop=False,include_cross_regulation=False,cancelled=cancellation.is_set)
            return compare_design(run,path,cancelled=cancellation.is_set,progress=lambda d,t,label:latest.__setitem__(0,f'{d}/{t} '+label))
        future=executor.submit(operation)
        def poll():
            if not future.done():
                if window.winfo_exists():status.set(latest[0]+f' · 已用时 {int(time.monotonic()-started)} s')
                if parent.winfo_exists():parent.after(150,poll)
                return
            executor.shutdown(wait=False)
            if not window.winfo_exists():return
            for button in (export_button,compare_button):button.configure(state='normal')
            cancel_button.configure(state='disabled')
            try:
                result=future.result()
                if compare:
                    level,title,message=comparison_feedback(result)
                    status.set(title+'：'+str(path))
                    (messagebox.showwarning if level=='warning' else messagebox.showinfo)(title,message+str(path),parent=window)
                else:
                    status.set('工程已导出：'+str(path))
                    messagebox.showinfo('工程已导出','使用 LTspice 打开 Flyback.asc，可看到功率级与控制器连接。\n'+str(path),parent=window)
            except Exception as exc:status.set('操作未完成');messagebox.showerror('仿真与导出',str(exc) or '已取消',parent=window)
        parent.after(150,poll)
    export_button=ttk.Button(bar,text='导出 ASC 工程…',command=lambda:start(False));export_button.pack(side='left',padx=4)
    compare_button=ttk.Button(bar,text='运行并导出对比报告…',command=lambda:start(True));compare_button.pack(side='left',padx=4)
    cancel_button=ttk.Button(bar,text='取消',command=cancellation.set,state='disabled');cancel_button.pack(side='left',padx=4)
    def close():cancellation.set();window.destroy()
    window.protocol('WM_DELETE_WINDOW',close)
