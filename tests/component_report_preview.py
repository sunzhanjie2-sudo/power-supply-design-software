"""Application-exported QA fixture; demonstrative identities are not selections."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
from component_management import component_registry,evaluate_components
from design_api import load_spec
from input_voltage_range import calculate_input_endpoints
from report_xlsx import export_input_range_xlsx


def run():
    out=ROOT/'artifacts/qa/component-management';out.mkdir(parents=True,exist_ok=True)
    p=load_spec(json.loads((ROOT/'examples/6_OUTPUT_FLYBACK_SSR.json').read_text(encoding='utf-8')))
    p.update(V_in_min=27.,V_in_max=33.)
    items={}
    for index,r in enumerate(component_registry(p)):
        item=dict(manufacturer='演示厂家',model='QA-'+r['ref'],package='封装待核定',note='QA 演示额定值，不能用于实物选型')
        if r['kind'] in ('mos','diode'):item['voltage_V']=100.
        elif r['kind']=='resistor':item['power_W']=.5
        elif r['kind']=='capacitor':item.update(voltage_V=50.,ripple_A=1.,capacitor_type=['electrolytic','mlcc','film'][index%3])
        items[r['ref']]=item
    p['component_management']=dict(version=1,zone='I',items=items)
    bundle=calculate_input_endpoints(p,include_loop=False,include_cross_regulation=False)
    results=[]
    for case in bundle['cases']:
        r=case['result'];assert r and not case.get('error'),case.get('error')
        case['efficiency_curve']=dict(fracs=[1.],etas=[r['eta']],modes=[r['op']['mode']],failures=[])
        results.append(dict(id=case['id'],bom=evaluate_components(case['p'],r)))
    result=export_input_range_xlsx(out/'component-report-qa.xlsx',bundle)
    (out/'report-checks.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    assert '14 关键器件BOM与降额' in result['sheet_names']
    assert result['successful_cases']==2
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':run()
