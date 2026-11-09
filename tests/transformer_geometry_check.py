"""The CAD exchange binds original bytes, the endpoint snapshot and actual plot boxes."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from design_engine.service import calculate
from transformer_geometry import (export_geometry_package,read_geometry_package,resolve_geometry,
                                  strict_json,validate_geometry)
from transformer_geometry_contract import profile_template,validate_profile,GEOMETRY_SCHEMA,PROFILE_SCHEMA
from winding_layout import validate_winding_config,iter_bundle_sections


def connected_profile(layers):
    p=profile_template(layers)
    p['frame'].update(z0_m=0.,r0_m_if_circular=.006)
    p['bobbin'].update(winding_route_type='circular',status='assumed',source='测试用名义圆形骨架')
    pins={'OUT1_A':('14','12'),'P_A':('1','2'),'OUT2_A':('11','10'),'OUT3_A':('9','8'),'OUT1_B':('12','13')}
    for key,(start,end) in pins.items():
        p['sections'][key].update(start_node=start,end_node=end,dot_node=start,direction='ccw',status='assumed',source='测试接线')
    for key,port in p['ports'].items():
        ids=[k for k,s in p['sections'].items() if s['winding_id']==key]
        port.update(connection='series',section_order=ids,dot_node=pins[ids[0]][0],other_node=pins[ids[-1]][1],
                    status='assumed',source='测试接线')
    p['terminals']=[dict(node='12',pin='12',position_xyz_m=None,external_connection='none',net=None,status='assumed',source='测试接线')]
    return p


class GeometryExchange(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=(ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_bytes()
        cls.cfg=strict_json(cls.raw)
        cls.design_run=calculate(cls.cfg,analysis='endpoints',include_loop=False,include_cross_regulation=False)
        cls.cases=cls.design_run.runtime_bundle()['cases']
        cls.g,cls.assess=resolve_geometry(cls.cases,'b'*64,'a'*64,'three-out')

    def resolve(self,p=None):
        return resolve_geometry(self.cases,'b'*64,'a'*64,'three-out',p)[0]

    def test_reference_layers_and_boxes(self):
        g=self.g
        self.assertEqual(g['ready'],dict(cross_section=True,geometry_3d=False,electromagnetic=False))
        self.assertEqual([s['section_id'] for s in g['physical_sections']],['OUT1_A','P_A','OUT2_A','OUT3_A','OUT1_B'])
        self.assertEqual([s['turns'] for s in g['physical_sections']],[6,6,5,2,6])
        self.assertAlmostEqual(g['checks']['height_margin_m'],6.813235904261014e-6,places=13)
        self.assertEqual([c['vin_V'] for c in g['operating_points']],[20.,30.])
        self.assertEqual(g['design_targets']['coupling_order'],['P','OUT1','OUT2','OUT3'])
        for row in self.assess['windings']:
            actual=[b['bbox_uv_m'] for s in g['physical_sections'] if s['winding_id']==row['id'] for b in s['bundles']]
            self.assertEqual(actual,[list(v) for v in iter_bundle_sections(row,self.assess['config'])])
        w=next(w for w in g['windings'] if w['id']=='OUT1')
        self.assertGreater(w['first_to_last_span_m'],w['sum_layer_envelope_height_m'])
        self.assertGreater(g['physical_sections'][0]['layer_envelope_uv_m'][2],g['physical_sections'][0]['occupied_width_m'])
        self.assertIsNone(g['connection_matrix']['values'])

    def test_profile_and_signed_connections(self):
        p=connected_profile(self.g['physical_sections'])
        g=self.resolve(p)
        self.assertTrue(g['ready']['geometry_3d'])
        self.assertFalse(g['ready']['electromagnetic'])
        m=g['connection_matrix']
        self.assertEqual(m['values'],[[0,1,0,0],[1,0,0,0],[0,0,1,0],[0,0,0,1],[0,1,0,0]])
        b=g['physical_sections'][0]['bundles'][0]
        self.assertEqual(b['center_rz_m'],[.006+b['center_uv_m'][1],b['center_uv_m'][0]])
        tapped=copy.deepcopy(p);tapped['terminals'][0].update(external_connection='net',net='AUX_LOAD')
        self.assertIsNone(self.resolve(tapped)['connection_matrix']['values'])
        p['sections']['OUT1_B']['dot_node']='13'
        g=self.resolve(p)
        self.assertEqual(g['connections'][1]['effective_series_turns'],0)
        self.assertEqual(g['connection_matrix']['values'][-1],[0,-1,0,0])
        self.assertFalse(g['ready']['geometry_3d'])
        p['ports']['OUT1']['section_order'].reverse()
        with self.assertRaises(ValueError):self.resolve(p)

    def test_partial_geometry_and_path_checks(self):
        p=connected_profile(self.g['physical_sections'])
        b=p['bobbin'];p['frame']['r0_m_if_circular']=None
        b.update(winding_route_type='rounded_rectangle',rounded_rectangle_m=dict(center_xy_m=[0,0],width_m=.012,height_m=.01,corner_radius_m=.002))
        self.assertTrue(self.resolve(p)['ready']['geometry_3d'])
        b.update(winding_route_type='custom_closed',rounded_rectangle_m=None,
                 winding_path_xy_m=[[0,0],[.01,0],[.01,.02],[0,.02],[0,0]])
        self.assertTrue(self.resolve(p)['ready']['geometry_3d'])
        b['winding_path_xy_m']=[[0,0],[.01,.02],[0,.02],[.01,0],[0,0]]
        with self.assertRaises(ValueError):validate_profile(p)
        altered=copy.deepcopy(self.g);altered['ready']['geometry_3d']=True
        with self.assertRaises(ValueError):validate_geometry(altered)
        with self.assertRaises(ValueError):validate_profile({'schema':'unknown'})
        cases=copy.deepcopy(self.cases);cases[1]['error']='test'
        with self.assertRaises(ValueError):resolve_geometry(cases,'b'*64,'a'*64,'case')
        with self.assertRaises(ValueError):resolve_geometry(self.cases[:1],'b'*64,'a'*64,'case')
        cases=copy.deepcopy(self.cases);cases[1]['p']['winding_config']['margin_x']*=.9
        with self.assertRaisesRegex(ValueError,'不一致'):resolve_geometry(cases,'b'*64,'a'*64,'case')
        for c in cases:c['p'].pop('winding_config',None)
        partial,_=resolve_geometry(cases,'b'*64,'a'*64,'case')
        self.assertFalse(partial['ready']['cross_section'])
        self.assertEqual(len(partial['windings']),4)

    def test_ids_and_parallel_bundle_conservation(self):
        plan=validate_winding_config(self.cfg['winding_config'])['layer_plan']
        ids=[r['section_id'] for r in plan]
        plan.insert(0,dict(winding_id='OUT1',turns=1))
        assigned=validate_winding_config(dict(layer_plan=plan))['layer_plan']
        self.assertEqual([r['section_id'] for r in assigned[1:]],ids)
        self.assertNotIn(assigned[0]['section_id'],ids)
        assigned[0]['section_id']=ids[-1]
        with self.assertRaises(ValueError):validate_winding_config(dict(layer_plan=assigned))
        cases=copy.deepcopy(self.cases)
        for c in cases: c['p']['winding_config']['overrides']['P']['parallel_bundles']=2
        with self.assertRaisesRegex(ValueError,'窗口容量'):resolve_geometry(cases,'b'*64,'a'*64,'test')
        for c in cases: c['p']['winding_config']['window_width']=.018
        g,_=resolve_geometry(cases,'b'*64,'a'*64,'test')
        p=next(s for s in g['physical_sections'] if s['winding_id']=='P')
        self.assertEqual(len(p['bundles']),12)
        self.assertEqual(len({b['turn_id'] for b in p['bundles']}),6)

    def test_package_roundtrip_original_and_edited_input(self):
        from jsonschema import Draft202012Validator
        for schema in (GEOMETRY_SCHEMA,PROFILE_SCHEMA):Draft202012Validator.check_schema(schema)
        raw=b'\xef\xbb\xbf'+self.raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'data.zip'
            export_geometry_package(self.design_run,path,self.cfg,original_name='T1.json',original_bytes=raw)
            g=read_geometry_package(path)
            with ZipFile(path) as z:
                self.assertEqual(z.read('calculator-input.json'),raw)
                self.assertEqual(g['source']['input_sha256'],hashlib.sha256(raw).hexdigest())
                self.assertIn(b'<svg',z.read('cross-section.svg'))
                self.assertTrue(z.read('cross-section.png').startswith(b'\x89PNG'))
                self.assertEqual(strict_json(z.read('manifest.json'))['input_kind'],'original_bytes')
            changed=dict(self.cfg,__comment='edited working project')
            export_geometry_package(self.design_run,path,changed,original_name='T1.json',original_bytes=raw)
            read_geometry_package(path)
            with ZipFile(path) as z:
                self.assertEqual(z.read('source-input.original.json'),raw)
                self.assertEqual(strict_json(z.read('calculator-input.json')),changed)
            before=path.read_bytes()
            with self.assertRaises(ValueError):export_geometry_package(self.design_run,path,dict(self.cfg,L=1.))
            self.assertEqual(path.read_bytes(),before)
            with ZipFile(path) as src,ZipFile(Path(tmp)/'damaged.zip','w') as dst:
                for name in src.namelist():
                    dst.writestr(name,b'broken' if name=='cross-section.png' else src.read(name))
            with self.assertRaisesRegex(ValueError,'校验'):read_geometry_package(Path(tmp)/'damaged.zip')


if __name__=='__main__':unittest.main(verbosity=2)
