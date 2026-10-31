"""Complete Word report from a current design snapshot; no GUI/pyplot dependency.

Imported only on export so python-docx/lxml and Agg do not slow GUI startup.
Charts are regenerated, not copied from visited GUI tabs. No automatic tuning
or changes to design parameters are made by export.
"""
import math
from datetime import datetime, timezone, timedelta
from io import BytesIO
from pathlib import Path

import numpy as np
from matplotlib import rc_context
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

from docx_layout import new_document, paragraph, table, figure, section, equation
from waveforms import make_waveforms
from capripple import capacitor_ripple_analysis
from semiconductor import device_stress
from loss_model import compute_design
from plants import resolve_controller_type
from power_charts import draw_power_signals, draw_power_switching
from switching_transients import switching_voltage_data, STAGE_NAMES

TOPOLOGY = {'BUCK':'降压 Buck','BOOST':'升压 Boost','BUCK-BOOST':'反相升降压 Buck-Boost',
            'FLYBACK':'反激 Flyback','QR-FLYBACK':'准谐振反激 QR-Flyback',
            'ACF-FORWARD':'有源钳位正激 Active-Clamp Forward'}
COLORS = ['#2068A0','#D18532','#4C8A79','#8677B2']
PARAMS = {
    'V_in':('输入电压','V'),'V_out':('输出电压','V'),'P_out':('输出功率','W'),
    'f_sw':('开关频率 / QR 频率上限','Hz'),'L':('电感 / 反激励磁电感','H'),
    'C_out':('主输出电容','F'),'Rc':('主输出电容 ESR','Ω'),'ESL':('主输出电容 ESL','H'),
    'Rs':('采样电阻','Ω'),'Vm':('PWM 锯齿波幅值','V'),'N':('原副边匝比 Np/Ns',''),
    'Vf':('旧版工作点整流压降（保留配置兼容）','V'),'ripple_target':('输出纹波目标比例',''),
    'eta_guess':('预设设计效率（输入比例）',''),
    'ring_margin':('非反激 MOS 电压应力裕量比例',''),'Rds_on':('主 MOSFET 导通电阻','Ω'),
    'Coss':('主 MOSFET 输出电容','F'),'Qg':('总栅电荷','C'),'Vgs':('驱动电压','V'),
    'Vth':('阈值电压','V'),'Vgp_on':('手动开通 / Qgs参考平台','V'),'Vgp_off':('手动关断米勒平台','V'),
    'gfs':('有效跨导（0 为固定平台）','A/V'),
    'Qg_th':('阈值栅电荷','C'),'Qgs':('栅源电荷','C'),'Qgd':('米勒电荷','C'),
    'Rg_drive':('驱动器输出电阻','Ω'),'Rs_on':('外部开通栅电阻','Ω'),
    'Rs_off':('外部关断栅电阻','Ω'),'Rg':('MOSFET 内部栅电阻','Ω'),'k_sw':('开关损耗系数',''),
    'Vf_diode':('损耗模型整流压降','V'),'Rd_diode':('二极管动态电阻','Ω'),
    'Qrr':('二极管反向恢复电荷','C'),'A_sense':('电流采样放大倍数',''),
    'ma_slope':('外加电流斜坡','A/s'),'Bmax':('匝数设计磁密上限','T'),
    'Bsat':('饱和磁密','T'),'J':('设计电流密度','A/m²'),'Ku':('面积乘积窗口利用系数',''),
    'rho':('导体电阻率','Ω·m'),'h_conv':('电感对流换热系数','W/(m²·K)'),
    'Rth_transformer':('变压器至环境热阻 Ri-a','K/W'),
    'k_core':('Steinmetz k',''),'a_core':('Steinmetz α',''),'b_core':('Steinmetz β',''),
    'MLT':('标准磁芯平均匝长（0=自动）','m'),'Np':('原边匝数（0=自动）',''),
    'Ns':('副边匝数（0=自动）',''),'d_wire_p':('原边单股线径（0=自动）','m'),
    'd_wire_s':('副边单股线径（0=自动）','m'),'n_strand_p':('原边并绕股数',''),
    'n_strand_s':('副边并绕股数',''),'target_eta':('模型效率目标比例',''),
    'Lm_forward':('正激励磁电感','H'),'C_clamp':('有源钳位电容','F'),
    'forward_dead_time':('设定死区','s'),'forward_d_max':('正激占空比上限',''),
    'Rds_aux':('钳位 MOSFET 导通电阻','Ω'),'Qg_aux':('钳位 MOSFET 栅电荷','C'),
    'Coss_aux':('钳位 MOSFET 输出电容','F'),'ESR_clamp':('钳位电容 ESR','Ω'),
    'Vf_din':('输入防反二极管 Vf','V'),'Rd_din':('输入防反二极管 Rd','Ω'),
    'Vf_dout':('输出防反二极管 Vf','V'),'Rd_dout':('输出防反二极管 Rd','Ω'),
}


def value(x, unit=''):
    if x is None:
        return '未定义'
    if isinstance(x,(bool,np.bool_)):
        return '启用' if x else '停用'
    if isinstance(x,str):
        return x
    x=float(x)
    if math.isnan(x):
        return '未能计算'
    if math.isinf(x):
        return '无有限值'
    if x==0:
        return '0'+(' '+unit if unit else '')
    if unit in ('Hz','H','F','Ω','C','s','m','W','V','A'):
        exp=max(-4,min(3,int(math.floor(math.log10(abs(x))/3))))
        prefix={-4:'p',-3:'n',-2:'μ',-1:'m',0:'',1:'k',2:'M',3:'G'}[exp]
        return f'{x/10**(3*exp):.4g} {prefix}{unit}'
    return f'{x:.4g}'+(' '+unit if unit else '')


def _mos_gate_report(doc, switch_loss):
    gate = switch_loss.get('gate')
    if not gate:
        paragraph(doc, '此快照缺少 MOS 平台工作点，请用新版重新计算，不以输入值伪装成已求解的平台。')
        return
    paragraph(doc, '当前平台模型：'+gate['label']+'。以下使用本输入电压与负载下的开通/关断电流；不会把 Vinmin 的平台直接复制给 Vinmax。')
    table(doc, ['过程','实际换流电流','计算平台电压','计算 Qgs'], [
        ('开通',value(gate['I_on'],'A'),value(gate['Vgp_on'],'V'),value(gate['Qgs_on'],'C')),
        ('关断',value(gate['I_off'],'A'),value(gate['Vgp_off'],'V'),value(gate['Qgs_off'],'C')),
    ], [1.,2.,2.,2.1])
    if gate['mode'] == 'curve':
        info=gate['curve_info']
        paragraph(doc,'所选曲线：'+info.get('name','MOS曲线')+'；类型：'+
            ('Id–Vgs 转移曲线' if info['kind']=='transfer' else 'Id–Vds 输出曲线族')+'。')
        details=[]
        if info.get('conditions'):details.append(info['conditions'])
        if 'Tj_C' in info:details.append(f"Tj={info['Tj_C']:g} °C")
        if 'Vds_test_V' in info:details.append(f"曲线测试 Vds={info['Vds_test_V']:g} V")
        if info.get('read_vds') is not None:details.append(f"曲线族读取 Vds={info['read_vds']:g} V（用户指定参考截面）")
        if details:paragraph(doc,'；'.join(details),True)
        origin=info.get('import_file') or info.get('source',{})
        if origin.get('filename'):paragraph(doc,'数据来源：'+origin['filename']+'；SHA256：'+origin.get('sha256','未记录'),True)
        paragraph(doc,'F 表示按声明坐标插值或端点趋势外推后的反函数。输出曲线族先在指定 Vds 截面得到 Id–Vgs 采样，再沿 Vgs 分组反查。外推情况另行提示，不将其他工况的平台复制为本工况。',True)
        equation(doc,'Vgp,on=F(Ids,on)')
        equation(doc,'Vgp,off=F(Ids,off)')
    if gate['mode'] == 'current':
        paragraph(doc, f"有效跨导 gfs={gate['gfs']:.4g} A/V；栅电荷曲线参考平台为 {value(gate['Vgp_reference'],'V')}。", True)
        equation(doc, 'Vgp,on=Vth+Ids,on/gfs')
        equation(doc, 'Vgp,off=Vth+Ids,off/gfs')
        paragraph(doc, '背景资料：TI SLUA618A 第 2.3 节式 (8)；旧版有效跨导近似仅作为兼容模式。'+gate['source'], True)
    if gate.get('charge_mode')=='curve':
        info=gate['charge_curve_info']
        paragraph(doc,'栅电荷来源：'+info.get('name','Vgs–Qg 曲线')+'。横轴为 Qg，纵轴为 Vgs；平台起止由用户校核。')
        table(doc,['电荷量','开通','关断'],[
            ('到阈值 Qg(th)',value(gate['Qg_th'],'C'),value(gate['Qg_th'],'C')),
            ('到平台 Qgs',value(gate['Qgs_on'],'C'),value(gate['Qgs_off'],'C')),
            ('平台段 Qgd',value(gate['Qgd_on'],'C'),value(gate['Qgd_off'],'C')),
            ('驱动电压对应总 Qg',value(gate['Qg_on'],'C'),value(gate['Qg_off'],'C')),
        ],[2.5,2.3,2.3])
        origin=info.get('import_file') or info.get('source',{})
        if origin.get('filename'):paragraph(doc,'栅电荷数据来源：'+origin['filename']+'；SHA256：'+origin.get('sha256','未记录'),True)
        paragraph(doc,'Fpre 是平台前上升支路的反函数，Fpost 是平台后上升支路的反函数。QM,start 与 QM,end 分别是已确认的平台起止电荷。各支路支持端点趋势外推，平台平段及平台后支路不参与 Qgs 的反查；外推不是新增实测点。',True)
        for formula in ('Qg_th=Fpre(Vth)','Qgs,on=Fpre(Vgp,on)','Qgs,off=Fpre(Vgp,off)',
                        'Qgd=Qplateau,end−Qplateau,start','Qg=Fpost(Vdrv)'):
            equation(doc,formula)
        paragraph(doc,'t1/t8 用曲线读取的 Qg(th)，t2/t7 分别用 Qgs,on/off，t3/t6 分别用 Qgd,on/off。驱动损耗用驱动电压对应总 Qg。t1/t2/t7 仍保留 XLSX 的 LN 形式，未改成 Q/I 常数近似。',True)
    elif gate['mode'] in ('current','curve'):
        equation(doc, 'Cgs,inc=(Qgs−Qg_th)/(Vgp,ref−Vth)')
        equation(doc, 'Qgs,on=Qg_th+Cgs,inc(Vgp,on−Vth)')
        equation(doc, 'Qgs,off=Qg_th+Cgs,inc(Vgp,off−Vth)')
        paragraph(doc, '时间仍采用参考 XLSX 的自然对数形式；t2 使用 Qgs,on 与 Vgp,on，t3 使用 Vgp,on，t6/t7 使用 Vgp,off，t7 使用 Qgs,off。t1/t8 保留阈值段电荷；零电流时电流过渡段按极限取零。', True)
    for note in gate['notes']:
        paragraph(doc, note, True)


