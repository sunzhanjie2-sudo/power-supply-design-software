"""Bundle existing model libraries and readable ASC templates as offline data."""
from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parents[1]
files={p.name:p.read_bytes().decode('utf8') for p in (ROOT/'resources/spice').iterdir() if p.suffix in ('.lib','.asy','.asc','.plt')}
data={'files':files,'sha256':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in files.items()}}
(ROOT/'web_app/frontend/src/native_engine/spice-assets.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf8')
print('Bundled',len(files),'offline SPICE assets; no simulator invoked.')
