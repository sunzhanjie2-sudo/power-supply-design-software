"""Unit-free two-column curve files. Axis meaning/scales belong to import UI."""
import csv
import hashlib
import io
import json
import math
from pathlib import Path

MAX_POINTS=20000


def number(v):
    if isinstance(v,bool):raise ValueError('坐标不能为布尔值')
    try:r=float(v)
    except (ValueError,TypeError,OverflowError):raise ValueError('曲线坐标须为数值') from None
    if not math.isfinite(r):raise ValueError('曲线坐标须为有限数值')
    return r


def parse_points(items):
    if not isinstance(items,list) or len(items)>MAX_POINTS:raise ValueError('曲线点格式无效或超过20000点')
    points=[]
    for p in items:
        if not isinstance(p,(list,tuple)) or len(p)!=2:raise ValueError('每个点需要 x 和 y 两个数')
        points.append([number(v) for v in p])
    if len(points)<2:raise ValueError('至少保留两个不同坐标的点才能确定趋势')
    return points


def read_simple(path):
    path=Path(path)
    if path.stat().st_size>5*1024*1024:raise ValueError('曲线文件超过5MiB')
    raw=path.read_bytes();text=raw.decode('utf-8-sig')
    if path.suffix.lower()=='.json':
        data=json.loads(text)
        if isinstance(data,dict) and ('schema' in data or 'schema_version' in data):return None
        if isinstance(data,dict) and 'curves' in data:entries=data['curves']
        elif isinstance(data,dict):entries=[data]
        elif isinstance(data,list) and data and isinstance(data[0],list) and len(data[0])==2 and not isinstance(data[0][0],(dict,list)):
            entries=[data]
        elif isinstance(data,list):entries=data
        else:raise ValueError('JSON 使用 [[x,y],...] 即可，也支持 points 或 curves')
        if not isinstance(entries,list) or not 1<=len(entries)<=100:raise ValueError('曲线集合须有1–100条曲线')
        curves=[]
        for index,entry in enumerate(entries,1):
            name=str(entry.get('name',f'{path.stem} {index}')) if isinstance(entry,dict) else f'{path.stem} {index}'
            points=entry.get('points',list(zip(entry['x'],entry['y'])) if 'x' in entry and 'y' in entry else None) if isinstance(entry,dict) else entry
            curves.append(dict(name=name[:200],points=parse_points(points)))
    elif path.suffix.lower()=='.csv':
        try:dialect=csv.Sniffer().sniff(text[:4096],delimiters=',;\t')
        except csv.Error:dialect=csv.excel
        rows=[r for r in csv.reader(io.StringIO(text),dialect) if r and any(x.strip() for x in r)]
        if not rows:raise ValueError('CSV为空')
        if len(rows[0])!=2:return None
        try:[number(x) for x in rows[0]]
        except ValueError:
            if any(x.strip() in ('Vgs_V','Ids_A','Vds_V','Qg_C') for x in rows[0]):return None
            rows=rows[1:]  # an optional arbitrary two-column header
        curves=[dict(name=path.stem,points=parse_points(rows))]
    else:raise ValueError('请选择 CSV 或 JSON')
    return dict(curves=curves,source=dict(filename=path.name,sha256=hashlib.sha256(raw).hexdigest()))


def cleaned_points(points):
    """Consolidate duplicate X and tiny pixel reversals; expose the removal count."""
    grouped={}
    for x,y in points:grouped.setdefault(number(x),[]).append(number(y))
    pts=[[x,sum(values)/len(values)] for x,values in sorted(grouped.items())]
    if len(pts)<2:raise ValueError('横坐标全部相同，无法确定端点趋势')
    if any(min(p)<0 for p in pts):raise ValueError('MOS 曲线坐标不能为负')
    span=max(y for x,y in pts)-min(y for x,y in pts)
    result=[]
    for p in pts:
        if result and p[1]<result[-1][1]:
            if result[-1][1]-p[1]>max(span*.03,1e-15):raise ValueError('曲线明显倒退，请检查轴方向或分线结果')
            continue
        result.append(p)
    return result,len(points)-len(result)


def to_transfer(curve,x_multiplier=1.,y_multiplier=1.,source=None):
    from mos_curves import SCHEMA,validate_curve
    pts,removed=cleaned_points(curve['points'])
    unique=[]
    for x,y in pts:
        if x>0 and (not unique or y>unique[-1][1]):unique.append([x*x_multiplier,y*y_multiplier])
    result=validate_curve(dict(schema=SCHEMA,kind='transfer',points=unique,name=curve['name'],allow_extrapolation=True,
        conditions=f'简洁坐标导入；X倍率={x_multiplier:g}，Y倍率={y_multiplier:g}；整理移除{removed}点，测试条件未声明',import_file=source or {}))
    return result


def to_charge(curve,x_multiplier=1e-9,y_multiplier=1.,start=None,end=None,source=None):
    from mos_gate_charge import SCHEMA,validate_charge,suggest_plateau,interpolate
    pts,removed=cleaned_points(curve['points'])
    pts=[[x*x_multiplier,y*y_multiplier] for x,y in pts]
    if start is None or end is None:
        start,end=suggest_plateau(pts)
    else:start,end=start*x_multiplier,end*x_multiplier
    vstart=interpolate(pts,start)
    # Quantized duplicate Vgs values below the selected plateau cannot form a
    # single-valued inverse; consolidate them without touching the flat span.
    cleaned=[]
    for p in pts:
        if p[0]<start and p[1]>=vstart:continue
        if p[0]<start and cleaned and p[1]==cleaned[-1][1]:continue
        cleaned.append(p)
    return validate_charge(dict(schema=SCHEMA,points=cleaned,name=curve['name'],Qgs_ref_C=start,Qplateau_end_C=end,
        Id_test_A=None,Vds_test_V=None,Tj_C=None,allow_extrapolation=True,import_file=source or {},
        conditions=f'简洁坐标导入；X倍率={x_multiplier:g}，Y倍率={y_multiplier:g}；测试条件未声明，平台起止由导入时确认'))
