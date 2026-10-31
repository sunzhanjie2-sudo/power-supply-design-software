"""Small, explicit MOS transfer/output-curve interchange; no PDF guessing.

CSV headers carry SI units. Studio JSON transfer curves retain their declared
axes and test conditions. Output families require numeric Vgs per trace.
"""
import bisect
import copy
import csv
import hashlib
import io
import json
import math
from pathlib import Path

SCHEMA = 'power-design.mos-miller-curve.v1'
MAX_POINTS = 20000


def finite(value, label):
    try:
        valid=not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value)
    except OverflowError:
        valid=False
    if not valid:
        raise ValueError(label+'必须为有限数值')
    return float(value)


def _points(points, label, scales, *, transfer=False):
    if not isinstance(points,list) or not 2 <= len(points) <= MAX_POINTS:
        raise ValueError(label+'需要 2–20000 个点')
    parsed=[]
    for row in points:
        if not isinstance(row,(list,tuple)) or len(row)!=2:
            raise ValueError(label+'每点必须有明确的两个坐标')
        x,y=(finite(v,label) for v in row)
        if x<0 or y<0 or (transfer and x==0):
            raise ValueError(label+'坐标必须非负，Vgs 必须为正')
        if (scales[0]=='log' and x<=0) or (scales[1]=='log' and y<=0):
            raise ValueError(label+'对数坐标必须为正')
        parsed.append([x,y])
    parsed.sort()
    if any(b[0]<=a[0] for a,b in zip(parsed,parsed[1:])):
        raise ValueError(label+'存在重复横坐标，不能作为单值曲线')
    if any(b[1]<a[1] for a,b in zip(parsed,parsed[1:])):
        raise ValueError(label+'电流不单调，请先校核描点')
    if transfer and any(b[1]<=a[1] for a,b in zip(parsed,parsed[1:])):
        raise ValueError(label+'反查需要电流严格递增；请去除重复电流或零电流平段')
    return parsed


def validate_curve(data):
    if not isinstance(data,dict) or data.get('schema')!=SCHEMA:
        raise ValueError('不是带物理量定义的 MOS 平台曲线格式')
    kind=data.get('kind')
    if kind not in ('transfer','output_family'):
        raise ValueError('曲线类型必须是 transfer 或 output_family')
    xs,ys=data.get('x_scale','linear'),data.get('y_scale','linear')
    if xs not in ('linear','log') or ys not in ('linear','log'):
        raise ValueError('坐标类型必须为 linear 或 log')
    out={k:copy.deepcopy(data[k]) for k in ('name','conditions','source','import_file','reviewed','Tj_C','Vds_test_V') if k in data}
    for key in ('source','import_file'):
        if key in out:
            if not isinstance(out[key],dict):raise ValueError('曲线来源必须为结构化对象')
            source={}
            for name in ('filename','sha256'):
                if name in out[key]:
                    if not isinstance(out[key][name],str) or len(out[key][name])>2000:raise ValueError('曲线来源文本无效')
                    source[name]=out[key][name]
            if out[key].get('page') is not None:
                page=finite(out[key]['page'],'来源页码')
                if page<1 or page!=int(page):raise ValueError('来源页码必须为正整数')
                source['page']=int(page)
            out[key]=source
    if 'reviewed' in out and not isinstance(out['reviewed'],bool):raise ValueError('曲线校核标记必须为布尔值')
    for key in ('name','conditions'):
        if key in out and (not isinstance(out[key],str) or len(out[key])>2000):
            raise ValueError('曲线名称和条件必须为文本，最多 2000 字符')
    for key in ('Tj_C','Vds_test_V'):
        if key in out:out[key]=finite(out[key],key)
    out.update(schema=SCHEMA,kind=kind,x_scale=xs,y_scale=ys)
    out['allow_extrapolation']=data.get('allow_extrapolation',True)
    if not isinstance(out['allow_extrapolation'],bool):raise ValueError('外推设置须为布尔值')
    if kind=='transfer':
        out['points']=_points(data.get('points'), 'Id–Vgs 转移曲线', (xs,ys),transfer=True)
    else:
        traces=data.get('traces')
        if not isinstance(traces,list) or not 2<=len(traces)<=100:
            raise ValueError('Id–Vds 输出曲线族至少需要两条不同 Vgs 曲线，最多 100 条')
        out['traces']=[]
        for t in traces:
            if not isinstance(t,dict):raise ValueError('输出曲线族缺少 Vgs 分组')
            if 'Tj_C' in t and ('Tj_C' not in out or finite(t['Tj_C'],'分组温度')!=out['Tj_C']):
                raise ValueError('输出曲线族存在不同或未统一的温度条件')
            vgs=finite(t.get('Vgs_V'),'每条曲线的 Vgs')
            if vgs<=0:raise ValueError('每条曲线的 Vgs 必须大于零')
            out['traces'].append(dict(Vgs_V=vgs,points=_points(t.get('points'),'Id–Vds 曲线',(xs,ys))))
        out['traces'].sort(key=lambda t:t['Vgs_V'])
        if len({t['Vgs_V'] for t in out['traces']})!=len(traces):
            raise ValueError('输出曲线族 Vgs 重复；不同温度/条件必须分开导入')
        if sum(len(t['points']) for t in out['traces'])>MAX_POINTS:
            raise ValueError('输出曲线族合计最多 20000 个点')
    return out


