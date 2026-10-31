"""Native ACF sheets, built transactionally with the configured LTspice MCP."""
import copy
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.build_spice_schematic_templates import operations as flyback_operations
from spice_circuit import CONTROL_KEYS


def operations(count):
    result=[]
    removed=('R_SN1','C_SN1','D_SN1')
    for item in copy.deepcopy(flyback_operations(count)):
        op=item['op'];ref=item.get('reference','')
        pins=[item.get(k,'') for k in ('from_pin','to_pin','pin')]
        if ref in removed or any(isinstance(v,str) and v.split('.')[0] in removed for v in pins):continue
        if op=='add_net_label' and item['net']=='clamp':continue
        if op=='wire_pins' and item.get('from_pin')==dict(x=688,y=328):continue
        if op=='wire_pins' and item.get('from_pin')=='U_CTRL.GATE':continue
        if op=='wire_pins' and str(item.get('from_pin','')).startswith('D_O') and str(item.get('to_pin','')).startswith('C_O'):continue
        if ref=='U_CTRL':
            item.update(symbol='GACF_CTRL',value='GACF_CTRL',attributes=dict(SpiceLine=' '.join(k+'={'+k+'}' for k in CONTROL_KEYS)+' TDEAD={TDEAD} RSYNC={RSYNC}'))
        if ref.startswith('LS'):
            i=int(ref[2:]);item.update(x=1104,y=184+(i-1)*320,rotation='R0')
        # Make room for a real output choke between rectifier and cap bank.
        for axis in ('x',):
            if item.get(axis,0)>=1350:item[axis]+=160
        for k in ('from_pin','to_pin','pin'):
            v=item.get(k)
            if isinstance(v,dict) and v.get('x',0)>=1350:v['x']+=160
            if isinstance(v,str) and v.startswith('LS'):
                item[k]=v[:-1]+('B' if v[-1]=='A' else 'A')
        for v in item.get('waypoints',[]):
            if v.get('x',0)>=1350:v['x']+=160
        if op=='add_directive' and item.get('kind')=='comment':
            item['instruction']=item['instruction'].replace('CONFIGURABLE FLYBACK SSR','ACTIVE-CLAMP FORWARD / MP6005-INSPIRED SSR')
        result.append(item)
    def part(ref,symbol,x,y,value,rotation='R0',**attrs):
        result.append(dict(op='add_component',reference=ref,symbol=symbol,x=x,y=y,value=value,rotation=rotation,attributes=attrs))
    def label(net,pin=None,**xy):result.append(dict(op='add_net_label',net=net,**(dict(pin=pin) if pin else xy)))
    def wire(a,b):result.append(dict(op='wire_pins',from_pin=a,to_pin=b))
    part('C_ACTIVE','PowerSmallCap',656,328,'{C_ACTIVE}',SpiceLine='Rser={ESR_ACTIVE}')
    part('QA','PowerPmos',624,464,'GACF_PMOS',SpiceLine='RON={QA_RON} COSS={QA_COSS} CG={QA_CG} VG={VG} CJ={DIODE_CJ}')
    wire('C_ACTIVE.A',dict(x=896,y=328));wire('C_ACTIVE.B','QA.D')
    label('aclamp','QA.D');label('0','QA.S');label('auxgate',x=576,y=528);wire('QA.G',dict(x=576,y=528))
    label('gate',x=800,y=544);wire('Q1.G',dict(x=800,y=544))
    label('sync','U_CTRL.SYNC');label('auxgate','U_CTRL.AUXG')
    for i in range(1,count+1):
        y=200+(i-1)*320
        part('LO'+str(i),'PowerChoke',1344,y,'{LO'+str(i)+'}',SpiceLine='Rser=0')
        part('D_F'+str(i),'PowerDiode',1312,y+128,'GPWR_DIODE','R270',SpiceLine=f'VF={{D_O{i}_VF}} CJ={{DIODE_CJ}}')
        wire(f'D_O{i}.K',f'LO{i}.A');wire(f'LO{i}.B',f'C_O{i}.P');wire(f'D_O{i}.K',f'D_F{i}.K')
        label('choke'+str(i),f'D_O{i}.K');label('sgnd',f'D_F{i}.A')
    result.append(dict(op='set_plot_panes',analysis='tran',panes=[dict(traces=[f'V(out{i},sgnd)' for i in range(1,count+1)]),
        dict(traces=['V(gate,sense)','V(auxgate)','V(sync)']),dict(traces=['V(drain,sense)','V(drain,aclamp)']),
        dict(traces=['I(LP)']+[f'-I(LS{i})' for i in range(1,count+1)]),dict(traces=[f'I(LO{i})' for i in range(1,count+1)])]))
    return result


if __name__=='__main__':
    from ltspice_mcp.api import Api
    stage=Path(sys.argv[1]);stage.mkdir(parents=True,exist_ok=True)
    for p in (ROOT/'resources/spice').glob('*.asy'):shutil.copy2(p,stage/p.name)
    for name in ('GenericFlybackPWM.lib','GenericACF_MP6005.lib'):shutil.copy2(ROOT/'resources/spice'/name,stage/name)
    import json
    with Api(working_dir=stage,config_path=sys.argv[2]) as api:
        for n in range(1,7):
            path=stage/f'ACF_Forward_{n}.asc'
            r=api.edit_schematic(target=str(path),base='blank',ops=operations(n),return_views=[])
            if r.get('commit_state')!='committed':raise RuntimeError(r)
            (ROOT/f'artifacts/qa/acf/template_{n}.json').write_text(json.dumps(r,ensure_ascii=False,default=str),encoding='utf-8')
            shutil.copy2(path,ROOT/f'resources/spice/ACF_Forward_{n}.asc')
            shutil.copy2(path.with_suffix('.plt'),ROOT/f'resources/spice/ACF_Forward_{n}.plt')
            print(n, r.get('warnings'),flush=True)
