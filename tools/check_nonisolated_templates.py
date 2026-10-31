"""Independent native ASC netlist export vs the CIR circuit contract."""
from pathlib import Path
import collections,json,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from design_engine.specification import load_spec
from spice_export import project_files

def main():
    base=ROOT/'artifacts/qa/nonisolated_20261029_templates';base.mkdir(exist_ok=True);summary=[]
    for stem in ('24W_BUCK_VM_TPS40200','24W_BOOST_PCM_LM5022'):
        p=load_spec(json.loads((ROOT/'examples'/(stem+'.json')).read_text(encoding='utf-8')));files=project_files(p);where=base/stem;where.mkdir(exist_ok=True)
        for k,v in files.items():(where/k).write_bytes(v)
        subprocess.run([r'D:\LTSPCIE\LTspice.exe','-netlist',str(where/'Flyback.asc')],cwd=where,check=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        native=(where/'Flyback.net').read_text(encoding='utf-8-sig',errors='replace')
        def cards(s):
            result=[]
            for line in s.splitlines():
                if not line or line[0] in '*;.':continue
                line=line.replace('§','');result.append(' '.join(line.split()).casefold())
            return collections.Counter(result)
        expected=cards(files['power_stage.inc'].decode());actual=cards(native)
        extra=actual-expected;missing=expected-actual
        row=dict(name=stem,missing=list(missing.elements()),extra=list(extra.elements()),passed=not missing and not extra)
        summary.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    (base/'native_contract.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(r['passed'] for r in summary):raise SystemExit(1)
if __name__=='__main__':main()