def interpolate(points, query, xscale='linear', yscale='linear', *, extrapolate=False, notes=None, label='曲线'):
    query=finite(query,'查询坐标')
    outside=not points[0][0]<=query<=points[-1][0]
    if outside and not extrapolate:
        raise ValueError(f'查询值 {query:g} 超出曲线范围 [{points[0][0]:g}, {points[-1][0]:g}]，禁止外推')
    if outside and notes is not None:notes.append(dict(quantity=label,query=query,low=points[0][0],high=points[-1][0]))
    i=bisect.bisect_left([p[0] for p in points],query)
    if i<len(points) and points[i][0]==query:return points[i][1]
    a,b=(points[:2] if i==0 else points[-2:] if i==len(points) else points[i-1:i+1])
    if xscale=='log' and query<=0:raise ValueError('对数外推的查询值须大于0')
    scale=lambda v,s:math.log10(v) if s=='log' else v
    x0,x1,x=(scale(v,xscale) for v in (a[0],b[0],query))
    y0,y1=(scale(v,yscale) for v in (a[1],b[1]))
    y=y0+(x-x0)/(x1-x0)*(y1-y0)
    return 10**y if yscale=='log' else y


def gate_voltage(data, current, read_vds=0., *, extrapolations=None):
    """Invert a validated transfer curve or a fixed-Vds slice of a family."""
    if data['kind']=='transfer':
        inverse=[[i,v] for v,i in data['points']]
        return interpolate(inverse,current,data['y_scale'],data['x_scale'],extrapolate=data.get('allow_extrapolation',True),notes=extrapolations,label='Id–Vgs 反查')
    read_vds=finite(read_vds,'输出曲线读取 Vds')
    if read_vds<=0:raise ValueError('Id–Vds 曲线族需要指定大于 0 的读取 Vds（V）')
    samples=[[interpolate(t['points'],read_vds,data['x_scale'],data['y_scale'],extrapolate=data.get('allow_extrapolation',True),notes=extrapolations,label='Id–Vds 截面'),t['Vgs_V']] for t in data['traces']]
    if any(b[0]<=a[0] for a,b in zip(samples,samples[1:])):
        raise ValueError('指定 Vds 下电流未随 Vgs 严格递增，不能唯一反查栅压')
    return interpolate(samples,current,extrapolate=data.get('allow_extrapolation',True),notes=extrapolations,label='Vgs 分组反查')


