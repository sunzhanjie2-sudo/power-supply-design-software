"""Editable auxiliary-power network and static worst-case supply budgets.

Connections are first-class records. OR-ing chooses voltage, never assumes
current sharing. Each case selects one incoming branch per consumer.
"""
import copy
import itertools
import math
import re

SCHEMA = 'power.system-network/2'
COLLECTIONS = {'bus': 'sources', 'unit': 'units', 'junction': 'junctions', 'load': 'loads'}


def nodes(project):
    return [(kind, node) for kind, collection in COLLECTIONS.items() for node in project.get(collection, [])]


def incoming(project, identity, *, enabled=False):
    return [e for e in project.get('connections', []) if e['target'] == identity and (not enabled or e['enabled'])]


def migrate(project):
    p = copy.deepcopy(project)
    if p.get('schema_version') == SCHEMA:
        return p
    from pcs_workspace import SCHEMA as OLD
    if p.get('schema_version') != OLD:
        raise ValueError('需要系统工程或旧版 PCS 辅源工程 JSON。')
    p.update(schema_version=SCHEMA, loads=[], junctions=[], connections=[])
    for unit in p['units']:
        s = unit.get('source', {})
        if s.get('kind') != 'none':
            p['connections'].append(dict(id=f"LINK-{len(p['connections'])+1:03d}", source=s,
                                         target=unit['id'], mode='direct', vf=0.3, enabled=True))
    return p


