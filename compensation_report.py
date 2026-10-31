"""Report the current SSR reference network using the existing RC solvers.

No Tk dependency, cached UI text, tuning, or write-back to the loop inputs.
Word dependencies remain lazy and the caller supplies a detached UI snapshot.
"""
import math
from pathlib import Path
import sys

import comp_design as compd


NETWORKS = {
    'opamp3': ('普通运放补偿网络', 'opamp3_clean.png'),
    'gm3': ('跨导运放补偿网络', 'gm3.png'),
    'tl431nf': ('TL431 与光耦无快车道网络', 'tl431nf.png'),
    'tl431f': ('TL431 与光耦快车道网络', 'tl431f_clean.png'),
}
UNITS = {'': 1., 'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'μ': 1e-6,
         'm': 1e-3, 'k': 1e3, 'M': 1e6, 'G': 1e9}
PARTS = {
    'R1': ('上分压电阻 R1', 'Ω'), 'R2': ('电阻 R2', 'Ω'),
    'R3': ('电阻 R3', 'Ω'), 'C1': ('电容 C1', 'F'),
    'C2': ('外加电容 C2', 'F'), 'C3': ('电容 C3', 'F'),
    'R_pz': ('快车道电阻 R_pz', 'Ω'), 'C_pz': ('快车道电容 C_pz', 'F'),
    'R_LED': ('LED 串联电阻 R_LED', 'Ω'), 'Rpullup': ('光耦上拉 R_pullup', 'Ω'),
    'Copto': ('光耦结电容 C_opto', 'F'), 'CTR': ('光耦 CTR', ''),
    'gm': ('运放跨导 gm', 'S'), 'Vref': ('分压参考电压', 'V'),
    'Vout': ('当前反馈取样电压（防反前）', 'V'), 'R_lower': ('下分压电阻 R_lower', 'Ω'),
    'C2_tot': ('光耦目标并联总电容', 'F'),
    'R_LED_max': ('LED 电阻偏置建议上限', 'Ω'),
}


def network_key(label):
    if label in NETWORKS:return label
    label=str(label)
    if label.startswith('普通运放'):return 'opamp3'
    if label.startswith('跨导运放'):return 'gm3'
    if '无快车道' in label:return 'tl431nf'
    if '快车道' in label:return 'tl431f'
    raise ValueError('无法识别当前补偿参考网络。')