def _csv(text, name):
    try:dialect=csv.Sniffer().sniff(text[:4096],delimiters=',;\t')
    except csv.Error:dialect=csv.excel
    reader=csv.DictReader(io.StringIO(text),dialect=dialect)
    headers=reader.fieldnames or []
    base={'Vgs_V','Ids_A'}
    if len(set(headers))!=len(headers) or not base.issubset(headers) or set(headers)-base-{'Vds_V','Tj_C'}:
        raise ValueError('CSV 表头须为 Vgs_V,Ids_A；输出曲线族另含 Vds_V，可选 Tj_C。不猜测 x/y 或单位')
    rows=[]
    for index,row in enumerate(reader,2):
        if None in row or any(v is None or not v.strip() for v in row.values()):
            raise ValueError(f'CSV 第 {index} 行缺少数值或列数错误')
        try:rows.append({k:float(v) for k,v in row.items()})
        except ValueError:raise ValueError(f'CSV 第 {index} 行不是数值') from None
        if len(rows)>MAX_POINTS:raise ValueError('CSV 最多 20000 个点')
    if len(rows)<2:raise ValueError('CSV 至少需要两个曲线点')
    data=dict(schema=SCHEMA,name=name,kind='output_family' if 'Vds_V' in headers else 'transfer')
    if 'Tj_C' in headers:
        temperatures={finite(r['Tj_C'],'Tj_C') for r in rows}
        if len(temperatures)!=1:raise ValueError('CSV 包含多种温度，请每次导入同一温度的数据')
        data['Tj_C']=temperatures.pop()
    if data['kind']=='transfer':data['points']=[[r['Vgs_V'],r['Ids_A']] for r in rows]
    else:
        groups={}
        for r in rows:groups.setdefault(r['Vgs_V'],[]).append([r['Vds_V'],r['Ids_A']])
        data['traces']=[dict(Vgs_V=v,points=p) for v,p in groups.items()]
    return [validate_curve(data)]


def read_curve_candidates(path):
    path=Path(path)
    if path.stat().st_size>5*1024*1024:raise ValueError('MOS 曲线文件超过 5 MB')
    raw=path.read_bytes();text=raw.decode('utf-8-sig')
    origin=dict(filename=path.name,sha256=hashlib.sha256(raw).hexdigest())
    if path.suffix.lower()=='.csv':items=_csv(text,path.stem)
    elif path.suffix.lower()=='.json':
        data=json.loads(text)
        if isinstance(data,dict) and data.get('schema')==SCHEMA:items=[validate_curve(data)]
        elif isinstance(data,dict) and data.get('family')=='mosfet' and isinstance(data.get('curves'),list):
            items=[]
            if len(data['curves'])>100:raise ValueError('单次最多导入 100 条候选曲线')
            for c in data['curves']:
                if not isinstance(c,dict):raise ValueError('器件曲线条目格式无效')
                if c.get('kind')!='mosfet_transfer':continue
                if (c.get('x_quantity'),c.get('y_quantity'))!=('Vgs','Ids'):
                    raise ValueError('Studio 转移曲线的物理量定义不匹配')
                xf={'V':1.,'mV':1e-3}.get(c.get('x_unit'));yf={'A':1.,'mA':1e-3}.get(c.get('y_unit'))
                if xf is None or yf is None:raise ValueError('Studio 曲线单位不支持，需 V/mV 与 A/mA')
                points=_points(c.get('points'),'Studio Id–Vgs',(c.get('x_scale','linear'),c.get('y_scale','linear')),transfer=True)
                item=dict(schema=SCHEMA,kind='transfer',name=(str(data.get('mpn',''))+' '+str(c.get('name',''))).strip(),
                    conditions=c.get('conditions',''),source=c.get('source',{}),reviewed=c.get('reviewed',False),
                    x_scale=c.get('x_scale','linear'),y_scale=c.get('y_scale','linear'),
                    points=[[x*xf,y*yf] for x,y in points])
                items.append(validate_curve(item))
            if not items:raise ValueError('未找到已定义的 Id–Vgs 转移曲线；Id–Vds 族请用带 Vgs_V 的三列 CSV，不从自由文本猜 Vgs')
        else:raise ValueError('JSON 需要 MOS 平台曲线格式或器件提取程序的 MOSFET JSON')
    else:raise ValueError('请选择 .csv 或 .json；PDF 曲线请先在器件提取程序中描点、校核')
    for item in items:item['import_file']=origin
    return items