def normalize(project):
    from pcs_workspace import validate_project, SCHEMA as OLD
    raw = migrate(project)
    # The existing specification loader remains authoritative for converters.
    base = copy.deepcopy(raw)
    base['schema_version'] = OLD
    for u in base['units']:
        u['source'] = dict(kind='none', id='', output=1)
    base['layout'] = dict(nodes={})
    out = validate_project(base)
    out.update(schema_version=SCHEMA, workspace_kind='power-system', loads=[], junctions=[], connections=[])
    for u, original in zip(out['units'], raw['units']):
        u['spec'].update({k: copy.deepcopy(v) for k, v in original['spec'].items() if k.startswith('__')})
        u['enabled'] = original.get('enabled', True)
    for b, original in zip(out['sources'], raw['sources']):
        b['enabled'] = original.get('enabled', True)
    used = {n['id'] for _, n in nodes(out)}
    def number(v, label, minimum=0):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < minimum:
            raise ValueError(label + '必须为有限数值且不小于' + str(minimum))
        return float(v)
    def identity(v):
        if not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', v):
            raise ValueError('节点/连线 ID 仅允许英文字母、数字、下划线、短横线。')
        return v
    for kind in ('junction', 'load'):
        values = raw.get(COLLECTIONS[kind], [])
        if not isinstance(values, list) or len(values) > 48:
            raise ValueError('每类最多48个汇流节点或负载。')
        for value in values:
            i = identity(value.get('id'))
            if i in used:
                raise ValueError('所有节点 ID 必须唯一。')
            used.add(i)
            name = value.get('name')
            if not isinstance(name, str) or not name.strip() or len(name) > 120:
                raise ValueError('负载/汇流节点名称须为1～120字。')
            n = dict(id=i, name=name.strip(), enabled=value.get('enabled', True))
            if kind == 'junction':
                n['capacity'] = number(value.get('capacity', 100), '汇流容量', 1e-9)
            else:
                n.update(power=number(value.get('power', 1), '负载功率'),
                         min=number(value.get('min', 0), '负载最小电压'), max=number(value.get('max', 0), '负载最大电压'))
                if n['max'] and n['max'] < n['min']:
                    raise ValueError('负载电压范围上限不得小于下限；均填0表示不检查电压。')
            out[COLLECTIONS[kind]].append(n)
    by_id = {n['id']: (kind, n) for kind, n in nodes(out)}
    for _, n in nodes(out):
        if not isinstance(n['enabled'], bool):
            raise ValueError('节点启用状态必须是布尔值。')
    edges = raw.get('connections', [])
    if not isinstance(edges, list) or len(edges) > 256:
        raise ValueError('最多256条供电连接。')
    edge_ids, pairs = set(), set()
    for e in edges:
        i = identity(e.get('id'))
        s, t = e.get('source', {}), e.get('target')
        kind, sid, port = s.get('kind'), s.get('id'), s.get('output', 1)
        if i in edge_ids or i in used:
            raise ValueError('连线 ID 重复或与节点相同。')
        edge_ids.add(i)
        if kind not in ('bus', 'unit', 'junction') or sid not in by_id or by_id[sid][0] != kind:
            raise ValueError('上游输入源/模块/汇流节点不存在；负载不能作为供电输出。')
        if t not in by_id or by_id[t][0] == 'bus':
            raise ValueError('下游必须是电源模块、汇流节点或负载。')
        count = len(by_id[sid][1]['rails']) if kind == 'unit' else 1
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= count:
            raise ValueError('上游输出端口不存在。')
        pair = (sid, port, t)
        if pair in pairs:
            raise ValueError('此端口到目标的连接已存在。')
        pairs.add(pair)
        mode = e.get('mode', 'diode' if by_id[t][0] == 'junction' else 'direct')
        if mode not in ('diode', 'direct') or not isinstance(e.get('enabled', True), bool):
            raise ValueError('连线方式须为直连或二极管隔离。')
        out['connections'].append(dict(id=i, source=dict(kind=kind, id=sid, output=port), target=t,
                                       mode=mode, vf=number(e.get('vf', .3), '二极管正向压降'), enabled=e.get('enabled', True)))
    for kind, n in nodes(out):
        ins = incoming(out, n['id'], enabled=True)
        if (len(ins) > 1 or kind == 'junction') and any(e['mode'] != 'diode' for e in ins):
            raise ValueError(n['id'] + ' 多源竞争供电必须逐支路二极管隔离，不能直接并联电源。')
    topological_order(out)  # check all edges, including disabled ones
    positions = raw.get('layout', {}).get('nodes', {})
    if not isinstance(positions, dict):
        raise ValueError('布局必须为节点坐标映射。')
    valid = {kind + ':' + n['id'] for kind, n in nodes(out)}
    out['layout'] = dict(nodes={})
    for key, point in positions.items():
        if key in valid:
            out['layout']['nodes'][key] = {axis: number(point.get(axis), '节点坐标') for axis in ('x', 'y')}
            if max(out['layout']['nodes'][key].values()) > 10000:
                raise ValueError('节点坐标不得超过10000。')
    diode_positions=raw.get('layout',{}).get('diodes',{})
    if not isinstance(diode_positions,dict):
        raise ValueError('二极管布局需为连接ID与坐标的映射。')
    valid_diodes={e['id'] for e in out['connections'] if e['mode']=='diode'}
    out['layout']['diodes']={}
    for identity,point in diode_positions.items():
        if identity not in valid_diodes:
            continue
        if not isinstance(point,dict):raise ValueError('二极管坐标无效。')
        xy={axis:number(point.get(axis),'二极管坐标') for axis in ('x','y')}
        if max(xy.values())>10000:raise ValueError('二极管坐标不得超过10000。')
        out['layout']['diodes'][identity]=xy
    return out


def topological_order(project):
    ids = [n['id'] for _, n in nodes(project)]
    parents = {i: [] for i in ids}
    for e in project['connections']:
        parents[e['target']].append(e['source']['id'])
    order, seen, stack = [], set(), set()
    def visit(i):
        if i in stack:
            raise ValueError('此连接会形成循环供电，不能连接。')
        if i in seen:
            return
        stack.add(i)
        for parent in parents[i]:
            visit(parent)
        stack.remove(i)
        seen.add(i)
        order.append(i)
    for i in ids:
        visit(i)
    return order


def port_key(source):
    return source['id'] + ('/OUT' + str(source['output']) if source['kind'] == 'unit' else '')