def compensation_snapshot(p, op, state):
    """Recompute from the current fields, not from the last clicked result."""
    if not state:
        raise ValueError('未提供⑨页的参考网络与输入；不使用默认电路替代当前设计。')
    key = network_key(state.get('key') or state.get('topo', ''))
    inputs = {}
    for name, entry in state.get('vars', {}).items():
        unit = entry.get('u', '')
        if unit not in UNITS:
            raise ValueError(f'{name} 的单位前缀无效：{unit}')
        value = float(entry['v'])*UNITS[unit]
        if not math.isfinite(value):
            raise ValueError(f'{name} 不是有限数值')
        inputs[name] = value
    targets = dict(KP=float(p['KP']), **{
        w: 2*math.pi*float(p[f]) for w, f in
        [('wz1','fz1'), ('wz2','fz2'), ('wp1','fp1'), ('wp2','fp2')]})
    reverse = state.get('dir') == 'rev'
    type2 = bool(state.get('type2', False))
    from plants import resolve_controller_type
    controller_type=resolve_controller_type(p.get('controller_type','auto'),p.get('control_mode','Voltage Mode'))
    exact_type2=not reverse and controller_type=='type2' and not type2
    vout = float(op.get('V_feedback',op.get('V_out_cap',op['V_out'])))
    args = [targets[k] for k in ('KP','wz1','wz2','wp1','wp2')]
    if reverse:
        parts = dict(inputs)
    elif exact_type2:
        parts = compd.type2_network_solve(key,targets['KP'],targets['wz1'],targets['wp1'],inputs,Vout=vout)
    elif key == 'opamp3':
        parts = compd.opamp_type3_solve(*args, inputs['R1'], type2=type2)
        parts['Vref'] = inputs['Vref']
    elif key == 'gm3':
        parts = compd.gm_type3_solve(*args, inputs['R2'], gm=inputs['gm'],
                                   R1=inputs.get('R1u') or None, type2=type2)
    else:
        common = dict(CTR=inputs['CTR'], Rpullup=inputs['Rpullup'],
                      Copto=inputs['Copto'], Vout=vout)
        if key == 'tl431nf':
            parts = compd.tl431_nf_solve(*args, inputs['R1'], inputs['R_LED'], **common)
        else:
            parts = compd.tl431_f_solve(*args, inputs['R1'], **common)
    if key == 'opamp3':
        realized = compd.opamp_type3_eval(*(parts[k] for k in ('R1','R2','R3','C1','C2','C3')))
    elif key == 'gm3':
        realized = compd.gm_type3_eval(*(parts[k] for k in ('gm','R1','R2','R3','C1','C2','C3')))
    elif key == 'tl431nf':
        realized = compd.tl431_nf_eval(*(parts[k] for k in
            ('CTR','Rpullup','Copto','R_LED','R1','R2','R3','C1','C2','C3')))
    else:
        realized = compd.tl431_f_eval(*(parts[k] for k in
            ('CTR','Rpullup','Copto','R_LED','R1','C1','R_pz','C_pz','C2')))
    if reverse and math.isfinite(realized['wp1']) and not math.isfinite(realized['wz2']) and not math.isfinite(realized['wp2']):
        controller_type='type2'
        exact_type2=True
    notes = [note.replace('④页','⑤页') for note in parts.get('warnings', [])]
    if exact_type2:
        notes.append('按⑤页二型实现：原点极点、fz1零点、fp1高频极点；未使用fz2/fp2，不用远端零极点近似抵消。')
        if key=='gm3' and not inputs.get('R1u'):
            notes.append('gm上分压R1未指定，按Vref=2.5V与当前反馈电压计算；实际芯片基准须核对。')
    if p.get('topology')=='QR-FLYBACK':
        notes.append('QR 的Gvc/Gc采用CS等效控制指令口径；实物L6565 COMP管脚的前馈缩放、电平转换与误差放大器仍需单独纳入。')
    buildable = True
    if parts.get('C2', 0) < 0:
        buildable = False
        notes.append('C2 计算为负值，不能作为实物电容安装。按当前 R_pullup 与 C_opto，'
                     '目标光耦极点高于其自身极点，不能靠并联正电容实现；代数回代匹配不代表可实现。')
    if key in ('opamp3','tl431nf','tl431f') and (key != 'opamp3' or 'Vref' in parts):
        vref = float(parts.get('Vref', 2.5))
        if vout <= vref:
            buildable = False
            notes.append('输出电压不高于分压基准，常规分压不能实现；不提供虚假的下分压阻值。')
            parts.pop('R_lower', None)
        else:
            parts['R_lower'] = parts['R1']*vref/(vout-vref)
        parts['Vref'] = vref
    parts['Vout'] = vout
    if key == 'gm3':
        notes.append(f"分压核验 Vref={vout*parts['R2']/(parts['R1']+parts['R2']):.6g} V，须与实际控制器基准核对。")
    if key.startswith('tl431'):
        notes.append('参考图中的 R_bias 与实际器件型号未自动设计，须另核对偏置电流。')
        if key=='tl431nf':
            notes.append('无快车道 LED 接独立偏置；R_LED 偏置上限沿用⑨页按 Vout 的初估，须用实际偏置电压复核。')
        if key == 'tl431f' and not exact_type2:
            notes.append('快车道存在高频增益地板；本表只复用⑨页的近似网络计算，不代表完整器件模型。')
        if parts.get('Copto', 0) > 0 and parts.get('Rpullup', 0) > 0:
            parts['fp_opto'] = 1/(2*math.pi*parts['Rpullup']*parts['Copto'])
            if parts['fp_opto'] < 10*p['fc_target']:
                notes.append('光耦自身极点低于 10×目标 fc，需复核光耦与反馈链的实际相位影响；此项不强制降低 fc。')
    return dict(key=key, direction='rev' if reverse else 'fwd', type2=type2 or exact_type2,
                exact_type2=exact_type2,legacy_type2=type2,controller_type=controller_type,
                active_fields=('KP','wz1','wp1') if controller_type=='type2' else ('KP','wz1','wz2','wp1','wp2'),
                inputs=inputs, parts=parts, targets=targets, realized=realized,
                buildable=buildable, notes=notes)


