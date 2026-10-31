"""Four-event snapshot, computed off the UI thread using fixed hardware."""


def event_rows(bundle):
    rows=[]
    for case in bundle['cases']:
        if case.get('error'):
            for event in ('开通','关断'):rows.append((case['id'],event,'失败',str(case['error']),'—','—','—','—'))
            continue
        g=case['result']['semi']['switch']['gate']
        for event,suffix in (('开通','on'),('关断','off')):
            rows.append((case['id'],event,g['I_'+suffix],g['Vgp_'+suffix],g['Qgs_'+suffix],g['Qgd_'+suffix],g['Qg_th'],g['Qg_'+suffix]))
    return rows


def calculate_four(p,cancelled=None):
    from input_voltage_range import calculate_input_endpoints
    return event_rows(calculate_input_endpoints(p,include_loop=False,include_cross_regulation=False))


def show_four_cases(app):
    import tkinter as tk
    from tkinter import ttk,messagebox
    from calculation_scheduler import LatestCalculationWorker,parameter_signature
    if getattr(app,'_mos_four_dialog',None) is not None:
        try:app._mos_four_dialog.lift();return
        except tk.TclError:pass
    try:p=app.get_params()
    except Exception as exc:messagebox.showerror('四工况未计算',str(exc),parent=app.root);return
    dialog=tk.Toplevel(app.root);app._mos_four_dialog=dialog
    dialog.title('MOS 两端输入 × 开通/关断 · 独立电压/电荷结果');dialog.geometry('1100x440')
    ttk.Label(dialog,text='同一套硬件，各事件独立读取 Vgp / Qgs。Qg(th)、Qgd、总Qg若复用同一参考曲线，可以相同，不强制生成四个不同数值。',wraplength=1000,padding=12).pack(fill='x')
    frame=ttk.Frame(dialog,padding=8);frame.pack(fill='both',expand=True)
    columns=('case','event','i','v','qgs','qgd','qth','qg')
    tree=ttk.Treeview(frame,columns=columns,show='headings',height=6)
    for key,title in zip(columns,('输入工况','事件','Id / A','Vgp / V','到平台 Qgs / nC','平台段 Qgd / nC','Qg(th) / nC','总 Qg / nC')):
        tree.heading(key,text=title);tree.column(key,width=128,anchor='center')
    scrollbar=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview);tree.configure(xscrollcommand=scrollbar.set)
    scrollbar.pack(side='bottom',fill='x');tree.pack(fill='both',expand=True)
    status=tk.StringVar(value='后台核算中；修改输入会丢弃旧结果。')
    ttk.Label(dialog,textvariable=status,padding=10,wraplength=1000).pack(fill='x')
    worker=LatestCalculationWorker(cache_size=0);signature=parameter_signature(p)
    worker.submit('mos-four',p,calculate_four)
    def close(event=None):
        if event is not None and event.widget is not dialog:return
        worker.close();app._mos_four_dialog=None
        if event is None:dialog.destroy()
    dialog.protocol('WM_DELETE_WINDOW',close);dialog.bind('<Destroy>',close,add='+')
    def poll():
        if not dialog.winfo_exists():return
        try:
            if parameter_signature(app.get_params())!=signature:
                worker.invalidate();status.set('输入已变更，此窗口结果已失效。请关闭后重新核算。');return
        except Exception:worker.invalidate();status.set('输入未完成，四工况已失效。');return
        try:result=worker.results.get_nowait()
        except Exception:dialog.after(200,poll);return
        if result.error:status.set('计算失败：'+str(result.error));return
        for row in result.value:
            display=[row[0],row[1]]
            for index,value in enumerate(row[2:],2):display.append(f'{value*(1e9 if index>=4 else 1):.6g}' if isinstance(value,(int,float)) else value)
            tree.insert('','end',values=display)
        status.set('已完成四事件快照。VDD,test 是栅电荷曲线测试电压，不是 Vin；按用户选择复用参考曲线，不自动重建不同电流的 Qgd。')
        dialog.after(500,watch)
    def watch():
        if not dialog.winfo_exists():return
        try:changed=parameter_signature(app.get_params())!=signature
        except Exception:changed=True
        if changed:
            worker.invalidate()
            tree.delete(*tree.get_children())
            status.set('输入已变更，旧结果已清除。请关闭后重新核算四工况。')
        else:dialog.after(500,watch)
    dialog.after(100,poll)
