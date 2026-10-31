"""Mechanical-window geometry is independent of the electrical solver."""
import copy
import json
import math
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from winding_layout import (validate_winding_config,transformer_windings,
                            assess_winding_window,draw_winding_cross_section,
                            iter_bundle_sections)


def winding(key='P',turns=10,strands=1,diameter=.5e-3):
    return dict(id=key,name=key,turns=turns,strands=strands,bare_diameter=diameter)


def config(**extra):
    return dict(window_width=5e-3,window_height=3e-3,margin_x=0.,margin_y=0.,
        diameter_allowance=0.,layer_insulation=0.,interwinding_insulation=0.,wire_gap=0.,**extra)


class WindingGeometryChecks(unittest.TestCase):
    def test_unconfigured_dimensions_not_guessed_from_core_area(self):
        result=assess_winding_window([winding()])
        self.assertFalse(result['configured'])
        self.assertIsNone(result['fits'])

    def test_exact_width_boundary_does_not_lose_a_turn(self):
        result=assess_winding_window([winding()],config())
        row=result['windings'][0]
        self.assertEqual(row['turns_per_layer'],10)
        self.assertEqual(row['layers'],1)
        self.assertAlmostEqual(result['required_height'],.5e-3)
        self.assertTrue(result['fits'])

    def test_partial_last_layer_and_tape_build_up(self):
        cfg=config();cfg['layer_insulation']=.1e-3
        result=assess_winding_window([winding(turns=21)],cfg)
        self.assertEqual(result['windings'][0]['layers'],3)
        self.assertAlmostEqual(result['required_height'],1.7e-3)

    def test_margins_are_subtracted_on_both_sides(self):
        cfg=config();cfg.update(margin_x=.5e-3,margin_y=.2e-3)
        result=assess_winding_window([winding()],cfg)
        self.assertEqual(result['windings'][0]['turns_per_layer'],8)
        self.assertAlmostEqual(result['required_height'],1.4e-3)
        self.assertAlmostEqual(result['usable_height'],2.6e-3)

    def test_enamel_uses_outer_diameter_not_bare_area_only(self):
        cfg=config();cfg['diameter_allowance']=.1e-3
        result=assess_winding_window([winding()],cfg)
        self.assertEqual(result['windings'][0]['turns_per_layer'],8)
        self.assertGreater(result['insulated_wire_fill'],result['copper_fill'])
        self.assertAlmostEqual(result['copper_fill'],10*math.pi*(.5e-3)**2/4/(5e-3*3e-3))

    def test_every_parallel_strand_is_counted_but_only_one_equivalent_bundle(self):
        result=assess_winding_window([winding(turns=3,strands=7)],config())
        row=result['windings'][0]
        self.assertEqual(row['layout_model'],'equivalent')
        self.assertEqual(row['wire_type'],'litz')
        self.assertEqual(row['parallel_bundles'],1)
        self.assertEqual(row['strands_per_bundle'],7)
        self.assertEqual(row['conductor_count'],21)
        self.assertEqual(row['bundle_count'],3)
        diameter=.5e-3*math.sqrt(7/.75)
        self.assertAlmostEqual(row['bundle_diameter'],diameter)
        self.assertAlmostEqual(row['bundle_width'],diameter*1.5)
        self.assertAlmostEqual(row['bundle_height'],diameter/1.5)

    def test_legacy_explicit_columns_preserve_distinct_geometries(self):
        rows=[winding(turns=6,strands=8)]
        compact=config();compact['overrides']={'P':dict(strand_columns=3)}
        a=assess_winding_window(rows,compact)
        cfg=config();cfg['overrides']={'P':dict(strand_columns=8)}
        b=assess_winding_window(rows,cfg)
        self.assertEqual(a['windings'][0]['layout_model'],'legacy_rectangular')
        self.assertEqual(a['windings'][0]['strand_rows'],3)
        self.assertAlmostEqual(a['windings'][0]['bundle_width'],1.5e-3)
        self.assertAlmostEqual(b['windings'][0]['bundle_width'],4e-3)
        self.assertNotEqual(a['windings'][0]['layers'],b['windings'][0]['layers'])
        self.assertEqual(a['conductor_count'],b['conductor_count'])
        self.assertAlmostEqual(a['copper_fill'],b['copper_fill'])

    def test_zero_legacy_columns_select_new_equivalent_model(self):
        cfg=config();cfg['overrides']={'P':dict(strand_columns=0,wire_type='litz')}
        result=assess_winding_window([winding(strands=4)],cfg)
        self.assertEqual(result['windings'][0]['layout_model'],'equivalent')

    def test_legacy_columns_and_new_geometry_cannot_mix_silently(self):
        for extra in (dict(wire_type='solid'),dict(parallel_bundles=1),
                      dict(winding_style='sparse'),dict(flatten_ratio=1.5)):
            cfg=config();cfg['overrides']={'P':dict(strand_columns=2,**extra)}
            with self.assertRaises(ValueError):
                assess_winding_window([winding(strands=4)],cfg)

    def test_flattening_preserves_equivalent_section_area(self):
        cfg=config();cfg['overrides']={'P':dict(flatten_ratio=1.5)}
        row=assess_winding_window([winding(turns=2,strands=4)],cfg)['windings'][0]
        self.assertAlmostEqual(row['bundle_width']/row['bundle_diameter'],1.5)
        self.assertAlmostEqual(row['bundle_height']/row['bundle_diameter'],1/1.5)
        self.assertAlmostEqual(math.pi*row['bundle_width']*row['bundle_height']/4,
                               math.pi*row['bundle_diameter']**2/4)

    def test_single_copper_wire_never_flattens_even_explicit_litz(self):
        for kind in ('auto','solid','litz'):
            cfg=config();cfg['overrides']={'P':dict(wire_type=kind,flatten_ratio=2.)}
            row=assess_winding_window([winding(strands=1)],cfg)['windings'][0]
            self.assertEqual(row['wire_type'],'solid')
            self.assertEqual(row['flatten_ratio'],1.)
            self.assertAlmostEqual(row['bundle_width'],.5e-3)
            self.assertAlmostEqual(row['bundle_width'],row['bundle_height'])

    def test_parallel_ordinary_copper_is_equivalent_round_not_flattened(self):
        cfg=config();cfg['overrides']={'P':dict(wire_type='solid',flatten_ratio=2.)}
        row=assess_winding_window([winding(strands=4)],cfg)['windings'][0]
        self.assertEqual(row['wire_type'],'solid')
        self.assertEqual(row['flatten_ratio'],1.)
        self.assertAlmostEqual(row['bundle_width'],row['bundle_height'])
        self.assertAlmostEqual(row['bundle_diameter'],.5e-3*math.sqrt(4/.75))

    def test_three_parallel_twenty_strand_bundles_conserve_electrical_copper(self):
        cfg=config();cfg['window_width']=12e-3
        cfg['wire_gap']=.1e-3
        cfg['overrides']={'P':dict(parallel_bundles=3,turns_per_layer=2)}
        electrical=[winding(turns=3,strands=60,diameter=.1e-3)]
        before=copy.deepcopy(electrical)
        result=assess_winding_window(electrical,cfg);row=result['windings'][0]
        self.assertEqual(electrical,before)
        self.assertEqual(row['strands'],60)
        self.assertEqual(row['strands_per_bundle'],20)
        self.assertEqual(row['parallel_bundles'],3)
        self.assertEqual(row['conductor_count'],180)
        self.assertEqual(row['bundle_count'],9)
        self.assertEqual(len(list(iter_bundle_sections(row,result['config']))),9)
        self.assertAlmostEqual(row['turn_width'],3*row['bundle_width']+2*.1e-3)
        self.assertAlmostEqual(result['copper_fill'],180*math.pi*(.1e-3)**2/4/(12e-3*3e-3))

    def test_parallel_single_wires_resolve_solid(self):
        cfg=config();cfg['overrides']={'P':dict(parallel_bundles=4,wire_type='litz')}
        row=assess_winding_window([winding(turns=1,strands=4)],cfg)['windings'][0]
        self.assertEqual(row['wire_type'],'solid')
        self.assertEqual(row['strands_per_bundle'],1)
        self.assertEqual(row['flatten_ratio'],1.)
        self.assertAlmostEqual(row['turn_width'],2e-3)

    def test_measured_bundle_diameter_overrides_packing_estimate(self):
        cfg=config();cfg['overrides']={'P':dict(bundle_diameter=1.3e-3,packing_factor=.6)}
        row=assess_winding_window([winding(turns=1,strands=4)],cfg)['windings'][0]
        self.assertAlmostEqual(row['bundle_diameter'],1.3e-3)
        self.assertAlmostEqual(row['bundle_width'],1.95e-3)
        self.assertAlmostEqual(row['bundle_height'],1.3e-3/1.5)

    def test_measured_bundle_cannot_contain_less_area_than_insulated_strands(self):
        cfg=config();cfg['diameter_allowance']=.1e-3
        cfg['overrides']={'P':dict(bundle_diameter=1.1e-3)}
        with self.assertRaises(ValueError):
            assess_winding_window([winding(strands=4)],cfg)

    def test_flattened_bundle_cannot_be_thinner_than_one_insulated_strand(self):
        for change in (dict(packing_factor=1.,flatten_ratio=1.5),
                       dict(packing_factor=.75,flatten_ratio=2.)):
            cfg=config();cfg['overrides']={'P':change}
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'束高'):
                assess_winding_window([winding(strands=2)],cfg)

    def test_flattened_height_equal_to_one_strand_remains_valid_boundary(self):
        cfg=config();cfg['overrides']={'P':dict(packing_factor=.5,flatten_ratio=2.)}
        row=assess_winding_window([winding(turns=1,strands=2)],cfg)['windings'][0]
        self.assertAlmostEqual(row['bundle_height'],row['outer_diameter'])

    def test_packing_factor_changes_envelope_not_copper_area(self):
        a=config();a['overrides']={'P':dict(packing_factor=1.)}
        b=config();b['overrides']={'P':dict(packing_factor=.5)}
        ar=assess_winding_window([winding(turns=2,strands=4)],a)
        br=assess_winding_window([winding(turns=2,strands=4)],b)
        self.assertAlmostEqual(br['windings'][0]['bundle_diameter'],
                               ar['windings'][0]['bundle_diameter']*math.sqrt(2))
        self.assertAlmostEqual(ar['copper_fill'],br['copper_fill'])
        self.assertAlmostEqual(ar['insulated_wire_fill'],br['insulated_wire_fill'])

    def test_sparse_layers_span_width_and_last_single_turn_is_centered(self):
        cfg=config();cfg['wire_gap']=.1e-3
        cfg['overrides']={'P':dict(winding_style='sparse',turns_per_layer=3)}
        result=assess_winding_window([winding(turns=7)],cfg)
        row=result['windings'][0];sections=list(iter_bundle_sections(row,result['config']))
        self.assertEqual(row['capacity'],8)
        self.assertEqual(row['turns_per_layer'],3)
        self.assertEqual(row['layers'],3)
        for actual,expected in zip([x[0] for x in sections],[0,2.25e-3,4.5e-3,0,2.25e-3,4.5e-3,2.25e-3]):
            self.assertAlmostEqual(actual,expected)
        for actual,expected in zip([x[1] for x in sections],[0,0,0,.5e-3,.5e-3,.5e-3,1e-3]):
            self.assertAlmostEqual(actual,expected)

    def test_dense_left_and_right_align_every_layer_including_partial(self):
        for style,expected in (
            ('dense_left',[0,.6e-3,1.2e-3,0,.6e-3,1.2e-3,0]),
            ('dense_right',[3.3e-3,3.9e-3,4.5e-3,3.3e-3,3.9e-3,4.5e-3,4.5e-3])):
            cfg=config();cfg['wire_gap']=.1e-3
            cfg['overrides']={'P':dict(winding_style=style,turns_per_layer=3)}
            result=assess_winding_window([winding(turns=7)],cfg)
            sections=list(iter_bundle_sections(result['windings'][0],result['config']))
            for actual,wanted in zip([x[0] for x in sections],expected):
                self.assertAlmostEqual(actual,wanted)

    def test_sparse_parallel_bundles_stay_together_in_turn_groups(self):
        cfg=config();cfg['window_width']=12e-3;cfg['wire_gap']=.1e-3
        cfg['overrides']={'P':dict(parallel_bundles=3,turns_per_layer=2,winding_style='sparse')}
        result=assess_winding_window([winding(turns=3,strands=60,diameter=.1e-3)],cfg)
        row=result['windings'][0];s=list(iter_bundle_sections(row,result['config']))
        pitch=row['bundle_width']+cfg['wire_gap']
        self.assertAlmostEqual(s[1][0]-s[0][0],pitch)
        self.assertAlmostEqual(s[2][0]-s[1][0],pitch)
        self.assertAlmostEqual(s[5][0]+s[5][2],12e-3)
        self.assertAlmostEqual(s[6][0],(12e-3-row['turn_width'])/2)

    def test_positions_respect_margins_and_section_height_matches_fit(self):
        cfg=config();cfg.update(margin_x=.25e-3,margin_y=.2e-3,layer_insulation=.1e-3)
        cfg['overrides']={'P':dict(turns_per_layer=3,winding_style='sparse')}
        result=assess_winding_window([winding(turns=7)],cfg)
        sections=list(iter_bundle_sections(result['windings'][0],result['config']))
        self.assertAlmostEqual(sections[0][0],.25e-3)
        self.assertAlmostEqual(sections[2][0]+sections[2][2],4.75e-3)
        self.assertAlmostEqual(max(y+h for _,y,_,h in sections)+cfg['margin_y'],result['required_height'])

    def test_turn_override_cannot_overfill_window_and_is_not_clipped(self):
        cfg=config();cfg['overrides']={'P':dict(turns_per_layer=11)}
        with self.assertRaises(ValueError):
            assess_winding_window([winding()],cfg)

    def test_seeded_geometry_sections_match_fit_without_overlap_or_input_mutation(self):
        rng=random.Random(20261017)
        tol=1e-12
        for trial in range(100):
            cfg=config();cfg.update(window_width=rng.uniform(10,35)*1e-3,
                window_height=1.,margin_x=rng.uniform(.05,.3)*1e-3,
                margin_y=rng.uniform(.05,.2)*1e-3,
                diameter_allowance=rng.uniform(.005,.03)*1e-3,
                layer_insulation=rng.uniform(0,.1)*1e-3,
                interwinding_insulation=rng.uniform(0,.2)*1e-3,
                wire_gap=rng.uniform(0,.08)*1e-3)
            sources=[];overrides={}
            for index in range(rng.randint(1,3)):
                key='P' if index==0 else f'OUT{index}'
                per_bundle=rng.choice((1,4,8,20));bundles=rng.randint(1,3)
                sources.append(winding(key,turns=rng.randint(1,15),
                    strands=per_bundle*bundles,diameter=rng.uniform(.02,.15)*1e-3))
                overrides[key]=dict(parallel_bundles=bundles,
                    packing_factor=rng.uniform(.55,.9),flatten_ratio=rng.uniform(1.,1.8),
                    wire_type=rng.choice(('auto','solid','litz')),
                    winding_style=rng.choice(('sparse','dense_left','dense_right')))
            cfg['overrides']=overrides
            preliminary=assess_winding_window(sources,cfg)
            for row in preliminary['windings']:
                self.assertGreater(row['capacity'],0)
                overrides[row['id']]['turns_per_layer']=rng.randint(1,min(7,row['capacity']))
            provisional=assess_winding_window(sources,cfg)
            # Half the cases fit exactly; half overflow radially. Width always fits.
            cfg['window_height']=(provisional['required_height'] if trial%2==0 else
                2*cfg['margin_y']+.7*(provisional['required_height']-2*cfg['margin_y']))
            saved_cfg=copy.deepcopy(cfg);saved_sources=copy.deepcopy(sources)
            result=assess_winding_window(sources,cfg)
            self.assertEqual(result['fits'],trial%2==0)
            self.assertEqual(cfg,saved_cfg)
            self.assertEqual(sources,saved_sources)
            all_sections=[]
            for row in result['windings']:
                sections=list(iter_bundle_sections(row,result['config']))
                self.assertEqual(len(sections),row['turns']*row['parallel_bundles'])
                self.assertEqual(row['conductor_count'],row['turns']*row['strands'])
                self.assertAlmostEqual(max(y+h for _,y,_,h in sections),row['top'])
                for x,y,w,h in sections:
                    self.assertGreaterEqual(x+tol,cfg['margin_x'])
                    self.assertLessEqual(x+w,cfg['window_width']-cfg['margin_x']+tol)
                    self.assertGreaterEqual(y+tol,cfg['margin_y'])
                    if result['fits']:
                        self.assertLessEqual(y+h,cfg['window_height']-cfg['margin_y']+tol)
                all_sections.extend(sections)
            for index,(x,y,w,h) in enumerate(all_sections):
                for other_x,other_y,other_w,other_h in all_sections[index+1:]:
                    if min(y+h,other_y+other_h)-max(y,other_y)>tol:
                        self.assertTrue(x+w<=other_x+tol or other_x+other_w<=x+tol,
                            f'overlapping sections in trial {trial}')
            self.assertEqual(len(all_sections),result['bundle_count'])
            json.dumps(result,allow_nan=False)

    def test_winding_barrier_is_counted_once_between_groups(self):
        cfg=config();cfg['interwinding_insulation']=.2e-3
        result=assess_winding_window([winding(),winding('OUT1')],cfg)
        self.assertAlmostEqual(result['required_height'],1.2e-3)
        self.assertAlmostEqual(result['windings'][1]['y'],.7e-3)

    def test_overflow_height_is_not_mistaken_for_area_pass(self):
        cfg=config();cfg['window_height']=.3e-3
        result=assess_winding_window([winding(turns=1)],cfg)
        self.assertFalse(result['fits'])
        self.assertLess(result['copper_fill'],.2)
        self.assertLess(result['height_margin'],0)

    def test_too_wide_bundle_is_explicit_failure(self):
        cfg=config();cfg['overrides']={'P':dict(strand_columns=12)}
        result=assess_winding_window([winding(turns=2,strands=12)],cfg)
        self.assertFalse(result['fits'])
        self.assertEqual(result['windings'][0]['turns_per_layer'],0)
        self.assertFalse(result['windings'][0]['horizontal_fit'])

    def test_invalid_geometry_and_wire_override_not_silently_clipped(self):
        for change in (dict(window_width=-1),dict(window_height=float('nan')),
                       dict(overrides={'P':dict(outer_diameter=.1e-3)}),
                       dict(overrides={'P':dict(strand_columns=2)}),dict(margin_x=3e-3)):
            cfg=config();cfg.update(change)
            with self.assertRaises(ValueError):assess_winding_window([winding()],cfg)
        for value in (True,.2,-1,0):
            with self.assertRaises(ValueError):assess_winding_window([winding(turns=value)],config())

    def test_invalid_equivalent_bundle_options_are_rejected(self):
        changes=[dict(parallel_bundles=v) for v in (0,True,1.5,3)]
        changes += [dict(packing_factor=v) for v in (0,-.1,1.1,True,float('nan'))]
        changes += [dict(flatten_ratio=v) for v in (.9,True,float('inf'))]
        changes += [dict(bundle_diameter=v) for v in (-1,True,float('nan'))]
        changes += [dict(turns_per_layer=v) for v in (-1,True,1.5)]
        changes += [dict(wire_type='foil'),dict(winding_style='center'),dict(unknown=0)]
        for change in changes:
            cfg=config();cfg['overrides']={'P':change}
            with self.subTest(change=change),self.assertRaises(ValueError):
                assess_winding_window([winding(strands=4)],cfg)

    def test_order_and_hidden_overrides_remain_serializable_and_immutable(self):
        cfg=config();cfg.update(order=['OUT1','P','OUT6'],overrides={'OUT6':dict(strand_columns=3)})
        before=copy.deepcopy(cfg)
        result=assess_winding_window([winding(),winding('OUT1')],cfg)
        self.assertEqual([x['id'] for x in result['windings']],['OUT1','P'])
        self.assertEqual(cfg,before)
        json.dumps(result,allow_nan=False)

    def test_primary_six_outputs_and_auxiliary_use_resolved_turns(self):
        tr=dict(ok=True,Np=6,Ns=12,n_strand_p=40,n_strand_s=30,d_wire_p=.1e-3,d_wire_s=.2e-3,
                windings=[dict(id=i,name=str(i),Ns=i+2,n_strand_s=2,d_wire_s=.2e-3) for i in range(1,7)],
                auxiliary=dict(Na=4,d_wire=.15e-3))
        rows=transformer_windings(dict(mag=dict(transformer=tr)))
        self.assertEqual(len(rows),8)
        self.assertEqual(rows[0]['turns'],6)
        self.assertEqual(rows[-1]['id'],'AUX')
        self.assertEqual(rows[-1]['turns'],4)
        self.assertEqual(transformer_windings(dict(mag=dict(transformer=dict(ok=False)))),[])

    def test_plot_has_equal_axes_and_one_section_per_equivalent_bundle(self):
        from matplotlib.figure import Figure
        cfg=config();cfg['window_height']=.3e-3
        result=assess_winding_window([winding(turns=3,strands=2)],cfg)
        fig=Figure();ax=fig.subplots()
        draw_winding_cross_section(ax,result)
        self.assertEqual(ax.get_aspect(),1.)
        self.assertEqual(sum(len(c.get_paths()) for c in ax.collections),3)
        self.assertGreater(ax.get_ylim()[1],result['required_height']*1e3)

    def test_thousands_of_microscopic_strands_still_draw_only_six_bundles(self):
        from matplotlib.figure import Figure
        cfg=config();cfg.update(window_width=30e-3,window_height=20e-3)
        result=assess_winding_window([winding(turns=6,strands=1000,diameter=.1e-3)],cfg)
        fig=Figure();ax=fig.subplots()
        draw_winding_cross_section(ax,result)
        self.assertEqual(result['conductor_count'],6000)
        self.assertEqual(result['bundle_count'],6)
        self.assertEqual(sum(len(c.get_paths()) for c in ax.collections),6)

    def test_legacy_plot_uses_one_rectangular_envelope_per_turn(self):
        from matplotlib.figure import Figure
        cfg=config();cfg['overrides']={'P':dict(strand_columns=2)}
        result=assess_winding_window([winding(turns=3,strands=4)],cfg)
        fig=Figure();ax=fig.subplots()
        draw_winding_cross_section(ax,result)
        self.assertEqual(sum(len(c.get_paths()) for c in ax.collections),3)

    def test_large_counts_do_not_allocate_millions_of_circles(self):
        from matplotlib.figure import Figure
        result=assess_winding_window([winding(turns=1000000,strands=8)],config())
        fig=Figure();ax=fig.subplots()
        draw_winding_cross_section(ax,result)
        self.assertFalse(ax.collections)
        self.assertIn('仅画层包络',ax.get_title())