def _chart(size, draw):
    with rc_context({'font.sans-serif':['Microsoft YaHei','SimHei','DejaVu Sans'],
                     'font.size':9,'axes.titlesize':10,'axes.labelsize':9,
                     'legend.fontsize':8,'axes.unicode_minus':False,
                     'axes.spines.top':False,'axes.spines.right':False,
                     'axes.prop_cycle':__import__('cycler').cycler(color=COLORS)}):
        fig=Figure(figsize=size,layout='constrained')
        FigureCanvasAgg(fig)
        draw(fig)
        from design_theme import style_figure
        style_figure(fig)
        stream=BytesIO(); fig.savefig(stream,format='png',dpi=220,facecolor='white')
        return stream.getvalue()


def _bars(names,vals,title,xlabel='损耗 / W',height=2.7):
    def draw(fig):
        ax=fig.subplots(); ys=np.arange(len(names)); a=np.asarray(vals,float)
        clean=np.where(np.isfinite(a),a,0)
        ax.barh(ys,clean,color=COLORS[0],height=.6)
        ax.set_yticks(ys,names); ax.invert_yaxis(); ax.set_xlabel(xlabel); ax.set_title(title)
        vmax=max(float(np.max(clean)) if len(clean) else 0,1e-6)
        ax.set_xlim(0,vmax*1.3)
        for y,v,raw in zip(ys,clean,a):
            ax.text(v+vmax*.025,y,f'{raw:.3g}' if np.isfinite(raw) else '未计算',va='center',fontsize=9)
        ax.grid(axis='x',alpha=.15); ax.set_axisbelow(True)
    return _chart((7.1,height),draw)


def capacitor_data(p,op):
    from capripple import analyze_capacitors
    return analyze_capacitors(p,op)


def loop_data(p,models):
    from loop_tuning import analyze_loop
    return analyze_loop(p,models)


def design_checks(p,op,wf,res,loop,loop_error=None):
    from design_checks import check_catalog, STATE_LABELS
    checks=res.get('checks')
    if checks is None:
        checks=check_catalog(p,res,loop,loop_error)
    return [(c['name'], value(c['value'], c['unit']),
             (c['comparison']+' '+value(c['limit'], c['unit'])) if c['limit'] is not None else c['note'],
             STATE_LABELS[c['state']]) for c in checks]


def _output_report(doc,p,res):
    if not res.get('outputs'): return
    section(doc,'1.1  多绕组输出与独立支路核算')
    paragraph(doc,'只输入主反馈或 PSR 基准路的电压，其余输出按已解析的整数副边匝数比估算；每路功率、整流器、电容和绕组参数分别配置。原边按总输出功率设计，共享磁芯、MOS、采样和输入电容只计一次。最多 6 路功率输出，PSR 辅助采样绕组另计。')
    equation(doc,'V_j,est = (V_b + Vf,block,b + Vf,rect,b)·Ns_j/Ns_b − Vf,rect,j − Vf,block,j')
    equation(doc,'Pout = Σ P_j'); equation(doc,'I_j = ','P_j','V_j')
    coupled = bool(res['op'].get('coupled_solution') is not None)
    paragraph(doc,'本次采用逐对耦合矩阵，联立二极管导通状态与各路周期平均电荷平衡。负载为反馈设定或匝比近似电压平方除以额定功率得到的固定电阻；仅主反馈路固定设定电压，其他输出电压及实际功率为解算结果。输出电容以刚性直流电压近似，非开关瞬态仿真。' if coupled else
              '本模型假定理想匝比关系和标称同步整流波形；反激电流按各路功率比例分配。非反馈输出不独立闭环，轻载、空载、整流压降和耦合导致的交叉调整率未被验证。多路正激仅支持每路均 CCM，DCM 角点明确跳过。',True)
    table(doc,['输出 / 名称','反馈设定或匝比估算 / 功率','直流电流','整流 RMS','纹波','整流 / 电容损耗'],[
        (f"OUT{r['id']} {r['name']}"+(' ★' if r['id']==p['feedback_output'] else ''),
         value(r['spec']['V_out'],'V')+' / '+value(r['spec']['P_out'],'W'),value(r['op']['I_out'],'A'),
         value(r['op']['I_d_rms'],'A'),value(r['ripple_pp'],'V'),value(r['P_rectifier'],'W')+' / '+value(r['P_cap'],'W'))
        for r in res['outputs']],[1.2,1.25,1.,1.,1.,1.65])
    if coupled:
        table(doc,['输出','端口参考 / 功率','解算端口 / 功率','电容端（防反前）','支路模式'],[
            (f"OUT{r['id']}",value(r['spec']['V_out'],'V')+' / '+value(r['spec']['P_out'],'W'),
             value(r['op']['V_out'],'V')+' / '+value(r['op']['P_out'],'W'),value(r['op'].get('V_out_cap',r['op']['V_out']),'V'),r['op']['branch_mode'])
            for r in res['outputs']],[.6,1.7,2.1,1.6,1.1])
    tr=res['mag'].get('transformer') or {}
    table(doc,['绕组','匝数 / 匝比','裸铜线径 / 股数','RMS / 电流密度','几何 DCR','铜损'],[
        (f"OUT{w['id']}",f"{w['Ns']} / {w['n_actual']:.4g}",value(w['d_wire_s']*1e3,'mm')+f" / {w['n_strand_s']}",
         value(w['I_rms'],'A')+' / '+value(w['J_actual']/1e6,'A/mm²'),value(w['R_dc'],'Ω'),value(w['P_cu'],'W'))
        for w in tr.get('windings',[])],[.65,1.1,1.35,1.65,1.15,1.2])
    for r,wf in zip(res['outputs'],res['wf']['outputs']):
        spec=r['spec']; idx=r['id']; section(doc,f'1.1.{idx}  OUT{idx} · {r["name"]} 参数与波形')
        from isolated_fields import FIELDS
        table(doc,['参数','值','参数','值'],[
            (FIELDS[a][0],value(spec[a]/FIELDS[a][2],FIELDS[a][1]),FIELDS[b][0],
             '不适用（反激共享 L）' if b=='L' and p['topology']!='ACF-FORWARD' else value(spec[b]/FIELDS[b][2],FIELDS[b][1]))
            for a,b in [('V_out','P_out'),('P_out_min','ripple_target'),('C_out','Rc'),('ESL','C_out2'),('Rc2','ESL2'),('Vf_diode','Qrr'),('Ns','n_strand_s'),('d_wire_s','L')]
            ],[1.7,1.85,1.7,1.85])
        paragraph(doc,f"并联电容数量：{len(__import__('capacitor_banks').bank(spec))} 颗；输出防反：{value(spec['d_out_enable'])}，固定 Vf={value(spec['Vf_dout'],'V')}；二极管曲线与对应损耗见第 3 节。"+
                  (f"正激输出电感磁芯：{spec['core_choice_L']}。" if p['topology']=='ACF-FORWARD' else ''))
        def waves(fig):
            from multi_output_charts import draw_output_currents
            axes=fig.subplots(1,2)
            draw_output_currents(axes[0],dict(r,wf=wf))
            axes[1].plot(wf['t']*1e6,wf['vout_ripple']*1000); axes[1].set(title=f'OUT{idx} 低频纹波',xlabel='时间 / μs',ylabel='mV')
            for ax in axes: ax.grid(alpha=.2)
        figure(doc,_chart((7.1,2.2),waves),f'图 1-OUT{idx}  '+('耦合矩阵解算电流与小纹波重建' if coupled else '对应输出的标称波形；非交叉调整率实测'))
        paragraph(doc,f'OUT{idx} 的电容组 RMS、单只电容损耗和频带柱状图集中列于第 4 节，不在此重复。',True)
        inds=res['mag'].get('inductors',[])
        if inds:
            dev=inds[idx-1]
            table(doc,['输出电感磁芯','匝数','峰值磁密','铜损','磁损','温升'],[(dev['core_label'],dev['N'],value(dev['B_pk'],'T'),value(dev['P_cu'],'W'),value(dev['P_core'],'W'),value(dev['dT'],'K'))])
            table(doc,['有效面积 Ae','有效体积 Ve','窗口面积 Wa','平均匝长 MLT'],[
                (value(dev['Ae']*1e6,'mm²'),value(dev['Ve']*1e6,'cm³'),
                 value(dev['Wa']*1e6,'mm²'),value(dev['MLT']*1e3,'mm'))])
            paragraph(doc,'OUT'+str(idx)+' 尺寸来源：'+dev['core']+'；MLT 来源：'+dev['MLT_source']+'。',True)


