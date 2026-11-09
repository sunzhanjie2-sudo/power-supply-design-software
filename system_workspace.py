"""System-network editing above the unchanged converter calculation engine."""
import copy
import json
import os
from pathlib import Path
from config_io import read_default_config, decode_config
import power_network as net

SCHEMA = net.SCHEMA
COLLECTIONS = net.COLLECTIONS
normalize_project = net.normalize
checks = net.analyze
all_nodes = net.nodes
incoming = net.incoming


def fresh_project(config=None):
    spec = copy.deepcopy(config if config is not None else read_default_config())
    p = decode_config(spec)
    return dict(schema_version=SCHEMA, title='开关电源系统设计', revision='A',
                sources=[dict(id='BUS-01', name='系统输入源', min=p.get('V_in_min', p.get('V_in', 30)),
                              max=p.get('V_in_max', p.get('V_in', 30)), capacity=100, enabled=True)],
                units=[dict(id='PSU-01', name='主电源', spec=spec, enabled=True)], loads=[], junctions=[],
                connections=[dict(id='LINK-001', source=dict(kind='bus', id='BUS-01', output=1),
                                  target='PSU-01', mode='direct', vf=.3, enabled=True)],
                activeUnit='PSU-01', layout={'nodes': {}})

def prepare_unit(project,identity):
    """Synchronize opt-in linear designs from the independently resolved graph."""
    from ldo import is_ldo
    unit=unit_by_id(project,identity)
    if is_ldo(unit['spec']) and unit['spec']['follow_input'] and incoming(project,identity,enabled=True):
        sync_input(project,identity)
    return unit_by_id(project,identity)


def disconnected():
    return dict(kind='none', id='', output=1)


def node_by_id(project, identity):
    return next(n for _, n in all_nodes(project) if n['id'] == identity)


def unit_by_id(project, identity):
    return next(u for u in project['units'] if u['id'] == identity)


def _commit(project, candidate):
    normalized = normalize_project(candidate)
    project.clear()
    project.update(normalized)


def connect(project, target, source):
    """Append a connection, upgrading a fan-in to explicit diode OR-ing."""
    if source['kind'] == 'none':
        disconnect(project, target, target=True)
        return
    candidate = copy.deepcopy(project)
    ins = incoming(candidate, target)
    if any(e['source'] == source for e in ins):
        raise ValueError('此供电连接已存在。可选中连线修改方式或压降。')
    is_junction = any(n['id'] == target for n in candidate['junctions'])
    mode = 'diode' if ins or is_junction else 'direct'
    if ins:
        for e in ins:
            e['mode'] = 'diode'
    edge = dict(id=next_id(candidate, 'LINK'), source=copy.deepcopy(source), target=target,
                mode=mode, vf=.3, enabled=True)
    candidate['connections'].append(edge)
    _commit(project, candidate)
    return edge['id']


def disconnect(project, identity, *, target=False):
    project['connections'] = [e for e in project['connections'] if (e['target'] if target else e['id']) != identity]


def set_unit_config(project, identity, config):
    candidate = copy.deepcopy(project)
    unit_by_id(candidate, identity)['spec'] = copy.deepcopy(config)
    probe = copy.deepcopy(candidate)
    probe['connections'] = []
    valid = normalize_project(probe)
    lengths = {u['id']: len(u['rails']) for u in valid['units']}
    removed = [e for e in candidate['connections'] if e['source']['kind'] == 'unit' and e['source']['output'] > lengths[e['source']['id']]]
    candidate['connections'] = [e for e in candidate['connections'] if e not in removed]
    _commit(project, candidate)
    return [e['target'] for e in removed]


def sync_input(project, identity):
    row = next(r for r in checks(project)['interfaces'] if r['unit'] == identity)
    if row['source_min'] is None or row['source_min'] <= 0:
        raise ValueError('没有有效的正电压输入，请先检查连线、节点启用与二极管压降。')
    lo, hi = row['source_min'], row['source_max']
    spec = copy.deepcopy(unit_by_id(project, identity)['spec'])
    spec.update(V_in_min=lo, V_in_max=hi, V_in=lo, input_voltage_case='min')
    set_unit_config(project, identity, spec)
    return lo, hi


