"""Engineering comparison pages based on real switching, FRA and load corners."""
from datetime import datetime
from io import BytesIO
from pathlib import Path
import math
import numpy as np


def write_report(path,evidence,*,chart_images=None):
    from docx import Document
    from docx.shared import Cm,Pt,RGBColor
    from docx.enum.section import WD_ORIENT
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx_layout import equation
    from spice_export import SETTINGS,CHOICES
    prepared=iter(chart_images) if chart_images is not None else None
    doc=Document();section=doc.sections[0];section.orientation=WD_ORIENT.LANDSCAPE
    section.page_width=Cm(29.7);section.page_height=Cm(21)
    section.top_margin=section.bottom_margin=Cm(1.3);section.left_margin=section.right_margin=Cm(1.7)
    for key in ('Normal','Title','Heading 1','Heading 2'):
        style=doc.styles[key];style.font.name='Calibri';style.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'微软雅黑')
        fonts=style.element.get_or_add_rPr().rFonts
        for attribute in list(fonts.attrib):
            if 'theme' in attribute.lower():del fonts.attrib[attribute]
        style.font.color.rgb=RGBColor(0,0,0)
        for border in list(style.element.iter(qn('w:pBdr'))):border.getparent().remove(border)
    normal=doc.styles['Normal'];normal.font.size=Pt(10);normal.paragraph_format.space_after=Pt(5)
    doc.styles['Title'].font.size=Pt(23);doc.styles['Heading 1'].font.size=Pt(16);doc.styles['Heading 2'].font.size=Pt(12)
    footer=section.footer.paragraphs[0];footer.text='Power Design   |   '+evidence['model']+'   |   '
    field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
    def paragraph(text):return doc.add_paragraph(str(text))
    def fmt(value,unit=''):
        if value is None:return '未取得'
        if isinstance(value,str):return value
        number=float(value)
        return f'{number:.5g}'+(' '+unit if unit else '') if math.isfinite(number) else '无有效值'
    def table(headers,rows,widths):
        t=doc.add_table(rows=1,cols=len(headers));t.autofit=False
        for column,width in zip(t.columns,widths):column.width=Cm(width)
        borders=OxmlElement('w:tblBorders')
        for name in ('top','left','bottom','right','insideH','insideV'):
            border=OxmlElement('w:'+name);border.set(qn('w:val'),'single');border.set(qn('w:sz'),'4');border.set(qn('w:color'),'D9D9D9');borders.append(border)
        t._tbl.tblPr.append(borders)
        for cells,values,index in [(t.rows[0].cells,headers,-1)]+[(t.add_row().cells,row,i) for i,row in enumerate(rows)]:
            for j,(cell,value,width) in enumerate(zip(cells,values,widths)):
                cell.text=str(value);cell.width=Cm(width);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
                if index<0 or index%2==0:
                    shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'183B65' if index<0 else 'F1F5FA');cell._tc.get_or_add_tcPr().append(shade)
                for p in cell.paragraphs:
                    p.paragraph_format.space_before=Pt(2);p.paragraph_format.space_after=Pt(2);p.paragraph_format.line_spacing=Pt(12.5)
                    if j>0:p.alignment=WD_ALIGN_PARAGRAPH.CENTER
                    for run in p.runs:
                        run.font.size=Pt(9.5)
                        if index<0:run.font.bold=True;run.font.color.rgb=RGBColor(255,255,255)
        repeat=OxmlElement('w:tblHeader');t.rows[0]._tr.get_or_add_trPr().append(repeat)
        for row in t.rows:
            no_split=OxmlElement('w:cantSplit');row._tr.get_or_add_trPr().append(no_split)
        return t
    def page(title):
        heading=doc.add_heading(title,1);heading.paragraph_format.page_break_before=True
    def chart(draw,height):
        if prepared is not None:doc.add_picture(BytesIO(next(prepared)),width=Cm(25.8));return
        from matplotlib import rc_context
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        with rc_context({'font.sans-serif':['Microsoft YaHei','DejaVu Sans'],'font.size':9,'axes.unicode_minus':False}):
            fig=Figure(figsize=(10.1,height),layout='constrained');FigureCanvasAgg(fig);draw(fig)
            stream=BytesIO();fig.savefig(stream,format='png',dpi=170);stream.seek(0)
            doc.add_picture(stream,width=Cm(25.8))
    def axes_format(axes):
        for axis in np.asarray(axes,dtype=object).ravel():
            axis.grid(alpha=.2);handles,_=axis.get_legend_handles_labels()
            if handles:axis.legend(fontsize=7,loc='best')
    def row_values(rows):
        return [(r['metric'],r['unit'] or '—',fmt(r['design']),fmt(r['simulation']),
            '不判差' if r['delta_percent'] is None else f"{r['delta_percent']:+.2f}%",r['status']) for r in rows]
    def metric_table(rows):
        table(['指标','单位','设计计算','LTspice 实测','偏差','判定口径'],row_values(rows),[6.4,1.1,3.1,3.1,2.2,9.9])
    def entry(value):return fmt(value) if value is not None else '未测到交越'
    settings=evidence['settings'];qr=evidence.get('topology')=='QR-FLYBACK';forward=evidence.get('topology')=='ACF-FORWARD'
    noniso=evidence.get('topology') in ('BUCK','BOOST');buck=evidence.get('topology')=='BUCK'
    doc.add_paragraph('有源钳位正激计算精度复核报告' if evidence.get('precision_summary') else '仿真与设计计算对比报告','Title')
    paragraph(datetime.now().strftime('%Y年%m月%d日')+'    '+evidence['model']+('    '+evidence['topology']+' 控制器逻辑参考' if noniso else '    准谐振反激 L6565 逻辑参考' if qr else '    有源钳位正激 MP6005 逻辑参考' if forward else '    固定频率反激 SSR'))
    paragraph('本报告用同一套 L/DCR、MOS、二极管及并联 C/ESR 对照计算与实际 LTspice 开关仿真。先检查直流收敛和逐周期重复性，再评估电感、MOS、D1 电流、输出纹波、开关闭环 FRA 和负载阶跃。输入两端分别验证；单路交叉调整率不适用。数值不同、未收敛和缺失测量均保留。' if noniso else '本报告用同一套冻结磁件与器件，对照设计计算和实际 LTspice 开关仿真。先检查直流收敛及逐周期重复性，再评估原副边电流、各路输出纹波、开关闭环 FRA 与 min/max 负载交叉调整率。数值不同、未收敛与缺失测量均保留，不能据此视为硬件已验证合格。')
    if evidence.get('calculation_revision_note'):paragraph(evidence['calculation_revision_note'])
    paragraph('电压节点统一：输出、负载功率和交叉调整率取防反管后 outN；反馈取防反管前电容端 capN。主反馈目标为端口设定电压加该路固定防反压降。未启用防反管时两节点重合。')
    table(['工况','Vin / V','主反馈输出 / V','逐周期检查','实际 FRA','交叉调整率'],[
        (c['id'],fmt(c['voltage']),f"OUT{c.get('feedback_output',1)} "+fmt(c['measurements'].get(f"out{c.get('feedback_output',1)}_before")),
         c.get('periodicity',{}).get('reason','未完成'),
         '已测并通过复核' if c.get('loop',{}).get('available') else '待复核 / 未执行',
         '完整' if c.get('cross',{}).get('complete') else '部分 / 不适用 / 未执行') for c in evidence['cases']],
        [5.3,1.6,3.2,5.1,5,5.6])
    doc.add_heading('本报告的判定规则',1)
    paragraph('QR 周期按实际门极上升沿划分，统计频率范围、脉宽、峰值和谷底开通电压。变频或跳谷不直接判为失稳；不能形成可重复工作点时不发布有效 FRA 裕度。' if qr else '平均输出电压变化小，不等于不存在大小波。周期检查统计末段 64 个时钟的脉宽、峰值电流、停脉冲与周期二交替；未通过时不将标称偏差标为通过，也不据此给出有效线性化 FRA。')
    paragraph('FRA 使用 LTspice 原生时域注入，并以半幅在关键频点复核；频带限制在 fsw/10 以内。无增益或相位交越表示本次频带没有测到，不写成无限裕度。交叉调整率只统计末段已收敛、无保护的角点均值；阶跃过冲不作为交叉调整率。')
    paragraph('表中平均值、RMS 和极值优先来自 .meas；纹波 AC RMS 以实际 RAW 的时间加权积分计算。图片为重采样概览，不用图上采样点替代数值统计。')
    if evidence.get('precision_summary'):
        page('计算模型修订与精度复核')
        paragraph('同一硬件、同一 LTspice 实际结果；仅重算独立预测。表中各项按原单位列出，百分偏差仍在后续完整表逐项展示。')
        table(['Vin / V','指标','修订前计算','本版计算','LTspice'],[(fmt(r['voltage']),r['metric'],fmt(r['before']),fmt(r['after']),fmt(r['simulation'])) for r in evidence['precision_summary']],[2,9,5,5,4.8])
        paragraph('高频尖峰受恒定 Coss/Cj、理想边沿和网格影响；与稳态电压、电流 RMS 分开评价。角点末段收敛不表示启动品质合格。')
    page('控制器与仿真配置')
    keys=('frequency_hz','soft_start_mode','soft_start_ms','enable_delay_ms','cs_limit','comp_offset_v',
        'ss_comp_start_v','ss_comp_end_v','short_mode','scp_threshold_v','olp_enabled','olp_ms','ocp_hold_us','hiccup_off_ms',
        'slope_mode','slope','cs_filter_ns','comp_voltage_max','fra_start_hz','fra_stop_hz','fra_oct','fra_amplitude_pct',
        'fra_cycles','cross_hold_ms','cross_mode','cycle_tolerance_pct','fra_enabled','cross_enabled')
    if qr:
        from qr_spice_settings import applicable_keys
        keys=tuple(applicable_keys('QR-FLYBACK'))
    elif forward:keys=keys+('acf_dead_ns','acf_sync_resistance')
    elif noniso:
        from qr_spice_settings import applicable_keys
        keys=tuple(applicable_keys(evidence['topology']))
    values=[]
    for key in keys:
        number=settings[key];label=CHOICES.get(key,{}).get(int(number),fmt(number))
        if key not in CHOICES and SETTINGS[key][4]:label+=' '+SETTINGS[key][4]
        values.append((SETTINGS[key][3],label))
    chunks=[values[i:i+36] for i in range(0,len(values),36)] if noniso else [values]
    for chunk_index,chunk in enumerate(chunks):
        if chunk_index:page('控制器与仿真配置续')
        if len(chunk)%2:chunk.append(('',''))
        half=len(chunk)//2
        table(['配置项','配置','配置项','配置'],[(*chunk[i],*chunk[i+half]) for i in range(half)],[6.4,6.5,6.4,6.5])
    if qr:
        page('QR 模型与参数来源')
        paragraph('主界面的 f_sw 是 QR 设计频率上限；导出参数 FSW 仅用于测量窗口、步长和 FRA 设置，没有固定频率振荡器。ZCD 经 RC、钳位与检测延时触发开通，CS 比较触发关断。')
        paragraph('L6565 阈值与时序依据 ST 数据手册：https://www.st.com/resource/en/datasheet/l6565.pdf。参考资料不是硅模型验证证明。用户参考库的自定义启动保持、硬编码定时器未直接移植。')
        for note in (evidence['cases'][0].get('approximation_notes',[]) if evidence['cases'] else []):paragraph(note)
    elif noniso:
        page('Buck / Boost 控制器与计算口径')
        for note in (evidence['cases'][0].get('approximation_notes',[]) if evidence['cases'] else []):paragraph(note)
        paragraph('计算模型求解 iL(T)=iL(0) 及各颗电容的周期电荷平衡，再联立峰值比较条件。二／三型补偿在比较器指令域；实际管脚电压由明示的比例与偏置换算。输入前馈与斜坡在计算和仿真共用；并联电容的两个 ESR 状态分别保留。')
        equation(doc,'VCOMP = Voffset + ','uCS','kCOMP')
        equation(doc,'vL = L·','diL','dt')
        paragraph('Buck 高侧 P-MOS 的实际 Vgs、Vds 是负极性；图中明确使用正幅值 Vsg、Vsd 进行包络对比。单路电路的交叉调整率不适用，改看两端输入、负载阶跃与输出恢复；不虚构多路角点。')
    else:
        paragraph('自动斜坡为最大副边反射下降斜率的 0.75 倍，再与设计已有值取大值；这是工程起点，不是 MP6005 实测参数。报告按实际导出的斜坡重建计算环路，并同时保留原始计算环路。')
        paragraph('MP6005 SSR 软启动的 COMP 临时上限从 1.5 V 升至 3.5 V，结束后释放。340 ms 打嗝未观察完整时不宣称重启已验证。')
    if forward:
        page('有源钳位正激电路与计算口径')
        first=next((c for c in evidence['cases'] if c.get('acf')),None)
        if first:
            detail=first['acf'];hw=first.get('hardware',{})
            table(['电路项','同一套冻结硬件'],[
                ('变压器原边匝数',fmt(hw.get('Np'))),
                ('各路副边匝数',' / '.join(fmt(w['Ns']) for w in hw.get('windings',[]))),
                ('变压器励磁电感 / μH',fmt(detail['magnetizing_inductance_h']*1e6)),
                ('各路输出电感 / μH',' / '.join(fmt(x*1e6) for x in detail['output_inductors_h'])),
                ('低侧钳位电容 / nF',fmt(detail['clamp_capacitance_f']*1e9)),
                ('设计双边沿死区 / ns',fmt(detail['dead_time_s']*1e9)),
            ],[11,14.8])
        paragraph('主 N-MOS 导通时向副边传能，关断后每路输出电感通过各自的续流二极管维持电流。低侧 P-MOS 与钳位电容实现磁复位；输出电感不能当作变压器励磁电感。所有两两 kij 进入 LTspice，主副边同名端按正激方向连接。')
        equation(doc,'D≈','Np(Vout+Vf+Vblock)','Ns·Vinbus')
        equation(doc,'Vclamp≈','Vinbus','1−D')
        if first and first.get('calculation_model'):
            equation(doc,'v − R·i = L·','di','dt')
            equation(doc,'⟨iL⟩ = ','Vout','Rload')
            paragraph('前两式仅用于预设计；正式值来自完整两两互感 MNA 周期解与各路电荷平衡，约束 i(T)=i(0)、钳位电压周期重复及单路主反馈。绕组方程还含几何 DCR 的 R·i 压降；不按功率比例分配副边电流。')
            paragraph(first['calculation_model']['assumptions'])
            paragraph('环路从同一周期解线性化，联立各路每颗 C+ESR 独立状态；共享仿真控制器的斜坡定义。高频电流网格敏感时仍可列已收敛的直流电压，但不发布该点有效裕度。')
        else:
            paragraph('上述为 CCM、固定压降和小钳位纹波近似。计算器标称工作点仍保留预设效率的等效负担；物理 SPICE 直接计算实际器件损耗，不额外乘预设效率。漏感换流会减少副边有效传能时间，轻载路还可能进入 DCM，因此不应期待各路电压、占空比和电流按理想匝比严格吻合。')
            paragraph('交叉负载表另列独立直流近似，包含 CCM/DCM、DCR 与一阶换流损失；它不是完整两两矩阵解。实际开关闭环 FRA、各支路电流和纹波分别作为验证证据，不用直流近似代替开关仿真。')
    for case in evidence['cases']:
        title=case['id']+'  Vin '+fmt(case['voltage'],'V')
        page(title+' 运行与稳态检查')
        if not case['complete']:
            paragraph('本工况未完整完成，不提供有效对比结论。'+case.get('error','未取得数据'));continue
        quality=case['periodicity'];ctrl=case['controller']
        paragraph('实际运行至 '+fmt(case['actual_end_s']*1000,'ms')+'。'+quality['reason']+'；脉宽范围 '+fmt(quality['duty_min']*100,'%')+' 至 '+fmt(quality['duty_max']*100,'%')+'，峰值电流周期间跨度 '+fmt(quality['peak_span_percent'],'%')+'。')
        paragraph(('QR 无固定时钟人工斜坡；' if qr else '设计斜坡 '+fmt(case['slope']['design'],'V/s')+'；实际仿真斜坡 '+fmt(case['slope']['resolved'],'V/s')+'。')+('故障测试只观察保护行为，不对标称设计判差。' if case['fault_test'] else '同一输入端点比较，非反馈路不被强制为名义电压。'))
        metric_table([r for r in case['rows'] if not r['metric'].startswith('OUT')])
        def startup(fig):
            axes=fig.subplots(1,2);data=case['startup'];t=np.array(data['time'])*1000
            for key,y in data.items():
                if key.startswith('v(out'):axes[0].plot(t,y,label=key)
            axes[0].set(title='全部输出启动与负载阶跃',xlabel='时间 / ms',ylabel='V')
            for key in ('v(ss)','v(fault)'):axes[1].plot(t,data[key],label=key)
            axes[1].set(title='软启动与保护',xlabel='时间 / ms',ylabel='归一化电平');axes_format(axes)
        chart(startup,2.15 if noniso else 2.55)
        if case.get('steady_before_step'):
            steady=case['steady_before_step']
            paragraph('阶跃前 '+fmt(steady['window_s']*1000,'ms')+' 长窗口：'+steady['reason']+'。逐周期重复、阶跃前稳态与启动品质分别核查；角点末段收敛不代表启动过冲/掉压合格。')
        if case.get('fault_events_s'):paragraph('检测到保护触发：'+', '.join(fmt(t*1000,'ms') for t in case['fault_events_s'][:8]))
        page(title+(' 电感电流与控制过程' if noniso else ' 原边电流与控制过程'))
        def primary(fig):
            axes=fig.subplots(2,2);data=case['switching'];t=(np.array(data['time'])-data['time'][0])*1e6;design=case.get('design_switching')
            axes[0,0].plot(t,data['i(lp)'],label='LTspice 电感 L1' if noniso else 'LTspice 原边绕组')
            if design:axes[0,0].plot(t,design['i_p'],'--',label='计算 电感 L1' if noniso else '计算 原边绕组')
            axes[0,0].set(title='电感电流对比' if noniso else '原边电流对比',xlabel='时间 / μs',ylabel='A')
            cycles=quality['cycles'];x=np.arange(len(cycles))
            axes[0,1].plot(x,[100*r['duty'] for r in cycles],marker='.',lw=.7,label='每周期占空比')
            axes[0,1].set(title='QR 实际边沿占空比' if qr else '连续时钟脉宽重复性',xlabel='实际周期序号' if qr else '末段时钟序号',ylabel='占空比 / %')
            axes[1,0].plot(t,np.array(data['v(drain)'])-data['v(sense)'],label='LTspice |Vsd|（P-MOS）' if buck else 'LTspice Vds')
            axes[1,0].plot(t,np.array(data['v(gate)'])-data['v(sense)'],label='LTspice Vsg（P-MOS）' if buck else 'LTspice Vgs')
            if design:axes[1,0].plot(t,design['v_sw'],'--',label='计算 Vds 包络')
            axes[1,0].set(title='开关电压',xlabel='时间 / μs',ylabel='V')
            axes[1,1].plot(t,np.array(data['v(comp)'])-ctrl['COFF'],label='COMP − 零电流偏置')
            axes[1,1].plot(t,data['v(ramp)'],label='滤波 CS × 增益' if qr else '滤波 CS × 增益 + 人工斜坡')
            axes[1,1].set(title='实际 PWM 比较信号',xlabel='时间 / μs',ylabel='V');axes_format(axes)
        chart(primary,5.5)
        if qr:
            page(title+' QR 变频与谷底开通检查')
            table(['项目','测量或设计值'],[
                ('设计频率上限 / Hz',fmt(case['qr']['frequency_limit_hz'])),
                ('计算实际频率 / Hz',fmt(case['qr']['design_frequency_hz'])),
                ('仿真实际频率 均值 / 最小 / 最大 Hz',' / '.join(fmt(quality.get(k)) for k in ('frequency_mean_hz','frequency_min_hz','frequency_max_hz'))),
                ('开通前 Vds 平均值 / V',fmt(quality.get('turnon_vds_mean_v'))),
                ('开通前局部谷底 Vds 平均值 / V',fmt(quality.get('valley_vds_mean_v'))),
                ('设计 Coss / 仿真有效 Cds pF',fmt(case['qr']['design_coss_f']*1e12)+' / '+fmt(case['qr']['cds_f']*1e12)),
                ('ZCD 解析附加延时 / ns',fmt(ctrl['ZDELAY']*1e9)),
            ],[13,12.8])
            paragraph('开通 Vds 在门极达到切换阈值前 50 ns 读取，谷底来自同一关断末段的局部最小值。正的谷底电压表示谷底开通，不能称为真正零电压开通。ZCD 负载、非线性 Coss 与布局寄生尚需实物复核。')
            if case.get('switching',{}).get('v(zcd)') is not None:
                def qr_signals(fig):
                    axes=fig.subplots(2,1);data=case['switching'];t=(np.array(data['time'])-data['time'][0])*1e6
                    axes[0].plot(t,np.array(data['v(drain)'])-data['v(sense)'],label='Vds')
                    axes[0].set(ylabel='V',title='退磁后的漏极谐振与实际开通位置')
                    for key in ('v(zcd)','v(gate)'):axes[1].plot(t,data[key],label=key)
                    axes[1].set(xlabel='时间 / μs',ylabel='V',title='ZCD 下降触发与门极脉冲');axes_format(axes)
                chart(qr_signals,3.0)
            paragraph('计算与仿真波形按各自真实周期绘制。QR 环路使用峰值电流控制的周期平均低频近似，实际时域 FRA 用于核对模型和工作点。')
        if forward:
            page(title+' 有源钳位时序与磁复位')
            check=case.get('acf_timing',{});m=case['measurements']
            table(['核对项','LTspice 结果'],[
                ('门极交叠','未检测到' if check.get('overlap') is False else '存在／未完成'),
                ('主管开通前最小死区 / ns',fmt(check.get('main_dead_min_s')*1e9 if check.get('main_dead_min_s') is not None else None)),
                ('辅助管开通前最小死区 / ns',fmt(check.get('aux_dead_min_s')*1e9 if check.get('aux_dead_min_s') is not None else None)),
                ('励磁伏秒残差 / 等效平均 V',fmt(check.get('flux_residual_mean_v'))),
                ('钳位电容平均电压 / V',fmt(m.get('clamp_mean'))),
                ('钳位电容电压峰峰值 / V',fmt(m.get('clamp_ripple'))),
                ('钳位电容电流 RMS / A',fmt(m.get('clamp_current_rms'))),
            ],[13,12.8])
            def clamp_signals(fig):
                axes=fig.subplots(1,2);d=case['switching'];t=(np.array(d['time'])-d['time'][0])*1e6
                axes[0].plot(t,np.array(d['v(gate)'])-d['v(sense)'],label='主 MOS Vgs')
                axes[0].plot(t,d['v(auxgate)'],label='P-MOS Vgs（负压开通）');axes[0].plot(t,d['v(sync)'],'--',label='SYNC 引脚')
                axes[0].set(title='两管驱动与死区',xlabel='时间 / μs',ylabel='V')
                axes[1].plot(t,np.array(d['v(drain)'])-d['v(aclamp)'],label='钳位电容电压')
                axes[1].plot(t,np.array(d['v(vin_bus)'])-d['v(drain)'],label='变压器原边电压')
                axes[1].set(title='物理钳位电容与双极性磁复位',xlabel='时间 / μs',ylabel='V');axes_format(axes)
            chart(clamp_signals,3.)
            paragraph('SYNC 高电平关断 P 管、低电平允许其导通；辅助栅极为理想 AC 电平移位。伏秒检查扣除原边 DCR 压降，按完整 64 周期积分。模型不含磁芯饱和、真实 AC 耦合驱动下垂或器件非线性结电容；不能据此保证 ZVS。')
        elif noniso:paragraph('L1 为物理储能／滤波电感，D1 为实际续流／整流支路；不存在变压器原副边。所有 RMS/平均值均统计完整周期。')
        else:paragraph('原边绕组电流与励磁电流分开定义：耦合计算采用 i_primary，理想反激采用开关导通电流；不再把关断期间的励磁下降斜坡当作外部原边电流叠加。')
        for branch in case.get('branches',[]):
            i=branch['id'];page(title+f' OUT{i} '+branch.get('name','')+(' 二极管电流与输出纹波' if noniso else ' 副边电流与输出纹波'))
            metric_table([r for r in case['rows'] if r['metric'].startswith(f'OUT{i} ')])
            paragraph('输出端实际纹波 AC RMS：'+fmt(branch['simulation_ripple']['ac_rms'],'V')+'；峰峰值：'+fmt(branch['simulation_ripple']['pp'],'V')+'。')
            def output(fig):
                axes=fig.subplots(1,2);data=case['switching'];t=(np.array(data['time'])-data['time'][0])*1e6
                axes[0].plot(t,data[f'i(ls{i})'],label=f'LTspice D{i}' if noniso else f'LTspice LS{i}')
                if branch.get('design_current') is not None:axes[0].plot(t,branch['design_current'],'--',label='计算 二极管 D1' if noniso else '计算 副边绕组')
                axes[0].set(title='二极管电流对比' if noniso else '副边绕组电流对比',xlabel='时间 / μs',ylabel='A')
                actual=np.array(data[f'v(out{i})']);times=np.array(data['time'])
                actual-=np.trapezoid(actual,times)/(times[-1]-times[0]);axes[1].plot(t,actual*1000,label='LTspice 输出端纹波')
                if branch.get('design_ripple') is not None:
                    expected=np.array(branch['design_ripple']);expected-=np.mean(expected);axes[1].plot(t,expected*1000,'--',label='计算 输出电容纹波')
                axes[1].set(title='去直流后的输出纹波',xlabel='时间 / μs',ylabel='mV');axes_format(axes)
            chart(output,3.4)
            paragraph('保留各路独立电流，不按主反馈路筛选。寄生、ESL 与整流换流口径不同，纹波尖峰及二极管反压只并列展示；实际硬件尖峰仍需实测。')
            if forward:
                page(title+f' OUT{i} 输出电感与续流回路')
                table(['指标','设计计算','LTspice'],[
                    ('输出电感 / μH',fmt(case['acf']['output_inductors_h'][i-1]*1e6),'同一电感'),
                    ('电感电流 RMS / A',fmt(branch.get('choke_design_rms')),fmt(case['measurements'].get(f'out{i}_choke_rms'))),
                    ('电感电流峰值 / A',fmt(branch.get('choke_design_peak')),fmt(case['measurements'].get(f'out{i}_choke_peak'))),
                    ('电感电流谷值 / A',fmt(branch.get('choke_design_valley')),fmt(case['measurements'].get(f'out{i}_choke_valley'))),
                    ('续流管反压 / V','未含尖峰',fmt(case['measurements'].get(f'out{i}_free_reverse'))),
                ],[11,7.4,7.4])
                def choke_signals(fig):
                    axes=fig.subplots(1,2);d=case['switching'];t=(np.array(d['time'])-d['time'][0])*1e6
                    axes[0].plot(t,d[f'i(lo{i})'],label='LTspice 输出电感')
                    if branch.get('design_choke') is not None:axes[0].plot(t,branch['design_choke'],'--',label='计算 输出电感')
                    axes[0].set(title='输出电感电流',xlabel='时间 / μs',ylabel='A')
                    axes[1].plot(t,d[f'i(lo{i})'],label='电感电流')
                    axes[1].plot(t,d[f'i(ls{i})'],label='正激整流 / 绕组电流')
                    axes[1].plot(t,np.maximum(np.array(d[f'i(lo{i})'])-d[f'i(ls{i})'],0),label='续流电流近似')
                    axes[1].set(title='整流与续流电流分配',xlabel='时间 / μs',ylabel='A');axes_format(axes)
                chart(choke_signals,3.4)
                paragraph('续流电流图由 LO−整流绕组电流得到，含结电容换流时并非独立二极管端口实测；整流与续流管的反压均可能含寄生尖峰。选型仍需留有余量并实测。')
        if case['fault_test']:continue
        loop=case.get('loop',{});page(title+' 环路增益与裕度对比')
        if not loop.get('simulation'):
            paragraph('没有有效的开关闭环 FRA 数据：'+str(loop.get('error') or '未执行'))
        else:
            sim=loop['simulation'];design=loop['design'];original=loop.get('original')
            reconstructed=loop.get('measured_reconstruction')
            paragraph(loop['definition']['method']+'。频带 '+fmt(loop['definition']['start_hz'],'Hz')+' 至 '+fmt(loop['definition']['stop_hz'],'Hz')+'。'+('半幅关键点复核通过。' if loop.get('available') else '当前 FRA 尚不能作为有效裕度结论：'+str(loop.get('error'))))
            if loop.get('diagnosis'):
                paragraph(loop['diagnosis'])
            table(['指标','原始计算环路','按导出参数重建','LTspice FRA'],[
                (label,entry(original.get(key)) if original else '未取得',entry(design['loop'].get(key)),entry(sim['loop'].get(key)))
                for label,key in [('穿越频率 / Hz','fc'),('相位裕度 / deg','pm'),('增益裕度 / dB','gm_db')]],[6.6,6.4,6.4,6.4])
            if reconstructed:
                pt=reconstructed['point']
                paragraph('实测点复核：Ipk '+fmt(pt['ipk'],'A')+'、频率 '+fmt(1/pt['period'],'Hz')+'、电容端 '+fmt(pt['vcap'],'V')+'；输出电流固定比例 '+fmt(pt['current_scale'])+'。此曲线使用仿真工作点与电流校正，仅用于归因，并非独立预测。')
            def bode(fig):
                axes=fig.subplots(1,2)
                curves=[('实际参数的计算环路',design['loop'],'--'),('LTspice 开关闭环 FRA',sim['loop'],'-')]
                if reconstructed:curves.insert(1,('仿真稳态点重建（非独立预测）',reconstructed['loop'],'-.'))
                if original:curves.insert(0,('原始计算环路',original,':'))
                for label,data,style in curves:
                    axes[0].semilogx(data['f'],data['db'],style,label=label);axes[1].semilogx(data['f'],data['phase'],style,label=label)
                axes[0].axhline(0,c='gray',lw=.7);axes[1].axhline(-180,c='gray',lw=.7)
                axes[0].set(title='开环增益幅值',xlabel='Hz',ylabel='dB');axes[1].set(title='开环增益相位',xlabel='Hz',ylabel='deg');axes_format(axes)
            chart(bode,3.35)
            paragraph('采用测得频带中的交越，存在多个 0 dB 交越时列出较小相位裕度。未测到相位交越不写成无限增益裕度。参数重建仍保留计算器功率级近似；CS 滤波、消隐及开关寄生没有在计算模型中完整反映，不要求两条曲线必然重合。')
            page(title+' 功率级与补偿器频率响应')
            def components(fig):
                axes=fig.subplots(2,2)
                for j,(key,label) in enumerate((('plant','Gvc 功率级'),('compensator','Gc 补偿器'))):
                    sources=[(design,'设计点计算','--'),(sim,'LTspice FRA','-')]
                    if reconstructed:sources.insert(1,(reconstructed,'仿真稳态点重建','-.'))
                    for source,name,style in sources:
                        data=source[key];axes[j,0].semilogx(data['f'],data['db'],style,label=name);axes[j,1].semilogx(data['f'],data['phase'],style,label=name)
                    axes[j,0].set(title=label+' 幅值',xlabel='Hz',ylabel='dB');axes[j,1].set(title=label+' 相位',xlabel='Hz',ylabel='deg')
                axes_format(axes)
            chart(components,4.2)
            check=loop.get('amplitude_check')
            if check:
                checks=[(fmt(f),fmt(db),fmt(phase)) for f,db,phase in zip(check['f'],check['db_error'],check['phase_error'])]
                if len(checks)>16:page(title+' 半幅注入复核')
                middle=(len(checks)+1)//2
                paired=[(*checks[i],*(checks[i+middle] if i+middle<len(checks) else ('—','—','—'))) for i in range(middle)]
                table(['半幅频率 / Hz','Δ幅值 / dB','Δ相位 / deg']*2,paired,[4.3]*6)
            paragraph('注入点为理想隔离反馈输出至控制器输入；补偿器探针去除负反馈符号。原始与半幅工程、日志及 FRA 复数 RAW 均附于 ZIP，可在 LTspice 复核。')
        cross=case.get('cross',{})
        if not cross.get('supported'):
            paragraph('交叉调整率：'+str(cross.get('error') or '不适用或未启用'));continue
        page(title+' 交叉调整率与电压包络')
        if not cross.get('supported') or not cross.get('summary'):
            paragraph('未取得交叉调整率结果：'+str(cross.get('error') or '未执行或不适用'))
        else:
            paragraph(cross['coverage']+'。'+cross['note'])
            if cross.get('design_note'):
                paragraph('计算侧采用与标称相同的完整 kij 周期解、钳位与各路电荷平衡；不拟合仿真值。电压网格与高频电流网格分别检查，电流敏感的角点仅对直流电压包络给出有效结果。模型边界见前文。' if case.get('calculation_model') else cross['design_note'])
            paragraph(f"计划 {cross.get('total_cases',len(cross['records']))} 组，实际完成 {cross.get('simulated_cases',len(cross['records']))} 组；末段收敛 {cross.get('settled_cases',sum(r['settled'] for r in cross['records']))} 组，计算解有效 {cross.get('design_valid_cases',sum(r.get('design') is not None for r in cross['records']))} 组。")
            paragraph('全部角点完成且收敛。' if cross['complete'] else '覆盖或收敛尚不完整：以下为已收敛角点的观察包络，不作为完整负载范围的极值承诺。')
            summary=cross['summary'];rows=[]
            for calc,actual in zip(summary['design'],summary['simulation']):
                rows.append((f"OUT{calc['id']}"+(' 主反馈' if calc['feedback'] else ''),
                    fmt(calc['V_min'])+' ～ '+fmt(calc['V_max']),fmt(actual['V_min'])+' ～ '+fmt(actual['V_max']),
                    fmt(0 if abs(calc['cross_only_pct'])<1e-8 else calc['cross_only_pct']),fmt(actual['cross_only_pct']),
                    '完整' if calc['complete'] and actual['complete'] else '部分'))
            table(['输出','计算 Vmin 至 Vmax / V','仿真 Vmin 至 Vmax / V','计算交叉变化 / %','仿真交叉变化 / %','覆盖'],rows,[3.2,6,6,4,4,2.6])
            paragraph('“交叉变化”保持该路自身负载及 Vin 不变，仅改变其它路负载，取最大电压跨度除以该路参考电压；电压包络则包含自身负载变化。反馈只闭合所选一路，不能把所有输出视为独立稳压。')
            def cross_wave(fig):
                axis=fig.subplots();data=cross['waveform'];t=np.array(data['time'])*1000
                for key,y in data.items():
                    if key!='time':axis.plot(t,y,label=key)
                for record in cross['records']:
                    axis.axvline(record['end_s']*1000,c='gray',lw=.5,alpha=.5)
                axis.set(title='各路负载角点切换与输出平均电压的收敛过程',xlabel='时间 / ms',ylabel='V');axes_format([axis])
            chart(cross_wave,2.7 if len(rows)<=3 else 2.2)
            page(title+' 交叉调整率角点明细')
            rows=[]
            for record in cross['records']:
                vector=lambda x:' / '.join(fmt(v) for v in x) if x is not None else '未取得'
                status='收敛' if record['settled'] else record.get('error') or '未收敛'
                if record.get('retry'):status+='；独立长时间复核'
                if record.get('periodicity') and not record['periodicity']['stable']:status+='；'+record['periodicity']['reason']
                if record.get('design_error'):status+='；计算：'+record['design_error']
                if record.get('design_point',{}).get('current_mesh_verified') is False:status+='；高频电流仅参考'
                rows.append((record['id'],vector(record['powers']),vector(record.get('design')),vector(record.get('simulation')),
                    fmt(max(record.get('drift_percent',[float('nan')]))),status))
            table(['角点','OUT 顺序负载 / W','计算 OUT 顺序电压 / V','仿真 OUT 顺序电压 / V','末段漂移 / %','状态'],rows,[1.5,3.7,6.2,6.2,2,6.2])
            paragraph('以同一组 min/max 负载组合逐项比较，未指定某一组合必然最坏。高电压或低电压对应的角点由实际结果搜索；若末段仍漂移，请延长保持时间后重跑，不能把电容尚未放完电的瞬态电压当成最终交叉调整率。')
            for record in cross['records']:
                if not record.get('retry'):continue
                page(title+' '+record['id']+' 独立角点复核')
                paragraph('原扫描过程保留在前图。此角点的最终均值来自独立固定负载、从零启动的长时间复核；电路、互感及控制器不变。数据与日志在 '+record['retry']['folder']+'，并未平移或修整原扫描曲线。')
                def retry_chart(fig):
                    a=fig.subplots();d=record['retry']['waveform'];t=np.array(d['time'])*1000
                    for key,y in d.items():
                        if key!='time':a.plot(t,y,label=key)
                    a.set(title='固定负载从零启动与末段收敛',xlabel='时间 / ms',ylabel='V');axes_format([a])
                chart(retry_chart,4.)
    page('计算口径与复核边界')
    equation(doc,'δ=100%×','S−C','C')
    paragraph('S 为仿真值，C 为设计值。只对相同工况、量纲且通过有效性检查的非零基准计算有符号偏差。频带、模式、寄生或统计口径不同的值仅并列展示。')
    if noniso:
        paragraph('三个原型均为原创可配置行为模型；本轮不包含独立原厂模型验证。反馈为理想电阻比例，误差放大器由二／三型传递函数实现，尚未覆盖芯片全部模拟特性及保护模式。')
        paragraph('快速闭环关闭 Coss/Cj 和门电容边沿，不用于尖峰或动态开关损耗签核；可选常数结电容模式保留这些近似。计算周期模型不含这些快边沿、ESL、传播延时或反向恢复，实际器件与样机仍需复核。')
        paragraph('ZIP 保留完整输入、模型、两端工程、日志、实际 FRA 复数 RAW 和 comparison.json。单路负载阶跃已在启动图中展示；多路交叉调整率不适用。普通大瞬态 RAW 不打包，可按工程重跑。')
        Path(path).parent.mkdir(parents=True,exist_ok=True);doc.save(path);return
    for text in (
        ('QR 采用 L6565 逻辑参考，单路 SSR 事件驱动模型；用户参考库仅用于研究，不等同厂家认证模型。外部参考缓升、理想 VCC、理想辅助电压映射与看门狗均为明确假设。' if qr else '通用固定频率 SSR 控制器参考 MP6005 的公开时序，不是完整芯片模型。人工斜坡、外部 CS 滤波、SCP 独立消隐和部分器件寄生为显式工程参数，需用目标芯片或实测复核。'),
        'MOS 为 Ron、常数 Coss、等效门电容和受控开关；二极管为固定 Vf 与通用结电容。未完整建模反向恢复、温度和器件非线性。磁芯为线性模型，不包含饱和与磁芯损耗。',
        ('正激矩阵周期模型与实际 SPICE 均包含 kij 和物理钳位；计算器仍采用刚性电容端和理想门极边沿，波形峰值对寄生与网格敏感。未启用矩阵时保留显式标称近似。差异用于定位模型缺项，不拟合仿真曲线。' if forward else '计算器耦合周期模型与完整 SPICE 在输出电容变化、ESR/ESL 和开关寄生方面存在差异；FRA 与交叉调整率用于找出这些差异，不修改结果使其人为吻合。'),
        '理想隔离反馈没有真实光耦/TL431 的延时及 CTR。开关 FRA 只验证该导出电路，不能替代实际反馈器件和样机 FRA。',
        'ZIP 保留全部输入、模型、各端点工程、日志、FRA 复数 RAW 和 comparison.json。普通瞬态大 RAW 不打包，可按工程重跑。模型与证据均未取得时保持空缺，不补零。'):
        paragraph(text)
    Path(path).parent.mkdir(parents=True,exist_ok=True);doc.save(path)