def analyze(project):
    """Evaluate endpoint and source-outage cases; report ties conservatively.

    Fixed-Vf, constant-power static budget. A converter input reserves its
    configured full output rating / eta; loads reserve output-port capacity.
    """
    from ldo import is_ldo, input_power, operating_point
    p = normalize(project)
    by_id = {n['id']: (kind, n) for kind, n in nodes(p)}
    order = topological_order(p)
    roots = [b['id'] for b in p['sources'] if b['enabled']]
    all_roots = frozenset(roots)
    availabilities = [('全部输入源', all_roots)]
    if len(roots) > 1:
        availabilities += [(r + ' 掉电', all_roots - {r}) for r in roots]
        availabilities += [(r + ' 单独供电', frozenset([r])) for r in roots]
    unique={}
    for name, available in availabilities:
        unique.setdefault(available,[]).append(name)
    availabilities=[(' / '.join(names),available) for available,names in unique.items()]
    capacity, iface, diode = {}, {}, {}
    for kind, n in nodes(p):
        if kind == 'unit':
            for i, r in enumerate(n['rails'], 1):
                capacity[n['id'] + '/OUT' + str(i)] = dict(capacity=r['P_out'])
        elif kind in ('bus', 'junction'):
            capacity[n['id']] = dict(capacity=n['capacity'])
        if kind != 'bus':
            spec = n.get('spec', {})
            lo = spec.get('V_in_min', spec.get('V_in', 0)) if kind == 'unit' else n.get('min', 0)
            hi = spec.get('V_in_max', spec.get('V_in', 0)) if kind == 'unit' else n.get('max', 0)
            if is_ldo(spec) and spec['follow_input']:
                lo,hi=spec['input_rating_min'] or 0,spec['input_rating_max'] or 0
            iface[n['id']] = dict(unit=n['id'], name=n['name'], kind=kind, design_min=lo, design_max=hi,
                                  source_min=None, source_max=None, ok=True, normal_available=True, unavailable=0, enabled=n['enabled'])
    for key, r in capacity.items():
        r.update(port=key, allocated=0., normal=0., worst_case='无供电需求', remaining=r['capacity'], ok=True)
    inputs = {i: incoming(p, i, enabled=True) for i in by_id}
    cases, coverage_complete = [], True
    linear = {}
    # All-low/all-high plus one independently high source covers voltage
    # competition reversals without exponential endpoint enumeration.
    variable=[b['id'] for b in p['sources'] if b['enabled'] and b['max']>b['min']]
    voltage_cases = [('Vinmin', {})]
    if variable:voltage_cases.append(('Vinmax', {r: True for r in variable}))
    voltage_cases += [(r + ' 高压', {r: True}) for r in variable] if len(variable) > 1 else []
    for available_name, available in availabilities:
        for voltage_name, high in voltage_cases:
            voltages, choices, outputs, ldo_cases = {}, {}, {}, {}
            for identity in order:
                kind, n = by_id[identity]
                if not n['enabled']:
                    continue
                if kind == 'bus':
                    if identity in available:
                        voltages[identity] = n['max'] if high.get(identity) else n['min']
                    continue
                candidates = []
                for e in inputs[identity]:
                    s = e['source']
                    parent = by_id[s['id']][1]
                    vin = voltages.get(s['id'])
                    if vin is not None and s['kind'] == 'unit':
                        vin = outputs.get(port_key(s))
                    v = vin - (e['vf'] if e['mode'] == 'diode' else 0) if vin is not None else -1
                    if v > 0:
                        candidates.append((e, v, vin))
                if not candidates:
                    continue
                winning = max(v for _, v, _ in candidates)
                # A small tie tolerance is numerical only, not a sharing model.
                choices[identity] = [(e, v, vin) for e, v, vin in candidates if abs(v - winning) <= 1e-8 * max(1, winning)]
                voltages[identity] = winning
                if kind=='unit':
                    if is_ldo(n['spec']):
                        c=operating_point(n['spec'],winning,n['spec']['I_out_max']);ldo_cases[identity]=c
                        if c['regulated']:outputs[identity+'/OUT1']=n['spec']['V_out']
                        item=linear.setdefault(identity,dict(unit=identity,name=n['name'],dropout_ok=True,max_loss=None,max_Tj=None,current_ok=True))
                        item['dropout_ok'] &= c['regulated']
                        item['current_ok'] &= c['within_current_rating'] is not False
                        for key,source in [('max_loss','P_chip'),('max_Tj','T_j')]:
                            if c[source] is not None:item[key]=max(item[key] if item[key] is not None else c[source],c[source])
                    else:
                        for j,rail in enumerate(n['rails'],1):outputs[identity+'/OUT'+str(j)]=rail['V_out']
            is_normal = available == all_roots
            for identity, r in iface.items():
                if not r['enabled']:
                    continue
                v = voltages.get(identity)
                if v is None:
                    r['unavailable'] += 1
                    if is_normal:
                        r['normal_available'] = False
                    continue
                r['source_min'] = min(r['source_min'], v) if r['source_min'] is not None else v
                r['source_max'] = max(r['source_max'], v) if r['source_max'] is not None else v
                r['ok'] &= (not r['design_min'] or v >= r['design_min'] - 1e-8) and (not r['design_max'] or v <= r['design_max'] + 1e-8)
            keys = list(choices)
            combinations = math.prod(len(choices[k]) for k in keys)
            if combinations > 128:
                coverage_complete = False
            for selection in itertools.islice(itertools.product(*(choices[k] for k in keys)), 128):
                if len(cases) >= 2048:
                    coverage_complete = False
                    break
                picked = dict(zip(keys, selection))
                demand, port_load, losses, routes = {}, {}, {}, {}
                for identity in reversed(order):
                    kind, n = by_id[identity]
                    if identity not in voltages or not n['enabled']:
                        continue
                    if kind == 'unit':
                        watts = input_power(n['spec'],voltages[identity]) if is_ldo(n['spec']) else sum(r['P_out'] for r in n['rails']) / n['spec']['eta_guess']
                    elif kind == 'load':
                        watts = n['power']
                    elif kind == 'junction':
                        watts = demand.get(identity, 0.)
                    else:
                        continue
                    if identity not in picked:
                        continue
                    e, delivered, upstream = picked[identity]
                    pin = watts * upstream / delivered
                    key = port_key(e['source'])
                    port_load[key] = port_load.get(key, 0.) + pin
                    demand[e['source']['id']] = demand.get(e['source']['id'], 0.) + pin
                    losses[e['id']] = max(0., pin - watts)
                    routes[identity] = e['id']
                name = available_name + ' · ' + voltage_name
                unavailable = [i for i, r in iface.items() if r['enabled'] and i not in voltages]
                case=dict(name=name, normal=is_normal, allocated=port_load, routes=routes, unavailable=unavailable)
                if ldo_cases:case['ldo']=ldo_cases
                cases.append(case)
                for key, watts in port_load.items():
                    r = capacity[key]
                    if watts > r['allocated']:
                        r.update(allocated=watts, worst_case=name)
                    if is_normal:
                        r['normal'] = max(r['normal'], watts)
                for e, watts in losses.items():
                    diode[e] = max(diode.get(e, 0.), watts)
    for r in capacity.values():
        r.update(remaining=r['capacity'] - r['allocated'], ok=r['allocated'] <= r['capacity'] + 1e-8 and coverage_complete)
    for r in iface.values():
        r['ok'] &= r['normal_available'] and r['source_min'] is not None
        r['note'] = ('未启用' if not r['enabled'] else '正常供电缺失' if not r['normal_available'] else
                     '存在掉电/独供工况失电' if r['unavailable'] else '已覆盖已评估工况')
        if r['unit'] in linear:
            item=linear[r['unit']];spec=by_id[r['unit']][1]['spec']
            item['thermal_ok']=item['max_Tj'] is not None and item['max_Tj']<=spec['junction_limit']
            if not item['dropout_ok'] or not item['current_ok'] or not item['thermal_ok']:
                r['ok']=False;r['note']+='；LDO 压差/电流/热设计需核对'
            if any(spec[k] is None for k in ('input_rating_min','input_rating_max','current_rating')) or not spec['thermal_verified']:
                r['ok']=False;r['note']+='；LDO 额定资料或有效热阻待核对'
    return dict(capacity=list(capacity.values()), interfaces=list(iface.values()), cases=cases,
                diode_losses=[dict(connection=e['id'], source=port_key(e['source']), target=e['target'],
                                   vf=e['vf'] if e['mode'] == 'diode' else 0., loss=diode.get(e['id'], 0.)) for e in p['connections']],
                coverage_complete=coverage_complete,ldo=list(linear.values()),
                method='固定Vf标称稳态预算；高电压支路优先，同压不假定均流，枚举独占供电。覆盖全源、逐源掉电和单源独供，以及全低/全高/逐源高压；非全部电压组合，非瞬态或切换仿真。LDO 按实际输入×(最大负载+分压+Iq)预算；压差不足不向后级宣称稳压。')
