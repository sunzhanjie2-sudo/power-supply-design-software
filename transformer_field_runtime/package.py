"""Read formal geometry ZIPs without executing or extracting package paths."""
from copy import deepcopy
import hashlib
from pathlib import Path
from zipfile import ZipFile

from .storage import strict_json,content_hash,sha
from .contract_v1 import (GEOMETRY_SCHEMA,LEGACY_GEOMETRY_SCHEMA,PRE_PARALLEL_GEOMETRY_SCHEMA,
                         PRE_PARALLEL_LEGACY_GEOMETRY_SCHEMA,PROFILE_SCHEMA,validate_profile)
from .geometry_semantics import validate_geometry

REQUIRED={'calculator-input.json','engine-snapshot.json','resolved-cross-section.json','geometry.schema.json',
          'cross-section.svg','cross-section.png','model-input.template.json','model-input.schema.json'}
ALLOWED=REQUIRED|{'manifest.json','model-input.json','source-input.original.json'}
MAX_BYTES=256*1024**2


def load_package(path):
    path=Path(path)
    with ZipFile(path) as z:
        names=z.namelist()
        if set(names)-ALLOWED or not REQUIRED|{'manifest.json'} <= set(names) or len(names)!=len(set(names)):
            raise ValueError('导出包缺少文件，或含未知/重复成员；需要正式三维建模ZIP。')
        if sum(i.file_size for i in z.infolist())>MAX_BYTES or any(i.flag_bits&1 for i in z.infolist()):
            raise ValueError('不支持加密包或解压后大于256MiB的包。')
        manifest=strict_json(z.read('manifest.json'))
        if manifest.get('schema')!='power-transformer.package.v1' or set(manifest.get('files',{}))!=set(names)-{'manifest.json'}:
            raise ValueError('包版本或清单条目不匹配。')
        for name,seal in manifest['files'].items():
            data=z.read(name)
            if seal!={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}:
                raise ValueError('文件校验失败：'+name)
        schema=strict_json(z.read('geometry.schema.json'))
        if schema not in (GEOMETRY_SCHEMA,LEGACY_GEOMETRY_SCHEMA,PRE_PARALLEL_GEOMETRY_SCHEMA,PRE_PARALLEL_LEGACY_GEOMETRY_SCHEMA):
            raise ValueError('几何Schema不受本版本支持；请更新工具。')
        if strict_json(z.read('model-input.schema.json'))!=PROFILE_SCHEMA:raise ValueError('建模设置Schema不匹配。')
        for name in ('model-input.json','model-input.template.json'):
            if name in names:validate_profile(strict_json(z.read(name)))
        g=validate_geometry(strict_json(z.read('resolved-cross-section.json')))
        snap=strict_json(z.read('engine-snapshot.json'))
        snapshot_hash=content_hash({k:v for k,v in snap.items() if k not in ('snapshot_id','created_at')})
        if snap.get('schema')!='power-design.snapshot.v1' or not snap.get('ok') or snap.get('analysis')!='endpoints':
            raise ValueError('设计软件的冻结双端点快照无效。')
        if snap.get('snapshot_id')!=snapshot_hash:raise ValueError('计算快照内容哈希不符。')
        for key,value in [('engine_snapshot_id',snapshot_hash),('input_sha256',manifest['files']['calculator-input.json']['sha256']),
                          ('geometry_sha256',g['source']['geometry_sha256'])]:
            if manifest.get(key)!=value or g['source'].get(key)!=value:raise ValueError('输入绑定不一致：'+key)
        if manifest.get('normalized_spec_sha256')!=content_hash(snap['spec']) or manifest.get('engine_model_version')!=snap['model_version']:
            raise ValueError('设计规格或引擎版本绑定不一致。')
        kind=manifest.get('input_kind')
        if kind not in ('original_bytes','working_copy'):raise ValueError('输入来源类型不受支持。')
        original='source-input.original.json' if 'source-input.original.json' in names else 'calculator-input.json' if kind=='original_bytes' else None
        if manifest.get('original_sha256')!=(manifest['files'][original]['sha256'] if original else None):
            raise ValueError('原始工程字节绑定不一致。')
        if not g['ready']['cross_section'] or not g['checks']['same_endpoint_geometry']:
            raise ValueError('需要有效截面和同一几何的双端点设计。')
        profile=strict_json(z.read('model-input.json')) if 'model-input.json' in names else {}
        return dict(geometry=deepcopy(g),profile=profile,manifest=manifest,path=str(path.resolve()),sha256=sha(path),
                    cross_section_png=z.read('cross-section.png'),
                    validation_scope='ZIP/SHA256/Schema/snapshot+geometry hashes/geometry+connection semantics; converter equations not rerun')