def _psr_report(doc,p,res):
    detail=res.get('psr')
    if not detail: return
    section(doc,'1.2  MP6005 原边反馈设计核算')
    paragraph(doc,f"控制器 MP6005，MODE 悬空；{detail['region']} 区域；PWM 固定 250kHz，内部 CS 增益 11。基准为 OUT{int(p.get('feedback_output',1))}，辅助采样绕组在原边参考地，不能直接连接到次级地。")
    equation(doc,'β = ','R_FB,L','R_FB,H + R_FB,L')
    equation(doc,'V_FB = β·((N_a/N_s)·(Vo + V_f) - I_reg·R_FB,H)')
    equation(doc,'L_min = ','(N_p/N_s)·(Vo + V_f)·0.7μs·R_s','0.033V')
    equation(doc,'G_c(s) = ','g_m·(1 + s·R_z·C_z)','s·(C_z + C_p)·(1 + s·R_z·C_z·C_p/(C_z + C_p))')
    table(doc,['核算量','结果','核算量','结果'],[
        ('Np / Ns / Na',f"{detail['Np']} / {detail['Ns']} / {detail['Na']}",'辅助导通采样电压',value(detail['Vaux'],'V')),
        ('FB 上 / 下电阻',value(detail['RfbH'],'Ω')+' / '+value(detail['RfbL'],'Ω'),'FB 标称采样',value(detail['Vfb'],'V')),
        ('负向 FB 电流',value(detail['Ifb_negative'],'A'),'建议 Rs 最大值',value(detail['Rs_recommended'],'Ω')),
        ('最小原边电感',value(detail['Lpri_min'],'H'),'33mV 条件导通时间',value(detail['tcon_min33'],'s')),
        ('当前次级导通时间',value(detail['tcon'],'s'),'去除 300ns 消隐的窗口',value(detail['sample_window'],'s')),
        ('采样峰值',value(detail['Vcs_peak'],'V'),'最低能量负载估算',value(detail['minimum_load'],'W')),
        ('Rreg 设置电阻',value(detail['Rreg'],'Ω'),'补偿档位 / A·V⁻¹',value(detail['compensation_gain'])),
        ('分压输出设定',value(detail['Vout_set'],'V'),'补偿直流偏置',value(detail['compensation_offset'],'V')),
        ('Rcomp / Ccomp',value(detail['Rcomp'],'Ω')+' / '+value(detail['Ccomp'],'F'),'Cpole',value(detail['Cpole'],'F')),
        ('COMP fz / fp',value(detail['fz'],'Hz')+' / '+value(detail['fp'],'Hz'),'gm / KP',value(detail['gm'])+' / '+value(detail['KP'])),
        ('静态/分压功耗',value(detail['P_controller'],'W'),'VCC',value(detail['Vcc'],'V')),
    ],[1.7,1.85,1.7,1.85])
    op=res['op']; wf=res['wf']; core=op.get('aggregate_op',op)
    def sample(fig):
        ax=fig.subplots(); t=np.asarray(wf['t']); phase=t%core['Ts']
        aux=np.where(phase<core['D']*core['Ts'],-op['V_in']*detail['Na']/detail['Np'],np.where(phase<(core['D']+core['Dp'])*core['Ts'],detail['Vaux'],0.))
        ax.plot(t*1e6,aux,label='辅助绕组端电压（未整流）')
        for k in range(2):
            start=(k+core['D'])*core['Ts']+detail['sample_blank']; end=(k+core['D']+core['Dp'])*core['Ts']
            if end>start: ax.axvspan(start*1e6,end*1e6,color=COLORS[2],alpha=.16)
        ax.set(title='PSR 辅助绕组与有效采样区间（绿色）',xlabel='时间 / μs',ylabel='V'); ax.legend(); ax.grid(alpha=.2)
    figure(doc,_chart((7.1,1.8),sample),'图 1-PSR  理想采样窗口示意；未重建漏感振铃与实际采样保持')
    paragraph(doc,'COMP 为 (Rcomp 与 Ccomp 串联) 并联 Cpole。PWM 环路含 gm、辅助分压与半周期延迟近似；内部斜坡、采样保持和动态补偿未精确建模，须 FRA 复核。PFM 不给此 Bode 裕度。',True)
    # Keep the full URL in the relationship, not as a long orphan paragraph.
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE
    citation=paragraph(doc,'依据：',True)
    link=OxmlElement('w:hyperlink')
    link.set(qn('r:id'),doc.part.relate_to(detail['source'],RELATIONSHIP_TYPE.HYPERLINK,is_external=True))
    run=OxmlElement('w:r'); prop=OxmlElement('w:rPr'); size=OxmlElement('w:sz'); size.set(qn('w:val'),'18'); prop.append(size)
    run.append(prop); label=OxmlElement('w:t'); label.text='MPS MP6005 Rev.1.1（2024-10-11）第 16、19–21、27 页'; run.append(label)
    link.append(run); citation._p.append(link)


