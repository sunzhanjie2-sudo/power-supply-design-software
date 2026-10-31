"""Operating-point Miller plateaus shared by loss, waveforms and reports.

Select manual plateaus or a measured/digitized curve lookup. Curve-derived gate
voltages are a static approximation, not a measured dynamic Miller plateau.
The TI SLUA618A effective-transconductance model remains for legacy designs only.
"""
import math

SOURCE = 'https://www.ti.com/lit/ml/slua618a/slua618a.pdf'


def _operating_gate(op, dev, direct_charge=False):
    def number(key, default):
        raw = dev.get(key, default)
        if isinstance(raw, bool):
            raise ValueError(f'MOS 参数 {key} 必须为有限数值，不能为布尔值')
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'MOS 参数 {key} 必须为有限数值') from exc
        if not math.isfinite(value):
            raise ValueError(f'MOS 参数 {key} 必须为有限数值')
        return value

    mode=dev.get('mos_miller_mode','auto')
    if mode not in ('auto','manual','curve','gfs'):
        raise ValueError('MOS 平台模式必须为 manual、curve 或旧版 auto/gfs')
    gfs = number('gfs', 0.) if mode in ('auto','gfs') else 0.
    if gfs < 0 or (mode=='gfs' and gfs==0):
        raise ValueError('旧版跨导模式需要正 gfs；常规计算请选择手动或曲线模式')
    if mode=='auto':mode='gfs' if gfs>0 else 'manual'
    vth = number('Vth', 2.5)
    vdrv = number('Vgs', 10.)
    ref = number('Vgp_on', 4.5)
    qth, qgs = number('Qg_th', 1.5e-9), number('Qgs', 2.5e-9)
    ion = max(float(op.get('I_sw_on', op.get('I_L_min', 0.))), 0.)
    ioff = abs(float(op.get('I_sw_off', op['I_L_pk'])))
    if op['topology'] == 'QR-FLYBACK':
        ioff = abs(float(op['I_L_pk']))
    if not all(math.isfinite(v) for v in (ion, ioff)):
        raise ValueError('MOS 开通/关断电流必须为有限数值')
    if not 0 < vth < ref < vdrv:
        raise ValueError('MOS 栅电荷参考要求 0 < Vth < Vgp_on < Vgs；Vgp_on 也是 Qgs 的参考平台')
    if qth < 0 or qgs < qth:
        raise ValueError('MOS 栅电荷法要求 Qgs >= Qg_th >= 0')
    if mode == 'manual':
        off = number('Vgp_off', 4.5)
        if off <= vth:
            raise ValueError('MOS 栅电荷法要求 Vgp_off > Vth；请核对关断平台电压')
        return dict(mode='fixed', label='手动固定平台（兼容模式）', gfs=gfs,
                    I_on=ion, I_off=ioff, Vgp_on=ref, Vgp_off=off,
                    Qgs_on=qgs, Qgs_off=qgs, Vgp_reference=ref,
                    notes=['手动平台：采用输入的开通/关断平台，不随输入电压自动调整；请按实际工况填写。'], source=SOURCE)

    info={}
    if mode=='curve':
        from mos_curves import validate_curve,gate_voltage
        curve=validate_curve(dev.get('mos_miller_curve'))
        read_vds=number('mos_curve_vds',0.) if curve['kind']=='output_family' else 0.
        extrapolations=[]
        try:
            on=gate_voltage(curve,ion,read_vds,extrapolations=extrapolations) if ion>0 else vth
            off=gate_voltage(curve,ioff,read_vds,extrapolations=extrapolations) if ioff>0 else vth
        except ValueError as exc:
            raise ValueError('MOS 平台曲线查值失败：'+str(exc)+'；请补充数据或切回手动平台') from exc
        if (on<vth or off<vth) and not extrapolations:
            raise ValueError('曲线查得的栅压不高于 Vth，请核对温度、门限与曲线定义，不自动限幅')
        floor_note=bool(on<vth or off<vth)
        if floor_note:on=max(on,vth);off=max(off,vth)
        info={k:curve[k] for k in ('kind','name','conditions','source','import_file','Tj_C','Vds_test_V','reviewed') if k in curve}
        info['read_vds']=read_vds if curve['kind']=='output_family' else None
        notes=['平台来自器件曲线反查的静态/脉冲栅压近似，不等同实测动态米勒平台；范围外沿端点趋势外推。']
        if extrapolations:notes.append('本工况使用电流曲线端点外推（'+str(len(extrapolations))+' 次查值），仅是趋势估算；须用器件数据或实测校核。')
        if floor_note:notes.append('低电流外推栅压低于阈值，采用 Vth 极限；不表示测得真实米勒平段。')
        if curve['kind']=='output_family':
            notes.append(f'Id–Vds 曲线族在用户指定 Vds={read_vds:g} V 处取各 Vgs 的电流，再沿 Vgs 分组反查；读取 Vds 固定，不冒充实际全段 Vds。')
        else:
            notes.append('Id–Vgs 转移曲线按声明的线性/对数坐标反查；测试 Vds、温度和脉冲条件按所选曲线，不自动插值温度。')
        if not curve.get('conditions') and 'Tj_C' not in curve:
            notes.append('导入数据未声明测试温度/条件，请回到规格书核对后再用于设计。')
    else:
        on, off = vth + ion/gfs, vth + ioff/gfs
        extrapolations=[]
        notes=['兼容旧配置：平台按 Vth+Id/gfs 近似，建议改为手动输入或曲线查值。']
    if not on < vdrv or not off < vdrv:
        raise ValueError(f'MOS 电流相关平台超出驱动能力：Vgp,on={on:.5g}V，'
                         f'Vgp,off={off:.5g}V，Vdrv={vdrv:g}V；请核对曲线/模型、Vth 和实际电流，不自动限幅')
    # Preserve Qg(th) and the reference Qgs point.  A constant incremental
    # Cgs above threshold gives separate current-dependent Qgs,on / Qgs,off.
    cgs = 0. if direct_charge else (qgs-qth)/(ref-vth)
    if not all(math.isfinite(v) for v in (cgs,qth+cgs*(on-vth),qth+cgs*(off-vth))):
        raise ValueError('MOS 等效栅电荷换算溢出，请核对参考电荷、单位和平台电压')
    if not direct_charge:notes.append('Qgs,on/off 按阈值以上等效 Cgs 从同一栅电荷参考点换算；Qg、Qgd、Coss 仍取输入值，未按 Vds/温度曲线修正。')
    notes.append('未计二极管反向恢复与位移电流尖峰；QR/有源钳位不据此判断 ZVS。')
    if ion == 0 or ioff == 0:
        notes.append('零电流事件取 Vgp=Vth、Qgs=Qg(th)、电流过渡段时长为零的极限；不代表实测存在平坦米勒段。')
    return dict(mode='curve' if mode=='curve' else 'current',
                label='曲线查值平台（栅压近似）' if mode=='curve' else '电流相关平台（旧跨导兼容）', gfs=gfs, curve_info=info,
                I_on=ion, I_off=ioff, Vgp_on=on, Vgp_off=off,
                Qgs_on=qth+cgs*(on-vth), Qgs_off=qth+cgs*(off-vth),
                Cgs_incremental=cgs, Vgp_reference=ref, notes=notes, source=SOURCE,extrapolations=extrapolations)


