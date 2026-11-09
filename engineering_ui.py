"""Engineering review UI. Background workflows never access Tk widgets."""
import copy
import json
import math
import queue
import threading
import tkinter as tk
import weakref
from tkinter import ttk, filedialog, messagebox

from design_checks import STATE_LABELS


def number(value, unit=''):
    if value is None:
        return '未定义'
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return '启用' if value else '停用'
    if not math.isfinite(value):
        return '无有限值'
    return f'{value:.5g}'+(' '+unit if unit else '')


class Tooltip:
    """One transient hint per owner, including delayed callbacks and cleanup."""
    def __init__(self, widget, text):
        self.widget, self.text, self.popup, self.job = widget, text, None, None
        self.owner = widget.winfo_toplevel()
        if not hasattr(self.owner, '_tooltip_instances'):
            self.owner._tooltip_instances = weakref.WeakSet()
            self.owner._active_tooltips = weakref.WeakSet()
            # Child bindtags include their toplevel: clicking/scrolling anywhere
            # in the window also dismisses a pending hint. Bind once per owner.
            for sequence in ('<ButtonPress>', '<MouseWheel>', '<FocusOut>', '<Unmap>', '<Configure>'):
                self.owner.bind(sequence, lambda _event: Tooltip.hide_all(self.owner), add='+')
        self.owner._tooltip_instances.add(self)
        widget.bind('<Enter>', self.enter, add='+')
        widget.bind('<Leave>', self.leave, add='+')
        widget.bind('<ButtonPress>', self.leave, add='+')
        widget.bind('<Unmap>', self.leave, add='+')
        widget.bind('<Destroy>', self.leave, add='+')

    @staticmethod
    def hide_all(owner):
        # Configure/Unmap fires for every field during reflow. Only pending or
        # visible hints need cleanup, not the entire parameter panel each time.
        for hint in tuple(getattr(owner, '_active_tooltips', ())):
            hint.leave()

    def enter(self, _event=None):
        Tooltip.hide_all(self.owner)
        try:
            if self.widget.winfo_exists() and self.widget.winfo_ismapped():
                self.job = self.widget.after(600, self.show)
                self.owner._active_tooltips.add(self)
        except tk.TclError:
            pass

    def _can_show(self):
        """A stale after must not display on another app or hidden control."""
        try:
            if not self.widget.winfo_exists() or not self.widget.winfo_viewable():
                return False
            if not self.owner.winfo_viewable():
                return False
            focused = self.owner.focus_displayof()
            if focused is None or focused.winfo_toplevel() is not self.owner:
                return False
            x, y = self.widget.winfo_pointerxy()
            target = self.owner.winfo_containing(x, y)
            while target is not None:
                if target is self.widget:
                    return True
                target = target.master
        except tk.TclError:
            pass
        return False

    def show(self):
        # Clear the previous callback/window before replacing any references.
        Tooltip.hide_all(self.owner)
        if not self._can_show():
            return
        try:
            self.popup = tk.Toplevel(self.owner)
            self.owner._active_tooltips.add(self)
            self.popup.withdraw()
            self.popup.wm_overrideredirect(True)
            self.popup.transient(self.owner)
            self.popup.geometry(f'+{self.widget.winfo_rootx()+12}+{self.widget.winfo_rooty()+28}')
            ttk.Label(self.popup, text=self.text, wraplength=440, padding=8,
                      background='#fff8e1', foreground='#22303c').pack()
            self.popup.deiconify()
        except tk.TclError:
            self.leave()

    def leave(self, _event=None):
        self.owner._active_tooltips.discard(self)
        job, self.job = self.job, None
        popup, self.popup = self.popup, None
        if job is not None:
            try:
                self.widget.after_cancel(job)
            except tk.TclError:
                pass
        if popup is not None:
            try:
                popup.destroy()
            except tk.TclError:
                pass