def snapshot_lines(data):
    """Concise desktop presentation of the shared, independently evaluated RC result."""
    from power_stage import fmt_eng
    key=data['key'];parts=data['parts']
    omitted={'opamp3':('R3','C3'),'gm3':('C1',),'tl431nf':('R3','C3'),'tl431f':('R_pz','C_pz')}
    lines=['标准二型：原点极点 + fz1 + fp1' if data['exact_type2'] else '参考网络阻容计算']
    for name,(label,unit) in PARTS.items():
        if name not in parts:continue
        if data['exact_type2'] and name in omitted[key]:
            lines.append(name+' 不装（省略该支路）')
        else:lines.append(label+' = '+fmt_eng(parts[name],unit))
    fields=[('KP','KP'),('fz1','wz1'),('fp1','wp1'),('fz2','wz2'),('fp2','wp2')]
    check=[]
    for label,name in fields:
        if name not in data['active_fields']:continue
        target,actual=data['targets'][name],data['realized'][name]
        match=math.isfinite(actual) and abs(actual-target)<=1e-6*max(abs(target),1e-30)
        divisor=1 if name=='KP' else 2*math.pi
        check.append(label+' '+fmt_eng(actual/divisor,'' if name=='KP' else 'Hz')+(' ✓' if match else '（与目标不符）'))
    lines.append('回代校验：'+'；'.join(check))
    if not data['buildable']:lines.append('当前阻容不可直接实现，见下列原因')
    lines.extend(data['notes'])
    return lines


def _equations(doc, data):
    """Native Word math, retaining the existing network equations."""
    from docx_layout import equation, paragraph
    key, parts = data['key'], data['parts']
    equation(doc, 'ω = 2πf')
    if data.get('exact_type2'):
        if key=='opamp3':
            formulas=['C1+C2=1/(KP·R1)','C2=(C1+C2)·ωz₁/ωp₁','R2=1/(ωz₁·C1)']
        elif key=='gm3':
            formulas=['C2+C3=gm·R2/[KP·(R1+R2)]','C3=(C2+C3)·ωz₁/ωp₁','R3=1/(ωz₁·C2)']
        elif key=='tl431nf':
            formulas=['C1=CTR·Rpullup/(KP·R_LED·R1)','R2=1/(ωz₁·C1)','C2=1/(ωp₁·Rpullup)-Copto']
        else:
            formulas=['C1=1/(R1·ωz₁)','R_LED=CTR·Rpullup·ωz₁/KP','C2=1/(ωp₁·Rpullup)-Copto']
        formulas.insert(0,'Gc(s)=KP·(1+s/ωz₁)/[s·(1+s/ωp₁)]')
    elif key == 'opamp3':
        if parts.get('C2') == 0 and parts.get('C3') == 0:
            formulas = ['C1=1/(KP·R1)', 'R2=1/(ωz₁·C1)']
        else:
            formulas = ['C1+C2=1/(KP·R1)', 'C2=(C1+C2)·ωz₁/ωp₁',
                        'R2=1/(ωz₁·C1)', 'R3=R1·ωz₂/(ωp₂-ωz₂)', 'C3=1/(ωp₂·R3)']
    elif key == 'gm3':
        formulas = ['KP=gm·R2/[(C2+C3)(R1+R2)]', 'ωz₁=1/(R3·C2)']
        if not (parts.get('C1') == 0 and parts.get('C3') == 0):
            formulas += ['ωz₂=1/(R1·C1)', 'ωp₁=(C2+C3)/(R3·C2·C3)',
                         'ωp₂=(R1+R2)/(R1·C1·R2)']
    elif key == 'tl431nf':
        formulas = ['C1=CTR·Rpullup/(KP·R_LED·R1)', 'R2=1/(ωz₁·C1)',
                    'C3=1/(ωz₂·R1)', 'R3=1/(ωp₁·C3)', 'C2=1/(ωp₂·Rpullup)-Copto']
    else:
        formulas = ['C1=1/(ωz₁·R1)', 'R_LED=CTR·Rpullup/(KP·R1·C1)',
                    'ωz₂=1/[(R_LED+R_pz)C_pz]', 'ωp₁=1/(R_pz·C_pz)',
                    'C2=1/(ωp₂·Rpullup)-Copto']
    for formula in formulas: equation(doc, formula)
    if 'R_lower' in parts:
        equation(doc, 'Rlower=R1·Vref/(Vo-Vref)')
    if data['direction'] == 'rev':
        paragraph(doc,'反向模式以所填阻容回代 KP 和零极点；本节关系式用于说明同一参考网络，'
                  '报告不会执行“反推并写入⑤页”。',True)


