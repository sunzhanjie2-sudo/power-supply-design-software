"""Physical power-accounting examples for diode OR-ing and editable loads."""
import copy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import system_workspace as w


def base():
    p=w.fresh_project();p['units']=[];p['connections']=[];p['activeUnit']=''
    p['sources']=[dict(id='A',name='主电源',min=24,max=24,capacity=100,enabled=True),
                  dict(id='B',name='备用电源',min=22,max=22,capacity=100,enabled=True)]
    p['loads']=[dict(id='DSP',name='控制板与采样',power=10,min=20,max=25,enabled=True)]
    return w.normalize_project(p)


def link(p,target,source,port=1,kind='bus',vf=.3):
    identity=w.connect(p,target,dict(kind=kind,id=source,output=port))
    e=next(e for e in p['connections'] if e['id']==identity);e['vf']=vf
    return identity


class NetworkChecks(unittest.TestCase):
    def test_highest_voltage_wins_and_backup_budget_not_double_counted(self):
        p=base();a=link(p,'DSP','A');b=link(p,'DSP','B',vf=.5)
        r=w.checks(p);budget={v['port']:v for v in r['capacity']}
        self.assertAlmostEqual(budget['A']['normal'],10*24/23.7)
        self.assertAlmostEqual(budget['B']['normal'],0)
        self.assertAlmostEqual(budget['B']['allocated'],10*22/21.5)
        self.assertAlmostEqual(r['interfaces'][0]['source_min'],21.5)
        self.assertAlmostEqual(r['interfaces'][0]['source_max'],23.7)
        self.assertTrue(all(c['routes']['DSP']==a for c in r['cases'] if c['normal']))
        losses={d['connection']:d['loss'] for d in r['diode_losses']}
        self.assertAlmostEqual(losses[b],10*.5/21.5)
        self.assertEqual(len(p['connections']),2)

    def test_equal_voltage_does_not_invent_current_sharing(self):
        p=base();p['sources'][1]['min']=p['sources'][1]['max']=24
        a=link(p,'DSP','A');b=link(p,'DSP','B')
        r=w.checks(p);normal=[c for c in r['cases'] if c['normal']]
        self.assertEqual({c['routes']['DSP'] for c in normal},{a,b})
        for c in normal:self.assertAlmostEqual(sum(c['allocated'].values()),10*24/23.7)
        for row in r['capacity']:self.assertAlmostEqual(row['allocated'],10*24/23.7)

    def test_or_bus_fans_out_and_root_accounts_diode_loss_once(self):
        p=base();p['junctions']=[dict(id='OR',name='24V竞争母线',capacity=12,enabled=True)]
        p['loads'].append(dict(id='FAN',name='风扇',power=5,min=18,max=26,enabled=True))
        link(p,'OR','A');link(p,'OR','B');link(p,'DSP','OR',kind='junction');link(p,'FAN','OR',kind='junction')
        r=w.checks(p);budget={v['port']:v for v in r['capacity']}
        self.assertEqual(budget['OR']['normal'],15)
        self.assertFalse(budget['OR']['ok'])
        self.assertAlmostEqual(budget['A']['normal'],15*24/23.7)
        self.assertAlmostEqual(budget['B']['allocated'],15*22/21.7)

    def test_same_source_feeds_converter_and_named_load(self):
        p=base();spec=w.fresh_project()['units'][0]['spec']
        p['units']=[dict(id='PSU',name='隔离模块',spec=spec,enabled=True)]
        p=w.normalize_project(p)
        link(p,'PSU','A');link(p,'DSP','A')
        r=w.checks(p);budget={v['port']:v for v in r['capacity']}
        self.assertAlmostEqual(budget['A']['normal'],40/.93+10)

    def test_cascade_load_reserves_output_rating_not_twice_on_input(self):
        p=base();p['units']=[dict(id='PSU',name='主电源',spec=w.fresh_project()['units'][0]['spec'])]
        p=w.normalize_project(p)
        link(p,'PSU','A');link(p,'DSP','PSU',kind='unit')
        r=w.checks(p);budget={v['port']:v for v in r['capacity']}
        self.assertAlmostEqual(budget['A']['allocated'],40/.93)
        self.assertEqual(budget['PSU/OUT1']['allocated'],10)

    def test_disabled_source_and_branch_lose_supply_explicitly(self):
        p=base();link(p,'DSP','A');b=link(p,'DSP','B')
        p['sources'][0]['enabled']=False
        e=next(e for e in p['connections'] if e['id']==b);e['enabled']=False
        r=w.checks(p)
        self.assertFalse(r['interfaces'][0]['normal_available'])
        self.assertIsNone(r['interfaces'][0]['source_min'])

    def test_delete_undo_restores_fanin_without_overwriting_rewire(self):
        p=base();link(p,'DSP','A');link(p,'DSP','B')
        record=w.remove_node(p,'bus','A');self.assertEqual(len(p['connections']),1)
        w.restore_node(p,record);self.assertEqual(len(p['connections']),2)
        record=w.remove_node(p,'bus','A')
        w.disconnect(p,p['connections'][0]['id'])
        w.restore_node(p,record);self.assertEqual(p['connections'],[])

    def test_reject_direct_parallel_and_cycles_preserves_project(self):
        p=base();link(p,'DSP','A');link(p,'DSP','B')
        p['connections'][0]['mode']='direct'
        with self.assertRaisesRegex(ValueError,'隔离'):w.normalize_project(p)
        p=base();p['junctions']=[dict(id='J1',name='汇流1',capacity=20),dict(id='J2',name='汇流2',capacity=20)]
        p=w.normalize_project(p);link(p,'J1','J2',kind='junction');old=copy.deepcopy(p)
        with self.assertRaisesRegex(ValueError,'循环'):link(p,'J2','J1',kind='junction')
        self.assertEqual(p,old)

    def test_legacy_project_migrates_connections_and_keeps_names(self):
        from pcs_workspace import SCHEMA
        p=w.fresh_project();p.update(schema_version=SCHEMA)
        p['units'][0]['source']=dict(kind='bus',id='BUS-01',output=1)
        for key in ('loads','junctions','connections'):p.pop(key)
        result=w.normalize_project(p)
        self.assertEqual(result['schema_version'],w.SCHEMA)
        self.assertEqual(result['connections'][0]['target'],'PSU-01')


if __name__=='__main__':unittest.main(verbosity=2)
