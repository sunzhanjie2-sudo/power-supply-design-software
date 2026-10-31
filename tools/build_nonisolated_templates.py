"""Build wired native Buck/Boost sheets with the guarded MCP editor."""
from pathlib import Path
import sys,shutil,argparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from spice_circuit import CONTROL_KEYS

def operations(buck):
    ops=[]
    def part(ref,sym,x,y,value,rotation='R0',line=None):
        item=dict(op='add_component',reference=ref,symbol=sym,x=x,y=y,value=value,rotation=rotation)
        if line:item['attributes']=dict(SpiceLine=line)
        ops.append(item)
    def label(net,pin):ops.append(dict(op='add_net_label',net=net,pin=pin))
    def wire(a,b,via=()):ops.append(dict(op='wire_pins',from_pin=a,to_pin=b,waypoints=[dict(x=x,y=y) for x,y in via]))
    def note(s,x,y):ops.append(dict(op='add_directive',kind='comment',instruction=s,x=x,y=y))
    def diode(ref,x,y,rotation='R0'):part(ref,'PowerDiode',x,y,'GPWR_DIODE',rotation,f'VF={{{ref}_VF}} ACT={{{ref}_EN}} CJ={{DIODE_CJ}}')
    def cap(ref,x,y):part(ref,'PowerCap',x,y,'GPWR_CAP',line=f'C={{{ref}_C}} ESR={{{ref}_ESR}} ESL={{{ref}_ESL}} ACT={{{ref}_EN}}')
    note(('BUCK -- high-side P-MOS / freewheel diode' if buck else 'BOOST -- low-side N-MOS / rectifier diode'),64,16)
    note('Native circuit. Edit design_params.inc. Controller is reference-inspired, not a manufacturer model.',64,56)
    part('VIN_SOURCE','PowerVoltage',64,184,'{VIN}');label('input','VIN_SOURCE.+');label('0','VIN_SOURCE.-')
    diode('D_IN',160,200);wire('VIN_SOURCE.+','D_IN.A')
    cap('C_IN1',288,200);cap('C_IN2',480,200);wire('D_IN.K','C_IN1.P');wire('C_IN1.P','C_IN2.P')
    label('vin_bus','C_IN1.P');label('0','C_IN1.N');label('0','C_IN2.N')
    if buck:
        part('RS1','NisoHres',688,200,'{RSENSE}');wire('C_IN2.P','RS1.A')
        part('Q1','NisoPmos',880,200,'GNISO_PMOS','R90','RON={Q_RON} COSS={Q_COSS} CG={Q_CG} VG={VG} CJ={DIODE_CJ}')
        wire('RS1.B','Q1.S');label('qsource','Q1.S');label('sw','Q1.D');label('gate_pin','Q1.G')
        part('L1','PowerChoke',992,248,'{L1}',line='Rser={RL1}');wire('Q1.D','L1.A')
        diode('D_O1',944,504,'R270');label('sgnd','D_O1.A');label('rect1','D_O1.K')
        part('V_D1','NisoProbe',944,344,'0','R180');wire('D_O1.K','V_D1.+');wire('V_D1.-','Q1.D')
        # Current probe polarity follows the forward diode current.
        # Connections are corrected below by pin labels; avoid hidden rect/sw shorts.
        # Put the zero-volt probe on the diode branch instead of changing a model.
        y=248
        label('cap1','L1.B');cap('C_O1',1200,y);wire('L1.B','C_O1.P')
    else:
        part('L1','PowerChoke',688,200,'{L1}',line='Rser={RL1}');wire('C_IN2.P','L1.A');label('sw','L1.B')
        part('Q1','NisoNmos',816,352,'GNISO_NMOS',line='RON={Q_RON} COSS={Q_COSS} CG={Q_CG} VG={VG} CJ={DIODE_CJ}');wire('L1.B','Q1.D',[(864,200)]);label('gate_pin','Q1.G')
        part('RS1','NisoRes',848,520,'{RSENSE}');wire('Q1.S','RS1.A');label('sense','Q1.S');label('0','RS1.B')
        part('V_D1','NisoProbe',960,200,'0','R270');wire('L1.B','V_D1.+');diode('D_O1',1120,200);wire('V_D1.-','D_O1.A');label('rect1','D_O1.A')
        y=200;cap('C_O1',1280,y);wire('D_O1.K','C_O1.P');label('cap1','C_O1.P')
    cap('C_O1_2',1488,y);wire('C_O1.P','C_O1_2.P');diode('D_OUT1',1680,y);wire('C_O1_2.P','D_OUT1.A')
    part('LOAD1','PowerLoad',1840,y,'I=V(out1,sgnd)/{RLOAD1}*(1+({LOAD_AFTER}-1)*limit((time-{TLOAD})/1e-6,0,1))')
    wire('D_OUT1.K','LOAD1.A');label('out1','LOAD1.A');wire('C_O1.N','C_O1_2.N');wire('C_O1_2.N','LOAD1.B');label('sgnd','LOAD1.B')
    part('U_CTRL','NisoController',544,912,'GNISO_CTRL',line=' '.join(k+'={'+k+'}' for k in CONTROL_KEYS)+' LIMIT_RAMP={LIMIT_RAMP}')
    label('fb','U_CTRL.FB');label('sense','U_CTRL.CS');label('en','U_CTRL.EN');label('vcc','U_CTRL.VCC');label('0','U_CTRL.COM')
    for pin,net in [('GATE','gate_cmd'),('COMP','comp'),('RAMP','ramp'),('SS','ss'),('FAULT','fault')]:label(net,'U_CTRL.'+pin)
    note('Driver adapter: support.inc. P-MOS has negative Vgs.',768,672)
    note('gate/drain monitors use positive magnitudes.',768,704)
    part('FBSEL','FeedbackSelector',1472,912,'GPWR_FEEDBACK',line='SEL={FB_SELECT} H={FB_SCALE}')
    label('cap1','FBSEL.OUT1')
    for i in range(2,7):label('sgnd','FBSEL.OUT'+str(i))
    label('sgnd','FBSEL.SG');label('0','FBSEL.COM');wire('FBSEL.FB','U_CTRL.FB',[(1216,880),(1216,1120),(320,1120),(320,816)])
    part('VCC_SOURCE','PowerVoltage',64,896,'{VG}');label('vcc','VCC_SOURCE.+');label('0','VCC_SOURCE.-')
    part('VEN','PowerVoltage',224,896,'PULSE(0 1 1e-6 10e-9 10e-9 {2*TSTOP} {3*TSTOP})');label('en','VEN.+');label('0','VEN.-')
    part('V_SECONDARY_REFERENCE','PowerVoltage',64,1120,'0');label('sgnd','V_SECONDARY_REFERENCE.+');label('0','V_SECONDARY_REFERENCE.-')
    note('V_SECONDARY_REFERENCE is a legacy-compatible zero-volt reference, not an isolation boundary.',288,1248)
    for j,line in enumerate(['.include design_params.inc','.include GenericFlybackPWM.lib','.include GenericBuckBoostPWM.lib','.include coupling.inc','.include support.inc','.include analysis.inc']):ops.append(dict(op='add_directive',instruction=line,x=64,y=1328+j*32))
    ops.append(dict(op='set_plot_panes',analysis='tran',panes=[dict(traces=['V(out1)','V(cap1)']),dict(traces=['I(L1)','I(V_D1)']),dict(traces=['V(gate_pin,qsource)' if buck else 'V(gate_pin,sense)','V(sw,qsource)' if buck else 'V(sw,sense)']),dict(traces=['V(comp)','V(ramp)','V(ss)','V(fault)'])]))
    return ops

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',required=True,type=Path);ap.add_argument('--config',required=True);a=ap.parse_args();a.stage.mkdir(parents=True,exist_ok=True)
    for ext in ('*.asy','*.lib'):
        for p in (ROOT/'resources/spice').glob(ext):shutil.copy2(p,a.stage/p.name)
    from ltspice_mcp.api import Api
    with Api(working_dir=a.stage,config_path=a.config) as api:
        for name,buck in [('Buck',True),('Boost',False)]:
            target=a.stage/(name+'.asc')
            expected=__import__('hashlib').sha256(target.read_bytes()).hexdigest() if target.exists() else None
            r=api.edit_schematic(target=str(target),base='blank',expected_sha256=expected,ops=operations(buck),return_views=[])
            (ROOT/'artifacts/qa/nonisolated_20261029'/('template_'+name+'.json')).write_text(__import__('json').dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
            if r.get('commit_state')!='committed':raise RuntimeError(r)
            for ext in ('.asc','.plt'):shutil.copy2(target.with_suffix(ext),ROOT/'resources/spice'/(name+ext))
            print(name,r.get('warnings'),flush=True)
if __name__=='__main__':main()
