"""Forward-characteristic lookup and periodic conduction loss, independent of UI.

File axes are always X=Vf [V], Y=If [A]. Names do not imply a temperature or
device identity: an explicit schematic designator owns each embedded curve.
"""
import copy
import math
import re

import numpy as np

SCHEMA = 'power-design.diode-forward.v1'
DEPRECATED_RD = ('Rd_diode', 'Rd_din', 'Rd_dout')
MAX_BACKTRACK_FRACTION = .03


def _monotonic_voltages(values):
    """Bounded pixel-noise cleanup by least-squares isotonic regression.

    Check the largest cumulative drawdown, not only adjacent differences: many
    small descending steps must not disguise a reversed/misidentified branch.
    Currents stay unchanged. The original source file is never overwritten.
    """
    voltage=np.asarray(values,dtype=float)
    tolerance=float(np.ptp(voltage))*MAX_BACKTRACK_FRACTION
    backtrack=float(np.max(np.maximum.accumulate(voltage)-voltage))
    if backtrack>tolerance:
        raise ValueError(f'正向曲线明显倒退：Vf 最大回退 {backtrack:.5g} V，'
                         f'超过曲线 Vf 跨度的 3%（{tolerance:.5g} V）；请检查分线、坐标方向或修点')
    if backtrack==0:return list(values),None
    blocks=[]
    for index,value in enumerate(values):
        blocks.append([value,1,index,index+1])
        while len(blocks)>1 and blocks[-2][0]>blocks[-1][0]:
            b=blocks.pop();a=blocks.pop()
            count=a[1]+b[1]
            blocks.append([a[0]+(b[0]-a[0])*(b[1]/count),count,a[2],b[3]])
    fitted=voltage.copy()
    for mean,count,start,end in blocks:fitted[start:end]=mean
    changes=np.abs(fitted-voltage)
    return fitted.tolist(),dict(method='isotonic_vf_if',adjusted_points=int(np.count_nonzero(changes)),
        max_adjustment_V=float(np.max(changes)),max_backtrack_V=backtrack,tolerance_V=tolerance)


def cleanup_message(curve):
    info=curve.get('cleanup',{})
    if not info.get('adjusted_points'):return ''
    return (f"已整理 {info['adjusted_points']} 个小幅回退点，"
            f"最大 Vf 修正 {info['max_adjustment_V']*1000:.4g} mV；原始文件未修改")


def validate_curve(data):
    if not isinstance(data, dict):raise ValueError('二极管曲线必须是点数据字典')
    if data.get('schema',SCHEMA)!=SCHEMA:raise ValueError('这不是二极管 Vf–If 曲线格式；请选择两列 XY 文件并确认导入入口')
    points=data.get('points')
    if not isinstance(points,list) or not 2<=len(points)<=20000:
        raise ValueError('Vf–If 曲线至少两个点，最多 20000 点')
    pairs=[]
    for p in points:
        if not isinstance(p,(list,tuple)) or len(p)!=2:raise ValueError('每个点应为 [Vf, If]')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in p):
            raise ValueError('Vf、If 须为有限非负数；X=Vf/V，Y=If/A')
        pairs.append([float(p[0]),float(p[1])])
    pairs.sort(key=lambda p:p[1])
    # A flat zero-current part cannot uniquely specify Vf(If). Use one midpoint
    # per repeated current, while preserving measured forward-voltage plateaus.
    groups={}
    for v,i in pairs:groups.setdefault(i,[]).append(v)
    points=[[float(np.median(values)),i] for i,values in sorted(groups.items())]
    if len(points)<2 or points[-1][1]<=0:raise ValueError('需要两个不同 If 坐标，且至少一个正电流点')
    voltage,cleanup=_monotonic_voltages([p[0] for p in points])
    points=[[v,p[1]] for v,p in zip(voltage,points)]
    if cleanup is None and 'cleanup' in data:
        # Keep provenance stable through config loads / repeated validation.
        info=data['cleanup']
        if not isinstance(info,dict) or info.get('method')!='isotonic_vf_if':
            raise ValueError('二极管曲线整理记录无效')
        count=info.get('adjusted_points')
        if isinstance(count,bool) or not isinstance(count,int) or not 0<=count<=20000:
            raise ValueError('二极管曲线整理点数无效')
        cleanup=dict(method='isotonic_vf_if',adjusted_points=count)
        for key in ('max_adjustment_V','max_backtrack_V','tolerance_V'):
            value=info.get(key)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                raise ValueError('二极管曲线整理幅度无效')
            cleanup[key]=float(value)
    source=data.get('source',data.get('import_file',{}))
    if not isinstance(source,dict):raise ValueError('二极管曲线来源格式无效')
    result=dict(schema=SCHEMA,name=str(data.get('name','Vf–If'))[:150],points=points,
                source={k:str(v)[:1000] for k,v in source.items() if k in ('filename','sha256')})
    if cleanup:result['cleanup']=cleanup
    return result


def from_xy(curve,x_multiplier=1.,y_multiplier=1.,source=None):
    for m in (x_multiplier,y_multiplier):
        if isinstance(m,bool) or not math.isfinite(m) or m<=0:raise ValueError('数量级倍率必须为有限正数')
    return validate_curve(dict(name=curve['name'],source=source or {},
        points=[[float(x)*x_multiplier,float(y)*y_multiplier] for x,y in curve['points']]))


