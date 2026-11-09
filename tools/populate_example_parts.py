"""Apply the reviewed, versioned reference-part catalogs to shipped examples.

This is a maintenance command, never an import-time mutation or a user-project
upgrader. Requirements/turns/winding layouts are preserved; old unrelated demo
curves are explicitly retired and all model assumptions travel with each part.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config_io import decode_config
from design_engine.specification import load_spec
from component_management import component_registry, normalize_management
from capacitor_banks import bank, output_ref

LIB = ROOT/'resources/components'
PASSIVES = json.loads((LIB/'example_passive_parts.json').read_text('utf-8'))['parts']
SEMIS = json.loads((LIB/'example_semiconductor_parts.json').read_text('utf-8'))['parts']
SUPPORT = json.loads((LIB/'example_support_parts.json').read_text('utf-8'))
RCD_BASIS = SUPPORT['rcd_candidate_sizing_basis']['worst_power_W']


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', 'utf-8')


def identity(part, *, extra=''):
    out = {k: copy.deepcopy(part[k]) for k in ('manufacturer','model','package','voltage_V','power_W','ripple_A','capacitor_type') if k in part}
    sources = part.get('sources') or [part.get('source_url', '')]
    urls = [r['url'] if isinstance(r, dict) else r for r in sources]
    out['conditions'] = (part.get('conditions') or part.get('source_document') or '')[:1000]
    out['note'] = '；'.join(filter(None, [part.get('note'), extra, '资料：'+' '.join(urls)]))[:1000]
    return out


def cap_choice(value, voltage):
    if voltage > 90:
        return 'B32774D4106K000'
    if value < 30e-6:
        return 'B32774D4106K000' if voltage > 55 else 'B32522C0106K000'
    if voltage > 45:
        return 'EEUFS2A221'
    if value >= 400e-6:
        return 'EEUFR1H471'  # same 470µF, higher verified ripple capability
    if value >= 270e-6:
        return 'EEUFR1H331L'
    if value >= 160e-6:
        return 'EEUFR1H221'
    return 'EEUFR1H101'


def capacitor_bank(values, voltage, prefix, refs, selections):
    result = []
    for old in values:
        # 440µF is an aggregate, not a fictitious single 440µF catalog part.
        chunks = [220e-6,220e-6] if math.isclose(old['C'],440e-6,rel_tol=1e-8) else [old['C']]
        for nominal in chunks:
            key = cap_choice(nominal, voltage)
            part = PASSIVES[key]
            result.append(copy.deepcopy(part['calculation']))
            ref = prefix(len(result))
            refs[ref] = identity(part, extra='额定纹波仅对应所列频温条件，跨条件需修正；ESL及阻抗代理见参数来源。')
            selections[ref] = dict(catalog='passive', key=key)
    return result


def legacy_bank(config, caps, side='output'):
    fields = ('Cin1','Rcin1','ESLin1','Cin2','Rcin2','ESLin2','cin2_enable') if side=='input' else ('C_out','Rc','ESL','C_out2','Rc2','ESL2','cout2_enable')
    config[side+'_capacitors'] = copy.deepcopy(caps)
    for keys,cap in ((fields[:3],caps[0]), (fields[3:6],caps[1] if len(caps)>1 else {'C':0.,'ESR':0.,'ESL':0.})):
        for key,field in zip(keys,('C','ESR','ESL')):
            config[key] = cap[field]
    config[fields[-1]] = len(caps)>1


def apply_switching(raw, name):
    p = load_spec(raw)
    cfg = copy.deepcopy(raw)
    meta, selected = {}, {}
    topo = p['topology']
    high = max(p.get('V_in_min',p['V_in']),p.get('V_in_max',p['V_in'])) > 100
    psr = p.get('feedback_mode')=='PSR-MP6005'
    qkey = ('STP80N340K6' if high else 'DMP6023LE-13' if topo=='BUCK' else 'SI7450DP-T1-GE3' if psr else 'BSC500N20NS3-G')
    q = SEMIS[qkey]
    drive = p.get('Vgs',q['calculator_parameters']['Vgs'])
    cfg.update(q['calculator_parameters'])
    if qkey=='DMP6023LE-13' and drive < 10:
        cfg['Vgs'] = drive
        cfg['Rds_on'] = q['parameters']['Rds_on_max_at_4p5V_ohm']
    meta['Q1'] = identity(q, extra=('P-channel；计算采用|Vgs|/|Vds|幅值等效；Qg仍按数据手册参考条件，非四事件实测。' if q['parameters']['polarity']=='P' else '') +
                          (' MP6005 SSR/ACF若用10V栅驱动，需外部门驱动/偏置；不是内部8.5V直驱的保证Rds。' if not psr and not high and topo not in ('BUCK','BOOST') else ''))
    meta['Q1']['conditions'] += '；'+q['parameters'].get('Rds_condition','')+'；'+q['parameters'].get('gate_charge_condition','')
    meta['Q1']['conditions'] += '；'+q['parameters']['polarity']+'-channel'
    if qkey=='DMP6023LE-13' and drive < 10:
        meta['Q1']['conditions'] += f'；本例驱动幅值{drive:g}V，采用4.5V保证上限35mΩ；Qg为10V测试参考，非本工况保证。'
    selected['Q1'] = dict(catalog='semiconductor', key=qkey)
    if topo=='ACF-FORWARD':
        cfg.update(SEMIS['IRF9640PBF']['calculator_parameters'])
        meta['Q2'] = identity(SEMIS['IRF9640PBF'], extra='P-channel低侧钳位；-10V负栅外驱动假设，实际电平转换与体二极管恢复未完整建模。')
        selected['Q2'] = dict(catalog='semiconductor', key='IRF9640PBF')
        ck = 'B32652A6104K000' if p['C_clamp']>=75e-9 else 'B32652A6473K000'
        cfg['C_clamp'], cfg['ESR_clamp'] = PASSIVES[ck]['calculation']['C'], PASSIVES[ck]['calculation']['ESR']
        meta['C_CL1'] = identity(PASSIVES[ck]); selected['C_CL1'] = dict(catalog='passive', key=ck)
    # Explicitly stop binding old anonymous/demo curves to the new identities.
    retired = [key for key in ('mos_miller_curve','mos_charge_curve','diode_curves','mos_manual_events') if cfg.get(key)]
    cfg.update(device_curve_settings=dict(mode='fixed',overrides={}),mos_miller_mode='manual',mos_charge_mode='manual',
               mos_miller_curve={},mos_charge_curve={},mos_manual_events={},diode_curves={},gfs=0.)
    if topo=='QR-FLYBACK':
        cfg.setdefault('spice_config',{})['qr_cds_pf'] = cfg['Coss']*1e12
    main_diode = 'STTH8L06D' if high else 'STPS5H100B-TR' if topo in ('BUCK','BOOST','BUCK-BOOST') else 'ES3D-M3/57T'
    cfg['Vf_diode'] = SEMIS[main_diode]['calculator_parameters']['Vf_diode']
    cfg['Qrr'] = SEMIS[main_diode]['calculator_parameters'].get('Qrr',0.)
    cfg.update(Vf_din=SEMIS['STTH3R06S' if high else 'SS3H10-E3/57T']['calculator_parameters']['Vf_din'],
               Vf_dout=SEMIS['SS3H10-E3/57T']['calculator_parameters']['Vf_dout'])
    input_bank = bank(p,'input')
    if name=='3_OUTPUT_CROSS_REGULATION.json' and len(input_bank)==2:
        input_bank = [input_bank[0],copy.deepcopy(input_bank[0]),input_bank[1]]
    inp = capacitor_bank(input_bank,p.get('V_in_max',p['V_in']),lambda i:'C_IN'+str(i),meta,selected)
    legacy_bank(cfg,inp,'input')
    multi = bool(p.get('outputs') or psr)
    rails = p.get('outputs') or [p]
    newrails = []
    rail_diodes = {}
    for i,rail in enumerate(rails,1):
        dk = 'STTH8L06D' if topo=='ACF-FORWARD' and i==1 else main_diode
        if topo=='ACF-FORWARD' and i==1:
            cfg['Vf_diode'] = SEMIS[dk]['calculator_parameters']['Vf_diode']
            cfg['Qrr'] = SEMIS[dk]['calculator_parameters'].get('Qrr',0.)
        rail_diodes[f'D_O{i}' if multi else 'D1'] = dk
        if topo=='ACF-FORWARD':
            rail_diodes[f'D_F{i}' if multi else 'D2'] = dk
        actual = dict(p,**rail)
        # Output specs inherit only explicitly absent legacy capacitor fields.
        if rail.get('output_capacitors') is None:
            actual['output_capacitors'] = None
        output_bank = bank(actual)
        if name in ('3_OUTPUT_COUPLED_FLYBACK.json','3_OUTPUT_CROSS_REGULATION.json') and i==3 and len(output_bank)==2:
            output_bank = [output_bank[0],copy.deepcopy(output_bank[0]),output_bank[1]]
        caps = capacitor_bank(output_bank,abs(float(rail.get('V_out',p['V_out']))),
            lambda j,i=i:output_ref(i,j,multi),meta,selected)
        target = copy.deepcopy((raw.get('outputs') or [{}])[i-1] if p.get('outputs') else {})
        legacy_bank(target,caps)
        target['Vf_diode'] = SEMIS[dk]['calculator_parameters']['Vf_diode']
        target['Vf_dout'] = cfg['Vf_dout']
        target['Qrr'] = SEMIS[dk]['calculator_parameters'].get('Qrr',0.)
        if p.get('outputs'):
            newrails.append(dict(copy.deepcopy(rail),**target))
        elif i==1:
            legacy_bank(cfg,caps)
    if newrails:
        cfg['outputs'] = newrails
        legacy_bank(cfg,newrails[int(p.get('feedback_output',1))-1]['output_capacitors'])
    if topo in ('BUCK','BOOST','BUCK-BOOST'):
        lk = 'XAL7070-223MEC' if math.isclose(p['L'],22e-6,rel_tol=1e-6) else 'XAL7070-473MEC'
        induct = SUPPORT['parts'][lk]
        cfg.update(inductor_design_enabled=False, inductor_extra_loss=0., **induct['calculation'])
        cfg.setdefault('spice_config',{})['niso_inductor_dcr'] = cfg['inductor_dcr']
        meta['L1'] = identity(induct); selected['L1'] = dict(catalog='support',key=lk)
    # Register the controller reference, without claiming physical drive pins.
    controller = 'L6565D' if topo=='QR-FLYBACK' else 'TPS40200D' if topo=='BUCK' and p.get('control_mode')=='Voltage Mode' else 'LTC3864EMSE#PBF' if topo=='BUCK' else 'LM5022MM/NOPB' if topo=='BOOST' else 'MP6005GK-Z'
    sources = {'L6565D':('STMicroelectronics','SO-8','https://www.st.com/resource/en/datasheet/l6565.pdf'),
        'TPS40200D':('Texas Instruments','SOIC-8','https://www.ti.com/lit/ds/symlink/tps40200.pdf'),
        'LTC3864EMSE#PBF':('Analog Devices','MSOP-12 exposed pad','https://www.analog.com/media/en/technical-documentation/data-sheets/3864fa.pdf'),
        'LM5022MM/NOPB':('Texas Instruments','VSSOP-10','https://www.ti.com/lit/ds/symlink/lm5022.pdf'),
        'MP6005GK-Z':('Monolithic Power Systems','MSOP-10','https://www.monolithicpower.com/en/mp6005.html')}
    maker,pkg,url = sources[controller]
    ctrl_ref = 'U_PSR' if psr else 'U_CTRL'
    meta[ctrl_ref] = dict(manufacturer=maker,model=controller,package=pkg,conditions='控制器功能原型；本例仍使用通用可配置行为逻辑，未展开原厂模型/驱动/偏置。',note='资料：'+url)
    if high and topo!='QR-FLYBACK':
        meta[ctrl_ref]['note'] += ' MP6005 VIN最高80V，不允许直连本例高压输入；此处仅算法原型，须独立低压供电/启动/输入接口，尚未完成实装控制器匹配。'
    selected[ctrl_ref] = dict(catalog='controller',key=controller,url=url)
    # Active designators determine identities, never retired topology drafts.
    pc = load_spec(cfg)
    for row in component_registry(pc):
        ref, kind = row['ref'],row['kind']
        if ref in meta:
            continue
        if kind=='connector':
            meta[ref] = identity(SUPPORT['parts']['MKDS_2']);selected[ref]=dict(catalog='support',key='MKDS_2')
        elif kind=='diode':
            dk = 'US3M' if ref=='D_SN1' else 'STTH3R06S' if ref=='D_IN' and high else 'SS3H10-E3/57T' if ref=='D_IN' or ref=='D_OUT' or ref.startswith('D_B') else rail_diodes.get(ref,main_diode)
            meta[ref] = identity(SEMIS[dk], extra='未计入的Qrr/Cj保持未覆盖，不以零值宣称物理为零；反压另需实测寄生尖峰。')
            selected[ref] = dict(catalog='semiconductor',key=dk)
        elif kind=='resistor':
            if ref=='R_S1':
                rk = 'PWR221T-30-R330F' if math.isclose(p['Rs'],.33,rel_tol=1e-6) else 'WSLP2010R0200FEA' if math.isclose(p['Rs'],.02,rel_tol=1e-6) else 'WFMB2512R0500FEA' if math.isclose(p['Rs'],.05,rel_tol=1e-6) else 'WSLP2010R0150FEA'
                # Sparse example defaults use the current input's actual Rs.
                cfg['Rs'] = PASSIVES[rk]['resistance_ohm']
                meta[ref] = identity(PASSIVES[rk]);selected[ref] = dict(catalog='passive',key=rk)
            elif ref=='R_SN1':
                base = PASSIVES['PR03000201803JAC00']
                # Versioned selection evidence travels with the catalogs;
                # maintenance must also work in a clean source checkout.
                if name not in RCD_BASIS:
                    raise ValueError(f'{name}: 缺少RCD候选功耗选值依据，需先复算并登记')
                n = max(4,math.ceil(RCD_BASIS[name]*1.2/.6))
                meta[ref] = identity(base,extra=f'{n}颗串联为{18*n}kΩ/{3*n}W候选；软件RCD的R仍按K/Kc派生，不能当作实装电阻已验证。')
                meta[ref].update(model=f'{n} × '+base['model']+' 串联（候选）',power_W=3.*n,package=f'{n}×Axial DIN0617')
                selected[ref] = dict(catalog='passive',key='PR03000201803JAC00',quantity=n,scope='candidate-only')
            else:
                # Reference PSR bias/compensation resistors are derived by its
                # own engine; do not invent an orderable exact resistor value.
                meta[ref] = dict(manufacturer='Vishay',model='CRCW0805 系列（阻值按PSR计算）',package='0805',power_W=.125,
                    conditions='D/CRCW0805额定0.125W@70°C；当前为系列选型，PSR派生阻值需落标准值后核订货号。',note='非完整可采购BOM；https://www.vishay.com/docs/20035/dcrcwe3.pdf')
                selected[ref] = dict(catalog='series',key='CRCW0805',scope='value-derived')
        elif ref=='C_SN1':
            key='B32652A1332J000';meta[ref]=identity(PASSIVES[key],extra='3.3nF标准件仅为候选；计算/电路仍使用派生C_snub，不声称实装容量一致。')
            selected[ref]=dict(catalog='passive',key=key,scope='candidate-only')
        elif kind=='magnetic':
            model = str(pc.get('core_choice') if ref in ('T1','N_A') else pc.get('core_choice_L','auto'))
            meta[ref] = dict(manufacturer='项目定制绕制 / DMEGC磁芯',model='DMR44 / '+model+' / '+ref+'（自绕）',package=model+'骨架/绕组',
                conditions='保留本例整数匝数、线径/股数/并绕与结构；并非已存在的商品变压器订货型号。',note=SUPPORT['magnetic_material_note']+' '+SUPPORT['magnetic_material_source'])
            selected[ref]=dict(catalog='custom-winding',key=model)
        elif kind=='block':
            meta[ref] = dict(manufacturer='TI / Vishay',model='TL431AIDBZR + VO617A-3（参考通路）',package='SOT-23-3 + DIP-4',
                conditions='SSR反馈模块参考，非单个商品器件；CTR=原配置参考值，须按实际LED电流/温度/分档校核。',note='未展开驱动与偏置。https://www.ti.com/lit/ds/symlink/tl431.pdf https://www.vishay.com/docs/83430/vo617a.pdf')
            selected[ref]=dict(catalog='feedback-reference',key='TL431A/VO617A-3')
        elif kind=='capacitor':
            meta[ref]=dict(manufacturer='Murata',model='GRM1885C 系列（PSR计算值）',package='0603 / C0G',voltage_V=50.,capacitor_type='mlcc',
                conditions='PSR补偿容量由原计算给出，需确认标准值和精确订货编码；ESR/ESL未另建模。',note='系列参考不等于完整采购BOM。https://www.murata.com/en-global/products/capacitor/ceramiccapacitor/overview/lineup/smd/grm')
            selected[ref]=dict(catalog='series',key='GRM1885C',scope='value-derived')
    cfg['component_management'] = normalize_management(dict(version=1,zone='I',items=meta,overrides={},override_reason=''))
    retired = sorted(set(retired + (raw.get('__real_parts') or {}).get('retired_curve_bindings', [])))
    cfg['__real_parts'] = dict(version=1,date='2026-11-08',selections=selected,retired_curve_bindings=retired,
        scope='原厂型号及参考电气标量初选；不等于原厂非线性模型、全温/启动或可生产BOM验证',
        assumptions=['各输入端点使用同一器件；Vgp/Qg参考条件不等于四事件实测。',
                     'RCD与PSR派生阻容未落标准值的条目明确为候选/系列，不冒充精确实装。',
                     '电解阻抗代理、ESL假设、磁件热阻/损耗系数和未知附加损耗按条件另核。'])
    notice = '已补真实器件初选；固定参考值模式。来源与限制见“关键器件BOM与降额”和docs/EXAMPLE_REAL_PARTS.md；旧匿名曲线已解除绑定。'
    cfg['__example_note'] = str(raw.get('__example_note',''))
    if notice not in cfg['__example_note']:
        cfg['__example_note'] += '\n'+notice
    return cfg


def apply_ldo(raw):
    cfg = copy.deepcopy(raw)
    part = SUPPORT['parts']['TLV75533PDBVR']
    cfg.update(part['calculation'])
    cfg.update({key:part[key] for key in ('manufacturer','model','package')})
    cap = SUPPORT['parts']['GRM21BR71E225KA73L']
    cfg.update(C_in=cap['calculation']['C'],C_out=cap['calculation']['C'],ESR_out=cap['calculation']['ESR'])
    cfg['component_management'] = normalize_management(dict(items={'U1':identity(part),'C_IN1':identity(cap),'C_OUT1':identity(cap)}))
    cfg['notes'] = part['conditions']+' '+part['note']+' '+cap['conditions']+' '+cap['note']+' 资料：'+' '.join(part['sources'])
    cfg['__real_parts'] = dict(version=1,date='2026-11-08',scope='LDO静态参考，热阻/有效容量未实板验证')
    return cfg


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--write',action='store_true');args=parser.parse_args()
    manifest=[]
    for path in sorted((ROOT/'examples').glob('*.json')):
        blob=path.read_bytes();raw=json.loads(blob.decode('utf-8-sig'));new=copy.deepcopy(raw)
        if raw.get('schema_version')=='power.system-network/2':
            for unit in new['units']:
                unit['spec'] = apply_ldo(unit['spec']) if unit['spec'].get('topology')=='LDO' else apply_switching(unit['spec'],path.name)
        else:
            new=apply_switching(raw,path.name)
        target=(ROOT/'examples'/path.name) if args.write else ROOT/'artifacts/example-real-parts-20261108/proposed'/path.name
        write(target,new)
        manifest.append(dict(file=path.name,old_sha256=hashlib.sha256(blob).hexdigest(),new_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    write(ROOT/'artifacts/example-real-parts-20261108/applied-manifest.json',dict(written=args.write,files=manifest))
    print(json.dumps(dict(files=len(manifest),written=args.write),ensure_ascii=False))


if __name__=='__main__':main()
