"""Configuration and presentation for isolated outputs and MP6005 PSR."""
import copy
import tkinter as tk
from tkinter import ttk, messagebox
from isolated_outputs import ISOLATED, output_specs
from mp6005 import DEFAULTS
from output_parameter_panel import OutputParameterPanel
from cross_regulation_ui import CrossRegulationUI
from winding_coupling import default_coupling_config, resolve_winding_model, validate_coupling_config

class IsolatedUI(CrossRegulationUI,OutputParameterPanel):
    def load_isolated_example(self,filename):
        import json
        from power_stage import DEFAULT_PARAMS
        from main import resource_path
        from pathlib import Path
        try:
            cfg=json.loads(Path(resource_path('examples/'+filename)).read_text(encoding='utf-8'))
            self._apply_config(dict(DEFAULT_PARAMS,**cfg))
            self.request_update()
        except Exception as exc: messagebox.showerror('隔离输出示例',str(exc))

    def _init_isolated_state(self):
        self.output_config=[]
        self.psr_config=dict(DEFAULTS)
        self.multi_enabled=tk.BooleanVar(value=False)
        self.feedback_mode=tk.StringVar(value='SSR')
        self.feedback_output=tk.IntVar(value=1)
        self._init_inline_output_state()

    def _isolated_parameters(self,p):
        if p['topology'] in ISOLATED:
            p.update(outputs=self._read_inline_outputs(p),
                     feedback_mode=self._effective_feedback_mode(),feedback_output=self.feedback_output.get() if self.multi_enabled.get() else 1)
            p.update(self._read_inline_psr())
            if p['feedback_mode']=='PSR-MP6005':
                p.update(controller_type='type2',control_mode='Peak Current Mode',A_sense=11.)
        p['coupling_config']=self._read_inline_coupling(p)
        return p

    def _isolated_config(self):
        # Saving uses the same validated inline source as calculation, so a
        # partially typed visible value cannot silently save its old value.
        # A design may be saved mid-import. This bypass is serialization-only:
        # every calculation/export still requires all requested curves.
        p=self.get_params(check_curve_sources=False)
        return dict(outputs=copy.deepcopy(p.get('outputs', [])),
                    feedback_mode=p.get('feedback_mode','SSR'),feedback_output=p.get('feedback_output',1),
                    coupling_config=copy.deepcopy(p['coupling_config']),**self.psr_config)

    def _load_isolated_config(self,cfg):
        from config_io import decode_config
        from power_stage import DEFAULT_PARAMS
        decoded=decode_config(cfg)
        candidate=dict(DEFAULT_PARAMS,**decoded)
        rails=output_specs(candidate)
        coupling=copy.deepcopy(candidate.get('coupling_config',default_coupling_config(len(rails) or 1)))
        # Validate the complete saved matrix before touching any existing UI
        # state. Unsupported topology drafts remain disabled in calculation.
        if isinstance(coupling,dict) and coupling.get('enabled') and candidate['topology']=='FLYBACK' and candidate.get('feedback_mode','SSR')=='SSR':
            resolve_winding_model(dict(candidate,coupling_config=coupling),rails)
        else:
            validate_coupling_config(coupling,len(rails) or 1)
        self._inline_binding_busy=True
        try:
            self.output_config=[{k:v for k,v in r.items() if k!='id'} for r in rails]
            self.multi_enabled.set(bool(rails))
            self.feedback_mode.set(candidate['feedback_mode'])
            self.feedback_output.set(int(candidate['feedback_output']) if rails else 1)
            self.psr_config={k:decoded.get(k,v) for k,v in DEFAULTS.items()}
            self._reset_inline_output_forms(candidate, self.output_config)
            self._sync_inline_psr_values()
            self._set_inline_coupling_config(coupling,len(rails) or 1)
        finally:
            self._inline_binding_busy=False
        self._sync_inline_output_context()

    def _build_isolated_controls(self,parent):
        book=ttk.Notebook(parent); book.pack(fill='both',expand=True)
        diagram=ttk.Frame(book); results=ttk.Frame(book); psr=ttk.Frame(book)
        book.add(diagram,text='拓扑与器件位号'); book.add(results,text='各路输出与绕组'); book.add(psr,text='MP6005 PSR 核算')
        self._isolated_result_book=book
        self._isolated_result_pages=(diagram,results,psr)
        self._cross_page=ttk.Frame(book)
        book.add(self._cross_page,text='交叉调整率与电压范围')
        self._build_cross_regulation(self._cross_page)
        self.output_note=tk.StringVar()
        ttk.Label(results,textvariable=self.output_note,wraplength=1050,justify='left').pack(fill='x',padx=8,pady=8)
        columns=('rail','spec','actual','mode','current','ripple','rect','cap','turns','cu')
        self.output_tree=ttk.Treeview(results,columns=columns,show='headings',height=8)
        for key,title,width in zip(columns,('输出/反馈','端口参考 V / W','端口 V / 电容端 V / W','支路模式','整流 RMS / A','纹波 / mV','整流损耗 / W','电容损耗 / W','副边匝数','铜损 / W'),(140,185,200,110,130,110,130,130,100,110)):
            self.output_tree.heading(key,text=title); self.output_tree.column(key,width=width,minwidth=60)
        self.output_tree.pack(fill='x',padx=6)
        output_xscroll=ttk.Scrollbar(results,orient='horizontal',command=self.output_tree.xview)
        output_xscroll.pack(fill='x',padx=6,pady=(0,4))
        self.output_tree.configure(xscrollcommand=output_xscroll.set)
        self.psr_text=tk.Text(psr,wrap='word',font=('Microsoft YaHei',11),relief='flat',padx=14,pady=10)
        sb=ttk.Scrollbar(psr,command=self.psr_text.yview); sb.pack(side='right',fill='y')
        self.psr_text.configure(yscrollcommand=sb.set,state='disabled'); self.psr_text.pack(fill='both',expand=True)
        self._sync_isolated_result_tabs()
        return diagram

    def _sync_isolated_result_tabs(self):
        book=self._isolated_result_book
        diagram,results,psr=self._isolated_result_pages
        allowed=((diagram,True),(results,self._inline_multiple_active() or (self._coupling_supported() and self.coupling_enabled.get())),
                 (psr,self._topo_key()=='FLYBACK' and self.feedback_mode.get()=='PSR-MP6005'),
                 (self._cross_page,self._inline_multiple_active() and self._topo_key()=='FLYBACK' and self.feedback_mode.get()=='SSR'))
        selected=book.select()
        if any(str(page)==selected and not show for page,show in allowed):
            book.select(diagram)
        for page,show in allowed:
            state=str(book.tab(page,'state'))
            if show and state=='hidden': book.add(page)
            elif not show and state!='hidden': book.hide(page)
        if not book.select() or str(book.tab(book.select(),'state'))=='hidden': book.select(diagram)

    def _toggle_outputs(self):
        if self._topo_key() not in ISOLATED:
            self.multi_enabled.set(False)
            messagebox.showinfo('多绕组输出','请选择隔离拓扑后再配置多绕组输出。')
            return
        self._sync_inline_output_context()
        self._filter_params()
        self.schedule_update()

    def edit_outputs(self):
        if self._topo_key() not in ISOLATED:
            return None
        return self._focus_inline_section('spec')

    def edit_psr(self):
        if self._topo_key() != 'FLYBACK':
            return None
        return self._focus_inline_section('ctrl')

    def _update_isolated_results(self,p,res):
        self.output_tree.delete(*self.output_tree.get_children())
        windings=(res['mag'].get('transformer') or {}).get('windings',[])
        coupling=res['op'].get('coupled_model') or {}
        physical=bool(coupling and not coupling.get('ideal_fallback'))
        for i,rail in enumerate(res.get('outputs',[])):
            winding=windings[i] if i<len(windings) else dict(Ns='未计算',P_cu=float('nan'))
            main=rail['id']==p['feedback_output']
            actual=f"{rail['op']['V_out']:.5g} / {rail['op'].get('V_out_cap',rail['op']['V_out']):.5g} / {rail['op']['P_out']:.5g}"
            mode=rail['op'].get('local_mode',rail['op']['mode']) if physical else '标称 '+rail['op']['mode']
            self.output_tree.insert('','end',values=(f"OUT{rail['id']} {rail['name']}"+(' ★' if main else ''),
                f"{rail['spec']['V_out']:g} / {rail['spec']['P_out']:g}",actual,mode,f"{rail['op']['I_d_rms']:.4g}",
                f"{rail['ripple_pp']*1000:.4g}",f"{rail['P_rectifier']:.4g}",f"{rail['P_cap']:.4g}",winding['Ns'],f"{winding['P_cu']:.4g}"))
        if physical:
            note=('绕组耦合矩阵实验模型：按实际匝数 / 自感、两两 kij、DCR、整流器和有限电压钳位求周期稳态。'
                  '\n★主反馈路目标稳压；其余路先按实际匝比估算电压，再以 R=V匝比²/P额定建立固定电阻负载；求解电压 / 功率单列。'
                  '支路 CCM/DCM 按副边能量传递期间是否提前截止判定；原边导通期间的正常零电流不计作 DCM。'
                  '\n输出电容采用恒定直流电压 / 周期平均电荷平衡；大纹波需复核。适用固定频率 SSR 反激；'
                  '不含绕组分布电容 / 高频谐振完整模型，需仿真与实测复核。')
        elif coupling.get('ideal_fallback'):
            note=('全部 kij=1：使用理想变压器极限。零漏感下的多绕组电流分配可能不唯一，当前仍采用标称功率比例分配；'
                  '不将该分配解释为真实交叉调整率求解。原边、磁芯、输入电容只计一次。')
        else:
            note=(('各路电流、纹波、整流/电容损耗和绕组铜损分别核算；原边、磁芯、输入电容只计一次。'
                   '\n★为主反馈/PSR采样基准；波形页显示该路。未反馈路交叉调整率未验证。'+
                   ('各路输出电感独立核算；多路正激仅支持各路均 CCM。' if p['topology']=='ACF-FORWARD' else '各路副边共享原边励磁电感，不存在正激输出电感。'))
                  if res.get('outputs') else '当前为单路模式。隔离多输出需求、器件和绕组在左侧对应分组统一配置。')
        from voltage_nodes import NOTE
        self.output_note.set(NOTE+'\n'+note)
        detail=res.get('psr'); self.psr_text.configure(state='normal'); self.psr_text.delete('1.0','end')
        if detail:
            from power_stage import fmt_eng as value
            units={'RfbH':'Ω','RfbL':'Ω','Rreg':'Ω','Rcomp':'Ω','Ccomp':'F','Cpole':'F','Vaux':'V','Vfb':'V','Vout_set':'V','Vout_error':'V','Ifb_negative':'A','Rs_recommended':'Ω','Vcs_peak':'V','Lpri_min':'H','tcon_min33':'s','tcon':'s','sample_window':'s','minimum_load':'W','fz':'Hz','fp':'Hz','P_controller':'W'}
            self.psr_text.insert('end',f"MP6005 · {detail['region']} · Np/Ns/Na = {detail['Np']}/{detail['Ns']}/{detail['Na']}\n\n")
            for key,unit in units.items(): self.psr_text.insert('end',f'{key}: {value(detail[key],unit)}\n')
            self.psr_text.insert('end','\n'+detail['note']+'\n\n'+detail['source'])
        else: self.psr_text.insert('end','选择 PSR-MP6005 后显示辅助绕组采样、分压、最小电感、电流限值和物理 COMP 网络。\n仅固定频率反激；SSR 保留原有补偿计算。')
        self.psr_text.configure(state='disabled')

    def _psr_auto_tune(self,p):
        from loss_model import compute_design
        from plants import build_loop_models
        from loop_tuning import kfactor_tune
        from mp6005 import compensation_parts
        res=compute_design(p); models,_=build_loop_models(p,res['op'])
        fc=min(p['fc_target'],res['op']['f_sw']/10)
        tuned=kfactor_tune(models[0],fc,p['pm_target'],'type2')
        if not tuned['feasible']: raise ValueError('此 fc/PM 需要超过二型可提供的相位提升；参数未写回')
        self.psr_config.update(compensation_parts(tuned))
        self._sync_inline_psr_values()
        self.set_param('fc_target',fc)
        self.tune_result.set('MP6005 PWM 近似整定：已写回 PSR 页 Rcomp/Ccomp/Cpole；须 FRA 实测复核。')
        self.schedule_update()
