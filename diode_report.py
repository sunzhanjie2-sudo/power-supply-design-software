"""Word-native formulas and explicit diode ownership, shared by XLSX export."""
from docx_layout import paragraph,table,equation,figure
from power_stage import fmt_eng
from diode_curves import cleanup_message


def add_diode_report(doc,p,res,*,charts=True):
    models=res.get('diode_models',[])
    if not models:return
    doc.add_heading('3.1 二极管导通损耗与曲线对应',2)
    paragraph(doc,'每条导入曲线按拓扑图位号绑定：X=Vf（V），Y=If（A）。按当前输入电压下的正向电流波形反查 Vf，逐点平均功率。输入防反使用脉冲输入电流，输出防反位于电容之后、使用直流负载电流。')
    equation(doc,'曲线积分：Pcond=1/Ts·∫_0^Ts Vf(If(t))·If(t) dt')
    equation(doc,'等步长周期采样：Pcond=Σ_(k=1)^Nsamples (If,k·Vf(If,k))/Nsamples')
    equation(doc,'未导入曲线：Pcond=Vf·Iavg')
    table(doc,['位号与用途','当前导通模型','导通损耗','恢复损耗','实际正向峰值'],[
        (m['ref']+' · '+m['role'],m['curve_name'] if m['model']=='vf_if_curve' else '固定 Vf',
         fmt_eng(m['P_cond'],'W'),fmt_eng(m.get('P_rr',0.),'W'),fmt_eng(m['I_max'],'A'))
        for m in models],[2.05,2.05,1.,1.,1.])
    paragraph(doc,'固定 Vf 与曲线二选一，不叠加 Rd·Irms²。反向恢复仍单列 Qrr·Vr·fs，Vf–If 曲线不能提供 Qrr。曲线温度/测试条件由用户名称区分，不自动修正结温。曲线仅用于损耗后处理；耦合换流与环路仍用固定 Vf 近似，旧动态电阻项已停用。',True)
    bank=p.get('diode_curves',{})
    used=[m for m in models if m['model']=='vf_if_curve']
    for m in used:
        c=bank[m['ref']];src=c.get('source',{})
        if cleanup_message(m):paragraph(doc,m['ref']+'：'+cleanup_message(m)+'。',True)
        paragraph(doc,m['ref']+' → '+c['name']+f"；{len(c['points'])} 点；If 范围 {m['curve_I_min']:.5g}–{m['curve_I_max']:.5g} A。"+
                  (('来源 '+src.get('filename','')+'；SHA256 '+src.get('sha256','')) if src else '来源未声明。'))
        if m['extrapolations']:paragraph(doc,m['ref']+'：'+'；'.join(m['extrapolations'])+'；仅按相邻端点线性趋势估算，外推负压降截为零，不代表数据手册覆盖。',True)
    if used and charts:
        from report_docx import _chart
        for start in range(0,len(used),4):
            group=used[start:start+4]
            def draw(fig,group=group):
                axes=fig.subplots((len(group)+1)//2,2,squeeze=False).ravel()
                for ax,m in zip(axes,group):
                    points=bank[m['ref']]['points']
                    ax.plot([pt[0] for pt in points],[pt[1] for pt in points],color='#2068A0')
                    ax.set(title=m['ref']+' · '+m['curve_name'][:28],xlabel='Vf / V',ylabel='If / A')
                    ax.grid(alpha=.2)
                for ax in axes[len(group):]:ax.set_visible(False)
            figure(doc,_chart((7.1,2.7*((len(group)+1)//2)),draw),
                   f'图 3-D{start//4+1} 二极管正向特性与位号绑定')
