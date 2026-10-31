"""One parameterized circuit contract shared by CIR and native ASC templates."""

CONTROL_KEYS=('FSW','MODE','DMAX','VM','A_CS','SLOPE','CS_LIM','TBLANK','TONMIN','TPROP',
    'VG','RDRV','UVLO','VSET','TSS','TYPE','KP','FZ1','FP1','FZ2','FP2','CMAX','TEN',
    'SSMODE','SSFRAC','COFF','SSCLO','SSCHI','SCMODE','SCP','SCPBLANK','OLPEN','TOLP','THOLD','TOFF','CS_TAU')


def extra_capacitor_cards(p,rails,settings):
    """Additional branches in a shared include: ASC and CIR see identical banks."""
    from capacitor_banks import bank
    cards=['* Additional parallel capacitor branches (first pair is on the native sheet).']
    groups=[('C_IN',bank(p,'input'),'vin_bus','0')]
    groups += [(f'C_O{i}_',bank(rail),f'cap{i}','sgnd') for i,rail in enumerate(rails,1)]
    for prefix,caps,a,b in groups:
        for j,c in enumerate(caps[2:],3):
            esl=c['ESL'] if settings['include_cap_esl'] else 0.
            cards.append(f'X{prefix}{j} {a} {b} GPWR_CAP C={c["C"]:.12g} ESR={c["ESR"]:.12g} ESL={esl:.12g} ACT=1')
    return cards


def render_stage(q,rails,geometry,kvals,clamp,settings):
    params={}
    def add(key,value):params[key]=float(value);return '{'+key+'}'
    lines=['* Same native circuit as Flyback_N.asc. Optional parts use explicit bypass/enable parameters.',
        'VIN_SOURCE input 0 {VIN}','VCC_SOURCE vcc 0 {VG}',
        'VEN en 0 PULSE(0 1 1e-6 10e-9 10e-9 {2*TSTOP} {3*TSTOP})',
        'V_SECONDARY_REFERENCE sgnd 0 0']
    def diode(ref,a,b,drop,enabled=1):
        lines.append(f'X{ref} {a} {b} GPWR_DIODE VF={add(ref+"_VF",drop)} ACT={add(ref+"_EN",enabled)} CJ={{DIODE_CJ}}')
    def cap(ref,a,b,c,esr,esl,enabled=1):
        lines.append(f'X{ref} {a} {b} GPWR_CAP C={add(ref+"_C",c)} ESR={add(ref+"_ESR",esr)} ESL={add(ref+"_ESL",esl if settings["include_cap_esl"] else 0)} ACT={add(ref+"_EN",enabled)}')
    diode('D_IN','input','vin_bus',q['Vf_din'],int(q.get('d_in_enable',False)))
    cap('C_IN1','vin_bus','0',q['Cin1'],q['Rcin1'],q['ESLin1'])
    cap('C_IN2','vin_bus','0',q['Cin2'],q['Rcin2'],q['ESLin2'],int(q.get('cin2_enable',False)))
    lines += [f'LP vin_bus drain {add("LP",q["L"])} Rser={add("RP",geometry["R_dc_p"])}',
        f'XQ1 drain gate sense GPWR_MOS RON={add("Q_RON",q["Rds_on"])} COSS={add("Q_COSS",max(q["Coss"],1e-12))} CG={add("Q_CG",max(q["Qg"]/q["Vgs"],1e-12))} VG={{VG}} CJ={{DIODE_CJ}}',
        f'RS1 sense 0 {add("RSENSE",q["Rs"])}']
    enabled=1 if clamp['C_snub']>0 and __import__('math').isfinite(clamp['R_snub']) else 0
    diode('D_SN1','drain','clamp',.7,1)
    lines += [f'R_SN1 clamp vin_bus {add("R_SN1",clamp["R_snub"] if enabled else 1e12)}',
        f'C_SN1 clamp vin_bus {add("C_SN1",clamp["C_snub"] if enabled else 1e-12)} Rser=0.01']
    for i,(rail,winding) in enumerate(zip(rails,geometry['windings']),1):
        lines.append(f'LS{i} sgnd rect{i} {add("LS"+str(i),q["L"]*(winding["Ns"]/geometry["Np"])**2)} Rser={add("RS"+str(i),winding["R_dc"])}')
        diode('D_O'+str(i),'rect'+str(i),'cap'+str(i),rail['Vf_diode'])
        cap('C_O'+str(i),'cap'+str(i),'sgnd',rail['C_out'],rail['Rc'],rail['ESL'])
        cap('C_O'+str(i)+'_2','cap'+str(i),'sgnd',rail['C_out2'],rail['Rc2'],rail['ESL2'],int(rail['cout2_enable']))
        diode('D_OUT'+str(i),'cap'+str(i),'out'+str(i),rail['Vf_dout'],int(rail.get('d_out_enable',False)))
        resistance=rail['V_out']**2/rail['P_out'] if rail['P_out']>0 else 1e12
        lines.append(f'BLOAD{i} out{i} sgnd I=V(out{i},sgnd)/{add("RLOAD"+str(i),resistance)}*(1+({{LOAD_AFTER}}-1)*limit((time-{{TLOAD}})/1e-6,0,1))')
        lines.append(f'SSHORT{i} out{i} sgnd short{i} 0 SHORT_SW')
        lines.append(f'BSHORT{i} short{i} 0 V=if(({{SHORT_EN}}>0.5)&({{SHORT_OUT}}=={i}),V(short_stim),0)')
    names=['LP']+['LS'+str(i) for i in range(1,len(rails)+1)]
    for i in range(len(names)):
        for j in range(i+1,len(names)):
            # These K cards live in parameters.inc for both the native sheet and CIR.
            params['K_'+str(i)+'_'+str(j)]=float(kvals[i][j])
    for i in range(len(names)):
        for j in range(i+1,len(names)):
            lines.append(f'K_{i}_{j} {names[i]} {names[j]} {{K_{i}_{j}}}')
    fbnodes=['cap'+str(i) if i<=len(rails) else 'sgnd' for i in range(1,7)]
    lines.append('XFBSEL '+' '.join(fbnodes)+' sgnd fb 0 GPWR_FEEDBACK SEL={FB_SELECT} H={FB_SCALE}')
    lines.append('XU_CTRL fb sense en vcc gate comp ramp ss fault 0 GFLY_CTRL2 '+' '.join(k+'={'+k+'}' for k in CONTROL_KEYS))
    return lines,params


def support_cards(count):
    return [
        'VSHORT short_stim 0 PULSE(0 1 {TSHORT} 1e-6 1e-6 {TSHORT_DUR} {2*TSTOP})',
        '.model SHORT_SW SW(Ron={SHORT_R} Roff=1e12 Vt=0.5 Vh=-0.1)',
        'BDUTY duty_mon 0 V=if(V(gate,sense)>{VG/2},1,0)',
    ]
