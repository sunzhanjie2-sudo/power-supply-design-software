"""Shipped real-part coverage and legacy-file isolation, not hardware approval."""
import json
import math
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from config_io import decode_config,read_default_config
from design_engine.specification import load_spec
from component_management import component_registry
from capacitor_banks import bank,output_ref
from device_curve_sources import source_for,TRANSFER


class RealExampleParts(unittest.TestCase):
    def specs(self):
        for path in (ROOT/'examples').glob('*.json'):
            raw=json.loads(path.read_text('utf-8-sig'))
            rows=[u['spec'] for u in raw['units']] if 'units' in raw else [raw]
            for row in rows:
                yield path.name,row

    def test_every_shipped_spec_has_explicit_traceable_identity(self):
        count=0
        for name,raw in self.specs():
            count+=1
            self.assertIn('__real_parts',raw,name)
            if raw.get('topology')=='LDO':
                import ldo
                p=ldo.normalize(raw)
                self.assertEqual(p['model'],'TLV75533PDBVR')
                refs=['U1','C_IN1','C_OUT1']
            else:
                p=load_spec(raw)
                refs=[r['ref'] for r in component_registry(p)]
                self.assertEqual(p['device_curve_settings']['mode'],'fixed')
                self.assertFalse(p['mos_miller_curve']);self.assertFalse(p['mos_charge_curve'])
                self.assertFalse(p['diode_curves']);self.assertFalse(p['mos_manual_events'])
                self.assertEqual(len(set(refs)),len(refs))
            for ref in refs:
                item=p['component_management']['items'].get(ref,{})
                self.assertTrue(all(item.get(k) for k in ('manufacturer','model','package')),name+' '+ref)
                self.assertTrue(item.get('note') or item.get('conditions'),name+' '+ref)
        self.assertEqual(count,19)

    def test_capacitor_voltage_ratings_cover_each_nominal_port(self):
        for name,raw in self.specs():
            if raw.get('topology')=='LDO':continue
            p=load_spec(raw);items=p['component_management']['items']
            voltage=p.get('V_in_max',p['V_in'])
            for i,_ in enumerate(bank(p,'input'),1):
                self.assertLessEqual(voltage,items['C_IN'+str(i)]['voltage_V']*.9,name)
            rails=p.get('outputs') or [p];multi=bool(p.get('outputs') or p.get('feedback_mode')=='PSR-MP6005')
            for i,rail in enumerate(rails,1):
                for j,_ in enumerate(bank(dict(p,**rail)),1):
                    ref=output_ref(i,j,multi)
                    self.assertLessEqual(abs(rail.get('V_out',p['V_out'])),items[ref]['voltage_V']*.9,name+' '+ref)

    def test_known_switching_reference_conditions_are_not_mixed(self):
        for name,raw in self.specs():
            if raw.get('topology')=='LDO':continue
            p=load_spec(raw);items=p['component_management']['items']
            if p['topology']=='BUCK':
                self.assertIn('DMP6023LE',items['Q1']['model'])
                self.assertIn('P-channel',items['Q1']['note'])
            if p['topology']=='QR-FLYBACK':
                self.assertAlmostEqual(p['spice_config']['qr_cds_pf'],p['Coss']*1e12)
                self.assertEqual(items['C_O1']['voltage_V'],100.)
                self.assertEqual(len(bank(p)),3)
            for i,rail in enumerate(p.get('outputs') or [],1):
                key=raw['__real_parts']['selections']['D_O'+str(i)]['key']
                self.assertEqual(rail['Qrr'],0. if key=='STTH8L06D' else 15e-9)

    def test_startup_example_does_not_inject_identity_or_disable_legacy_curves(self):
        from mos_curves_check import demo
        raw=dict(topology='BUCK',V_in=12.,V_out=5.,P_out=5.,f_sw=100e3,L=47e-6,
                 Cin1=47e-6,Cin2=22e-6,cin2_enable=True,C_out=100e-6,C_out2=22e-6,
                 mos_miller_mode='curve',mos_miller_curve=demo())
        p=load_spec(raw)
        self.assertEqual(p['component_management']['items'],{})
        self.assertEqual(source_for(p,TRANSFER),'curve')
        self.assertEqual([r['C'] for r in bank(p,'input')],[47e-6,22e-6])
        actual=load_spec(read_default_config())
        self.assertIn('Q1',actual['component_management']['items'])
        self.assertEqual(actual['device_curve_settings']['mode'],'fixed')


if __name__=='__main__':unittest.main(verbosity=2)
