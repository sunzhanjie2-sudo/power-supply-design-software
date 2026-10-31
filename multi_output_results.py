"""Scrollable GUI presentation of every output in one computed snapshot.

No electrical calculation is performed here. Shared devices and input caps
belong to the overview; branch cards consume only the matching branch result.
"""
import tkinter as tk
from tkinter import ttk

from matplotlib.figure import Figure
from matplotlib.backend_bases import FigureCanvasBase
from resource_canvas import EfficientFigureCanvasTkAgg as FigureCanvasTkAgg

from semiconductor import device_stress
from scrollable_results import ScrollableResults


class MultiOutputResultsUI:
    @staticmethod
    def _result_label(parent, **options):
        options.setdefault('wraplength', 900)
        options.setdefault('justify', 'left')
        label = ttk.Label(parent, **options)
        label.bind('<Configure>', lambda event: label.configure(wraplength=max(160, event.width-12)))
        return label

    def _build_results_scroll(self, parent, name):
        if not hasattr(self, '_result_scrolls'):
            self._result_scrolls = {}
            self._output_result_cards = {}
            self._output_result_hosts = {}
            self._output_result_notes = {}
            self._result_redraw_jobs = {}
            self._result_layout_modes = {}
            self._result_overview_heights = {}
            self._result_size_jobs = {}
            self._result_card_jobs = {}
        view = ScrollableResults(parent)
        view.pack(fill='both', expand=True)
        self._result_scrolls[name] = view
        self._output_result_cards[name] = {}
        # Tk considers clipped children mapped too. Do not use a card's Map
        # state as a proxy for visibility: use the scroll viewport below.
        view.canvas.configure(yscrollcommand=lambda first, last, n=name:
                              self._output_result_scrolled(n, first, last))
        view.canvas.bind('<Configure>', lambda event, n=name:
                         self._schedule_output_result_viewport(n), add='+')
        view.bind('<Map>', lambda event, n=name, v=view:
                  self._schedule_output_result_viewport(n) if event.widget is v else None, add='+')
        view.bind('<Unmap>', lambda event, n=name, v=view:
                  self._hide_output_result_page(n) if event.widget is v else None, add='+')
        view.bind('<Destroy>', lambda event, n=name, v=view:
                  self._cancel_output_result_viewport(n) if event.widget is v else None, add='+')
        return view.content

    def _output_result_scrolled(self, kind, first, last):
        self._result_scrolls[kind].scrollbar.set(first, last)
        self._schedule_output_result_viewport(kind)

    def _cancel_output_result_viewport(self, kind):
        job = self._result_card_jobs.pop(kind, None)
        if job:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass

    def _schedule_output_result_viewport(self, kind, delay=90):
        if (not getattr(self, '_lazy_output_cards', False)
                or getattr(self, '_closing', False)):
            return
        self._cancel_output_result_viewport(kind)
        if not self._result_scrolls[kind].winfo_viewable():
            return
        self._result_card_jobs[kind] = self.root.after(
            delay, lambda: self._refresh_output_result_viewport(kind))

    def _hide_output_result_page(self, kind):
        self._cancel_output_result_viewport(kind)
        if getattr(self, '_lazy_output_cards', False):
            for card in self._output_result_cards[kind].values():
                self._release_output_result_canvas(card)

    def _output_result_card_visible(self, card):
        view = self._result_scrolls[card['kind']]
        if not view.winfo_viewable() or not card['frame'].winfo_viewable():
            return False
        top = view.canvas.winfo_rooty()
        bottom = top + view.canvas.winfo_height()
        plot_top = card['plot'].winfo_rooty()
        return plot_top < bottom and plot_top + card['plot'].winfo_height() > top

    def _refresh_output_result_viewport(self, kind):
        """Draw one visible rail per callback; clipped cards own no pixel buffer."""
        self._result_card_jobs.pop(kind, None)
        if (getattr(self, '_closing', False)
                or not getattr(self, '_lazy_output_cards', False)):
            return
        view = self._result_scrolls[kind]
        cards = list(self._output_result_cards[kind].values())
        if not view.winfo_viewable():
            self._hide_output_result_page(kind)
            return
        # Fix all reserved heights before intersecting the viewport, including
        # offscreen cards. This keeps OUT6 reachable on a narrow display.
        resized = False
        for card in cards:
            if card['branch'] is not None:
                resized |= self._size_output_result_card(card)
        if resized:
            view.sync()
        for card in cards:
            if not self._output_result_card_visible(card):
                self._release_output_result_canvas(card)
        if not getattr(self, '_snapshot_valid', True):
            return
        for card in cards:
            if (card['branch'] is not None and self._output_result_card_visible(card)
                    and (card['canvas'] is None or card['dirty'])):
                self._render_output_result_card(card)
                # Yield to input and paint events between expensive Matplotlib
                # layouts instead of drawing a six-output burst.
                self._schedule_output_result_viewport(kind, delay=15)
                break

    def _bind_result_overview(self, name, canvas):
        widget = canvas.get_tk_widget()
        widget.bind('<Configure>', lambda event: self._schedule_result_redraw(name, event.width), add='+')
        widget.bind('<Destroy>', lambda event: self._cancel_result_redraw(name), add='+')
        view=self._result_scrolls[name]
        for target in (view.canvas,view.content):
            target.bind('<Configure>',lambda event,n=name:self._schedule_result_size(n),add='+')

    def _schedule_result_size(self,name):
        if self._closing or name in self._result_size_jobs:return
        def resize():
            self._result_size_jobs.pop(name,None)
            view=self._result_scrolls[name]
            if self._closing or not view.winfo_viewable():return
            widget=getattr(self,'canvas_'+name).get_tk_widget()
            minimum=self._result_overview_heights.get(name,widget.winfo_reqheight())
            # Expand only the overview. Keep the content frame's natural
            # height so newly added rail cards can still request more space.
            other=max(0,view.content.winfo_reqheight()-widget.winfo_reqheight())
            height=minimum if self._output_result_cards[name] else max(minimum,view.canvas.winfo_height()-other)
            if abs(widget.winfo_reqheight()-height)>1:widget.configure(height=height)
        self._result_size_jobs[name]=self.root.after_idle(resize)

    def _scale_result_text(self,name,figure=None):
        figure=figure if figure is not None else getattr(self,'fig_'+name)
        scale=max(.85,getattr(self,'_font_k',14/13)*13/14)
        for ax in figure.axes:
            if name=='power' and ' · Id=' in ax.title.get_text():
                ax.set_title(ax.title.get_text().replace(' · ','\n',1))
            if name=='power' and ax.title.get_text().startswith('Q1 MOS') and scale>1.4:
                # Keep all t1–t8 values readable at large type sizes instead
                # of shrinking the text or letting adjacent durations overlap.
                labels=[label.get_text().replace(' ns','\nns') for label in ax.get_xticklabels()]
                if labels:ax.set_xticks(ax.get_xticks(),labels)
                ax.set_xlabel(ax.get_xlabel().replace('；','；\n'))
                for label in ax.texts:label.set_text(label.get_text().replace(' ns','\nns'))
            ax.title.set_fontsize(10*scale)
            ax.xaxis.label.set_fontsize(8*scale);ax.yaxis.label.set_fontsize(8*scale)
            ax.tick_params(labelsize=8*scale)
            for label in ax.texts:label.set_fontsize(8*scale)
            legend=ax.get_legend()
            if legend:
                for label in legend.get_texts():label.set_fontsize(8*scale)

    def _cancel_result_redraw(self, name):
        job=self._result_size_jobs.pop(name,None)
        if job:
            try:self.root.after_cancel(job)
            except tk.TclError:pass
        job = self._result_redraw_jobs.pop(name, None)
        if job:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass

    def _schedule_result_redraw(self, name, width):
        if width <= 1 or not self._result_scrolls[name].winfo_viewable():
            return
        mode=self._result_overview_mode(name,width)
        if self._result_layout_modes.get(name) == mode:
            return
        self._result_layout_modes[name] = mode
        self._cancel_result_redraw(name)
        def redraw():
            self._result_redraw_jobs.pop(name, None)
            if self._closing or not self._snapshot_valid or self._last is None:
                return
            result = self._last
            if name == 'power':
                self._update_power(result['op'], result['wf'], result['res'], result['p'])
            elif name == 'cap':
                self._update_cap(result['op'], result['p'], result['res'])
            else:
                self._update_stress(result['op'], result['res'])
        self._result_redraw_jobs[name] = self.root.after_idle(redraw)

    def _result_overview_mode(self,name,width):
        scale=max(1,self._font_k*13/20)
        if name=='power':
            columns=3 if width>=1050*scale else 2 if width>=720*scale else 1
            return (6//columns,columns)
        return width<720*scale

    def _prepare_result_overview(self, name):
        canvas = self._result_scrolls[name].canvas
        width = canvas.winfo_width()
        if width <= 1:
            width = max(900, self.nb.winfo_width()-24)
        scale=max(1,self._font_k*13/20)
        mode=self._result_overview_mode(name,width)
        compact=mode==(6,1) if name=='power' else mode
        self._result_layout_modes[name] = mode
        self._cancel_result_redraw(name)
        figure = getattr(self, 'fig_'+{'power':'power', 'stress':'stress', 'cap':'cap'}[name])
        widget = getattr(self, 'canvas_'+{'power':'power', 'stress':'stress', 'cap':'cap'}[name]).get_tk_widget()
        if name == 'power':
            shape=mode
            height = round((1680 if shape[1]==1 else 330*shape[0])*scale)
            if getattr(figure, '_result_grid_shape', None) != shape:
                grid = figure.add_gridspec(*shape)
                for index, ax in enumerate(self.ax_power.ravel()):
                    ax.set_subplotspec(grid[index//shape[1], index%shape[1]])
                for drain, ax in zip(self.ax_power_drain, self.ax_power.ravel()[-2:]):
                    drain.set_subplotspec(ax.get_subplotspec())
                figure._result_grid_shape = shape
        elif name == 'stress':
            height = round((600 if compact else 300)*scale)
            shape = (2, 1) if compact else (1, 2)
            if getattr(figure, '_result_grid_shape', None) != shape:
                grid = figure.add_gridspec(*shape)
                for index, ax in enumerate(self.ax_stress):
                    ax.set_subplotspec(grid[index//shape[1], index%shape[1]])
                figure._result_grid_shape = shape
        else:
            height = round(700*scale)
        self._result_overview_heights[name]=height
        figure.set_size_inches(width/figure.dpi, height/figure.dpi, forward=False)
        widget.configure(height=height)
        self._schedule_result_size(name)
        return compact

    def _build_output_result_host(self, parent, name):
        host = ttk.Frame(parent)
        host.pack(fill='x', padx=6, pady=(4, 8))
        note = tk.StringVar()
        label = ttk.Label(host, textvariable=note, style='Margin.TLabel',
                          wraplength=900, justify='left', padding=(6, 6))
        label.pack(fill='x')
        label.bind('<Configure>', lambda event: label.configure(wraplength=max(180, event.width-16)))
        self._output_result_hosts[name] = host
        self._output_result_notes[name] = note

    def _release_output_result_canvas(self, card):
        """Retain the logical card/geometry, release both Tk and Agg pixels."""
        self._cancel_output_card_redraw(card)
        canvas = card.get('canvas')
        if canvas is None:
            return
        widget = canvas.get_tk_widget()
        dispose = getattr(canvas, 'dispose', None)
        if dispose:
            dispose()
        else:
            for name in ('_idle_draw_id', '_event_loop_id'):
                job = getattr(canvas, name, None)
                if job:
                    try:
                        widget.after_cancel(job)
                    except tk.TclError:
                        pass
                    setattr(canvas, name, None)
        card['figure'].clear()
        # Figure.canvas otherwise retains the retired TkAgg instance and its
        # PhotoImage/renderer even after the widget has been destroyed.
        FigureCanvasBase(card['figure'])
        card['axes'] = {}
        card['canvas'] = None
        card['dirty'] = True
        try:
            widget.destroy()
        except tk.TclError:
            pass
        # PhotoImage owns a Tcl image independently of the Canvas widget.
        photo = getattr(canvas, '_tkphoto', None)
        if photo is not None:
            try:
                self.root.tk.call('image', 'delete', str(photo))
            except tk.TclError:
                pass
            canvas._tkphoto = None
        if hasattr(canvas, 'renderer'):
            canvas.renderer = None
        if card['placeholder'].winfo_exists():
            card['placeholder'].pack(fill='both', expand=True)

    def _discard_output_result_card(self, card):
        self._release_output_result_canvas(card)
        job = card.pop('redraw_job', None)
        if job:
            try:
                card['frame'].winfo_toplevel().after_cancel(job)
            except tk.TclError:
                pass
        card['figure'].clear()
        card['frame'].destroy()

    def _new_output_result_card(self, kind, rail_id):
        from multi_output_charts import (OUTPUT_POWER_FIGSIZE, OUTPUT_CAPACITORS_FIGSIZE,
                                         OUTPUT_LOSSES_FIGSIZE)
        size = {'power': OUTPUT_POWER_FIGSIZE, 'cap': OUTPUT_CAPACITORS_FIGSIZE,
                'stress': OUTPUT_LOSSES_FIGSIZE}[kind]
        frame = ttk.LabelFrame(self._output_result_hosts[kind], padding=8)
        frame.pack(fill='x', pady=(6, 8))
        detail = tk.StringVar()
        label = ttk.Label(frame, textvariable=detail, wraplength=900, justify='left', style='Muted.TLabel')
        label.pack(fill='x', pady=(0, 4))
        label.bind('<Configure>', lambda event: label.configure(wraplength=max(180, event.width-12)))
        plot = ttk.Frame(frame, height=round(size[1]*100))
        plot.pack(fill='x')
        plot.pack_propagate(False)
        fig = Figure(figsize=size, dpi=100)
        placeholder = ttk.Label(plot, text='滚动到此处后显示本路图表', anchor='center',
                                style='Muted.TLabel')
        placeholder.pack(fill='both', expand=True)
        card = dict(id=rail_id, kind=kind, frame=frame, detail=detail, plot=plot, figure=fig,
                    canvas=None, placeholder=placeholder, axes={}, branch=None,
                    redraw_job=None, rendered_width=None, reserved_size=None, dirty=True)
        plot.bind('<Configure>', lambda event: self._resize_output_result_card(card, event.width), add='+')
        frame.bind('<Destroy>', lambda event: self._cancel_output_card_redraw(card) if event.widget is frame else None, add='+')
        return card

    def _cancel_output_card_redraw(self, card):
        job = card.get('redraw_job')
        if job:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
            card['redraw_job'] = None

    def _resize_output_result_card(self, card, width):
        if self._closing or width <= 1 or card['branch'] is None:
            return
        if getattr(self, '_lazy_output_cards', False):
            if card['rendered_width'] != width:
                card['dirty'] = True
                # The TkAgg widget has its own Configure handler. Pause it
                # during a resize burst so it cannot redraw an obsolete rail
                # layout repeatedly before our coalesced viewport callback.
                if card['canvas'] is not None:
                    card['canvas'].set_render_active(False)
            self._schedule_output_result_viewport(card['kind'])
            return
        previous = card['rendered_width']
        if previous is not None and (previous < 720) == (width < 720) and abs(previous-width) < 80:
            return
        self._cancel_output_card_redraw(card)
        def redraw():
            card['redraw_job'] = None
            if not self._closing and self._snapshot_valid and card['frame'].winfo_exists():
                self._render_output_result_card(card)
        card['redraw_job'] = self.root.after_idle(redraw)

    def _size_output_result_card(self, card):
        from multi_output_charts import output_chart_figsize
        width = card['plot'].winfo_width()
        if width <= 1:
            width = max(360, self._result_scrolls[card['kind']].canvas.winfo_width()-32)
            if width <= 360:
                width = max(540, self.nb.winfo_width()-56)
        size = output_chart_figsize(card['kind'], card['branch']['op']['topology'], width/card['figure'].dpi)
        # The chart text uses a 14px baseline too. Using a 20px height
        # baseline squeezes data areas as soon as users enlarge the font.
        size=(size[0],size[1]*max(1,getattr(self,'_font_k',14/13)*13/14))
        target = (width, round(size[1]*card['figure'].dpi))
        if target == card['reserved_size']:
            return False
        card['figure'].set_size_inches(*size, forward=False)
        card['plot'].configure(height=target[1])
        card['reserved_size'] = target
        card['dirty'] = True
        return True

    def _render_output_result_card(self, card):
        """Explicit eager draw remains available to callers and diagnostics."""
        self._cancel_output_card_redraw(card)
        self._size_output_result_card(card)
        width = card['reserved_size'][0]
        if card['canvas'] is None:
            card['placeholder'].pack_forget()
            card['canvas'] = FigureCanvasTkAgg(card['figure'], master=card['plot'])
            card['canvas'].get_tk_widget().pack(fill='both', expand=True)
        card['rendered_width'] = width
        card['axes'] = card['draw'](card['figure'], card['branch'], feedback=card['feedback'])
        self._scale_result_text(card['kind'],figure=card['figure'])
        from multi_output_charts import relayout_output_figure
        relayout_output_figure(card['figure'],max(.85,getattr(self,'_font_k',14/13)*13/14))
        card['canvas'].set_render_active(True)
        card['canvas'].draw()
        card['dirty'] = False

    def _update_output_result_cards(self, kind, op, res):
        from multi_output_charts import draw_output_power, draw_output_capacitors, draw_output_losses
        rows = res.get('outputs', [])
        cards = self._output_result_cards[kind]
        host = self._output_result_hosts[kind]
        ids = {row['id'] for row in rows}
        for rail_id in list(cards):
            if rail_id not in ids:
                self._discard_output_result_card(cards.pop(rail_id))
        if not rows:
            if kind == 'stress':
                self._multi_stress_ledger = None
                self._multi_stress_total = None
            host.pack_forget()
            self._output_result_notes[kind].set('')
            self._result_scrolls[kind].sync()
            return
        if not host.winfo_manager():
            host.pack(fill='x', padx=6, pady=(4, 8))
        waveforms = res['wf'].get('outputs', [])
        if len(rows) != len(waveforms):
            raise ValueError('各路结果与波形数量不一致，不能显示上一设计的数据')
        feedback_id = op['feedback_output']
        notes = {
            'power': f'全部 {len(rows)} 路输出波形 · ★ OUT{feedback_id} 为主反馈/PSR基准 · 上方仅展示共享原边/MOS，向下滚动查看每路。',
            'cap': f'全部 {len(rows)} 路输出电容 · ★ OUT{feedback_id} 为主反馈/PSR基准 · 输入电容仅在上方计一次；各路 RMS 不直接相加。',
            'stress': f'全部 {len(rows)} 路功率器件 · ★ OUT{feedback_id} 为主反馈/PSR基准 · 逐路仅含整流/续流和输出防反，不重复计主MOS/钳位MOS。',
        }
        self._output_result_notes[kind].set(notes[kind])
        for row, wf in zip(rows, waveforms):
            rail_id = row['id']
            if rail_id not in cards:
                cards[rail_id] = self._new_output_result_card(kind, rail_id)
            card = cards[rail_id]
            branch = dict(row, wf=wf)
            card['branch'] = branch
            card['dirty'] = True
            feedback = rail_id == feedback_id
            card['feedback'] = feedback
            card['frame'].configure(text=f"OUT{rail_id} · {row['name']}"+(' ★ 主反馈/PSR基准' if feedback else ''))
            if kind == 'power':
                solved = row['op']
                demand = (f"反馈设定/匝比估算 {row['spec']['V_out']:g} V / {row['spec']['P_out']:g} W；解算 {solved['V_out']:.4g} V / {solved['P_out']:.4g} W"
                          if op.get('coupled_model') else f"{row['spec']['V_out']:g} V / {row['spec']['P_out']:g} W")
                card['detail'].set(demand+f" · {solved.get('branch_mode',solved['mode'])} · "
                                   f"副边电流 {row['op']['I_d_rms']:.4g} A rms · 低频纹波 {row['ripple_pp']*1000:.4g} mVpp。"
                                   +('输出电感电流为本路独立 Lout。' if op['topology'] == 'ACF-FORWARD' else '本路为副边波形，原边励磁电感与主开关由所有输出共享。'))
                card['draw'] = draw_output_power
            elif kind == 'cap':
                caps = row['capacitors']['output']['caps']
                card['detail'].set(f"输出银行 {row['capacitors']['total_out']:.4g} A rms · "
                                   f"{len(caps)} 只电容 · ESR 损耗合计 {row['P_cap']:.5g} W · "
                                   f"低频纹波 {wf['ripple_pp']*1000:.4g} mVpp / 含ESL {wf['ripple_pp_total']*1000:.4g} mVpp。")
                card['draw'] = draw_output_capacitors
            else:
                stress = device_stress(row['op'])
                diode = stress['diode']
                text = [f"D_O{rail_id} 整流：Vr,max {diode['V_max']:.4g} V，If,rms {diode['I_rms']:.4g} A，"
                        f"If,pk {diode['I_pk']:.4g} A，If,avg {diode['I_avg']:.4g} A。"]
                if row.get('freewheel'):
                    free = stress['freewheel']
                    text.append(f"D_F{rail_id} 续流：Vr,max {free['V_max']:.4g} V，If,rms {free['I_rms']:.4g} A，"
                                f"If,pk {free['I_pk']:.4g} A；与本路整流共用输入的 Vf/Rd/Qrr。")
                text.append(f"整流/续流损耗 {row['P_rectifier']:.5g} W；输出防反 {'已启用' if row['spec']['d_out_enable'] else '未启用'}，"
                            f"损耗 {row['P_dout']:.5g} W；本路功率半导体合计 {row['P_rectifier']+row['P_dout']:.5g} W。")
                text.append(__import__('stress_notes').DIODE_STRESS_NOTE)
                card['detail'].set('\n'.join(text))
                card['draw'] = draw_output_losses
            if getattr(self, '_lazy_output_cards', False):
                self._size_output_result_card(card)
            else:
                self._render_output_result_card(card)
        self._result_scrolls[kind].sync()
        self._schedule_output_result_viewport(kind)

    def _prune_output_result_cards(self, res):
        """Retire old snapshots even on lazy pages that are not visited.

        Surviving cards keep their frame and reserved height so the scrollbar
        does not jump. Their numerical source and old artists must not keep a
        previous full design alive outside the worker's bounded cache, though.
        The page updater supplies the new branch before viewport rendering.
        """
        ids = {row['id'] for row in res.get('outputs', [])}
        for kind, cards in self._output_result_cards.items():
            for rail_id in list(cards):
                if rail_id not in ids:
                    self._discard_output_result_card(cards.pop(rail_id))
                elif getattr(self, '_lazy_output_cards', False):
                    card = cards[rail_id]
                    self._release_output_result_canvas(card)
                    if card['figure'].axes:
                        card['figure'].clear()
                    card['axes'] = {}
                    card['branch'] = None
                    card['dirty'] = True
            if not ids:
                self._output_result_hosts[kind].pack_forget()
                self._output_result_notes[kind].set('')
                if kind == 'stress':
                    self._multi_stress_ledger = None
                    self._multi_stress_total = None
            self._result_scrolls[kind].sync()

    def _draw_multi_stress_overview(self, op, res, draw_bars):
        rows = res['outputs']
        self._fill_tree(self.di_tree, [
            (f"OUT{row['id']} {row['name']}"+(' ★' if row['id'] == op['feedback_output'] else ''),
             f"{row['op']['V_d_max']:.3g} V / {row['op']['I_d_rms']:.3g} A rms") for row in rows])
        self._fill_tree(self.dil_tree, [
            (f"OUT{row['id']} 整流/续流", f"{row['P_rectifier']:.4g} W") for row in rows])
        labels = ['Q1 导通', 'Q1 开通', 'Q1 关断', 'Q1 Coss', 'Q1 栅极驱动']
        switch = res['semi']['switch']
        vals = [switch[key] for key in ('P_cond', 'P_sw_on', 'P_sw_off', 'P_coss', 'P_gate')]
        if res['semi'].get('auxiliary'):
            labels.append('Q2 钳位 MOS')
            vals.append(res['semi']['auxiliary']['P_total'])
        if op.get('aggregate_params', {}).get('d_in_enable', True):
            labels.append('输入防反 D_IN')
            vals.append(res['P_din'])
        draw_bars(self.ax_stress[0], labels, vals, f'共享功率器件 · {sum(vals):.4g} W', '#c0392b')
        branch_totals = [row['P_rectifier']+row['P_dout'] for row in rows]
        draw_bars(self.ax_stress[1], [f"OUT{row['id']}"+(' ★' if row['id'] == op['feedback_output'] else '') for row in rows],
                  branch_totals, f'各路整流 / 续流 / 输出防反 · {sum(branch_totals):.4g} W', '#2980b9')
        self._multi_stress_total = sum(vals)+sum(branch_totals)
        self._multi_stress_ledger = dict(shared=sum(vals), outputs=branch_totals, total=self._multi_stress_total)

    def _multi_stress_note(self, res):
        auxiliary = res['semi'].get('auxiliary', {}).get('P_total', 0.)
        auxiliary_note = f'钳位 Q2 {auxiliary:.4g} W + ' if res['semi'].get('auxiliary') else ''
        return (f"全路功率器件合计 {res['P_semi']+res['P_din']+res['P_dout']:.5g} W = "
                f"共享 Q1 {res['semi']['switch']['P_total']:.4g} W + "+auxiliary_note+
                f"输入防反 {res['P_din']:.4g} W + 各路整流/续流 {sum(row['P_rectifier'] for row in res['outputs']):.4g} W + "
                f"各路输出防反 {res['P_dout']:.4g} W。P_semi 本身不含防反二极管；不含磁件/电容/采样等其他损耗。")
