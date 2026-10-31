"""Build native, wired ASC templates through the MCP editor, never text-write ASC.

Use the MCP Python environment and a dedicated allowed workspace. The desktop
exporter only copies these checked templates and writes their parameter include.
"""
from pathlib import Path
import argparse
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from spice_circuit import CONTROL_KEYS


def operations(count):
    ops=[];locations={}
    def part(ref,symbol,x,y,value=None,rotation='R0',attributes=None):
        symbol={'res':'PowerRes','cap':'PowerSmallCap','voltage':'PowerVoltage'}.get(symbol,symbol)
        if ref=='RS1':symbol='PowerSenseRes'
        item=dict(op='add_component',reference=ref,symbol=symbol,x=x,y=y,rotation=rotation)
        if value is not None:item['value']=value
        if attributes:item['attributes']=attributes
        ops.append(item)
        pins={'PowerCap':{'P':(16,0),'N':(16,128)},'PowerRes':{'A':(16,16),'B':(16,96)},
            'PowerDiode':{'A':(0,0),'K':(96,0)},'PowerSmallCap':{'A':(16,0),'B':(16,64)},'PowerSenseRes':{'A':(16,16),'B':(16,96)}}.get(symbol,{})
        for pin,(px,py) in pins.items():
            if rotation=='R270':px,py=py,-px
            if rotation=='R180':px,py=-px,-py
            locations[ref+'.'+pin]=(x+px,y+py)
    def wire(a,b,via=()):
        if locations.get(a,a) == locations.get(b,b):return  # pin already on a bus
        def point(v):return dict(x=v[0],y=v[1]) if isinstance(v,tuple) else v
        ops.append(dict(op='wire_pins',from_pin=point(a),to_pin=point(b),waypoints=[point(x) for x in via]))
    def label(net,pin=None,xy=None):
        ops.append(dict(op='add_net_label',net=net,**({'pin':pin} if pin else dict(x=xy[0],y=xy[1]))))
    def note(text,x,y,size=2):ops.append(dict(op='add_directive',kind='comment',instruction=text,x=x,y=y,size=size))
    def diode(ref,x,y,rotation='R0'):
        part(ref,'PowerDiode',x,y,'GPWR_DIODE',rotation,dict(SpiceLine=f'VF={{{ref}_VF}} ACT={{{ref}_EN}} CJ={{DIODE_CJ}}'))
    def cap(ref,x,y):
        part(ref,'PowerCap',x,y,'GPWR_CAP',attributes=dict(SpiceLine=f'C={{{ref}_C}} ESR={{{ref}_ESR}} ESL={{{ref}_ESL}} ACT={{{ref}_EN}}'))
    note('CONFIGURABLE FLYBACK SSR -- native power circuit and controller',64,16,3)
    note('T1: LP / LS1...LSn. OUT is after blocking diode; CAP before it feeds the selector.',64,64)
    note('Values and enabled parts: design_params.inc. An optional diode with *_EN=0 is bypassed.',64,96)
    part('VIN_SOURCE','voltage',64,184,'{VIN}');label('0','VIN_SOURCE.-')
    diode('D_IN',160,200);wire('VIN_SOURCE.+','D_IN.A')
    part('LP','ind2',880,184,'{LP}',attributes=dict(SpiceLine='Rser={RP}'))
    wire('D_IN.K','LP.A');label('input','VIN_SOURCE.+');label('vin_bus','LP.A')
    cap('C_IN1',288,200);cap('C_IN2',448,200)
    wire('C_IN1.P',(304,200));wire('C_IN2.P',(464,200))
    label('0','C_IN1.N');label('0','C_IN2.N')
    label('clamp',xy=(688,328));label('clamp',xy=(800,328))
    part('R_SN1','res',672,184,'{R_SN1}');wire('R_SN1.A',(688,200));wire('R_SN1.B',(688,328))
    part('C_SN1','cap',784,200,'{C_SN1}',attributes=dict(SpiceLine='Rser=0.01'))
    wire('C_SN1.A',(800,200));wire('C_SN1.B',(800,328));wire((688,328),(800,328))
    diode('D_SN1',736,424,'R270');wire('D_SN1.K',(736,328))
    part('Q1','PowerMos',848,480,'GPWR_MOS',attributes=dict(SpiceLine='RON={Q_RON} COSS={Q_COSS} CG={Q_CG} VG={VG} CJ={DIODE_CJ}'))
    wire('LP.B','Q1.D');wire('D_SN1.A',(896,424));label('drain','Q1.D')
    part('RS1','res',880,632,'{RSENSE}');wire('Q1.S','RS1.A');label('0','RS1.B');label('sense','Q1.S')
    note('T1 primary',848,144)
    part('U_CTRL','GFLY_CTRL2',320,640,'GFLY_CTRL2',attributes=dict(SpiceLine=' '.join(k+'={'+k+'}' for k in CONTROL_KEYS)))
    wire('U_CTRL.GATE','Q1.G');label('gate','U_CTRL.GATE')
    label('sense',xy=(896,624));wire('U_CTRL.CS',(896,624),[(144,608),(144,864),(960,864),(960,624)])
    for pin,net in [('COMP','comp'),('RAMP','ramp'),('SS','ss'),('FAULT','fault')]:
        pos={'COMP':608,'RAMP':672,'SS':736,'FAULT':768}[pin]
        label(net,xy=(544,pos));wire('U_CTRL.'+pin,(544,pos))
    label('0','U_CTRL.COM');label('en','U_CTRL.EN');label('vcc','U_CTRL.VCC')
    part('VCC_SOURCE','voltage',288,944,'{VG}');label('vcc','VCC_SOURCE.+');label('0','VCC_SOURCE.-')
    part('VEN','voltage',496,944,'PULSE(0 1 1e-6 10e-9 10e-9 {2*TSTOP} {3*TSTOP})');label('en','VEN.+');label('0','VEN.-')
    note('Controller settings: frequency / soft start / CS / SCP / OLP / hiccup',112,896)
    for i in range(1,count+1):
        y=200+(i-1)*320
        part('LS'+str(i),'ind2',1136,y+96,'{LS'+str(i)+'}','R180',dict(SpiceLine='Rser={RS'+str(i)+'}'))
        diode('D_O'+str(i),1216,y)
        wire(f'LS{i}.B',f'D_O{i}.A');label('rect'+str(i),f'LS{i}.B')
        cap('C_O'+str(i),1376,y);cap('C_O'+str(i)+'_2',1568,y)
        diode('D_OUT'+str(i),1760,y)
        wire(f'D_O{i}.K',f'C_O{i}.P');wire(f'C_O{i}.P',f'C_O{i}_2.P');wire(f'C_O{i}_2.P',f'D_OUT{i}.A');label('cap'+str(i),f'D_OUT{i}.A')
        wire(f'C_O{i}.P',(1392,y));wire(f'C_O{i}_2.P',(1584,y))
        part('LOAD'+str(i),'PowerLoad',1984,y,'I=V(out'+str(i)+',sgnd)/{RLOAD'+str(i)+'}*(1+({LOAD_AFTER}-1)*limit((time-{TLOAD})/1e-6,0,1))')
        wire(f'D_OUT{i}.K',f'LOAD{i}.A');label('out'+str(i),xy=(2080,y));wire(f'LOAD{i}.A',(2080,y))
        wire(f'C_O{i}.N',f'C_O{i}_2.N');wire(f'C_O{i}_2.N',f'LOAD{i}.B')
        label('sgnd',xy=(1120,y+128));wire(f'LS{i}.A',(1120,y+128));wire((1120,y+128),f'C_O{i}.N');label('sgnd',f'LOAD{i}.B')
        note(f'T1 secondary OUT{i}',1064,y+168)
    fy=max(1184,200+(count-1)*320+352)
    part('FBSEL','FeedbackSelector',1920,fy,'GPWR_FEEDBACK',attributes=dict(SpiceLine='SEL={FB_SELECT} H={FB_SCALE}'))
    for i in range(1,7):
        yy=fy-96+(i-1)*32
        label('cap'+str(i) if i<=count else 'sgnd',xy=(2128,yy));wire(f'FBSEL.OUT{i}',(2128,yy))
    label('sgnd','FBSEL.SG');label('0','FBSEL.COM')
    wire('FBSEL.FB','U_CTRL.FB',[(64,fy-32),(64,544)])
    label('fb','U_CTRL.FB')
    note('SSR ideal feedback senses CAP before blocking diode; FB_SELECT selects the rail.',1280,fy+208)
    note('Not an optocoupler/TL431 device model. Real feedback delay must be added for sign-off.',1280,fy+240)
    part('V_SECONDARY_REFERENCE','voltage',800,944,'0');label('sgnd','V_SECONDARY_REFERENCE.+');label('0','V_SECONDARY_REFERENCE.-')
    dy=max(1184,fy+320)
    for index,line in enumerate(('.include design_params.inc','.include coupling.inc','.include support.inc','.include analysis.inc')):
        ops.append(dict(op='add_directive',instruction=line,x=64,y=dy+index*32))
    note('support.inc contains the optional short-circuit test fixture. GND reference is mathematical, not a hardware bond.',64,dy+176)
    return ops


def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);p.add_argument('--config',required=True)
    p.add_argument('--revision',default='a');p.add_argument('--counts',default='1,2,3,4,5,6')
    a=p.parse_args();a.stage.mkdir(parents=True,exist_ok=True)
    for file in (ROOT/'resources/spice').glob('*.asy'):shutil.copy2(file,a.stage/file.name)
    shutil.copy2(ROOT/'resources/spice/GenericFlybackPWM.lib',a.stage/'GenericFlybackPWM.lib')
    from ltspice_mcp.api import Api
    with Api(working_dir=a.stage,config_path=a.config) as api:
        for count in map(int,a.counts.split(',')):
            target=a.stage/f'Flyback_{count}_{a.revision}.asc'
            result=api.edit_schematic(target=str(target),base='blank',ops=operations(count))
            if result.get('commit_state')!='committed':raise RuntimeError(result)
            shutil.copy2(target,ROOT/f'resources/spice/Flyback_{count}.asc')
            print(count,result.get('warnings'),flush=True)


if __name__=='__main__':main()
