"""Stable locations, margin/collision checks and geometry package consistency."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from winding_layout import assess_winding_window,validate_winding_config,iter_bundle_sections
from winding_positions import freeze_plan


class WindingPositions(unittest.TestCase):
    def base(self):
        rows=[dict(id='P',name='P',turns=6,strands=1,parallel_wires=2,bare_diameter=.4e-3)]
        cfg=dict(window_width=.01,window_height=.004,margin_x=0.,margin_y=0.,diameter_allowance=0.)
        return rows,cfg,assess_winding_window(rows,cfg)

    def test_manual_movement_changes_only_selected_box_and_keeps_stable_ids(self):
        rows,cfg,a=self.base();self.assertEqual(len(a['cross_sections']),12)
        point=a['cross_sections'][1];center=point['x']+point['width']/2+.05e-3
        cfg.update(layer_plan=freeze_plan(a),turn_positions={point['section_id']:{point['position_key']:center}})
        b=assess_winding_window(rows,cfg)
        self.assertTrue(b['fits'])
        self.assertEqual(a['conductor_count'],b['conductor_count'])
        self.assertEqual(a['copper_fill'],b['copper_fill'])
        for old,new in zip(a['cross_sections'],b['cross_sections']):
            self.assertEqual(old['id'],new['id'])
            self.assertEqual(old['y'],new['y'])
            self.assertAlmostEqual(new['x']-old['x'],.05e-3 if old['id']==point['id'] else 0.)
        bcfg=json.loads(json.dumps(b['config']))
        self.assertEqual(b['cross_sections'],assess_winding_window(rows,bcfg)['cross_sections'])

    def test_collision_boundary_and_orphan_positions_are_explicit(self):
        rows,cfg,a=self.base();sid=a['physical_layers'][0]['section_id']
        for mapping,phrase in [({'1:2':.3e-3},'重叠'),({'1:1':-.1e-3},'留边'),({'7:1':.3e-3},'已失效')]:
            b=assess_winding_window(rows,dict(cfg,turn_positions={sid:mapping}))
            self.assertFalse(b['fits']);self.assertEqual(b['status'],'position_conflict')
            self.assertIn(phrase,' '.join(b['position_issues']))
        for positions in ({'P_A':{'0:1':.2}}, {'P_A':{'1:1':float('nan')}}, {'bad id':{'1:1':1}}):
            with self.assertRaises(ValueError):validate_winding_config(dict(cfg,turn_positions=positions))

    def test_new_parallel_wires_and_offsets_export_and_reopen(self):
        from design_engine.service import calculate
        from transformer_geometry import export_geometry_package,read_geometry_package
        p=json.loads((ROOT/'examples/40W_CCM_3OUT_FLYBACK.json').read_text(encoding='utf-8'))
        p['parallel_wires_p']=2;p['winding_config']['window_width']=.025
        from winding_layout import transformer_windings
        initial=calculate(p,analysis='endpoints',include_loop=False,include_efficiency=False,include_cross_regulation=False)
        c=initial.runtime_bundle()['cases'][0];a=assess_winding_window(transformer_windings(c['result']),p['winding_config'])
        self.assertTrue(a['fits'])
        point=next(s for s in a['cross_sections'] if s['winding_id']=='P' and s['turn']==1 and s['bundle']==2)
        p['winding_config']['turn_positions']={point['section_id']:{point['position_key']:point['x']+point['width']/2+.01e-3}}
        run=calculate(p,analysis='endpoints',include_loop=False,include_efficiency=False,include_cross_regulation=False)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'T1.zip';export_geometry_package(run,path,p);g=read_geometry_package(path)
        w=next(w for w in g['windings'] if w['id']=='P')
        self.assertEqual(w['parallel_wires'],2);self.assertEqual(w['strands_per_wire'],40);self.assertEqual(w['strands'],80)
        boxes=[b for s in g['physical_sections'] if s['winding_id']=='P' for b in s['bundles']]
        self.assertEqual(len(boxes),12)
        self.assertAlmostEqual(boxes[1]['center_uv_m'][0],p['winding_config']['turn_positions'][point['section_id']][point['position_key']])

    def test_live_preview_skips_bitmap_and_retains_snapshot(self):
        from unittest.mock import patch
        from web_app.actions import execute,validate_options
        rows,cfg,a=self.base()
        result=dict(mag=dict(transformer=dict(ok=True,Np=6,Ns=2,n_strand_p=1,n_strand_s=1,
            parallel_wires_p=2,parallel_wires_s=1,d_wire_p=.4e-3,d_wire_s=.4e-3)))
        case=dict(id='Vinmin',p={},result=result)
        class Run:
            def runtime_bundle(self):return dict(cases=[case])
        before=copy.deepcopy(case)
        with tempfile.TemporaryDirectory() as folder,patch('web_app.actions._figure',side_effect=AssertionError('unneeded PNG')):
            response=execute(Run(),'winding_preview',dict(config=cfg,render_chart=False),str(Path(folder)/'preview.png'))
        self.assertFalse(response['has_chart']);self.assertTrue(response['assessment']['editable'])
        self.assertEqual(len(response['assessment']['cross_sections']),14);self.assertEqual(case,before)
        with self.assertRaises(ValueError):validate_options('winding_preview',dict(config=cfg,render_chart=1))

    def test_report_records_copies_and_manual_centers(self):
        from winding_report import add_winding_snapshot
        from report_xlsx import _capture_document
        from docx_layout import new_document
        rows,cfg,a=self.base();point=a['cross_sections'][1]
        center=point['x']+point['width']/2+.05e-3
        cfg.update(turn_positions={point['section_id']:{point['position_key']:center}})
        result=dict(mag=dict(transformer=dict(ok=True,Np=6,Ns=2,n_strand_p=1,n_strand_s=1,
            parallel_wires_p=2,parallel_wires_s=1,d_wire_p=.4e-3,d_wire_s=.4e-3)))
        doc=new_document('绕制检查','测试','测试')
        a=add_winding_snapshot(doc,dict(winding_config=cfg),result)
        self.assertEqual(a['windings'][0]['bundle_count'],12)
        text=' '.join(c.text for t in doc.tables for r in t.rows for c in r.cells)
        self.assertIn('6 × 1 × 2',text);self.assertIn(f'{center*1e3:.6g}',text)
        self.assertIn('中心 X / mm',str(_capture_document(doc)))


if __name__=='__main__':unittest.main(verbosity=2)
