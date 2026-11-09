"""Selected IC and P-channel identity remain visible without changing physics."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from component_management import component_registry, evaluate_components, primary_mos_role
from design_engine.specification import load_spec
from loss_model import compute_design
from power_stage import DEFAULT_PARAMS, TOPOLOGIES
from topology_diagram import topology_components, draw_topology


def identity(model='TPS40200', conditions=''):
    return dict(manufacturer='Texas Instruments', model=model, package='SOIC-8', conditions=conditions)


def params(topology='BUCK'):
    return dict(copy.deepcopy(DEFAULT_PARAMS),topology=topology,V_in=30,V_out=50 if topology=='BOOST' else 12,
        P_out=15,L=50e-6,N=1.,f_sw=100e3,Kc=1.5,K=.99,dC=.1,outputs=[],feedback_mode='SSR',
        component_management={'items':{'U_CTRL':identity()}})


class ControllerReferenceChecks(unittest.TestCase):
    def test_missing_reference_does_not_invent_an_ic(self):
        p=params();p['component_management']={}
        self.assertNotIn('U_CTRL',{r['ref'] for r in component_registry(p)})
        self.assertNotIn('U_CTRL',{r['ref'] for r in topology_components(p)})

    def test_reference_owned_by_bom_and_parameter_map(self):
        p=params();res=compute_design(p)
        registry=component_registry(p,res)
        table=topology_components(p,res['op'])
        self.assertEqual({r['ref'] for r in registry},{r['ref'] for r in table if not r['ref'].startswith('R_LOAD')})
        data=evaluate_components(p,res)
        row=next(r for r in data['rows'] if r['ref']=='U_CTRL')
        self.assertEqual(row['model'],'TPS40200')
        self.assertEqual(row['quantity'],1)
        self.assertIn('未展开',row['role'])
        self.assertFalse(row['checks'], '未定义的芯片工况不能冒充已计算降额')

    def test_p_channel_identity_is_an_explicit_amplitude_model(self):
        p=params()
        p['component_management']['items']['Q1']=identity('P-test','P-channel；30V，|Vgs|=10V')
        self.assertIn('P-MOS（幅值等效）',primary_mos_role(p))
        self.assertIn('P-MOS（幅值等效）',next(r for r in component_registry(p) if r['ref']=='Q1')['role'])
        self.assertIn('P-MOS（幅值等效）',next(r for r in topology_components(p) if r['ref']=='Q1')['role'])

    def test_metadata_changes_no_working_point_or_loss(self):
        base=params();base['component_management']={}
        selected=copy.deepcopy(base)
        selected['component_management']={'items':{'U_CTRL':identity(),'Q1':identity('P-test','P-channel')}}
        left,right=compute_design(base),compute_design(selected)
        for key in ('eta','P_sense','P_rcd'):
            self.assertEqual(left.get(key),right.get(key))
        for key in ('D','f_sw','I_L_pk','V_sw_max'):
            self.assertEqual(left['op'].get(key),right['op'].get(key))

    def test_every_scalar_topology_draws_the_reference_once(self):
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        for topology in TOPOLOGIES:
            with self.subTest(topology=topology):
                p=params(topology);res=compute_design(p)
                figure=Figure(figsize=(12,7));FigureCanvasAgg(figure)
                ax=figure.add_subplot(111)
                rows=draw_topology(ax,p,res['op'])
                self.assertEqual(sum(row['ref']=='U_CTRL' for row in rows),1)
                self.assertEqual(sum(t.get_text().startswith('U_CTRL ·') for t in ax.texts),1)
                self.assertLess(ax.get_ylim()[0],-1.9)

    def test_multi_output_reference_preserved_and_psr_not_duplicated(self):
        from matplotlib.figure import Figure
        for filename in ('6_OUTPUT_FLYBACK_SSR.json','MP6005_PSR_FLYBACK.json'):
            with self.subTest(filename=filename):
                p=load_spec(json.loads((ROOT/'examples'/filename).read_text('utf-8')))
                p['component_management']={'items':{'U_CTRL':identity('MP6005'),'U_PSR':identity('MP6005')}}
                res=compute_design(p)
                figure=Figure(figsize=(12,8));ax=figure.add_subplot(111)
                rows=draw_topology(ax,p,res['op'])
                refs={row['ref'] for row in rows}
                registry={row['ref'] for row in component_registry(p,res)}
                self.assertEqual(registry,{r for r in refs if not r.startswith('R_LOAD')})
                if p['feedback_mode']=='PSR-MP6005':
                    self.assertIn('U_PSR',refs)
                    self.assertNotIn('U_CTRL',refs)
                else:
                    self.assertIn('U_CTRL',refs)


if __name__=='__main__':unittest.main(verbosity=2)
