"""Reviewed Vgs(Qg) reference curves, with an explicit Miller interval.

Shared verbatim with the standalone extractor. Charges are SI coulombs.
Only the pre-Miller branch is inverted for Qgs and Qg(th). Never read the
post-Miller branch as Qgs when an event exceeds the available reference range.
"""
import bisect
import csv
import hashlib
import io
import json
import math
from pathlib import Path

SCHEMA='power-design.mos-gate-charge.v1'
COLLECTION='power-design.mos-gate-charge-collection.v1'


def finite(value,label):
    try:
        if isinstance(value,bool):raise ValueError()
        out=float(value)
        if not math.isfinite(out):raise ValueError()
        return out
    except (ValueError,TypeError,OverflowError):raise ValueError(label+'须为有限数值') from None


def interpolate(points,value,*,extrapolate=False,notes=None,label='栅电荷'):
    value=finite(value,'查询值')
    outside=not points[0][0]<=value<=points[-1][0]
    if outside and not extrapolate:
        raise ValueError(f'查询值 {value:.6g} 超出 [{points[0][0]:.6g}, {points[-1][0]:.6g}]，禁止外推')
    if outside and notes is not None:notes.append(dict(quantity=label,query=value,low=points[0][0],high=points[-1][0]))
    i=bisect.bisect_left([p[0] for p in points],value)
    if i<len(points) and points[i][0]==value:return points[i][1]
    a,b=(points[:2] if i==0 else points[-2:] if i==len(points) else points[i-1:i+1])
    result=a[1]+(value-a[0])/(b[0]-a[0])*(b[1]-a[1])
    return max(0.,result) if outside else result


def validate_charge(data):
    if not isinstance(data,dict) or data.get('schema')!=SCHEMA:raise ValueError('需要 Vgs–Qg 栅电荷曲线格式，不能用 Id–Vgs 代替')
    points=data.get('points')
    if not isinstance(points,list) or not 4<=len(points)<=20000:raise ValueError('栅电荷曲线需要 4–20000 个 [Qg_C,Vgs_V] 点')
    pts=[]
    for pair in points:
        if not isinstance(pair,(list,tuple)) or len(pair)!=2:raise ValueError('栅电荷坐标须为 [Qg_C,Vgs_V]')
        q,v=[finite(x,'栅电荷点') for x in pair]
        if min(q,v)<0:raise ValueError('栅电荷及栅压不能为负')
        pts.append([q,v])
    pts.sort()
    if any(b[0]<=a[0] or b[1]<a[1] for a,b in zip(pts,pts[1:])):raise ValueError('Qg 须严格递增，Vgs 须单调不降；平台平段允许')
    start=finite(data.get('Qgs_ref_C'),'平台起点 Qgs_ref_C')
    end=finite(data.get('Qplateau_end_C'),'平台终点 Qplateau_end_C')
    if not pts[0][0]<start<end<pts[-1][0]:raise ValueError('平台起止电荷必须位于曲线内部，且起点 < 终点')
    vstart,vend=interpolate(pts,start),interpolate(pts,end)
    if vstart<=0 or vend-vstart>max(.25,.06*vstart):raise ValueError('所选平台段电压变化较大，请核对两个平台拐点')
    tol=(pts[-1][0]-pts[0][0])*1e-10
    pre=[p for p in pts if p[0]<start-tol]+[[start,vstart]]
    post=[[end,vend]]+[p for p in pts if p[0]>end+tol]
    if any(b[1]<=a[1] for a,b in zip(pre,pre[1:])):raise ValueError('平台前支路栅压须严格递增，请整理重复栅压/拐点')
    # Above-plateau inverse must also be single-valued; equality at the boundary
    # may be an observed flat tail, retained at its last charge coordinate.
    post_unique=[]
    for p in post:
        if post_unique and p[1]==post_unique[-1][1]:post_unique[-1]=p
        else:post_unique.append(p)
    if len(post_unique)<2:raise ValueError('平台后支路不足以读取驱动电压对应的总 Qg')
    out=dict(schema=SCHEMA,points=pts,Qgs_ref_C=start,Qplateau_end_C=end)
    out['allow_extrapolation']=data.get('allow_extrapolation',True)
    if not isinstance(out['allow_extrapolation'],bool):raise ValueError('外推设置须为布尔值')
    for key in ('Id_test_A','Vds_test_V','Tj_C'):
        if data.get(key) in (None,''):
            out[key]=None
            continue
        out[key]=finite(data.get(key),key)
        if key!='Tj_C' and out[key]<=0:raise ValueError(key+'必须大于0，并填原图测试条件，不是 Vin')
    for key in ('name','conditions'):
        value=data.get(key,'')
        if not isinstance(value,str) or len(value)>2000:raise ValueError('栅电荷曲线名称/条件文本无效')
        out[key]=value
    for key in ('source','import_file'):
        if key in data:
            if not isinstance(data[key],dict):raise ValueError('栅电荷来源须为对象')
            out[key]={k:str(data[key][k])[:2000] for k in ('filename','sha256','page') if k in data[key]}
    if not isinstance(data.get('reviewed',False),bool):raise ValueError('校核标记须为布尔值')
    out['reviewed']=data.get('reviewed',False)
    return out