class EngineeringUI:
    def _init_engineering_state(self):
        self._corner_result = self._comparison = self._baseline = None
        self._work_queue = queue.Queue()
        self._work_cancel = threading.Event()
        self._work_running = False
        self._work_poll = None

    def _build_param_filters(self, parent):
        frame = ttk.Frame(parent, padding=6); frame.pack(fill='x')
        ttk.Label(frame, text='参数搜索').pack(anchor='w')
        self.param_search = tk.StringVar()
        ttk.Entry(frame, textvariable=self.param_search).pack(fill='x', pady=4)
        # Compatibility handle for older integrations/tests only. There is no
        # basic/advanced switch and this value no longer filters any inputs.
        self.advanced_params = tk.BooleanVar(value=True)
        ttk.Button(frame, text='展开全部', command=self._expand_params).pack(side='right')
        self.param_search.trace_add('write', lambda *_: self._filter_params())

    def _expand_params(self):
        self._folded_sections.clear()
        self.param_search.set('')
        self._filter_params()

    def _fold_section(self, frame):
        if frame in self._folded_sections:
            self._folded_sections.remove(frame)
        else:
            self._folded_sections.add(frame)
        self._filter_params()

    def _filter_params(self):
        if hasattr(self, 'param_search'):
            self._filter_parameter_panel()

    def _sync_parameter_scrollregion(self):
        self._param_layout_job = None
        if not getattr(self, '_closing', False) and not getattr(self,'_param_scroll_syncing',False):
            # The scheduled pass follows geometry notifications. Do not enter
            # a nested idle loop here: that also draws every pending figure and
            # starves input/timer events during a multi-output reflow.
            canvas=self.left_canvas
            width=max(1,canvas.winfo_width())
            height=max(self.left_inner.winfo_reqheight(),canvas.winfo_height())
            # A scroll region shorter than the viewport lets Tk retain a
            # negative origin after folding: the inputs then sit below a gap.
            canvas.configure(scrollregion=(0,0,width,height))
            if self.left_inner.winfo_reqheight()<=canvas.winfo_height() or canvas.canvasy(0)<0:
                canvas.yview_moveto(0)

    def _schedule_parameter_scrollregion(self,_event=None):
        if not getattr(self,'_closing',False) and not getattr(self,'_param_scroll_syncing',False) and self._param_layout_job is None:
            # Nested pack requests may settle after the first idle callback;
            # an offscreen Canvas window then emits no Configure notification.
            self._param_layout_job=self.root.after(16,self._sync_parameter_scrollregion)

    def _tree(self, frame, columns, labels, widths=None):
        box = ttk.Frame(frame); box.pack(fill='both', expand=True, padx=6, pady=4)
        tree = ttk.Treeview(box, columns=columns, show='headings', height=10)
        for col,label,width in zip(columns,labels,widths or [120]*len(columns)):
            tree.heading(col,text=label)
            tree.column(col,width=width,minwidth=70,anchor='w')
        sy = ttk.Scrollbar(box,command=tree.yview); sy.pack(side='right',fill='y')
        sx = ttk.Scrollbar(box,orient='horizontal',command=tree.xview); sx.pack(side='bottom',fill='x')
        tree.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        tree.pack(fill='both',expand=True)
        for tag,color in [('review','#b54708'),('undefined','#a83232'),('pass','#197442'),('na','#64748b')]:
            tree.tag_configure(tag,foreground=color)
        return tree

    def _build_review_tab(self):
        nb = ttk.Notebook(self.tab_review); nb.pack(fill='both',expand=True,padx=4,pady=4)
        self.review_notebook = nb
        acceptance_frame = ttk.Frame(nb)
        nb.add(acceptance_frame, text='工程验证与验收')
        from engineering_acceptance_ui import AcceptancePanel
        self.acceptance_panel = AcceptancePanel(acceptance_frame, get_spec=self._current_spec,
            on_apply=lambda data: self._acceptance_apply(data),
            on_refresh=lambda: self._acceptance_refresh_endpoints(),
            on_import_evidence=lambda: self._acceptance_import_evidence(),
            get_range_result=lambda: self._acceptance_get_range_result(),
            get_joint_record=lambda: self._acceptance_get_joint_record(),
            get_spice_evidence=lambda: self._acceptance_get_spice_evidence())
        self.acceptance_panel.pack(fill='both', expand=True)
        check_frame, corner_frame, compare_frame = [ttk.Frame(nb) for _ in range(3)]
        for f,label in [(check_frame,'统一设计检查'),(corner_frame,'固定硬件角点'),(compare_frame,'方案 A / B 对比')]:
            nb.add(f,text=label)
        self.review_summary = tk.StringVar(value='等待首轮计算…')
        ttk.Label(check_frame,textvariable=self.review_summary,wraplength=1100,
                  padding=8,style='Margin.TLabel').pack(fill='x')
        self.review_tree = self._tree(check_frame,('name','actual','limit','state'),
                                     ('检查项','计算值','阈值 / 建议','结论'),[230,170,210,90])
        self.review_note = tk.StringVar(value='选择检查项查看依据。满足仅表示模型内满足阈值。')
        ttk.Label(check_frame,textvariable=self.review_note,wraplength=1100,padding=8).pack(fill='x')
        self.review_tree.bind('<<TreeviewSelect>>',self._review_selected)
        controls = ttk.Frame(corner_frame,padding=6); controls.pack(fill='x')
        self.corner_lo = tk.DoubleVar(value=30); self.corner_hi = tk.DoubleVar(value=30)
        self.corner_lo.trace_add('write', lambda *_: self._invalidate_workflows())
        self.corner_hi.trace_add('write', lambda *_: self._invalidate_workflows())
        for label,var in [('输入下限 / V',self.corner_lo),('输入上限 / V',self.corner_hi)]:
            ttk.Label(controls,text=label).pack(side='left',padx=4)
            ttk.Entry(controls,textvariable=var,width=8,state='readonly').pack(side='left')
        self.corner_button = ttk.Button(controls,text='分析输入端点角点',command=self._run_corners_ui)
        self.corner_button.pack(side='left',padx=8)
        ttk.Button(controls,text='取消',command=self._work_cancel.set).pack(side='left')
        ttk.Button(controls,text='使用需求输入范围',command=self._reset_corner_range).pack(side='left',padx=8)
        self.corner_status = tk.StringVar(value='输入范围与需求页一致；固定 Vin min 的磁芯、匝数、线径与补偿参数，扫描两端输入 × 10–100% 负载。')
        ttk.Label(corner_frame,textvariable=self.corner_status,wraplength=1100,padding=6).pack(fill='x')
        self.corner_progress = ttk.Progressbar(corner_frame,maximum=10); self.corner_progress.pack(fill='x',padx=6)
        self.corner_tree = self._tree(corner_frame,
            ('id','vin','load','mode','eta','vds','ripple','dt','pm','state'),
            ('角点','Vin / V','负载','模式','效率 / %','Vds / V','纹波 / mV','温升 / K','最小 PM / °','检查'),
            [75,90,75,75,100,100,110,100,110,160])
        self.corner_worst = tk.StringVar(value='最坏角点尚未计算；不自动整定、不修改当前参数。')
        ttk.Label(corner_frame,textvariable=self.corner_worst,wraplength=1100,padding=6).pack(fill='x')
        self.corner_tree.bind('<<TreeviewSelect>>',self._corner_selected)
        controls = ttk.Frame(compare_frame,padding=6); controls.pack(fill='x')
        ttk.Button(controls,text='锁定当前方案为 A',command=self._capture_baseline).pack(side='left',padx=4)
        ttk.Button(controls,text='当前设计作为 B',command=lambda:self._compare_ui(False)).pack(side='left',padx=4)
        ttk.Button(controls,text='读取配置作为 B',command=lambda:self._compare_ui(True)).pack(side='left',padx=4)
        self.compare_status = tk.StringVar(value='先锁定 A，再修改参数或读取 B 配置。不会把 B 配置写回当前设计。')
        ttk.Label(compare_frame,textvariable=self.compare_status,wraplength=1100,padding=6).pack(fill='x')
        self.compare_tree = self._tree(compare_frame,('name','a','b','delta'),
                                      ('指标 / 输入差异','方案 A','方案 B','B − A'),[240,180,180,160])
        from matplotlib.figure import Figure
        from resource_canvas import EfficientFigureCanvasTkAgg as FigureCanvasTkAgg
        self.fig_compare = Figure(figsize=(8,2.8),layout='constrained')
        self.canvas_compare = FigureCanvasTkAgg(self.fig_compare,master=compare_frame)
        self.canvas_compare.get_tk_widget().pack(fill='both',expand=True)

    def _clear_review(self, error):
        if hasattr(self,'review_tree'):
            self.review_tree.delete(*self.review_tree.get_children())
            self.review_summary.set('当前输入未成功计算：'+error)
        if hasattr(self, 'acceptance_panel'):
            self.acceptance_panel.refresh()

    def _update_review(self):
        if hasattr(self, 'acceptance_panel'):
            self.acceptance_panel.refresh()
        if not self._snapshot_valid or not self._last or not hasattr(self,'review_tree'):
            return
        checks = self._last['checks']
        self.review_tree.delete(*self.review_tree.get_children())
        for c in checks:
            self.review_tree.insert('', 'end', iid=c['id'], values=(c['name'],number(c['value'],c['unit']),
                c['comparison']+' '+number(c['limit'],c['unit']) if c['limit'] is not None else '—',
                STATE_LABELS[c['state']]), tags=(c['state'],))
        failed = sum(c['state']=='review' for c in checks)
        undefined = sum(c['state']=='undefined' for c in checks)
        p = self._last.get('calculation_params', self._last['p'])
        label = 'Vinmax' if p.get('input_voltage_case') == 'max' else 'Vinmin'
        self.review_summary.set(f'{label} = {p["V_in"]:.6g} V · 同一计算快照 · {len(checks)} 项核查 · {failed} 项需复核 · {undefined} 项未计算。模型内通过 ≠ 硬件认证。')

    def _review_selected(self, _event):
        ids = self.review_tree.selection()
        if ids and self._last:
            c = next((c for c in self._last['checks'] if c['id']==ids[0]),None)
            if c:
                self.review_note.set(c['name']+'：'+(c['note'] or '按当前输入与统一检查阈值计算。'))

    def _current_spec(self):
        p = self.get_params()
        p.update(self._rcd_parameters())
        if hasattr(self, '_winding_config'):
            winding = self._winding_config().get('winding_config') or {}
            if winding.get('window_width', 0) > 0 and winding.get('window_height', 0) > 0:
                p['winding_config'] = copy.deepcopy(winding)
        return p

    def _invalidate_workflows(self):
        # A is deliberately frozen; corners/current-B are invalidated by edits.
        try:
            current = self._current_spec()
            scan_range = (self.corner_lo.get(), self.corner_hi.get())
        except Exception:
            current, scan_range = None, None
        if self._corner_result is not None and (
                self._corner_result['base_spec'] != current or tuple(self._corner_result['v_in']) != scan_range):
            self.corner_status.set('当前输入已变化；上次角点结果已失效，请重新分析。')
            self._corner_result = None
            self.corner_tree.delete(*self.corner_tree.get_children())
            self.corner_worst.set('结果已失效。')
        if self._comparison is not None and self._comparison['context_spec'] != current:
            self.compare_status.set('A 仍已锁定；当前 B 输入已变化，请重新比较。')
            self._comparison = None
            self.compare_tree.delete(*self.compare_tree.get_children())
            self.fig_compare.clear(); self.canvas_compare.draw_idle()

    def _reset_corner_range(self):
        try:
            self._sync_corner_input_range()
            self._corner_result = None
            self.corner_tree.delete(*self.corner_tree.get_children())
            self.corner_status.set('已使用需求页输入范围；请重新分析。')
        except Exception as exc:
            messagebox.showerror('角点范围',str(exc))

    def _sync_corner_input_range(self):
        """The demand range is the single source of review endpoint voltages."""
        if not hasattr(self, 'corner_lo'):
            return
        try:
            vin = self.get_param('V_in')
            lo = self.get_param('V_in_min') if 'V_in_min' in self.params else vin
            hi = self.get_param('V_in_max') if 'V_in_max' in self.params else vin
            if not (math.isfinite(lo) and math.isfinite(hi) and 0 < lo <= hi):
                return
            for var, value in ((self.corner_lo, lo), (self.corner_hi, hi)):
                if var.get() != value:
                    var.set(value)
            if hasattr(self, 'corner_button'):
                self.corner_button.configure(text=f'分析 {5 if lo == hi else 10} 个角点')
        except (KeyError, ValueError, tk.TclError):
            pass

    def _start_work(self, kind, spec, fn, callback):
        if self._work_running:
            messagebox.showinfo('分析任务','已有分析正在运行，请等待完成或取消。'); return
        self._work_running = True
        self._work_cancel.clear()
        spec = copy.deepcopy(spec)
        self.corner_button.configure(state='disabled')
        def worker():
            try:
                result = fn()
                self._work_queue.put(('done',result))
            except Exception as exc:
                self._work_queue.put(('error',str(exc)))
        threading.Thread(target=worker,name='engineering-analysis',daemon=True).start()
        def poll():
            self._work_poll = None
            if self._closing:
                return
            while not self._work_queue.empty():
                state,data = self._work_queue.get_nowait()
                if state=='progress':
                    done,total,label = data
                    self.corner_progress.configure(maximum=total,value=done)
                    self.corner_status.set(f'正在分析 {label} · {done}/{total}，界面可继续操作。')
                    continue
                self._work_running = False
                self.corner_button.configure(state='normal')
                if state=='done' and kind=='corners' and self._work_cancel.is_set():
                    self.corner_status.set('角点分析已取消；不保留不完整结果。'); return
                if state=='error':
                    self.corner_status.set(data) if kind=='corners' else self.compare_status.set(data)
                    if not self._work_cancel.is_set(): messagebox.showerror('工程分析',data)
                    return
                try:
                    unchanged = self._current_spec()==spec
                except Exception:
                    unchanged = False
                if not unchanged:
                    self.corner_status.set('计算期间输入已变化，结果未应用，请重新分析。') if kind=='corners' else self.compare_status.set('计算期间输入已变化，结果未应用。')
                    return
                callback(data); return
            self._work_poll = self.root.after(80,poll)
        self._work_poll = self.root.after(80,poll)

    def _run_corners_ui(self):
        try:
            if self._work_running:
                messagebox.showinfo('分析任务','请等待当前分析完成。'); return
            from analysis_workflows import corners
            self._sync_corner_input_range()
            p = self._current_spec(); lo,hi = self.corner_lo.get(),self.corner_hi.get()
            self._corner_result = None; self.corner_tree.delete(*self.corner_tree.get_children())
            self.corner_status.set('正在固定标称磁件并计算角点…')
            self.corner_progress.configure(value=0)
            self._start_work('corners',p,lambda:corners(p,lo,hi,progress=lambda *data:self._work_queue.put(('progress',data)),
                            cancelled=self._work_cancel.is_set),self._show_corners)
        except Exception as exc:
            messagebox.showerror('角点分析',str(exc))

    def _show_corners(self, result):
        # Also reject a changed scan range, not just a changed power design.
        if tuple(result['v_in'])!=(self.corner_lo.get(),self.corner_hi.get()):
            self.corner_status.set('扫描范围已变化，请重新分析。'); return
        self._corner_result = result
        for c in result['corners']:
            if c['skipped']:
                vals = (c['id'],number(c['V_in']),f"{c['load_frac']*100:g}%",'无效','—','—','—','—','—',c['error'])
            else:
                vals = (c['id'],number(c['V_in']),f"{c['load_frac']*100:g}%",c['mode'],number(c['eta']*100),
                        number(c['V_sw_max']),number(c['ripple_pp']*1000),number(c['dT']),number(c['min_pm']),
                        f"{len(c['failed_checks'])} 项需复核" if c['failed_checks'] else '满足')
            self.corner_tree.insert('','end',iid=c['id'],values=vals,
                                    tags=('review' if c['skipped'] or c['failed_checks'] else 'pass',))
        summary = []
        for key,label,scale,unit in [('min_eta','最低效率',100,'%'),('max_dT','最高温升',1,'K'),
                                     ('max_ripple_pp','最大纹波',1000,'mV'),('min_pm','最小 PM',1,'°')]:
            if key in result['worst']:
                summary.append(label+' '+number(result['worst'][key]*scale,unit)+' @ '+result['worst_cases'][key]['id'])
        self.corner_worst.set('；'.join(summary))
        self.corner_status.set('角点完成。磁件、L/C、器件与补偿均固定；无效点显式列出。点击角点查看复核项。')

    def _corner_selected(self, _event):
        ids = self.corner_tree.selection()
        if ids and self._corner_result:
            c = next(c for c in self._corner_result['corners'] if c['id']==ids[0])
            details = c.get('error') or '；'.join(x['name']+'：'+STATE_LABELS[x['state']] for x in c['checks'] if x['state'] in ('review','undefined')) or '已建模检查满足阈值。'
            self.corner_status.set(c['id']+' · '+details)

    def _capture_baseline(self):
        try:
            if self._work_running:
                messagebox.showinfo('分析任务','请等待当前分析完成。'); return
            from analysis_workflows import evaluate
            p = self._current_spec()
            self._start_work('baseline',p,lambda:evaluate(p),self._show_baseline)
            self.compare_status.set('正在计算并锁定方案 A…')
        except Exception as exc:
            messagebox.showerror('方案 A',str(exc))

    def _show_baseline(self, snap):
        self._baseline = snap; self._comparison = None
        self.compare_tree.delete(*self.compare_tree.get_children())
        self.fig_compare.clear(); self.canvas_compare.draw_idle()
        self.compare_status.set('方案 A 已锁定：'+snap['op']['topology']+'。可以修改当前参数或读取配置作为 B。')

    def _compare_ui(self, from_file):
        if not self._baseline:
            messagebox.showinfo('方案对比','请先锁定方案 A。'); return
        try:
            if self._work_running:
                messagebox.showinfo('分析任务','请等待当前分析完成。'); return
            from analysis_workflows import evaluate, compare
            from design_api import load_spec
            p = self._current_spec(); b = copy.deepcopy(p); name = 'B：当前设计'
            if from_file:
                path = filedialog.askopenfilename(filetypes=[('设计配置','*.json')],title='读取方案 B，不修改当前参数')
                if not path: return
                with open(path,encoding='utf-8-sig') as f: b = load_spec(json.load(f))
                from pathlib import Path
                name = 'B：'+Path(path).stem
            self._comparison = None
            self.compare_tree.delete(*self.compare_tree.get_children())
            self.fig_compare.clear(); self.canvas_compare.draw_idle()
            baseline = copy.deepcopy(self._baseline)
            def calculate():
                result = compare(baseline,evaluate(b),('A：锁定快照',name))
                result['source'] = 'file' if from_file else 'current'
                result['context_spec'] = copy.deepcopy(p)
                return result
            self._start_work('compare',p,calculate,self._show_comparison)
            self.compare_status.set('正在计算方案 B 并比较…')
        except Exception as exc:
            messagebox.showerror('方案对比',str(exc))

    def _show_comparison(self, result):
        self._comparison = result
        self.compare_tree.delete(*self.compare_tree.get_children())
        for row in result['metrics']:
            unit = row['unit']
            self.compare_tree.insert('','end',values=(row['name'],number(row['a'],unit),number(row['b'],unit),
                number(row['delta'],'百分点' if unit=='%' else unit)))
        for diff in result['differences']:
            self.compare_tree.insert('','end',values=('输入：'+diff['key'],number(diff['a']),number(diff['b']),'—'))
        for snap,label in [(result['a'],'A'),(result['b'],'B')]:
            failed = [c['name'] for c in snap['checks'] if c['state'] in ('review','undefined')]
            self.compare_tree.insert('','end',values=(label+' 需复核', '；'.join(failed),'',''),tags=('review',))
        self.compare_status.set('同输入 / 输出 / 功率需求，可比较；差值 B − A，不自动判定优劣。' if result['same_requirements'] else
                                '注意：A / B 电路需求不同，指标不可直接作为方案优劣结论。')
        self.fig_compare.clear(); axes = self.fig_compare.subplots(1,2)
        for snap,label in [(result['a'],'A'),(result['b'],'B')]:
            loop = snap['res'].get('loop')
            if loop:
                import numpy as np
                axes[0].semilogx(loop['f'],20*np.log10(np.maximum(abs(loop['gains'][2]),1e-300)),label=label)
                axes[1].semilogx(loop['f'],loop['phases'][2],label=label)
        axes[0].axhline(0,color='#999',lw=.7); axes[1].axhline(-180,color='#999',lw=.7)
        for ax,ylabel in zip(axes,('开环增益 / dB','开环相位 / °')):
            ax.set(xlabel='频率 / Hz',ylabel=ylabel); ax.grid(alpha=.2)
            if ax.get_legend_handles_labels()[0]: ax.legend()
        self.canvas_compare.draw_idle()