def validate_bank(data):
    if not isinstance(data,dict) or len(data)>23:raise ValueError('diode_curves 须按二极管位号保存，最多 23 项')
    result={}
    for ref,curve in data.items():
        if not isinstance(ref,str) or not re.fullmatch(r'D1|D2|D_IN|D_OUT|D_[OFB][1-6]',ref):
            raise ValueError('未知二极管位号：'+str(ref))
        result[ref]=validate_curve(curve)
    return result


def active_diodes(p):
    """The same designators as topology_diagram, excluding unmodelled clamps."""
    rows=[]
    if p.get('d_in_enable'):rows.append(dict(ref='D_IN',role='共享输入防反',vf_key='Vf_din',kind='input',rail=None))
    rails=p.get('outputs') or []
    if rails or p.get('feedback_mode')=='PSR-MP6005':
        for n,r in enumerate(rails or [p],1):
            name=f"OUT{n} {r.get('name','')}".strip()
            rows.append(dict(ref=f'D_O{n}',role=name+' · 输出整流',vf_key='Vf_diode',kind='rectifier',rail=n))
            if p['topology']=='ACF-FORWARD':rows.append(dict(ref=f'D_F{n}',role=name+' · 续流',vf_key='Vf_diode',kind='freewheel',rail=n))
            if r.get('d_out_enable'):rows.append(dict(ref=f'D_B{n}',role=name+' · 输出防反',vf_key='Vf_dout',kind='output',rail=n))
    else:
        rows.append(dict(ref='D1',role='功率级续流' if p['topology']=='BUCK' else '输出整流',vf_key='Vf_diode',kind='rectifier',rail=None))
        if p['topology']=='ACF-FORWARD':rows.append(dict(ref='D2',role='输出续流',vf_key='Vf_diode',kind='freewheel',rail=None))
        if p.get('d_out_enable'):rows.append(dict(ref='D_OUT',role='输出防反',vf_key='Vf_dout',kind='output',rail=None))
    return rows


def refs(p,rail=None):
    if rail is not None or p.get('outputs') or p.get('feedback_mode')=='PSR-MP6005':
        n=rail or int(p.get('feedback_output',1));return f'D_O{n}',f'D_F{n}',f'D_B{n}'
    return 'D1','D2','D_OUT'


def conduction(current,curve=None,vf=.7,average=None):
    """Uniform periodic samples; reverse current excluded (Qrr is separate).

    Curve mode averages instantaneous I*Vf(I), not Vf(Iavg)*Iavg. Endpoint
    linear extrapolation is explicit, Vf is clipped at zero, and I=0 costs zero.
    """
    values=np.asarray(current,dtype=float)
    if values.size==0 or not np.all(np.isfinite(values)):raise ValueError('二极管电流样本必须是非空有限数值')
    current=np.maximum(values,0.)
    if not curve:
        vf=float(vf)
        if not math.isfinite(vf) or vf<0:raise ValueError('固定二极管 Vf 必须为有限非负数')
        mean=float(np.mean(current)) if average is None else float(average)
        if not math.isfinite(mean) or mean<0:raise ValueError('二极管正向平均电流必须为有限非负数')
        return dict(P_cond=vf*mean,model='fixed_vf',curve_name='',I_min=0.,I_max=float(np.max(current)),
                    extrapolations=[],notes=['固定 Vf × 正向平均电流；不再叠加动态电阻项'])
    data=validate_curve(curve)
    pts=np.asarray(data['points']);voltage,amps=pts[:,0],pts[:,1]
    forward=np.interp(current,amps,voltage)
    for edge,a,b in (('low',0,1),('high',-2,-1)):
        mask=(current<amps[0]) if edge=='low' else (current>amps[-1])
        forward=np.where(mask,voltage[a]+(current-amps[a])*(voltage[b]-voltage[a])/(amps[b]-amps[a]),forward)
    forward=np.maximum(forward,0.)
    positive=current[current>0]
    ext=[]
    for edge,mask in (('低电流',positive<amps[0]),('高电流',positive>amps[-1])):
        if np.any(mask):ext.append(f'{edge}端趋势外推：{float(np.min(positive[mask])):.5g}–{float(np.max(positive[mask])):.5g} A')
    power=float(np.mean(current*forward))
    if not math.isfinite(power):raise ValueError('二极管曲线外推功耗超出有限范围，请检查数量级')
    cleaned=cleanup_message(data)
    return dict(P_cond=power,model='vf_if_curve',curve_name=data['name'],source=copy.deepcopy(data['source']),
                cleanup=copy.deepcopy(data.get('cleanup',{})),
                I_min=float(np.min(positive)) if positive.size else 0.,I_max=float(np.max(current)),
                curve_I_min=float(amps[0]),curve_I_max=float(amps[-1]),extrapolations=ext,
                notes=['按当前周期正向电流逐点反查 Vf 并平均 I×Vf；不叠加固定 Vf 或 Rd',
                       '所选曲线条件由名称区分，不自动修正结温；曲线仅用于损耗后处理']+([cleaned] if cleaned else [])+ext)