def export_design_docx(path,p,op,wf,res,models=None,loop_error=None,corners=None,comparison=None,
                       *,mos_real_time=False,efficiency_curve=None,compensation_state=None,
                       document=None,case_label=None,save=True):
    """Write a complete .docx without mutating the design snapshot.

    MOS axis mode follows the GUI option, defaulting to stage unfolding for
    headless callers. Waveform contents share the power-page implementation.
    ``document`` appends the complete report to an existing Word document; its
    relationships, figure IDs, page fields and native equation counter remain
    owned by that single document. ``save=False`` avoids intermediate files.
    """
    from isolated_outputs import selected_params
    source_p=dict(p)
    fixed_hardware=any(key.startswith('_fixed_') for key in source_p)
    from device_curve_sources import effective_sources
    p=selected_params(effective_sources(p))
    if res.get('psr'):
        detail=res['psr']
        p.update(controller_type='type2',control_mode='Peak Current Mode',KP=detail['KP'],
                 fz1=detail['fz'],fp1=detail['fp'],A_sense=11.)
    caps=res.get('capacitors') or capacitor_data(p,op)
    loop=res.get('loop')
    if loop is None and models is not None and 'checks' not in res:
        try:
            loop=loop_data(dict(p,f_sw=op['f_sw']),models)
        except Exception as exc:
            loop_error=str(exc)
    checks=design_checks(p,op,wf,res,loop,loop_error)
    failed=[c for c in checks if c[3] in ('需复核','未计算')]
    stamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M %Z')
    doc=document if document is not None else new_document('开关电源设计评审报告',
        f"{TOPOLOGY.get(op['topology'],op['topology'])}  |  {value(p['P_out'],'W')}  |  {stamp}",
        '开关电源设计与环路分析  ·  设计计算报告')
    start_paragraph=len(doc.paragraphs)
    start_figure=len(doc.inline_shapes)
    if document is not None:
        section(doc,'完整设计核算' if case_label else '当前工况完整设计核算')
        hardware_scope=('磁芯、匝数、线径及补偿参数与另一端点相同。' if fixed_hardware else
                        '未成功固定有效磁件，保留可用的电气计算结果；补偿参数不变。')
        paragraph(doc,f"本部分所有参数、表格和波形对应 {case_label or '当前工况'}，输入电压为 {value(p['V_in'],'V')}。{hardware_scope}各节编号只在本工况内引用。")
    doc.add_heading('设计概览',1)
    paragraph(doc,f"本报告记录导出时的设计快照，面向研发与设计评审。共核查 {len(checks)} 项，{len(failed)} 项需复核。结果为分析模型估算，不代替样机实测、器件数据手册和安规认证。")
    from voltage_nodes import NOTE
    paragraph(doc,NOTE)
    table(doc,['输出端口（防反后）','电容端／反馈取样（防反前）','输入母线（防反后）'],[
        (value(op['V_out'],'V'),value(op.get('V_out_cap',op['V_out']),'V'),value(op.get('V_in_bus',op['V_in']),'V'))])
    table(doc,['电路需求','当前设定','说明'],[
        ('输入 / 输出电压',value(p['V_in'],'V')+' / '+value(p['V_out'],'V'),
         (case_label+' 输入端点；完整输入范围见报告开头') if case_label else '标称需求；扫描范围另见角点节（如有）'),
        ('总功率 / 主反馈路电流' if res.get('outputs') else '输出功率 / 电流',value(p['P_out'],'W')+' / '+value(op['I_out'],'A'),'所选路负载电阻 '+value(op['R'],'Ω')),
        ('开关频率设定',value(p['f_sw'],'Hz'),'MP6005 使用 250kHz PWM / 轻载降频' if res.get('psr') else 'QR 为频率上限；其余为固定频率'),
        ('控制方式',p['control_mode'],'当前补偿器：'+resolve_controller_type(p.get('controller_type','auto'),p['control_mode'])),
        ('纹波目标',value(p['ripple_target']*p['V_out'],'V'),'输出低频峰峰值目标'),
        ('环路目标',value(p.get('fc_target'),'Hz')+' / '+value(p.get('pm_target'),'°'),'导出不进行自动整定'),
        ('效率目标',f"{p['target_eta']*100:.1f}%",'仅比较已建模损耗口径'),
        ('预设设计效率',f"{op['eta_guess']*100:.2f}%",'工作点与波形的设计假设；不被最终效率覆盖'),
    ],[1.65,2.25,3.2])
    doc.add_heading('评审摘要',2)
    table(doc,['工作模式','模型效率','总损耗','低频纹波'],[
        (op['mode'],f"{res['eta']*100:.2f}%",value(res['P_total'],'W'),value(wf['ripple_pp'],'V'))])
    paragraph(doc,'优先复核：'+('；'.join(c[0] for c in failed) if failed else '本快照的已建模检查满足当前阈值，仍需完成额定值、热态和实测验证。'))
    paragraph(doc,'报告导航：工作点与核查 → 关键波形 → 功率器件 → 电容纹波 → 磁件 → 环路与补偿电路 → 损耗与效率 → 模型限制与输入参数。',True)

    section(doc,'0  拓扑、绕组与反馈架构')
    from topology_diagram import draw_topology,topology_components
    def topology(fig): draw_topology(fig.subplots(),source_p,op)
    rail_count=len(res.get('outputs',[]))
    figure(doc,_chart((7.1,6.4 if rail_count>3 else 4.6 if rail_count>1 else 3.4),topology),'图 0-1  与软件①页同步的拓扑参考图；工程示意，不是可生产原理图')
    rows=topology_components(source_p,op)
    table(doc,['位号','器件 / 用途','配置参数'],[(r['ref'],r['role'],r['values']) for r in rows],[1.,2.7,3.4])
    paragraph(doc,(f"反馈方式：{source_p.get('feedback_mode','SSR')}；主反馈/PSR基准：OUT{int(source_p.get('feedback_output',1))}。仅该路电压作为设定输入，其余路以整数副边匝数比估算；耦合解算电压另列，不作为独立稳压设定。" ) if res.get('outputs') or res.get('psr') else '当前采用兼容单路配置。')

    section(doc,'1  工作点与设计核查')
    table(doc,['计算量','结果','计算量','结果'],[
        ('导通占空比 D',value(op['D']),'续流 / 退磁占空比 Dp',value(op['Dp'])),
        ('实际开关频率',value(op['f_sw'],'Hz'),'开关周期',value(op['Ts'],'s')),
        ('电感 L',value(p['L'],'H'),'工作点输入匝比 N',value(p['N']) if op['topology'] in ('FLYBACK','QR-FLYBACK','ACF-FORWARD') else '不适用'),
        ('电感 / 原边峰值电流',value(op['I_L_pk'],'A'),'电流峰峰纹波',value(op['dI_L'],'A')),
        ('电感 / 原边谷值电流',value(op['I_L_min'],'A'),'工作模式',op['mode']),
        ('RHP 零点','耦合模型不沿用' if op.get('coupled_solution') is not None else value(op.get('rhp_zero'),'Hz'),
         '含 ESL 总纹波',value(wf.get('ripple_pp_total'),'V')),
    ],[2.2,1.35,2.2,1.35])
    table(doc,['核查项','计算值','目标 / 阈值','结论'],checks,[2.15,1.3,2.85,.8])
    paragraph(doc,f"温升上限为 {p.get('temp_rise_limit',40):g} K，GUI / API / 报告共用此阈值。窗口填充率未计骨架、绝缘和爬电空间；‘满足’仅表示数学模型内满足阈值。器件额定值及降额初筛见关键器件 BOM 节；额定电流、电容寿命与完整热态性能仍未核定。",True)
    from component_report import add_component_report
    add_component_report(doc, source_p, res)
    _output_report(doc,source_p,res)
    _psr_report(doc,source_p,res)
    from cross_regulation_report import add_report as add_cross_regulation_report
    add_cross_regulation_report(doc,source_p,res)
    if op.get('coupled_model'):
        from coupling_report import add_coupling_snapshot
        add_coupling_snapshot(doc,op)

    section(doc,'2  关键时域波形')
    paragraph(doc,'波形与软件②功率级页面共用绘图逻辑和导出快照；多路模式显示共享 Q1 电流、输入电流、Vds 和磁链等效量，支路电流与纹波在各路核算节列出。单路兼容模式顺序为 Q1 电流、D1 电流、输出纹波、输出电压。随后均展示 Q1 开通、关断过程。')
    if res.get('outputs'):
        paragraph(doc,f"本节 D1 为所选 OUT{int(source_p['feedback_output'])} 整流支路的通用波形标签；实际器件位号见图 0-1。其余输出分别见多路输出核算节。",True)
    paragraph(doc,'前四图为两周期模型波形，RMS 与峰值按相同采样计算。输出纹波与页面一致，以 mV 显示低频分量，不叠加 ESL 尖峰；电容分流和纹波 RMS 见第 4 节。',True)
    from stress_notes import DIODE_STRESS_NOTE, FLYBACK_STRESS_NOTE
    paragraph(doc,DIODE_STRESS_NOTE,True)
    def steady(fig):
        if res.get('outputs'):
            from multi_output_charts import draw_shared_power_signals
            draw_shared_power_signals(fig.subplots(2,2),op,wf)
        else:
            draw_power_signals(fig.subplots(2,2),op['topology'],wf)
    figure(doc,_chart((7.1,4.1),steady),'图 2-1  '+('共享 MOS 电流、输入电流、Vds 与磁链等效量' if res.get('outputs') else 'Q1 电流、D1 电流、输出纹波与输出电压')+'（按行排列）')

    section(doc,'2.1  Q1 开通与关断过程')
    _mos_gate_report(doc, res['semi']['switch'])
    paragraph(doc,'开通对应 t1–t4，关断对应 t5–t8；蓝色左轴为 Vgs，橙色右轴为 Vds。下图保留软件页面相同的分段颜色、边界、时间标注及电压曲线。')
    paragraph(doc,'导出时的 MOS 时间轴选项：'+('真实时间轴（ns）；时长未知时该图退回阶段展开。' if mos_real_time else '阶段展开（非等时长），各阶段下方标注实际时长。'),True)
    def switching(fig):
        draw_power_switching(fig.subplots(1,2),op,p,res,real_time=mos_real_time)
    figure(doc,_chart((7.1,2.9),switching),'图 2-2  Q1 MOS 开通 Vgs / Vds（左）与关断 Vgs / Vds（右）')
    switching_data=switching_voltage_data(op,p,res['semi']['switch'])
    table(doc,['过程','分段','阶段含义','时长','来源'],[
        ('开通' if i<=4 else '关断',f't{i}'+('*' if i in (4,5) else ''),
         STAGE_NAMES[f't{i}'],value(switching_data['times'][f't{i}'],'s'),
         '补充估算' if i in (4,5) else '栅电荷损耗模型') for i in range(1,9)],
        [.6,.65,1.5,1.4,2.95])
    for note in switching_data['notes']: paragraph(doc,note,True)
    paragraph(doc,'关断总栅阻包含 MOS 内部栅阻。交叠损耗只使用 t2+t3 与 t6+t7；上述曲线是分段重建参考，不是 SPICE 瞬态或实测结果。',True)

    from parasitic_report import add_report as add_parasitic_report
    add_parasitic_report(doc,source_p,res)
    section(doc,'3  功率器件参数与应力')
    from device_curve_report import add_device_source_report
    add_device_source_report(doc,source_p,res)
    stress=device_stress(op); names={'switch':'主 MOSFET','diode':'整流二极管','auxiliary':'钳位 MOSFET','freewheel':'续流二极管'}
    table(doc,['器件','耐压应力','峰值电流','有效值电流','平均电流'],[
        (names.get(k,k),value(v['V_max'],'V'),value(v['I_pk'],'A'),value(v['I_rms'],'A'),value(v['I_avg'],'A')) for k,v in stress.items()
    ],[1.7,1.35,1.35,1.35,1.35])
    paragraph(doc,DIODE_STRESS_NOTE)
    if op['topology'] in ('FLYBACK','QR-FLYBACK'):
        paragraph(doc,FLYBACK_STRESS_NOTE)
        clamp=op.get('clamp',{})
        valid_clamp=clamp.get('V_ceiling',0)>op['V_in']+op['V_r']
        table(doc,['MOS 电压量','当前结果','含义'],[
            ('阻断平台',value(clamp.get('V_plateau'),'V'),'Vin + Vreflect'),
            ('Kc 钳位上限',value(clamp.get('V_ceiling') if valid_clamp else None,'V'),
             'Vin + Kc × Vreflect；不叠加振铃裕度' if valid_clamp else '未配置有效 Kc>1；仅理想平台，未覆盖尖峰应力'),
            ('模拟波形峰值',value(clamp.get('V_peak'),'V'),'按漏感能量与钳位求得，可低于上限')],[1.6,1.3,4.2])
    else:
        paragraph(doc,'MOS 应力包含用户设定的 MOS 电压裕量，不将该裕量套用到二极管反压。')
    paragraph(doc,'计算应力不是器件额定值。选型需再核对 SOA、温度降额、反向恢复、雪崩和真实尖峰。')
    keys=['Rds_on','Coss','Qg','Vgs','Vf_diode','Qrr']
    if op['topology']=='ACF-FORWARD': keys+=['Rds_aux','Coss_aux','Qg_aux']
    table(doc,['器件 / 控制参数','符号','当前值'],[(PARAMS[k][0],k,value(p[k],PARAMS[k][1])) for k in keys],[3.7,1.5,1.9])
    from diode_report import add_diode_report
    add_diode_report(doc,source_p,res)
    doc.add_heading('器件损耗分项',2)
    table(doc,['器件','导通','开关 / 恢复','输出电容','栅驱动','合计 / W'],[
        (names[k],value(res['semi'][k].get('P_cond',0),'W'),value(res['semi'][k].get('P_sw_on',0)+res['semi'][k].get('P_sw_off',0)+res['semi'][k].get('P_rr',0),'W'),
         value(res['semi'][k].get('P_coss',0),'W'),value(res['semi'][k].get('P_gate',0),'W'),value(res['semi'][k]['P_total'],'W'))
        for k in names if k in res['semi']],[1.6,1.1,1.25,1.1,1.05,1])
    paragraph(doc,'主开关采用栅电荷时间法；栅极模型全参数见附录。正激钳位开关仅估算导通、栅驱动和 Coss 项，未建模开关交叠。QR 分支假定理想谷底开通，开通与 Coss 损耗记零；有源钳位正激不自动获得 ZVS 损耗减免。',True)

    section(doc,'4  电容组与纹波电流')
    caprows=[]; capnames=[]; capvals=[]; caplist=[]
    multiple=bool(res.get('outputs'))
    groups=[('共享输入' if multiple else '输入',caps['input'])]
    groups += [(f"OUT{row['id']}",row['capacitors']['output']) for row in res['outputs']] if multiple else [('输出',caps['output'])]
    if multiple:
        paragraph(doc,'共享输入仅列一次；全部 OUT 的电容详细结果统一列于本节。第 1.1 节只保留支路电压纹波与电流波形，不再重复电容 RMS 表格和柱状图。')
    for label,bank in groups:
        for i,c in enumerate(bank['caps'],1):
            name=f'{label} C{i}'; capnames.append(name); capvals.append(c['total']); caplist.append((name,c,bank['labels']))
            caprows.append((name,value(c['C'],'F'),value(c['ESR'],'Ω'),value(c['ESL'],'H'),value(c['total'],'A'),value(c['ESR']*c['total']**2,'W')))
    table(doc,['电容','容量','ESR','ESL','纹波 RMS','ESR 损耗'],caprows,[1.1,1.1,1.1,1.1,1.4,1.3])
    paragraph(doc,'；'.join(f"{label}组总纹波 {value(bank['total_bank'],'A')}" for label,bank in groups)+
              '。单只电流按各频率复阻抗分配，不能将单只 RMS 算术相加。额定纹波需按厂家频率、温度和寿命条件校验。',True)
    figure(doc,_bars(capnames,capvals,'各电容总纹波电流','有效值 / A',max(1.8,.25*len(capnames)+.65)),
           '图 4-1  单只电容总纹波电流（统一口径）')
    def harmonics(fig,items):
        axes=np.atleast_1d(fig.subplots(math.ceil(len(items)/2),2,squeeze=False)).ravel()
        ticks=[0,2,5,10,15,21]
        for ax,(name,c,labels) in zip(axes,items):
            ax.bar(np.arange(len(labels)),c['bands'],color=COLORS[0],width=.7)
            ax.set_xticks(ticks,['LF' if x==0 else labels[x] for x in ticks]); ax.set(title=name,xlabel='相对开关频率的频带',ylabel='RMS / A'); ax.grid(axis='y',alpha=.15)
        for ax in axes[len(items):]: ax.set_visible(False)
    if multiple:
        for index,(label,bank) in enumerate(groups,2):
            items=[(f'{label} C{i}',c,bank['labels']) for i,c in enumerate(bank['caps'],1)]
            figure(doc,_chart((7.1,1.9),lambda fig,items=items: harmonics(fig,items)),
                   f'图 4-{index}  {label} 电容 FFT 分带（仅列一次）')
    else:
        figure(doc,_chart((7.1,3.3 if len(caplist)>2 else 1.9),lambda fig: harmonics(fig,caplist)),
               '图 4-2  FFT 分带；LF < 0.5fs，HF > 20.5fs；稀疏显示刻度')
    paragraph(doc,'输入与输出电容 ESR 均计入最终损耗。整周期采样按全部 DFT 频点进行复阻抗分流，并以 Parseval 校核能量；仅非整周期采样采用平顶窗近似。单只 RMS 可因环流大于组总 RMS。',True)

    section(doc,'5  磁件设计与热评估')
    table(doc,['基础输入','当前值','基础输入','当前值'],[
        (PARAMS[a][0],value(p[a],PARAMS[a][1]),PARAMS[b][0],value(p[b],PARAMS[b][1]))
        for a,b in [('Bmax','Bsat'),('J','Ku'),('rho','Rth_transformer' if res['mag'].get('transformer') else 'h_conv'),('k_core','a_core'),('b_core','MLT')]
    ],[2.15,1.4,2.15,1.4])
    devices=[]
    for kind,label in [('transformer','变压器'),('inductor','电感')]:
        dev=res['mag'].get(kind)
        if not dev: continue
        if not dev.get('ok'):
            paragraph(doc,label+'未能选芯：'+str(dev.get('reason','未知原因'))); continue
        devices.append((kind,label,dev)); doc.add_heading(label+' · '+dev['core_label'],2)
        paragraph(doc,'磁芯尺寸来源：'+dev['core']+'；MLT 来源：'+dev['MLT_source']+'。',True)
        rows=[('有效截面积 Ae',value(dev['Ae']*1e6,'mm²'),'有效体积 Ve',value(dev['Ve']*1e6,'cm³')),
              ('窗口面积 Wa',value(dev['Wa']*1e6,'mm²'),'平均匝长 MLT',value(dev['MLT']*1e3,'mm')),
              ('峰值磁密',value(dev['B_pk'],'T'),'峰峰磁通摆幅',value(dev['dB'],'T')),
              ('窗口填充率',f"{dev['fill']*100:.1f}%",'估算温升',value(dev['dT'],'K')),
              ('铜损',value(dev['P_cu'],'W'),'磁芯损耗',value(dev['P_core'],'W'))]
        if kind=='transformer':
            equation(doc,'ΔT=(Pcu+Pcore)·Rth')
            rows += [('至环境热阻 Ri-a',value(dev['Rth_transformer'],'K/W'),
                      '温升计算',f"{dev['P_total']:.5g} W × {dev['Rth_transformer']:.5g} K/W = {dev['dT']:.5g} K")]
            rows += [('实际匝数 Np / Ns',f"{dev['Np']} / {dev['Ns']}",'实际匝比',value(dev['n_actual'])),
                     ('原 / 副边单股线径',value(dev['d_wire_p'],'m')+' / '+value(dev['d_wire_s'],'m'),'并绕股数',f"{dev['n_strand_p']} / {dev['n_strand_s']}"),
                     ('原 / 副边直流电阻',value(dev['R_dc_p'],'Ω')+' / '+value(dev['R_dc_s'],'Ω'),'交流修正系数',value(dev['Fr_p'])+' / '+value(dev['Fr_s']))]
            rows += [('原 / 副边 RMS 电流密度',value(dev['J_actual_p']/1e6,'A/mm²')+' / '+value(dev['J_actual_s']/1e6,'A/mm²'),
                      'DCR 来源','ρ × MLT × 匝数 / 总裸铜截面积')]
        else:
            rows += [('电感对流系数 h',value(dev['h_conv'],'W/(m²·K)'),
                      '经验散热面积',value(dev['A_surf'],'m²'))]
            rows += [('匝数',str(dev['N']),'估算气隙',value(dev['gap'],'m')),
                     ('单线线径',value(dev['d_wire'],'m'),'直流电阻 / Fr',value(dev['R_dc'],'Ω')+' / '+value(dev['Fr']))]
        table(doc,['计算参数','结果','计算参数','结果'],rows,[1.9,1.65,1.9,1.65])
    paragraph(doc,'磁芯损耗采用实际理想 B(t) 的 NSE 数值积分。铜损为直流电阻乘简化趋肤修正；未计邻近效应、端接损耗、热态电阻或绝缘填充。变压器温升 ΔT=(全部绕组铜损+磁芯损耗)×用户输入 Ri-a；默认 100 K/W 仅为初始假设，须按实测或热设计填写。独立电感保留经验表面积与对流模型。两者均不是局部热点温度或实测温升。',True)
    if devices:
        section(doc,'5.1  磁通波形与损耗分配')
        def flux(fig):
            axes=np.atleast_1d(fig.subplots(len(devices),1))
            for ax,(kind,label,dev) in zip(axes,devices):
                if kind=='inductor': B=op['L']*wf['iL']/(dev['N']*dev['Ae'])
                elif op['topology']=='ACF-FORWARD': B=op['Lm_forward']*wf['i_mag']/(dev['Np']*dev['Ae'])
                else: B=op['L']*wf['i_p']/(dev['Np']*dev['Ae'])
                ax.plot(wf['t']*1e6,B,label=label+' B(t)')
                from magnetic_plot import show_flux_range
                show_flux_range(ax,[B],p['Bsat'],unit='T')
                ax.set(xlabel='时间 / μs',ylabel='磁密 / T',title=label); ax.grid(alpha=.2)
        figure(doc,_chart((7.1,3.9 if len(devices)>1 else 2.6),flux),'图 5-1  磁通密度波形；纵轴按实际摆幅，±Bsat 数值见图内')
        figure(doc,_bars([label+' '+part for _,label,d in devices for part in ['铜损','磁芯损耗']],
                       [d[k] for _,_,d in devices for k in ['P_cu','P_core']], '磁件损耗构成',height=2.1),'图 5-2  磁件铜损 / 磁芯损耗')
        for kind,label,dev in devices:
            if kind=='transformer' and not math.isclose(dev['n_actual'],p['N'],rel_tol=.01):
                paragraph(doc,f"需复核：{label}实际匝比 {dev['n_actual']:.4g} 与工作点输入 N={p['N']:.4g} 不一致；整数匝数未回馈重算工作点。")

    from winding_report import add_winding_snapshot
    add_winding_snapshot(doc,source_p,res)

    section(doc,'6  环路与补偿器')
    if res.get('psr'): paragraph(doc,res['psr']['note'],True)
    kind=resolve_controller_type(p.get('controller_type','auto'),p['control_mode'])
    paragraph(doc,'二型：原点积分极点 + 一个有限零点 + 一个有限极点；三型：原点积分极点 + 两个有限零点 + 两个有限极点。名称中的原点极点不在频率输入框中另占一行。')
    table(doc,['当前补偿器参数','结果','作用'],[
        ('类型',kind,'独立于功率级控制方式；auto 根据 VM/PCM 选择'),
        ('KP',value(p['KP']),'积分器系数，不是无量纲比例增益'),
        ('fz1 / fp1',value(p['fz1'],'Hz')+' / '+value(p['fp1'],'Hz'),'有效有限零点 / 极点'),
        ('fz2 / fp2',value(p['fz2'],'Hz')+' / '+value(p['fp2'],'Hz'),'仅三型使用；二型忽略这两项'),
    ],[1.55,2.35,3.2])
    if loop:
        if loop.get('model'):
            model = loop['model']
            paragraph(doc,f"唯一主反馈路：OUT{model['feedback_output']}。"+model['assumptions'],True)
            from loop_report import add_capacitor_bank_snapshot
            add_capacitor_bank_snapshot(doc,model)
            if model.get('experimental'):
                table(doc,['临时频带限制','目标 fc','差分一致性误差','近似闭环极点'],[(
                    '已停用', value(p['fc_target'],'Hz'),
                    value(model['derivative_error']*100,'%'), '稳定' if loop['closed_loop_stable'] else '存在非稳定极点')])
        table(doc,['实际 fc','所选 PM','最小 PM','GM'],[(value(loop['fc'],'Hz'),value(loop['pm'],'°'),value(loop['min_pm'],'°'),
            '扫描范围内未检出' if (loop.get('gm_scan_limited') or loop.get('gm_band_limited')) and loop['gm_db'] is None else
            '未检出有限 -180° 穿越' if loop['gm_infinite'] else value(loop['gm_db'],'dB'))])
        def bode(fig):
            axes=fig.subplots(2,2)
            for idx,label in [(0,'对象 Gvc'),(1,'补偿器 Gc')]:
                axes[0,0].semilogx(loop['f'],20*np.log10(np.maximum(abs(loop['gains'][idx]),1e-300)),label=label)
                axes[0,1].semilogx(loop['f'],loop['phases'][idx],label=label)
            axes[1,0].semilogx(loop['f'],20*np.log10(np.maximum(abs(loop['gains'][2]),1e-300)),label='开环 T')
            axes[1,1].semilogx(loop['f'],loop['phases'][2],label='开环 T')
            axes[1,0].axhline(0,color=COLORS[1],ls='--',lw=.7); axes[1,1].axhline(-180,color=COLORS[1],ls='--',lw=.7)
            for ax in axes.flat:
                ax.set_xlabel('频率 / Hz'); ax.grid(which='both',alpha=.15); ax.legend(loc='best')
                if loop['fc']: ax.axvline(loop['fc'],color=COLORS[2],ls=':',lw=.8)
            axes[0,0].set(title='对象 / 补偿器幅频',ylabel='增益 / dB'); axes[0,1].set(title='对象 / 补偿器相频',ylabel='相位 / °')
            axes[1,0].set(title='开环幅频',ylabel='增益 / dB'); axes[1,1].set(title='开环相频',ylabel='相位 / °')
        figure(doc,_chart((7.1,4.2),bode),'图 6-1  当前参数 Bode 图；绿色线为所选下降穿越频率')
        multi = loop.get('multi_output')
        if multi:
            equation(doc,'T(s) = Gc(s)·Gb(s)')
            equation(doc,'Hj(s) = ','Gj(s)·Gc(s)','1 + T(s)')
            paragraph(doc,'Gb 是主反馈路对象，Gj 是第 j 路对象。所有输出使用同一个闭环分母，不为每一路分别标注 PM。参考响应图按各路直流电压归一化为相对变化率；负载输入的正方向为增大下拉电流。')
            from loop_charts import draw_multi_output_response
            selected = int(multi['feedback_output'])
            figure(doc,_chart((7.1,4.5),lambda fig: draw_multi_output_response(fig.subplots(2,2),loop,selected)),
                   '图 6-2  全部输出参考响应与主反馈路负载扰动；低频局部小信号，不是大信号阶跃')
            if multi['dc_load'] is not None:
                equation(doc,'Zjk(s) = Gjk(s) - ','Gj(s)·Gc(s)·Gbk(s)','1 + T(s)')
                table(doc,['被观察输出']+[f'OUT{r["id"]} 负载 / V·A⁻¹' for r in multi['outputs']],
                    [(f'OUT{rail["id"]}',)+tuple(f'{v:.5g}' for v in row)
                     for rail,row in zip(multi['outputs'],multi['dc_load'])])
                paragraph(doc,'上表为积分控制稳态下的局部负载灵敏度。负值表示增载导致电压下降，正值表示该路抬升；它是导数，不代表增加 1 A 后仍可按表线性外推。仅主反馈路的直流变化受到积分环路约束。')
        if len(loop['all_crosses'])>1:
            paragraph(doc,'存在多个 0 dB 穿越；所选 fc 是最接近目标的下降穿越，全部上升与下降穿越的最小 PM 用于核查。应结合 Nyquist、闭环极点与实测验证。',True)
            table(doc,['全部穿越 / Hz','方向','相位裕度 / °'],[
                (value(c['fc'],'Hz'),'下降' if c['direction']=='down' else '上升',value(c['pm'],'°'))
                for c in loop['all_crosses']],[2.5,1.6,3.0])
    else:
        paragraph(doc,'环路计算未能完成：'+str(loop_error or '未提供传递函数')+'。未用默认值替代真实结果。')
    if loop and loop.get('model',{}).get('experimental'):
        paragraph(doc,'周期映射模型独立保留各路电容与局部导通状态，不使用原单路 DCM/CCM 公式，也不重新乘预设效率。增益裕度仅检查扫描范围，未检出不代表无限裕量。高频寄生、真实采样控制及全部独立负载角点仍需 SPICE 与样机 FRA。',True)
    else:
        paragraph(doc,'模型边界：DCM/BCM 为低频单极点近似；普通 PWM 模型不含输出 ESR 零点。正激仅 CCM 电压模式含主输出 ESR，PCM 未含。'
              +('多路输出的两组电容均按刚性匝比折算，未建立支路独立动态与交叉调整率模型。' if res.get('outputs') else '单路兼容模型未包含第二并联电容。')
              +'未包含完整钳位谐振动态；PCM 斜坡回退不代表通过次谐波稳定验证。',True)

    from compensation_report import add_compensation_report
    compensation_available=add_compensation_report(doc,p,op,compensation_state,psr=bool(res.get('psr')))

    if op['topology']=='ACF-FORWARD' or (op['topology'] in ('FLYBACK','QR-FLYBACK') and p.get('Kc',0)>1):
        section(doc,'7  钳位与复位设计')
        if op['topology']=='ACF-FORWARD':
            rows=[(name,value(op[k],unit)) for k,name,unit in [
                ('Lm_forward','励磁电感','H'),('C_clamp','钳位电容','F'),('V_clamp','钳位基准电压','V'),
                ('V_reset','反向复位电压','V'),('V_clamp_hump','电压隆起估算','V'),('C_clamp_min','5% 隆起预算最小电容','F'),
                ('I_mag_pk','励磁峰值电流','A'),('I_clamp_rms','钳位电容有效值电流','A'),('f_clamp','Lm-Ccl 谐振频率','Hz'),
                ('f_clamp_effective','折算谐振频率','Hz'),('fc_recommended_max','建议 fc 上限','Hz')]]
            table(doc,['正激钳位 / 复位参数','计算值'],rows,[4.5,2.6])
            paragraph(doc,'原边通过双极性励磁电流完成伏秒复位；钳位电压隆起使用简化抛物线近似。未进行漏感换流、死区能量和 ZVS 充放电判据求解，因此不能据此宣称全负载软开关。')
            if 'v_clamp' in wf:
                def clamp(fig):
                    ax=fig.subplots(); ax.plot(wf['t']*1e6,wf['v_clamp']); ax.set(xlabel='时间 / μs',ylabel='电压 / V',title='有源钳位电容电压（简化波形）'); ax.grid(alpha=.2)
                figure(doc,_chart((7.1,2.2),clamp),'图 7-1  有源钳位电压与复位周期')
            for warning in op.get('warnings',[]): paragraph(doc,'模型提示：'+warning,True)
        else:
            from flyback_clamp import rcd_components
            r=rcd_components(op,p)
            table(doc,['RCD 参数','结果'],[(k,value(r.get(k),u)) for k,u in [('K',''),('Kc',''),('L_leak','H'),('V_clamp','V'),('R_snub','Ω'),('C_snub','F'),('P_res','W')]])
            paragraph(doc,'钳位 R/C 以同一波形模型的功耗 P 与电荷预算计算；R=Vc²/P，C≈P/(fs·Vc·ΔVc)。逐对耦合模型使用钳位支路积分，不叠加等效漏感能量；旧快速模型保留 Lσ=(1−K)Lp 的历史输入约定，K 不是 kij。RCD 功耗只计一次。')

    section(doc,'8  损耗构成与效率')
    losses=[('半导体','P_semi'),('磁件','P_mag'),('输入电容 ESR','P_cap_in'),('输出电容 ESR','P_cap'),('采样电阻','P_sense'),('RCD 吸收','P_rcd'),('输入防反二极管','P_din'),('输出防反二极管','P_dout'),('有源钳位电容 ESR','P_clamp'),('MP6005 静态/分压','P_controller')]
    if res.get('P_parasitic',0):losses.append(('布线 / RC 吸收电阻','P_parasitic'))
    table(doc,['损耗类别','功率','占已建模损耗'],[(name,value(res.get(k,0),'W'),f"{res.get(k,0)/res['P_total']*100:.1f}%" if res['P_total']>0 else '未定义') for name,k in losses],[3.9,1.5,1.7])
    paragraph(doc,f"Pout={value(res['P_out'],'W')}；Pin（由损耗反算）={value(res['P_in'],'W')}；η=Pout/(Pout+ΣP)={res['eta']*100:.2f}%。")
    figure(doc,_bars([n for n,k in losses],[res.get(k,0) for _,k in losses],'当前工况损耗分配',height=2.25),'图 8-1  横向损耗分项，标签与数值独立布局')
    doc.add_heading('关键计算关系',2)
    equation(doc,'Pin,est=Po/η₀；U=Vo/η₀；Io=Po/Vo')
    equation(doc,'ηfinal=Pout/(Pout+Ptotal)')
    equation(doc,'Pcap=Σ_j(Rc,j·Ic,rms,j^2)')
    equation(doc,'PM=180°+arg(T(j2πfc))')
    paragraph(doc,'上述为原生 Word 数学对象。电容分流、磁芯 NSE 与补偿公式的完整定义详见《计算方法与公式说明》。',True)
    section(doc,'8.1  预设效率与最终计算效率')
    table(doc,['效率设计 / 复核','结果','说明'],[
        ('预设设计效率',f"{op['eta_guess']*100:.2f}%",'所有拓扑的工作点输入，保持固定'),
        ('预估输入功率 / 损耗预算',value(op['P_in_est'],'W')+' / '+value(op['P_loss_budget'],'W'),'Pin,est=Po/η；预算不再次加入损耗'),
        ('最终计算效率 / 差值',f"{res['eta']*100:.2f}% / {res['eta_delta']*100:+.2f} pp",'由实际已建模分项汇总；不是样机实测'),
        ('输入功率差值',value(res['P_in_delta'],'W'),'损耗反算 Pin − 预估 Pin；差值较大应调整预设并重新设计'),
    ],[2.2,2.25,2.65])
    paragraph(doc,'统一采用一阶等效输出电压负担 U=Vo/η、等效负载 R*=R/η，保持 Io=Po/Vo。效率预算包含整流压降，稳态不再另加旧参数 Vf；真实二极管参数仍参与最终损耗。波形、电容电流和磁件来自同一工作点，环路按固定预设作近似折算。效率本身不能唯一确定真实损耗分布，此模型不代替寄生参数仿真；损耗反算 Pin 与波形输入均值可能不同，不宣称已实现自洽迭代。',True)
    doc.add_heading('同一预设下的效率随负载变化',2)
    curve_errors=[]
    if efficiency_curve is not None:
        fractions=np.asarray(efficiency_curve['fracs'],dtype=float)
        etas=np.asarray(efficiency_curve['etas'],dtype=float)*100
        modes=list(efficiency_curve['modes'])
        if fractions.ndim!=1 or etas.shape!=fractions.shape or len(modes)!=len(fractions) or not len(modes):
            raise ValueError('报告效率曲线长度或维度不一致')
        if not np.isfinite(fractions).all() or np.any(fractions<=0):
            raise ValueError('报告效率曲线负载比例无效')
        curve_errors=[f'{frac*100:.0f}%：{error}' for frac,error in efficiency_curve.get('failures',[])]
    else:
        fractions=np.linspace(.1,1.,5 if op.get('coupled_model') else 19); etas=[]; modes=[]
        for frac in fractions:
            try:
                from isolated_outputs import scale_load
                r=compute_design(scale_load(source_p,frac)); etas.append(r['eta']*100); modes.append(r['op']['mode'])
                if not math.isfinite(r['eta']): curve_errors.append(f'{frac*100:.0f}%：磁件 / 损耗结果无效')
            except Exception as exc:
                etas.append(np.nan); modes.append('无效'); curve_errors.append(f'{frac*100:.0f}%：{exc}')
    def efficiency(fig):
        ax=fig.subplots(); ax.plot(fractions*100,etas,marker='o',ms=3); ax.axhline(p['target_eta']*100,color=COLORS[1],ls='--',label='模型目标'); ax.legend()
        ax.set(xlabel='相对本报告输出功率 / %',ylabel='模型效率 / %',
               title='同一套固定磁件下重新求解各负载点' if fixed_hardware else '每个负载点重新求解工作点与磁件'); ax.grid(alpha=.2)
    figure(doc,_chart((7.1,2.5),efficiency),('图 8-2  '+case_label+' 输入下的效率曲线；预设不变，无效点留空') if case_label else '图 8-2  标称输入下的效率曲线；预设不变，无效点留空')
    sample_indices=sorted(set(np.linspace(0,len(fractions)-1,5,dtype=int)))
    table(doc,['负载','额定功率比例','模式','模型效率'],[(f'{fractions[i]*100:.0f}%',value(p['P_out']*fractions[i],'W'),modes[i],value(etas[i],'%')) for i in sample_indices])
    paragraph(doc,'磁芯、匝数、平均匝长与线径保持固定，仅重新求解负载工作点及对应损耗；该曲线是固定硬件的模型估算，不是实测效率曲线。' if fixed_hardware else '自动选芯 / 匝数会在每个负载点重新设计，因此该曲线是各工作点的重新计算结果，不是固定实物磁件的实测效率曲线。不能用此图替代整机效率验证。')
    for err in curve_errors: paragraph(doc,'曲线未计算点：'+err,True)

    if corners:
        section(doc,'8.2  固定硬件输入与负载角点')
        paragraph(doc,f"输入范围 {value(corners['v_in'][0],'V')}–{value(corners['v_in'][1],'V')}；共 {len(corners['corners'])} 个角点。固定标称磁芯、匝数、线径、L/C、器件和补偿参数，不在轻载点重新选芯或整定。QR 随运行点更新实际频率。未扫描温度与器件容差。")
        table(doc,['固定磁件','磁芯','匝数','单股线径'],[
            (k,d['core'],f"{d['Np']} / {d['Ns']}" if k=='transformer' else str(d['N']),
             value(d.get('d_wire_p',d.get('d_wire')),'m')) for k,d in corners['hardware'].items() if isinstance(d,dict)],
            [1.4,1.7,1.4,2.6])
        rows=[]
        for c in corners['corners']:
            rows.append((c['id'],value(c['V_in']),f"{c['load_frac']*100:g}%",c.get('mode','无效'),
                value(c['eta']*100,'%') if not c['skipped'] else '—',value(c.get('dT'),'K'),
                value(c.get('min_pm'),'°'),f"{len(c['failed_checks'])} 项复核" if not c['skipped'] else '无效'))
        table(doc,['角点','Vin / V','负载','模式','效率','最高温升','最小 PM','结论'],rows,
              [.55,.7,.55,.55,.9,1.,1.,1.85])
        names={'min_eta':('最低效率','%',100),'max_dT':('最高温升','K',1),
               'max_ripple_pp':('最大低频纹波','V',1),'max_V_sw_max':('最大主开关电压','V',1),
               'max_I_L_pk':('最大电感 / 原边峰值','A',1),'max_B_pk':('最大磁密','T',1),
               'min_pm':('最小相位裕度','°',1)}
        section(doc,'8.3  最坏角点追溯')
        table(doc,['最坏指标','数值','角点','输入与负载'],[
            (label,value(corners['worst'][k]*scale,unit),corners['worst_cases'][k]['id'],
             value(corners['worst_cases'][k]['V_in'],'V')+' / '+f"{corners['worst_cases'][k]['load_frac']*100:g}%")
            for k,(label,unit,scale) in names.items() if k in corners['worst']],[2.2,1.35,.75,2.8])
        def corner_plot(fig):
            axes=fig.subplots(1,3)
            for vin in sorted(set(c['V_in'] for c in corners['corners'])):
                points=[c for c in corners['corners'] if c['V_in']==vin and not c['skipped']]
                for ax,key,scale,label in zip(axes,['eta','dT','min_pm'],[100,1,1],['模型效率 / %','最高温升 / K','最小 PM / °']):
                    ax.plot([c['load_frac']*100 for c in points],[c.get(key)*scale if c.get(key) is not None else np.nan for c in points],marker='o',ms=3,label=f'{vin:g} V')
                    ax.set(xlabel='负载 / %',ylabel=label); ax.grid(alpha=.2)
            axes[0].legend()
        figure(doc,_chart((7.1,2.8),corner_plot),'图 8-3  固定硬件角点趋势；未定义点留空')
        # Group identical findings without dropping their corner identities.
        # Keep invalid points separate from review / undefined model checks.
        from design_checks import STATE_LABELS
        groups, notes = {}, {}
        for c in corners['corners']:
            if c['skipped']:
                key = ('invalid', c.get('error') or '无法计算该角点')
                findings = '无效点：'+key[1]
            else:
                failed_checks = [x for x in c['checks'] if x['state'] in ('review','undefined')]
                if not failed_checks:
                    continue
                key = tuple((x['id'],x['state'],x['note']) for x in failed_checks)
                findings = '；'.join(x['name']+'（'+STATE_LABELS[x['state']]+'）' for x in failed_checks)
                for x in failed_checks:
                    if x['note']:
                        notes[(x['name'],x['note'])] = None
            if key not in groups:
                groups[key] = ([],findings)
            groups[key][0].append(c['id'])
        for ids,findings in groups.values():
            paragraph(doc,'、'.join(ids)+'：'+findings,True)
        if notes:
            paragraph(doc,'复核口径：'+'；'.join(name+'：'+note for name,note in notes),True)

    if comparison:
        section(doc,'8.4  方案 A 与 B 对比')
        paragraph(doc,' / '.join(comparison['names'])+'。对比使用独立冻结快照；B 不写回当前设计，差值定义为 B−A。')
        paragraph(doc,'A / B 输入、输出与功率需求一致；不自动判定优劣。' if comparison['same_requirements'] else '注意：A / B 电路需求不同，不能直接按效率或应力判定方案优劣。')
        table(doc,['指标','方案 A','方案 B','B − A'],[(r['name'],value(r['a'],r['unit']),value(r['b'],r['unit']),value(r['delta'],'百分点' if r['unit']=='%' else r['unit'])) for r in comparison['metrics']],
              [2.35,1.55,1.55,1.65])
        def compare_plot(fig):
            axes=fig.subplots(1,2)
            for snap,name in [(comparison['a'],'A'),(comparison['b'],'B')]:
                lp=snap['res'].get('loop')
                if lp:
                    axes[0].semilogx(lp['f'],20*np.log10(np.maximum(abs(lp['gains'][2]),1e-300)),label=name)
                    axes[1].semilogx(lp['f'],lp['phases'][2],label=name)
            axes[0].axhline(0,color=COLORS[1],ls='--',lw=.7); axes[1].axhline(-180,color=COLORS[1],ls='--',lw=.7)
            for ax,label in zip(axes,['开环增益 / dB','开环相位 / °']):
                ax.set(xlabel='频率 / Hz',ylabel=label); ax.grid(alpha=.2)
                if ax.get_legend_handles_labels()[0]: ax.legend()
        figure(doc,_chart((7.1,2.7),compare_plot),'图 8-4  两个方案独立工作点的开环响应')
        section(doc,'8.5  方案输入差异与复核结论')
        if comparison['differences']:
            table(doc,['参数 / SI 值','方案 A','方案 B'],[(r['key'],value(r['a']),value(r['b'])) for r in comparison['differences']],[2.2,2.45,2.45])
        else:
            paragraph(doc,'两个方案的输入参数完全一致。')
        for snap,name in [(comparison['a'],'A'),(comparison['b'],'B')]:
            paragraph(doc,name+' 需复核：'+('；'.join(c['name'] for c in snap['checks'] if c['state'] in ('review','undefined')) or '已建模检查满足阈值。'))

    section(doc,'9  模型限制与评审建议')
    for text in [
        (f'需求边界：本部分仅核算 {case_label} 输入端点、指定输出和负载。两个输入端点的结果不证明区间内部所有输入、负载、温度和器件容差均合格；额定值及安规要求未核定，未执行全边界认证。' if case_label else '需求边界：标称输入、指定输出和负载是本次设计需求。角点扫描范围（如有）另见分析节，不等同额定输入范围；环境温度、器件容差、额定值及安规要求未核定，未执行全边界认证。'),
        ('稳态：耦合模型包含输入/输出防反固定压降，输出端口与反馈取样节点分开；输出电容采用恒直流电压边界，未包含 Coss/Cj 和完整寄生换流。' if op.get('coupled_solution') is not None else
         '稳态：端口与电容端按固定防反压降区分；非耦合工作点仍采用预设效率的等效负担近似，未独立解算全部压降和寄生换流。')+'波形不等于开关节点真实瞬态。',
        '效率：输入与输出电容 ESR 均计入；'+('MP6005 额外计入典型静态与分压功耗，但未覆盖完整控制 / 辅助供电。' if res.get('psr') else '未包含控制 / 辅助供电。')+'整流桥、PCB / 连接器、EMI 滤波、温度依赖与邻近效应未计。模型效率可能偏乐观，不能保证为实测上限或固定误差范围。',
        '磁件：磁芯材料参数应来自对应温度、频率、磁密的数据。面积乘积、气隙与对流表面积为工程近似；Bsat 应按最坏温度选取。',
        '环路：传递函数为工作点附近的线性近似。没有有限穿越不表示稳定；有多个穿越或非最小相位对象时应结合 Nyquist / 闭环极点。RHP 零点和钳位谐振附近需详细仿真。',
        ('补偿网络：MP6005 使用独立 gm-COMP 物理二型网络，由 Rcomp / Ccomp / Cpole 构成。⑨页原版 SSR 阻容正反算不用于 PSR；内部斜坡、采样和动态压降补偿仍需厂商模型或样机 FRA 核验。' if res.get('psr') else '补偿网络：使用⑨页的原版元件计算。其“二型简化支路”与⑤页的标准二型高频极点不一一对应；不能根据参考电路表自行认定零极点完全匹配。报告并列全部回代结果与目标，未替换第 6 节 Bode 的参数。'),
        '实施顺序：核对需求与额定值 → 使用热态参数重算 → 容差 / 输入 / 负载扫描 → SPICE 或样机波形 → FRA 环路测量与负载阶跃 → 修订评审结论。',
    ]: paragraph(doc,text)
    doc.add_heading('导出内容与可追溯性',2)
    paragraph(doc,'所有表格和图像均来自同一导出快照；导出不会修改设计或执行整定。附录记录主要输入。软件计算方法详见帮助菜单中的《计算方法与公式说明》。本报告不自动生成未在软件中输入的 BOM 型号或实测结论。')

    section(doc,'附录 A  计算输入参数快照')
    gate=['gfs','Vth','Vgp_on','Vgp_off','Qg_th','Qgs','Qgd','Rg_drive','Rs_on','Rs_off','Rg','k_sw']
    if res['semi']['switch'].get('gate',{}).get('mode') in ('current','curve'):
        gate.remove('Vgp_off')  # inactive manual draft is not a calculation input
    if res['semi']['switch'].get('gate',{}).get('mode') != 'current':gate.remove('gfs')
    if res['semi']['switch'].get('gate',{}).get('charge_mode')=='curve':
        gate=[k for k in gate if k not in ('Qg_th','Qgs','Qgd') and not (k=='Vgp_on' and res['semi']['switch']['gate']['mode'] in ('curve','current'))]
        paragraph(doc,'本设计采用 Vgs–Qg 曲线直接读取电荷，未采用的手动电荷草稿不列为计算输入；曲线条件、来源及有效电荷见功率级 MOS 核算。',True)
    if res['semi']['switch'].get('gate',{}).get('manual_case'):
        gate=[k for k in gate if k not in ('Vgp_on','Vgp_off','Qgs')]
        from mos_manual import normalize_events
        manual=normalize_events(p['mos_manual_events'])
        table(doc,['手动输入端点','事件','Vgp','零伏至平台 Qgs'],[
            ('Vinmin' if case=='min' else 'Vinmax','开通' if edge=='on' else '关断',
             value(manual[case][edge]['Vgp'],'V'),value(manual[case][edge]['Qgs'],'C') if p.get('mos_charge_mode')!='curve' else '由 Vgs–Qg 曲线读取')
            for case in ('min','max') for edge in ('on','off')],[1.3,1.,2.,2.8])
    table(doc,['栅电荷 / 开关时间输入','符号','值'],[(PARAMS[k][0],k,value(p.get(k,0.),PARAMS[k][1])) for k in gate],[3.8,1.4,1.9])
    paragraph(doc,'主开关 t1–t8 的时长、阶段含义与来源见第 2.1 节。栅电荷损耗时间按参考表的自然对数公式计算；图中的 t4/t5 为补充估算，不修改损耗。',True)
    section(doc,'附录 B  其他输入与配置')
    extra=['Np','Ns','d_wire_p','d_wire_s','n_strand_p','n_strand_s'] if res['mag'].get('transformer') else []
    extra += ['forward_dead_time','forward_d_max','ESR_clamp'] if op['topology']=='ACF-FORWARD' else []
    extra += ['Rs','A_sense','ma_slope']
    extra += ['Vf_din'] if p.get('d_in_enable') else []
    extra += ['Vf_dout'] if p.get('d_out_enable') else []
    if extra: table(doc,['其他输入','符号','值'],[(PARAMS[k][0],k,value(p[k],PARAMS[k][1])) for k in extra],[3.8,1.4,1.9])
    table(doc,['配置项','设定'],[(k,value(bool(p.get(k)) if k.endswith('_enable') else p.get(k))) for k in ['core_material','core_choice','core_choice_L','d_in_enable','d_out_enable','controller_type']]+[
        ('输入并联电容数量',str(len(caps['input']['caps']))),('当前输出并联电容数量',str(len(caps['output']['caps'])))],[3.8,3.3])
    if case_label:
        # Prefix only this append's headings/captions, including sections added
        # by compensation/coupling helpers. Do not rewrite equation XML/runs.
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        for item in doc.paragraphs[start_paragraph:]:
            if item.style.name.startswith('Heading') or item.style.name=='Caption':
                prefix=OxmlElement('w:r'); text=OxmlElement('w:t')
                text.set(qn('xml:space'),'preserve'); text.text=f'[{case_label}] '
                prefix.append(text)
                item._p.insert(1 if item._p.pPr is not None else 0,prefix)
        for shape in list(doc.inline_shapes)[start_figure:]:
            for prop in shape._inline.xpath('.//wp:docPr'):
                prop.set('descr',f'[{case_label}] '+prop.get('descr',''))
    if save:
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        doc.save(path)
    return dict(path=str(path),checks=len(checks),needs_review=len(failed),figures=len(doc.inline_shapes)-start_figure,
                loop_available=loop is not None,compensation_available=compensation_available)