def remove_node(project, kind, identity):
    rows = project[COLLECTIONS[kind]]
    index = next(i for i, n in enumerate(rows) if n['id'] == identity)
    record = dict(kind=kind, index=index, node=copy.deepcopy(rows[index]),
                  connections=[copy.deepcopy(e) for e in project['connections'] if e['source']['id'] == identity or e['target'] == identity],
                  position=project.get('layout', {}).get('nodes', {}).get(kind + ':' + identity))
    removed_ids={e['id'] for e in record['connections']}
    record['remaining_inputs']={e['target']:[v['id'] for v in incoming(project,e['target']) if v['id'] not in removed_ids]
                                for e in record['connections']}
    record['diodes']={k:copy.deepcopy(v) for k,v in project.get('layout',{}).get('diodes',{}).items() if k in removed_ids}
    rows.pop(index)
    project['connections'] = [e for e in project['connections'] if e['source']['id'] != identity and e['target'] != identity]
    for key in removed_ids:project.get('layout',{}).get('diodes',{}).pop(key,None)
    project.get('layout', {}).get('nodes', {}).pop(kind + ':' + identity, None)
    if project.get('activeUnit') == identity:
        project['activeUnit'] = project['units'][0]['id'] if project['units'] else ''
    return record


def restore_node(project, record):
    candidate = copy.deepcopy(project)
    node, kind = copy.deepcopy(record['node']), record['kind']
    if any(n['id'] == node['id'] for _, n in all_nodes(candidate)):
        raise ValueError('同名节点已存在，不能恢复。')
    rows = candidate[COLLECTIONS[kind]]
    rows.insert(min(record['index'], len(rows)), node)
    if record['position']:
        candidate['layout']['nodes'][kind + ':' + node['id']] = record['position']
    unchanged={identity for identity, ids in record.get('remaining_inputs',{}).items()
               if {e['id'] for e in incoming(candidate,identity)} == set(ids)}
    for e in record['connections']:
        if e['target'] != node['id'] and e['target'] not in unchanged:
            continue
        probe = copy.deepcopy(candidate)
        probe['connections'].append(e)
        try:
            normalize_project(probe)
            candidate = probe
            if e['id'] in record.get('diodes',{}):
                candidate['layout'].setdefault('diodes',{})[e['id']]=copy.deepcopy(record['diodes'][e['id']])
        except (ValueError, KeyError):
            pass
    _commit(project, candidate)


def next_id(project, prefix):
    used = {n['id'] for _, n in all_nodes(project)} | {e['id'] for e in project.get('connections', [])}
    return next(f'{prefix}-{n:03d}' if prefix == 'LINK' else f'{prefix}-{n:02d}' for n in range(1, 1000)
                if (f'{prefix}-{n:03d}' if prefix == 'LINK' else f'{prefix}-{n:02d}') not in used)


def auto_layout(project):
    depths, bottoms, positions = {}, {}, {}
    for identity in net.topological_order(project):
        ins = incoming(project, identity)
        d = max([depths[e['source']['id']] + 1 for e in ins] + [0])
        depths[identity] = d
        kind, n = next((k, n) for k, n in all_nodes(project) if n['id'] == identity)
        positions[kind + ':' + identity] = dict(x=40 + d * 385, y=bottoms.get(d, 50))
        bottoms[d] = bottoms.get(d, 50) + 220 + 26 * max(0, len(n.get('rails', [])) - 1)
    project['layout'] = dict(nodes=positions)


def save_project(project, path):
    normalized = normalize_project(project)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(temporary, target)


def load_project(path):
    return load_project_data(json.loads(Path(path).read_text(encoding='utf-8-sig')))


def load_project_data(value):
    if value.get('schema')=='power.ldo-result/1':value=value['spec']
    return normalize_project(value if value.get('schema_version') in (SCHEMA, 'pcs.aux-workspace/1') else fresh_project(value))


def recovery_path():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'PowerDesign' / 'system-workspace.json'