def branches(data):
    pts=data['points'];start,end=data['Qgs_ref_C'],data['Qplateau_end_C']
    tol=(pts[-1][0]-pts[0][0])*1e-10
    pre=[p for p in pts if p[0]<start-tol]+[[start,interpolate(pts,start)]]
    post=[[end,interpolate(pts,end)]]+[p for p in pts if p[0]>end+tol]
    unique=[]
    for q,v in post:
        if unique and v==unique[-1][0]:unique[-1]=[v,q]
        else:unique.append([v,q])
    return [[v,q] for q,v in pre],unique


def read_charges(data,vth,vdrive,von,voff):
    c=validate_charge(data);pre,post=branches(c)
    used=[]
    def read(points,value,label):return interpolate(points,value,extrapolate=c['allow_extrapolation'],notes=used,label=label)
    try:
        qth=read(pre,vth,'Qg(th) 平台前')
        on=read(pre,von,'Qgs,on 平台前');off=read(pre,voff,'Qgs,off 平台前')
    except ValueError as exc:
        raise ValueError('Vgs–Qg 平台前支路查值失败：'+str(exc)+'。不可改用平台后支路或等效 Cgs；请补充曲线/校核平台电压') from exc
    if not vdrive>post[0][0]:raise ValueError('驱动电压必须高于参考曲线的平台后起点')
    try:total=read(post,vdrive,'总 Qg 平台后')
    except ValueError as exc:raise ValueError('总 Qg 查值失败：'+str(exc)+'；请补充覆盖驱动电压的曲线') from exc
    return dict(Qg_th=qth,Qgs_on=on,Qgs_off=off,Qgd_on=c['Qplateau_end_C']-c['Qgs_ref_C'],
                Qgd_off=c['Qplateau_end_C']-c['Qgs_ref_C'],Qg_on=total,Qg_off=total,
                charge_mode='curve',charge_curve_info={k:v for k,v in c.items() if k!='points'},
                charge_extrapolations=used,
                Vgp_charge_reference=interpolate(c['points'],c['Qgs_ref_C']))


def read_charge_candidates(path):
    path=Path(path)
    if path.stat().st_size>5*1024*1024:raise ValueError('栅电荷文件超过 5 MiB')
    raw=path.read_bytes();text=raw.decode('utf-8-sig')
    if path.suffix.lower()=='.json':
        data=json.loads(text)
        if isinstance(data,dict) and data.get('schema')==COLLECTION:
            items=data.get('curves')
            if not isinstance(items,list) or not 1<=len(items)<=100:raise ValueError('栅电荷曲线集合须有 1–100 条曲线')
        else:items=[data]
    elif path.suffix.lower()=='.csv':
        reader=csv.DictReader(io.StringIO(text));headers=reader.fieldnames or []
        required={'Qg_C','Vgs_V','Tj_C','Id_test_A','Vds_test_V','Qgs_ref_C','Qplateau_end_C'}
        if set(headers)!=required or len(headers)!=len(required):raise ValueError('栅电荷 CSV 需要 Qg_C,Vgs_V,Tj_C,Id_test_A,Vds_test_V,Qgs_ref_C,Qplateau_end_C；不猜测 nC 单位或平台拐点')
        rows=list(reader)
        if not 4<=len(rows)<=20000:raise ValueError('栅电荷 CSV 需要4–20000个点')
        parsed=[]
        for row in rows:
            if None in row:raise ValueError('栅电荷 CSV 列数错误')
            parsed.append({k:(None if k=='Tj_C' and row.get(k) in (None,'') else finite(row.get(k),k)) for k in required})
        meta={}
        for key in required-{'Qg_C','Vgs_V'}:
            values={r[key] for r in parsed}
            if len(values)!=1:raise ValueError('一个 CSV 只能含同一测试条件和平台标记')
            meta[key]=values.pop()
        items=[dict(schema=SCHEMA,name=path.stem,**meta,points=[[r['Qg_C'],r['Vgs_V']] for r in parsed])]
    else:raise ValueError('请选择栅电荷 CSV 或 JSON')
    result=[validate_charge(item) for item in items]
    for item in result:item['import_file']=dict(filename=path.name,sha256=hashlib.sha256(raw).hexdigest())
    return result


def suggest_plateau(points):
    """Suggest only; the user must confirm the two landmarks before export."""
    if len(points)<4:raise ValueError('局部曲线无法自动区分米勒平台，请在导入窗口填写平台起止电荷')
    dq=points[-1][0]-points[0][0];dv=points[-1][1]-points[0][1]
    if min(dq,dv)<=0:raise ValueError('栅电荷曲线跨度无效')
    # A tolerance band over a monotonic curve is robust to one-pixel steps;
    # testing each adjacent slope used to split one plateau into many runs.
    band=dv*.02;left=0;best=(0.,0,0)
    for right,p in enumerate(points):
        while left<right and p[1]-points[left][1]>band:left+=1
        mid=(p[1]+points[left][1])*.5
        width=p[0]-points[left][0]
        if points[0][1]+dv*.05<mid<points[-1][1]-dv*.05 and width>best[0]:best=(width,left,right)
    if best[0]<dq*.04:raise ValueError('未找到可靠平坦段，请手动确认平台起止电荷')
    import statistics
    level=statistics.median(p[1] for p in points[best[1]:best[2]+1]);epsilon=dv*.002
    near=[p for p in points if abs(p[1]-level)<=epsilon]
    if len(near)<2:raise ValueError('平台位置不明确，请手动填写')
    return near[0][0],near[-1][0]
