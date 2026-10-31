"""Analytical identities, dropout boundaries, typed networks and exported data."""
import sys,copy,math,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import ldo
import system_workspace as w

class LdoChecks(unittest.TestCase):
    def test_static_energy_and_lightload(self):
        r=ldo.calculate(dict(V_in_min=5.,V_in_max=12.,I_out_min=0.,Iq_max=50e-6))
        a,b=r['corners'][1],r['corners'][3]
        self.assertAlmostEqual(a['P_chip'],.17025);self.assertAlmostEqual(b['P_chip'],.8706)
        self.assertEqual(r['corners'][0]['eta'],0.)
        for c in r['corners']:self.assertAlmostEqual(c['P_in'],c['P_out']+c['P_chip']+c['P_divider'])
        self.assertGreater(b['T_j'],a['T_j'])
        self.assertTrue(any(c['state']=='undefined' for c in r['checks']))

    def test_adjustable_divider_and_derating(self):
        p=dict(output_mode='adjustable',Iq_max=0.,component_management={'items':{'R1':{'power_W':.001}}})
        r=ldo.calculate(p);d=r['divider'];self.assertAlmostEqual(d['R_bottom'],10000*1.2/2.1)
        self.assertAlmostEqual(d['I_divider'],.00021)
        self.assertEqual(next(c for c in r['checks'] if c['id']=='bom_R1')['state'],'review')
        for c in r['corners']:self.assertAlmostEqual(c['P_in']-c['P_out'],c['P_chip']+c['P_divider'])

    def test_dropout_and_missing_evidence(self):
        r=ldo.calculate(dict(V_in_min=3.5,V_in_max=5.))
        self.assertFalse(r['corners'][0]['regulated']);self.assertIsNone(r['corners'][0]['P_in']);self.assertIsNone(r['corners'][0]['T_j'])
        p=ldo.normalize();p.update(V_in_min=p['V_out']*1.01+p['dropout_max']);self.assertTrue(ldo.calculate(p)['corners'][0]['regulated'])
        for key,value in [('Iq_max',float('nan')),('theta_ja',0),('I_out_min',-.1),('V_out',True),('accuracy_pct',100),('I_out_min',.2)]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):ldo.normalize({key:value})

    def test_network_voltage_dependent_budget_and_dropout(self):
        p=w.load_project(ROOT/'examples/SYSTEM_LDO.json');r=w.checks(p)
        bus=next(x for x in r['capacity'] if x['port']=='BUS-01');self.assertAlmostEqual(bus['allocated'],5.25*.10005)
        self.assertAlmostEqual(r['ldo'][0]['max_loss'],.1952625)
        # Upstream source range, not a stale saved efficiency, controls reserve.
        p['sources'][0]['max']=6.;p['units'][0]['spec']['eta_guess']=.99
        self.assertAlmostEqual(next(x for x in w.checks(p)['capacity'] if x['port']=='BUS-01')['allocated'],6*.10005)
        p['sources'][0]['min']=3.5;r=w.checks(p)
        self.assertFalse(r['ldo'][0]['dropout_ok']);self.assertTrue(any('LOAD-01' in c['unavailable'] for c in r['cases']))
        w.prepare_unit(p,'LDO-01');self.assertEqual(p['units'][0]['spec']['V_in_min'],3.5)
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'系统.json';w.save_project(p,f);self.assertEqual(w.load_project(f),p)

    def test_or_branch_loss_and_multi_fanout(self):
        p=w.load_project(ROOT/'examples/SYSTEM_LDO.json');p['sources'][0].update(min=5.,max=5.)
        p['connections'][0].update(mode='diode',vf=.3);r=w.checks(p)
        self.assertAlmostEqual(next(x for x in r['capacity'] if x['port']=='BUS-01')['allocated'],5*.10005)
        self.assertAlmostEqual(r['diode_losses'][0]['loss'],.3*.10005)
        self.assertAlmostEqual(next(x for x in r['capacity'] if x['port']=='LDO-01/OUT1')['allocated'],.33)
        rec=w.remove_node(p,'unit','LDO-01');w.restore_node(p,rec);self.assertEqual(len(p['connections']),3)

    def test_reports_and_api(self):
        from fastapi.testclient import TestClient
        from web_app.server import create_app
        from ldo_report import export_report
        from zipfile import ZipFile
        r=ldo.calculate(dict(output_mode='adjustable'))
        with tempfile.TemporaryDirectory() as d:
            for kind in ('docx','xlsx','json'):
                path=Path(d)/('LDO.'+kind);export_report(r,path);self.assertGreater(path.stat().st_size,100)
                if kind=='docx':
                    with ZipFile(path) as z:self.assertIn(b'oMath',z.read('word/document.xml'))
                if kind=='xlsx':
                    from openpyxl import load_workbook
                    book=load_workbook(path);self.assertEqual(book['双端点角点对比']['A1'].value,'Vinmin');self.assertEqual(book['双端点角点对比']['I1'].value,'Vinmax')
                if kind=='json':self.assertEqual(w.load_project(path)['units'][0]['spec']['topology'],'LDO')
        with TestClient(create_app(testing=True)) as client:
            h={'X-Power-Token':client.get('/api/bootstrap').json()['token']}
            self.assertEqual(client.post('/api/ldo/calculate',headers=h,json={'spec':{}}).status_code,200)
            self.assertEqual(client.post('/api/ldo/calculate',headers=h,json={'spec':{'theta_ja':0}}).status_code,422)
            self.assertEqual(client.post('/api/ldo/export/xlsx',headers=h,json={'spec':{}}).content[:2],b'PK')

if __name__=='__main__':unittest.main(verbosity=2)
