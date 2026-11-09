"""On-demand background load-corner scans; no Tk access in numerical jobs."""
import queue
import tkinter as tk
from tkinter import ttk


class CrossRegulationUI:
    def _build_cross_regulation(self, parent):
        self._cross_progress=queue.SimpleQueue()
        self._cross_result=None
        self._cross_progress_token=None
        self.cross_note=tk.StringVar(value='先在左侧设置各路最大/最小输出功率，再按需扫描；导出报告会自动扫描。旧文件最小值默认等于最大值，未假定轻载比例。')
        note_frame=ttk.Frame(parent);note_frame.pack(fill='x',padx=8,pady=8)
        note_text=tk.Text(note_frame,height=2,wrap='word',font=('Microsoft YaHei',11),relief='flat')
        note_scroll=ttk.Scrollbar(note_frame,command=note_text.yview)
        note_scroll.pack(side='right',fill='y')
        note_text.configure(yscrollcommand=note_scroll.set)
        note_text.pack(fill='x',expand=True)
        def show_status(*_):
            note_text.configure(state='normal');note_text.delete('1.0','end')
            note_text.insert('1.0',self.cross_note.get());note_text.configure(state='disabled')
        self.cross_note.trace_add('write',show_status);show_status()
        actions=ttk.Frame(parent);actions.pack(fill='x',padx=8)
        self.cross_button=ttk.Button(actions,text='扫描最小/最大负载组合',command=self._start_cross_regulation)
        self.cross_button.pack(side='left')
        ttk.Button(actions,text='取消扫描',command=self._cancel_cross_regulation).pack(side='left',padx=8)
        body=ttk.Panedwindow(parent,orient='vertical')
        cols=('rail','ref','range','deviation','span','cross','min','max')
        summary_frame=ttk.Frame(body)
        body.add(summary_frame,weight=1)
        self.cross_tree=ttk.Treeview(summary_frame,columns=cols,show='headings',height=3)
        for key,label,width in zip(cols,('输出','参考 / V','观察电压范围 / V','偏差范围 / %','包络跨度 / %','纯交叉跨度 / %','最低角点','最高角点'),(100,100,190,180,130,140,100,100)):
            self.cross_tree.heading(key,text=label);self.cross_tree.column(key,width=width,minwidth=70)
        summary_scroll=ttk.Scrollbar(summary_frame,command=self.cross_tree.yview)
        summary_scroll.pack(side='right',fill='y')
        self.cross_tree.configure(yscrollcommand=summary_scroll.set)
        bar=ttk.Scrollbar(summary_frame,orient='horizontal',command=self.cross_tree.xview)
        bar.pack(side='bottom',fill='x')
        self.cross_tree.pack(fill='both',expand=True)
        self.cross_tree.configure(xscrollcommand=bar.set)
        frame=ttk.Frame(body);body.add(frame,weight=3)
        cols=('id','vin','loads','voltages','frequency','state')
        self.cross_cases=ttk.Treeview(frame,columns=cols,show='headings',height=6)
        for key,label,width in zip(cols,('角点','Vin / V','各路设定负载 / W','各路解算直流电压 / V','实际频率 / Hz','状态'),(70,85,300,300,125,150)):
            self.cross_cases.heading(key,text=label);self.cross_cases.column(key,width=width,minwidth=65)
        self.cross_cases.grid(row=0,column=0,sticky='nsew')
        ybar=ttk.Scrollbar(frame,command=self.cross_cases.yview);ybar.grid(row=0,column=1,sticky='ns')
        xbar=ttk.Scrollbar(frame,orient='horizontal',command=self.cross_cases.xview);xbar.grid(row=1,column=0,sticky='ew')
        self.cross_cases.configure(yscrollcommand=ybar.set,xscrollcommand=xbar.set)
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        self.cross_detail=tk.StringVar(value='范围是输入端点与负载角点的直流平均电压，不含开关纹波或动态过冲；失败角点不会被当作 0 V。选择明细查看完整状态。')
        detail_frame=ttk.Frame(parent)
        # Reserve a bounded, scrollable explanation area instead of allowing
        # a long model note to push the case table outside a small window.
        detail_frame.pack(side='bottom',fill='x',padx=8,pady=8)
        self.cross_detail_text=tk.Text(detail_frame,height=3,wrap='word',font=('Microsoft YaHei',11),relief='flat')
        detail_scroll=ttk.Scrollbar(detail_frame,command=self.cross_detail_text.yview)
        detail_scroll.pack(side='right',fill='y')
        self.cross_detail_text.configure(yscrollcommand=detail_scroll.set)
        self.cross_detail_text.pack(fill='x',expand=True)
        def show_note(*_):
            self.cross_detail_text.configure(state='normal')
            self.cross_detail_text.delete('1.0','end')
            self.cross_detail_text.insert('1.0',self.cross_detail.get())
            self.cross_detail_text.configure(state='disabled')
        self.cross_detail.trace_add('write',show_note)
        show_note()
        body.pack(fill='both',expand=True,padx=8,pady=8)
        self.cross_cases.bind('<<TreeviewSelect>>',self._select_cross_case)
        # Status/model explanations scroll instead of pushing the table off
        # a small viewport. Summaries retain every output through their scroll.
        def fit_cross_view(event):
            # Keep real corner rows reachable on a small window. All output
            # summaries remain available through their own vertical scroll.
            rows=1 if event.height<460 else 2 if event.height<650 else 3
            if int(self.cross_tree.cget('height'))!=rows:
                self.cross_tree.configure(height=rows)
        parent.bind('<Configure>',fit_cross_view,add='+')

    def _mark_cross_regulation_stale(self):
        if not hasattr(self,'cross_note'):return
        self._cross_result=None
        self._cross_progress_token=None
        self.cross_button.configure(state='normal')
        self.cross_tree.delete(*self.cross_tree.get_children())
        self.cross_cases.delete(*self.cross_cases.get_children())
        self.cross_note.set('待扫描：参数变化后旧结果已清除。请在左侧填写实际最小功耗，再扫描负载组合。')
        self.cross_detail.set('尚无当前参数的扫描结果。电压范围为离散角点的直流平均值，不包含开关纹波或动态过冲。')

    def _start_cross_regulation(self):
        if not self._snapshot_valid or not self._last:
            self.cross_note.set('请等待当前参数计算完成，再扫描交叉调整率。');return
        from cross_regulation import scan_cross_regulation
        self._mark_cross_regulation_stale()
        self.cross_button.configure(state='disabled')
        token=self._cross_progress_token=object()
        request=dict(p=self._last['p'],calculation_p=self._last.get('calculation_params',self._last['p']))
        def calculate(snapshot,cancelled):
            return scan_cross_regulation(snapshot['calculation_p'],cancelled=cancelled,
                progress=lambda done,total,cid:self._cross_progress.put((token,done,total,cid)))
        self._calculation_worker.submit('cross_regulation',request,calculate,cache=True)
        self.cross_note.set('后台扫描中，可继续操作；编辑参数会取消此扫描。最多 6 路、每个输入端点 64 种负载组合。')
        self._ensure_calculation_poll()

    def _cancel_cross_regulation(self):
        if str(self.cross_button.cget('state'))=='disabled':
            self._calculation_worker.invalidate()
            self._mark_cross_regulation_stale()
            self.cross_note.set('扫描已取消；未保留不完整的旧任务结果。')

    def _drain_cross_progress(self):
        if not hasattr(self,'_cross_progress'):return
        last=None
        while not self._cross_progress.empty():
            item=self._cross_progress.get_nowait()
            if item[0] is self._cross_progress_token:last=item[1:]
        if last and str(self.cross_button.cget('state'))=='disabled':
            self.cross_note.set(f'后台扫描 {last[0]} / {last[1]}，当前 {last[2]}。可取消，修改参数将作废本次结果。')

    def _finish_cross_regulation(self, job):
        self.cross_button.configure(state='normal')
        if not self._snapshot_valid or not self._last or job.parameters['p']!=self._last['p']:return
        if job.error is not None:
            self.cross_note.set('扫描失败：'+str(job.error));return
        data=self._cross_result=job.value
        if not data.get('supported'):
            self.cross_note.set('未计算：'+str(data.get('error')));return
        from cross_regulation import load_label
        self.cross_note.set(f"有效角点 {data['successful_cases']} / {data['total_cases']}。"+
            ('离散扫描完成；连续负载区间仍需复核。' if data['complete'] else '存在空载/失败角点，以下仅是观察范围，不是完整电压上下限。')+
            '包络含本路和其他路负载变化；纯交叉跨度固定本路负载及 Vin，只改变其他路。')
        if not data.get('varied_outputs'):
            self.cross_note.set(self.cross_note.get()+'所有最小值等于最大值，未覆盖轻载；0 跨度不代表全负载为 0。')
        for row in data['summary']:
            solved=row['V_min'] is not None
            self.cross_tree.insert('','end',values=(f'OUT{row["id"]}'+(' ★' if row['feedback'] else ''),f'{row["V_reference"]:g}',
                f'{row["V_min"]:.5g} – {row["V_max"]:.5g}' if solved else '未求解',
                f'{row["deviation_min_pct"]:+.3g} – {row["deviation_max_pct"]:+.3g}' if solved else '—',
                f'{row["span_pct"]:.3g}' if solved else '—',f'{row["cross_only_pct"]:.3g}' if solved else '—',
                row['min_case'] or '—',row['max_case'] or '—'))
        for c in data['cases']:
            self.cross_cases.insert('','end',iid=c['id'],values=(c['id'],f'{c["V_in"]:g}',load_label(c),
                '；'.join(f'OUT{i+1}={v:.5g}' for i,v in enumerate(c['voltages'])) if c['voltages'] else '未求解',
                f'{c["f_sw"]:.5g}' if c.get('f_sw') else '—',
                ('已求解；频率超限' if (c.get('qr_timing') or {}).get('design_frequency_limit_exceeded') else '已求解') if c['status']=='ok' else '未计算/失败'))
        self.cross_detail.set(data['note'])

    def _select_cross_case(self,_event=None):
        selected=self.cross_cases.selection()
        if not selected or not self._cross_result:return
        case=next(c for c in self._cross_result['cases'] if c['id']==selected[0])
        from cross_regulation import load_label
        self.cross_detail.set(f'{case["id"]} · Vin={case["V_in"]:g}V · '+load_label(case)+'\n'+
            (case['error'] or f'周期电流/电荷平衡已验证，归一化残差 {case["residual"]:.3g}；各路实际功率并不等于恒阻负载设定功耗。'))
        if case.get('qr_timing'):
            self.cross_detail.set(self.cross_detail.get()+'\nQR：'+
                str(case['qr_timing'].get('timing_policy','矩阵退磁与离散谷底时序'))+
                (f'；该角点实际频率 {case["f_sw"]:.6g} Hz。' if case.get('f_sw') else ''))
            if case['qr_timing'].get('design_frequency_limit_exceeded'):
                self.cross_detail.set(self.cross_detail.get()+f' 频率超过设计上限 {case["qr_timing"]["design_frequency_limit_hz"]:g} Hz，需调整硬件/控制或复核；数值收敛不表示选型合格。')
            model=case['qr_timing']
            if model.get('rcd_hardware'):
                self.cross_detail.set(self.cross_detail.get()+f'\n固定RCD平均钳位 {model["clamp_voltage"]:.5g} V；'
                    f'R={model["rcd_hardware"]["R_ohm"]:.5g} Ω，C={model["rcd_hardware"]["C_F"]:.5g} F；'
                    f'Q/C相对纹波上界约 {model["rcd_ripple_upper_relative"]*100:.3g}%。')