def operating_gate(op,dev):
    from mos_manual import normalize_events,manual_platform
    manual=bool(dev.get('mos_manual_events') and manual_platform(dev))
    selected=dev.get('input_voltage_case','min')
    event_values=None
    if manual:
        if selected not in ('min','max'):raise ValueError('MOS 输入工况须为 min 或 max')
        event_values=normalize_events(dev['mos_manual_events'])[selected]
        dev=dict(dev,Vgp_on=event_values['on']['Vgp'],Vgp_off=event_values['off']['Vgp'],Qgs=event_values['on']['Qgs'])
    charge_mode=dev.get('mos_charge_mode','manual')
    if charge_mode not in ('manual','curve'):raise ValueError('栅电荷来源须为 manual 或 curve')
    if charge_mode=='manual':
        gate=_operating_gate(op,dev)
        gate.update(charge_mode='manual',Qg_th=float(dev.get('Qg_th',1.5e-9)),
                    Qgd_on=float(dev.get('Qgd',3e-9)),Qgd_off=float(dev.get('Qgd',3e-9)),
                    Qg_on=float(dev.get('Qg',10e-9)),Qg_off=float(dev.get('Qg',10e-9)))
        if manual:
            gate.update(Qgs_on=event_values['on']['Qgs'],Qgs_off=event_values['off']['Qgs'],manual_case=selected,
                        label='手动四事件 '+('Vinmin' if selected=='min' else 'Vinmax'))
            gate['notes']=['本工况分别使用手动开通/关断 Vgp 与对应零伏至平台 Qgs，不共用另一输入端点的参数；随负载扫描时仍是用户指定的端点近似。']
        return gate
    from mos_gate_charge import validate_charge,branches,interpolate,read_charges
    curve=validate_charge(dev.get('mos_charge_curve'))
    pre,_=branches(curve)
    qth=interpolate(pre,float(dev.get('Vth',2.5)),extrapolate=curve['allow_extrapolation'])
    ref=pre[-1][0]
    proxy=dict(dev,Qg_th=qth,Qgs=curve['Qgs_ref_C'],Qgd=curve['Qplateau_end_C']-curve['Qgs_ref_C'])
    platform_mode=dev.get('mos_miller_mode','auto')
    auto_platform=platform_mode in ('curve','gfs') or (platform_mode=='auto' and float(dev.get('gfs',0))>0)
    if auto_platform:proxy['Vgp_on']=ref
    gate=_operating_gate(op,proxy,direct_charge=True)
    if manual:
        gate.update(manual_case=selected,label='手动四事件 '+('Vinmin' if selected=='min' else 'Vinmax'))
        gate['notes']=['平台取本输入端点的开通/关断手动值；对应 Qgs 由 Vgs–Qg 曲线读取。']
    gate.update(read_charges(curve,float(dev.get('Vth',2.5)),float(dev['Vgs']),gate['Vgp_on'],gate['Vgp_off']))
    gate.pop('Cgs_incremental',None)
    gate['notes']=[n for n in gate['notes'] if '等效 Cgs' not in n]
    temp='未声明（不假定25°C）' if curve['Tj_C'] is None else f"{curve['Tj_C']:g} °C"
    testid='未声明' if curve['Id_test_A'] is None else f"{curve['Id_test_A']:g} A"
    testv='未声明' if curve['Vds_test_V'] is None else f"{curve['Vds_test_V']:g} V"
    gate['notes'] += ['电荷直接读取所选 Vgs–Qg 曲线：Qg(th)/Qgs,on/off 只反查平台前上升段；Qgd 为已确认平台终点与起点电荷之差；总 Qg 在平台后按驱动电压读取。未用等效 Cgs 换算。',
        f"按用户要求，四个开关事件复用所选参考曲线：Id,test={testid}，VDD,test={testv}，Tj={temp}。未按实际电流/Vds自动重建栅电荷曲线，Qgd/总Qg可能相同；这是参考曲线复用近似。",
        '到平台的电荷 Qgs 与平台段电荷 Qgd 是不同物理量；不会为了得到四个不同数字而强行改变 Qgd。']
    if gate.get('charge_extrapolations'):
        gate['notes'].append('栅电荷存在端点外推：'+ '、'.join(dict.fromkeys(x['quantity'] for x in gate['charge_extrapolations']))+'。只延长对应前/后支路，负电荷取0物理下限；不是新增实测点。')
    return gate
