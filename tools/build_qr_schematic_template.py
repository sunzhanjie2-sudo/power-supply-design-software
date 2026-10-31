"""Prepare one-rail QR template operations for the guarded MCP ASC editor."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from build_spice_schematic_templates import operations
from qr_spice_export import CONTROL_KEYS


def qr_operations():
    ops=operations(1)
    for op in ops:
        if op.get('reference')=='U_CTRL':
            op.update(symbol='GQR_CTRL',value='GQR_CTRL',attributes=dict(SpiceLine=' '.join(k+'={'+k+'}' for k in CONTROL_KEYS)))
        if op.get('reference')=='VCC_SOURCE':op['value']='{QR_VCC}'
        if op.get('instruction','').startswith('CONFIGURABLE FLYBACK'):
            op['instruction']='QR FLYBACK SSR -- L6565-inspired ZCD / CS event-driven controller'
        if op.get('instruction','').startswith('Controller settings:'):
            op['instruction']='ZCD triggers turn-on; CS triggers turn-off. FSW is a measurement reference, NOT a clock.'
    ops += [dict(op='add_net_label',net='zcd',pin='U_CTRL.ZCD'),
        dict(op='add_component',reference='ZCD',symbol='QR_ZCD',x=1440,y=624,value='GQR_ZCD',
             attributes=dict(SpiceLine='RATIO={Z_RATIO} RZ={Z_R} CZ={Z_C}')),
        dict(op='add_net_label',net='drain',pin='ZCD.DRAIN'),
        dict(op='add_net_label',net='vin_bus',pin='ZCD.VIN'),
        dict(op='add_net_label',net='zcd',pin='ZCD.ZCD'),
        dict(op='add_net_label',net='0',pin='ZCD.COM'),
        dict(op='add_directive',kind='comment',instruction='ZCD: unloaded auxiliary winding voltage replica + RC + clamps. Not VCC supply.',x=1152,y=800,size=2),
        dict(op='set_plot_panes',analysis='tran',panes=[dict(traces=['V(out1,sgnd)']),dict(traces=['V(drain,sense)','V(gate,sense)']),dict(traces=['I(LP)','I(LS1)']),dict(traces=['V(zcd)'])])]
    return ops


if __name__=='__main__':print(json.dumps(qr_operations()))
