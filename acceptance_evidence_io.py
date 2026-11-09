"""Bound JSON evidence and small persistent references, never a simulator."""
import hashlib
from pathlib import Path
from zipfile import ZipFile, BadZipFile

LIMIT = 32 * 1024 * 1024


def normalize_reference(value=None):
    if value is None:
        return None
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('不支持的验收证据引用')
    path, digest = value.get('path'), value.get('payload_sha256')
    if not isinstance(path, str) or len(path) > 4096 or not path:
        raise ValueError('验收证据路径无效')
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('验收证据数据校验值无效')
    return dict(version=1, path=path, payload_sha256=digest)


def _payload(source):
    if not source.is_file():
        raise ValueError('验收证据文件不可用；请重新定位原文件')
    if source.suffix.lower() == '.json':
        if source.stat().st_size > LIMIT:
            raise ValueError('验收证据JSON超过32MiB')
        return source.read_bytes()
    if source.suffix.lower() != '.zip':
        raise ValueError('请选择新版comparison.json、联合joint-record.json或仿真工程ZIP')
    try:
        with ZipFile(source) as archive:
            matches = [v for v in archive.infolist() if v.filename == 'comparison.json']
            if len(matches) != 1 or matches[0].file_size > LIMIT:
                raise ValueError('ZIP须含唯一且不超过32MiB的comparison.json')
            return archive.read(matches[0])
    except (BadZipFile, RuntimeError) as exc:
        raise ValueError('无法读取验收证据ZIP') from exc


def load_evidence(path, *, reference=None):
    from transformer_geometry import strict_json
    from engineering_acceptance import input_fingerprint
    source = Path(path).resolve()
    blob = _payload(source)
    digest = hashlib.sha256(blob).hexdigest()
    if reference is not None and normalize_reference(reference)['payload_sha256'] != digest:
        raise ValueError('证据数据已变化，旧引用失效；请核对后重新导入')
    value = strict_json(blob)
    if not isinstance(value, dict):
        raise ValueError('验收证据必须是JSON对象')
    record = value.get('record') if isinstance(value.get('record'), dict) else value
    if record.get('schema') == 'power-design.joint-simulation.v1':
        adopted = record.get('adopted_config')
        evidence = (record.get('circuit') or {}).get('evidence')
        if not isinstance(adopted, dict) or not isinstance(evidence, dict):
            raise ValueError('联合记录缺少采用后的输入或电路证据，不能绑定验收')
        fingerprint = input_fingerprint(adopted)
        origin = '联合记录采用后的硬件'
    elif record.get('schema') == 'powerdesign-spice-comparison-2':
        evidence, fingerprint = record, record.get('input_fingerprint')
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise ValueError('旧版比较证据缺少输入指纹；请通过同任务联合记录关联，或用新版重新导出')
        origin = '本轮输入绑定的电路比较证据'
    else:
        raise ValueError('文件不是受支持的电路比较或联合任务记录')
    return (dict(version=1, path=str(source), payload_sha256=digest),
            dict(input_fingerprint=fingerprint, evidence=evidence,
                 source=origin+' / '+str(source), evidence_payload_sha256=digest))