def add_compensation_report(doc, p, op, state, *, psr=False):
    from docx_layout import section, paragraph, table, figure
    from report_docx import value
    if psr:
        doc.add_heading('补偿电路适用性',2)
        paragraph(doc,'本设计采用 MP6005 PSR，物理 COMP 阻容及计算见 PSR 核算节。'
                  '⑨页 SSR 参考网络不适用，不重复套用 TL431 或运放网络。')
        return False
    try:
        data = compensation_snapshot(p, op, state)
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        doc.add_heading('6.1  补偿电路参数计算',2)
        paragraph(doc,'当前补偿电路未能计算：'+str(exc)+'。其余报告保留，不使用默认阻容或上次结果替代。')
        return False
    section(doc, '6.1  补偿电路参数计算')
    key, parts = data['key'], data['parts']
    paragraph(doc,NETWORKS[key][0]+'；'+('反向输入阻容回代' if data['direction']=='rev' else '正向由⑤页 KP 和零极点计算阻容')+
              ('；标准二型，保留有限高频极点。' if data['exact_type2'] else '；旧版简化支路。' if data['type2'] else '。')+
              '使用当前页面输入，未浏览⑨页也会重新计算。多路电压取当前主反馈路的实际工作点。')
    rows=[]
    for name,(label,unit) in PARTS.items():
        if name not in parts: continue
        v=parts[name]
        source='用户输入' if name in data['inputs'] else '电路计算'
        if name=='R1' and key=='gm3' and data['inputs'].get('R1u'): source='用户输入'
        if name=='Vout': source='当前工作点'
        if name=='Vref' and key.startswith('tl431'): source='TL431 模型基准'
        note='不可实现（负电容）' if name=='C2' and v < 0 else '省略 / 不焊' if v == 0 and name.startswith('C') else ''
        rows.append((label,value(v,unit),source,note))
    table(doc,['电路参数','数值','来源','说明'],rows,[2.5,1.5,1.45,1.65])
    from app_resources import resource_path
    image_path=resource_path('comp_images')/NETWORKS[key][1]
    if image_path.is_file():
        from PIL import Image
        with Image.open(image_path) as img: ratio=img.width/img.height
        figure(doc,image_path.read_bytes(),'图 6-3  当前补偿参考电路；位号与上表一致，非完整可生产原理图',
               width=min(7.1,3.3*ratio))
    else:
        paragraph(doc,'参考电路图资源缺失；未用其他网络的图替代。')
    section(doc,'6.2  补偿电路计算关系与回代核验')
    _equations(doc,data)
    from plants import resolve_controller_type
    kind=resolve_controller_type(p.get('controller_type','auto'),p['control_mode'])
    checks=[]
    for name,field in [('KP','KP'),('fz1','wz1'),('fz2','wz2'),('fp1','wp1'),('fp2','wp2')]:
        if field not in data['active_fields']:continue
        target,actual=data['targets'][field],data['realized'][field]
        enabled=not(kind=='type2' and name in ('fz2','fp2'))
        matched=math.isfinite(actual) and abs(actual-target) <= 1e-6*max(abs(target),1e-30)
        status=('⑤二型未启用该字段' if not enabled else '代数匹配，器件需复核' if matched and not data['buildable'] else
                '匹配' if matched else '未匹配 / 需复核')
        divisor=1 if field=='KP' else 2*math.pi
        unit='' if field=='KP' else 'Hz'
        checks.append((name,value(target/divisor,unit),value(actual/divisor,unit),status))
    table(doc,['量','⑤页当前目标','阻容回代结果','核验'],checks,[.65,1.8,1.85,2.8])
    if 'fp_opto' in parts:
        paragraph(doc,'光耦自身极点：'+value(parts['fp_opto'],'Hz')+'；负电容不能作为实现该目标极点的方法。',True)
    for note in data['notes']: paragraph(doc,'需复核：'+note,True)
    paragraph(doc,'回代表使用⑨页同一组 comp_design 求解与回代函数。标准二型只核验KP、fz1、fp1；'
              '旧版省略高频极点的简化支路单独保留。第 6 节 Bode 仍使用⑤页参数，'
              '不会因导出而替换为本节网络，也不因 KP 匹配而认定实物电路完全匹配。',True)
    return True