class PhysicalLayerPlanChecks(unittest.TestCase):
    """One electrical winding may occupy separated physical layers."""

    def setUp(self):
        self.sources=[winding(turns=6),winding('OUT1',turns=4)]
        self.cfg=config()
        self.cfg.update(layer_insulation=.1e-3,interwinding_insulation=.2e-3,
            layer_plan=[dict(winding_id='P',turns=3),
                        dict(winding_id='OUT1',turns=4),
                        dict(winding_id='P',turns=3)])

    def test_sandwich_uses_physical_positions_and_two_interwinding_barriers(self):
        result=assess_winding_window(self.sources,self.cfg)
        self.assertTrue(result['interleaved'])
        self.assertEqual(result['total_layer_count'],3)
        self.assertEqual(len(result['windings']),2)
        self.assertEqual([x['winding_id'] for x in result['physical_layers']],['P','OUT1','P'])
        self.assertEqual([x['layer_index'] for x in result['physical_layers']],[1,2,3])
        self.assertAlmostEqual(result['required_height'],1.9e-3)
        for layer,expected_y,tape in zip(result['physical_layers'],[0,.7e-3,1.4e-3],[0,.2e-3,.2e-3]):
            self.assertAlmostEqual(layer['y'],expected_y)
            self.assertAlmostEqual(layer['top'],expected_y+.5e-3)
            self.assertAlmostEqual(layer['height'],.5e-3)
            self.assertAlmostEqual(layer['insulation_before'],tape)
        primary=result['windings'][0]
        self.assertEqual(primary['physical_layer_indices'],[1,3])
        self.assertEqual(primary['layer_turns'],[3,3])
        self.assertEqual(primary['layers'],2)
        self.assertAlmostEqual(primary['buildup'],1e-3)
        self.assertAlmostEqual(primary['stack_span'],1.9e-3)
        sections=list(iter_bundle_sections(primary,result['config']))
        self.assertEqual(len(sections),6)
        self.assertEqual([round(s[1]*1e3,6) for s in sections],[0,0,0,1.4,1.4,1.4])

    def test_same_winding_adjacent_layer_uses_layer_tape_only(self):
        self.cfg['layer_plan']=[dict(winding_id='P',turns=2),
            dict(winding_id='P',turns=4),dict(winding_id='OUT1',turns=4)]
        result=assess_winding_window(self.sources,self.cfg)
        self.assertAlmostEqual(result['required_height'],1.8e-3)
        self.assertAlmostEqual(result['physical_layers'][1]['insulation_before'],.1e-3)
        self.assertAlmostEqual(result['physical_layers'][2]['insulation_before'],.2e-3)
        self.assertEqual(result['windings'][0]['physical_layer_indices'],[1,2])
        self.assertAlmostEqual(result['windings'][0]['buildup'],1.1e-3)
        self.assertAlmostEqual(result['windings'][0]['stack_span'],1.1e-3)

    def test_per_layer_winding_style_overrides_then_inherits_winding_default(self):
        self.cfg['overrides']={'P':dict(winding_style='dense_right')}
        self.cfg['layer_plan'][0]['winding_style']='sparse'
        result=assess_winding_window(self.sources,self.cfg)
        primary=result['windings'][0]
        self.assertEqual([x['winding_style'] for x in primary['layer_layout']],['sparse','dense_right'])
        sections=list(iter_bundle_sections(primary,result['config']))
        for actual,expected in zip([x[0] for x in sections],[0,2.25e-3,4.5e-3,3.5e-3,4e-3,4.5e-3]):
            self.assertAlmostEqual(actual,expected)

    def test_manual_layers_preserve_exact_electrical_copper_and_input(self):
        self.sources[0]['strands']=20
        self.cfg['window_width']=15e-3
        before_cfg=copy.deepcopy(self.cfg);before_sources=copy.deepcopy(self.sources)
        automatic=assess_winding_window(self.sources,dict(self.cfg,layer_plan=[]))
        manual=assess_winding_window(self.sources,self.cfg)
        self.assertEqual(manual['conductor_count'],6*20+4)
        self.assertEqual(manual['bundle_count'],10)
        self.assertAlmostEqual(manual['copper_fill'],automatic['copper_fill'])
        self.assertAlmostEqual(manual['insulated_wire_fill'],automatic['insulated_wire_fill'])
        self.assertEqual(self.cfg,before_cfg)
        self.assertEqual(self.sources,before_sources)
        restored=json.loads(json.dumps(self.cfg,allow_nan=False))
        self.assertEqual(assess_winding_window(self.sources,restored),manual)

    def test_manual_additional_insulation_can_change_pass_to_overflow(self):
        self.cfg['window_height']=1.5e-3
        automatic=assess_winding_window(self.sources,dict(self.cfg,layer_plan=[]))
        manual=assess_winding_window(self.sources,self.cfg)
        self.assertTrue(automatic['fits'])
        self.assertFalse(manual['fits'])
        self.assertAlmostEqual(manual['height_margin'],-.4e-3)

    def test_explicit_physical_plan_takes_precedence_over_logical_winding_order(self):
        self.cfg['order']=['OUT1','P']
        result=assess_winding_window(self.sources,self.cfg)
        self.assertEqual([x['id'] for x in result['windings']],['OUT1','P'])
        self.assertEqual([x['winding_id'] for x in result['physical_layers']],['P','OUT1','P'])
        by_id={x['id']:x for x in result['windings']}
        self.assertEqual(by_id['P']['physical_layer_indices'],[1,3])
        self.assertAlmostEqual(by_id['OUT1']['y'],.7e-3)

    def test_unknown_missing_and_wrong_turn_sum_are_rejected(self):
        for plan in (
            [dict(winding_id='P',turns=6)],
            [dict(winding_id='P',turns=6),dict(winding_id='OUT1',turns=3)],
            [dict(winding_id='P',turns=6),dict(winding_id='OUT1',turns=5)],
            [dict(winding_id='P',turns=6),dict(winding_id='OUT1',turns=4),dict(winding_id='OUT6',turns=1)]):
            with self.subTest(plan=plan),self.assertRaises(ValueError):
                assess_winding_window(self.sources,dict(self.cfg,layer_plan=plan))

    def test_layer_turns_cannot_exceed_physical_capacity_or_user_limit(self):
        source=[winding(turns=12)]
        cfg=dict(self.cfg,layer_plan=[dict(winding_id='P',turns=11),dict(winding_id='P',turns=1)])
        with self.assertRaises(ValueError):assess_winding_window(source,cfg)
        cfg=dict(self.cfg,overrides={'P':dict(turns_per_layer=3)},
            layer_plan=[dict(winding_id='P',turns=4),dict(winding_id='OUT1',turns=4),dict(winding_id='P',turns=2)])
        with self.assertRaises(ValueError):assess_winding_window(self.sources,cfg)

    def test_manual_plan_schema_rejects_malformed_empty_and_excessive_layers(self):
        bad_plans=(None,{},'P:3',True,[{}],[dict(winding_id='P')],
            [dict(winding_id='P',turns=True)],[dict(winding_id='P',turns=0)],
            [dict(winding_id='P',turns=-1)],[dict(winding_id='P',turns=1.5)],
            [dict(winding_id='P',turns=float('nan'))],
            [dict(winding_id=1,turns=1)],[dict(winding_id='',turns=1)],
            [dict(winding_id='P',turns=1,winding_style='center')],
            [dict(winding_id='P',turns=1,unknown=1)],
            [dict(winding_id='P',turns=1)]*1001)
        for plan in bad_plans:
            with self.subTest(plan=str(plan)[:100]),self.assertRaises(ValueError):
                validate_winding_config(dict(self.cfg,layer_plan=plan))

    def test_build_automatic_plan_ignores_existing_manual_plan_and_preserves_geometry(self):
        from winding_layout import build_automatic_layer_plan
        self.cfg['overrides']={'P':dict(turns_per_layer=4,winding_style='dense_right')}
        original=copy.deepcopy(self.cfg)
        plan=build_automatic_layer_plan(self.sources,self.cfg)
        self.assertEqual([x['winding_id'] for x in plan],['P','P','OUT1'])
        self.assertEqual([x['turns'] for x in plan],[4,2,4])
        automatic=assess_winding_window(self.sources,dict(self.cfg,layer_plan=[]))
        manual=assess_winding_window(self.sources,dict(self.cfg,layer_plan=plan))
        self.assertAlmostEqual(automatic['required_height'],manual['required_height'])
        self.assertEqual(automatic['copper_fill'],manual['copper_fill'])
        self.assertEqual(automatic['physical_layers'],manual['physical_layers'])
        for ar,mr in zip(automatic['windings'],manual['windings']):
            self.assertEqual(list(iter_bundle_sections(ar,automatic['config'])),
                             list(iter_bundle_sections(mr,manual['config'])))
        self.assertEqual(self.cfg,original)

    def test_build_automatic_plan_rejects_more_than_1000_rows_without_mass_allocation(self):
        from winding_layout import build_automatic_layer_plan
        cfg=config();cfg['overrides']={'P':dict(turns_per_layer=1)}
        with self.assertRaises(ValueError):
            build_automatic_layer_plan([winding(turns=1000000)],cfg)

    def test_build_automatic_plan_rejects_a_turn_wider_than_net_window(self):
        from winding_layout import build_automatic_layer_plan
        cfg=config();cfg['window_width']=.3e-3
        with self.assertRaisesRegex(ValueError,'宽度'):
            build_automatic_layer_plan([winding(turns=1)],cfg)

    def test_automatic_millions_of_layers_use_constant_size_fallback(self):
        cfg=config();cfg['overrides']={'P':dict(turns_per_layer=1)}
        result=assess_winding_window([winding(turns=1000000)],cfg)
        self.assertEqual(result['total_layer_count'],1000000)
        self.assertFalse(result['interleaved'])
        self.assertIsNone(result['physical_layers'])
        self.assertIsNone(result['windings'][0]['layer_layout'])
        self.assertIsNone(result['windings'][0]['physical_layer_indices'])
        self.assertIsNone(result['windings'][0]['layer_turns'])

    def test_automatic_materialized_layer_boundary_does_not_draw_36000_patches(self):
        from matplotlib.figure import Figure
        cfg=config();cfg['overrides']={'P':dict(turns_per_layer=1)}
        result=assess_winding_window([winding(turns=12000)],cfg)
        # Detailed numeric layer metadata may exist without thousands of artists.
        self.assertEqual(len(result['physical_layers']),12000)
        fig=Figure();ax=fig.subplots();draw_winding_cross_section(ax,result)
        self.assertLess(len(ax.patches),12)
        self.assertFalse(ax.collections)
        self.assertIn('仅画层包络',ax.get_title())

    def test_large_manual_interleaving_batches_bands_without_merging_other_windings(self):
        from matplotlib.figure import Figure
        sources=[winding(turns=500,diameter=.01e-3),winding('OUT1',turns=500,diameter=.01e-3)]
        cfg=config();cfg.update(window_height=30e-3,interwinding_insulation=.01e-3,
            layer_plan=[dict(winding_id='P' if i%2==0 else 'OUT1',turns=1) for i in range(1000)])
        result=assess_winding_window(sources,cfg)
        fig=Figure();ax=fig.subplots();draw_winding_cross_section(ax,result)
        self.assertLess(len(ax.patches),12)
        bands=[c for c in ax.collections if c.get_alpha()==.13]
        self.assertEqual(len(bands),1)
        self.assertEqual(len(bands[0].get_paths()),1000)
        for path,layer in zip(bands[0].get_paths(),result['physical_layers']):
            box=path.get_extents()
            self.assertAlmostEqual(box.y0,layer['y']*1e3)
            self.assertAlmostEqual(box.height,.01)
        self.assertEqual(len(ax.collections),2)  # Physical bands and 999 tapes; no ellipses.
        self.assertEqual(len(ax.collections[1].get_paths()),999)
        self.assertIn('仅画层包络',ax.get_title())

    def test_exact_manual_plan_limit_is_valid_and_counts_each_tape_once(self):
        cfg=config();cfg['layer_insulation']=.01e-3
        cfg['layer_plan']=[dict(winding_id='P',turns=1) for _ in range(1000)]
        result=assess_winding_window([winding(turns=1000,diameter=.01e-3)],cfg)
        self.assertEqual(result['total_layer_count'],1000)
        self.assertEqual(len(result['physical_layers']),1000)
        self.assertAlmostEqual(result['required_height'],1000*.01e-3+999*.01e-3)

    def test_all_six_outputs_and_auxiliary_survive_arbitrary_manual_sequence(self):
        sources=[winding(turns=4)]+[winding(f'OUT{i}',turns=1) for i in range(1,7)]
        sources.append(winding('AUX',turns=1))
        plan=[dict(winding_id='P',turns=2)]
        plan.extend(dict(winding_id=f'OUT{i}',turns=1) for i in (6,2,5))
        plan.append(dict(winding_id='P',turns=2))
        plan.extend(dict(winding_id=key,turns=1) for key in ('AUX','OUT1','OUT4','OUT3'))
        cfg=dict(self.cfg,window_height=8e-3,layer_plan=plan)
        result=assess_winding_window(sources,cfg)
        self.assertEqual(result['total_layer_count'],9)
        self.assertEqual(result['conductor_count'],11)
        self.assertEqual(len(result['windings']),8)
        self.assertEqual([x['winding_id'] for x in result['physical_layers']],
                         [x['winding_id'] for x in plan])
        self.assertEqual(result['windings'][0]['physical_layer_indices'],[1,5])

    def test_seeded_interleaved_plans_match_adjacent_insulation_and_no_overlaps(self):
        rng=random.Random(2171017)
        tol=1e-12
        for trial in range(100):
            sources=[];plan=[];overrides={}
            cfg=config();cfg.update(window_width=15e-3,window_height=1.,
                margin_x=.2e-3,margin_y=.1e-3,
                layer_insulation=rng.uniform(.01,.1)*1e-3,
                interwinding_insulation=rng.uniform(.11,.3)*1e-3)
            for index in range(rng.randint(2,4)):
                key='P' if index==0 else f'OUT{index}'
                turns=rng.randint(2,10);bundles=rng.randint(1,2)
                sources.append(winding(key,turns=turns,strands=4*bundles,
                    diameter=rng.uniform(.04,.2)*1e-3))
                overrides[key]=dict(parallel_bundles=bundles,turns_per_layer=3,
                    wire_type=rng.choice(('solid','litz')),
                    winding_style=rng.choice(('sparse','dense_left','dense_right')))
                remaining=turns
                while remaining:
                    count=rng.randint(1,min(3,remaining));remaining-=count
                    entry=dict(winding_id=key,turns=count)
                    if rng.choice((True,False)):
                        entry['winding_style']=rng.choice(('sparse','dense_left','dense_right'))
                    plan.append(entry)
            rng.shuffle(plan);cfg.update(overrides=overrides,layer_plan=plan)
            original_cfg=copy.deepcopy(cfg);original_sources=copy.deepcopy(sources)
            result=assess_winding_window(sources,cfg)
            by_id={r['id']:r for r in result['windings']}
            expected_cursor=cfg['margin_y'];previous=None
            for layer,entry in zip(result['physical_layers'],plan):
                tape=(0. if previous is None else cfg['layer_insulation']
                    if previous==entry['winding_id'] else cfg['interwinding_insulation'])
                self.assertAlmostEqual(layer['insulation_before'],tape)
                self.assertAlmostEqual(layer['y'],expected_cursor+tape)
                self.assertEqual(layer['turns'],entry['turns'])
                expected_cursor+=tape+by_id[entry['winding_id']]['bundle_height']
                previous=entry['winding_id']
            self.assertAlmostEqual(result['required_height'],expected_cursor+cfg['margin_y'])
            all_sections=[]
            for row in result['windings']:
                layers=[x for x in result['physical_layers'] if x['winding_id']==row['id']]
                self.assertEqual(row['physical_layer_indices'],[x['layer_index'] for x in layers])
                self.assertEqual(sum(row['layer_turns']),row['turns'])
                expected_buildup=sum(x['height']+(x['insulation_before']
                    if x['insulation_kind']=='layer' else 0.) for x in layers)
                self.assertAlmostEqual(row['buildup'],expected_buildup)
                self.assertAlmostEqual(row['stack_span'],layers[-1]['top']-layers[0]['y'])
                sections=list(iter_bundle_sections(row,result['config']))
                self.assertEqual(len(sections),row['turns']*row['parallel_bundles'])
                all_sections.extend(sections)
            for index,(x,y,w,h) in enumerate(all_sections):
                self.assertGreaterEqual(x+tol,cfg['margin_x'])
                self.assertLessEqual(x+w,cfg['window_width']-cfg['margin_x']+tol)
                for other_x,other_y,other_w,other_h in all_sections[index+1:]:
                    if min(y+h,other_y+other_h)-max(y,other_y)>tol:
                        self.assertTrue(x+w<=other_x+tol or other_x+other_w<=x+tol)
            self.assertEqual(result['conductor_count'],sum(x['turns']*x['strands'] for x in sources))
            self.assertEqual(cfg,original_cfg)
            self.assertEqual(sources,original_sources)

    def test_plot_uses_separate_layer_envelopes_not_foreign_winding_span(self):
        from matplotlib.figure import Figure
        result=assess_winding_window(self.sources,self.cfg)
        fig=Figure();ax=fig.subplots();draw_winding_cross_section(ax,result)
        primary_y=[x['y']*1e3 for x in result['windings'][0]['layer_layout']]
        colored=[p for p in ax.patches if p.get_alpha()==.13]
        # Exactly three winding bands, each only one physical wire-height thick.
        self.assertEqual(len(colored),3)
        self.assertTrue(all(abs(p.get_height()-.5)<1e-9 for p in colored))
        for y in primary_y:
            self.assertTrue(any(abs(p.get_y()-y)<1e-9 for p in colored))
        self.assertEqual(sum(len(c.get_paths()) for c in ax.collections),10)


if __name__=='__main__':unittest.main(verbosity=2)
