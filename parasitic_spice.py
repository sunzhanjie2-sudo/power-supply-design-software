"""Apply the same lumped parasitics to CIR and native ASC parameter cards.

Uncoupled series inductances are absorbed into Lii, with Mij held fixed by
recomputing kij. This is electrically equivalent at the external winding pins
and needs no invisible rewiring of the verified native schematic.
"""
import json
import math
import re


def schematic(content, count, forward=False):
    text=content.decode('utf-8')
    ref=''
    output=[]
    for line in text.splitlines():
        if line.startswith('SYMATTR InstName '):ref=line.split()[-1]
        if line.startswith('SYMATTR SpiceLine ') and 'CJ={DIODE_CJ}' in line:
            key='PAR_'+ref+'_CJ' if ref.startswith(('D_O','D_F')) and not ref.startswith('D_OUT') else 'DIODE_CJ'
            line=line.replace('CJ={DIODE_CJ}','CJ={'+key+'}')+' RCJ={PAR_RCJ}'
        output.append(line)
    # Parameterized extra parallel parts are present in both ASC and CIR.
    output += ['TEXT 64 1744 Left 2 !.include parasitics.inc',
               'TEXT 64 1776 Left 2 ;Lii includes series PCB L; Mij unchanged. Extra CW and RC: parasitics.inc.']
    return ('\n'.join(output)+'\n').encode('utf-8')


def apply_project(files,p):
    if not p.get('parasitic_config'):return files
    from parasitics import resolved,NOTE
    meta=json.loads(files['manifest.json'])
    count=len(meta['hardware']['windings']);cfg=resolved(p,count);forward=p['topology']=='ACF-FORWARD'
    inc=files['design_params.inc'].decode('ascii')
    values={k:float(v) for k,v in re.findall(r'(?m)^\.param (\w+)=([-+\d.eE]+)\s*$',inc)}
    old_l=[values['LP']]+[values[f'LS{i}'] for i in range(1,count+1)]
    new_l=[old_l[0]+cfg['lp_pcb']]+[old_l[i]+cfg['rails'][i-1]['l_pcb'] for i in range(1,count+1)]
    changes=dict(LP=new_l[0],RP=values['RP']+cfg['rp_pcb'],Q_COSS=cfg['coss'],DIODE_CJ=cfg['cj_default'],PAR_RCJ=cfg['r_cj'])
    if forward:changes['QA_COSS']=cfg['coss_aux']
    for i,r in enumerate(cfg['rails'],1):
        changes[f'LS{i}']=new_l[i];changes[f'RS{i}']=values[f'RS{i}']+r['r_pcb']
        changes[f'PAR_D_O{i}_CJ']=r['cj'];changes[f'PAR_D_F{i}_CJ']=r['cj_free']
    for i in range(count+1):
        for j in range(i+1,count+1):
            k=f'K_{i}_{j}';changes[k]=values[k]*math.sqrt(old_l[i]*old_l[j]/(new_l[i]*new_l[j]))
    for key,value in changes.items():
        line=f'.param {key}={value:.12g}'
        pattern=r'(?m)^\.param '+key+r'=[^\r\n]*'
        inc=re.sub(pattern,line,inc) if re.search(pattern,inc) else inc+'\n'+line
    files['design_params.inc']=(inc+'\n').encode('ascii')
    extra=['* Explicit lumped parallel capacitances and RC snubbers. SI values.']
    if cfg['cw_primary']:extra += [f'C_PAR_P vin_bus drain {cfg["cw_primary"]:.12g}']
    def rc(ref,a,b,r,c):
        if c:extra.extend([f'R_PAR_{ref} {a} par_{ref} {r:.12g}',f'C_PAR_{ref} par_{ref} {b} {c:.12g}'])
    rc('Q1','drain','sense',cfg['snub_r_primary'],cfg['snub_c_primary'])
    for i,r in enumerate(cfg['rails'],1):
        if r['cw']:extra += [f'C_PAR_S{i} rect{i} sgnd {r["cw"]:.12g}']
        rc(f'D{i}',f'rect{i}',f'choke{i}' if forward else f'cap{i}',r['snub_r'],r['snub_c'])
    files['parasitics.inc']=('\n'.join(extra)+'\n').encode('ascii')
    files['Flyback.cir']=files['Flyback.cir'].replace(b'.include analysis.inc',b'.include parasitics.inc\n.include analysis.inc')
    stage=files['power_stage.inc'].decode('ascii');rows=[]
    for line in stage.splitlines():
        if 'CJ={DIODE_CJ}' in line:
            ref=line.split()[0][1:];key='PAR_'+ref+'_CJ' if ref.startswith(('D_O','D_F')) and not ref.startswith('D_OUT') else 'DIODE_CJ'
            line=line.replace('CJ={DIODE_CJ}','CJ={'+key+'}')+' RCJ={PAR_RCJ}'
        rows.append(line)
    files['power_stage.inc']=('\n'.join(rows)+'\n').encode('ascii')
    for name in ('GenericFlybackPWM.lib','GenericACF_MP6005.lib'):
        if name not in files:continue
        lib=files[name].decode('ascii').replace('CJ=20e-12','CJ=20e-12 RCJ=0.1').replace('Rser=0.1 m={ACT}','Rser={RCJ} m={ACT}').replace('VF=0.8 CJ={CJ}','VF=0.8 CJ=0 RCJ={RCJ}')
        files[name]=lib.encode('ascii')
    if 'Flyback.asc' in files:files['Flyback.asc']=schematic(files['Flyback.asc'],count,forward)
    import hashlib
    meta['library_sha256']=hashlib.sha256(files['GenericFlybackPWM.lib']).hexdigest()
    meta['parasitics']=dict(resolved=cfg,note=NOTE,series_inductance_method='Lii+=Lpcb; Mij unchanged',
        calculation_scope='flyback-local-single-port-estimate; ACF-periodic-MNA; SPICE-full-network')
    meta.setdefault('approximation_notes',[]).append(NOTE)
    if forward:meta['acf']['library_sha256']=hashlib.sha256(files['GenericACF_MP6005.lib']).hexdigest()
    files['manifest.json']=json.dumps(meta,ensure_ascii=False,indent=2).encode('utf-8')
    files['README.md']+=('\n## 寄生参数\n\n'+NOTE+'\n\nLii 合并串联布线电感，Mij 保持不变；原 kij 按此折算，不能把折算后的 kij 当作变压器实测耦合系数。'
        'parasitics.inc 含绕组端间电容和独立 RC 吸收，两种入口均包含。计算器反激局部估算和 SPICE 完整网络的模型范围不同，不保证尖峰一致。\n').encode('utf-8')
    return files
