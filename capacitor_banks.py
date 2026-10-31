"""Configurable parallel banks. SI lists are authoritative; legacy pairs load unchanged."""
import copy
import math

LEGACY_INPUT=('Cin1','Rcin1','ESLin1','Cin2','Rcin2','ESLin2','cin2_enable')
LEGACY_OUTPUT=('C_out','Rc','ESL','C_out2','Rc2','ESL2','cout2_enable')
FIELDS=LEGACY_INPUT+LEGACY_OUTPUT


def validate(value):
    if not isinstance(value,list) or not value:
        raise ValueError('电容组至少需要一颗电容')
    result=[]
    for i,row in enumerate(value,1):
        if not isinstance(row,dict) or set(row)-{'C','ESR','ESL'}:
            raise ValueError(f'电容 {i} 需要 C、ESR、ESL 参数（SI 单位）')
        data={key:row.get(key,0.) for key in ('C','ESR','ESL')}
        for key,v in data.items():
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 or (key=='C' and v==0):
                raise ValueError(f'电容 {i}：C 必须大于零，ESR/ESL 不得为负，且数值有限')
        result.append({k:float(v) for k,v in data.items()})
    return result


def bank(p,side='output'):
    key=side+'_capacitors'
    if p.get(key) is not None:
        return validate(p[key])
    if side=='input':
        values=[dict(C=p['Cin1'],ESR=p['Rcin1'],ESL=p.get('ESLin1',0.))]
        if p.get('cin2_enable'):values.append(dict(C=p['Cin2'],ESR=p['Rcin2'],ESL=p.get('ESLin2',0.)))
    else:
        values=[dict(C=p['C_out'],ESR=p['Rc'],ESL=p.get('ESL',0.))]
        if p.get('cout2_enable'):values.append(dict(C=p['C_out2'],ESR=p['Rc2'],ESL=p.get('ESL2',0.)))
    return validate(values)


def tuples(p,side='output'):
    return [(r['C'],r['ESR'],r['ESL']) for r in bank(p,side)]


def total(p,side='output'):
    return sum(r['C'] for r in bank(p,side))


def normalize(p):
    """Project the first pair only for backward-compatible scalar consumers."""
    if (p.get('input_capacitors') is None and p.get('output_capacitors') is None
            and not any(r.get('output_capacitors') is not None for r in p.get('outputs',[]) if isinstance(r,dict))):
        return dict(p)
    p=copy.deepcopy(p)
    for side,fields in (('input',LEGACY_INPUT),('output',LEGACY_OUTPUT)):
        if p.get(side+'_capacitors') is None:continue
        values=bank(p,side);p[side+'_capacitors']=values
        for k,v in zip(fields[:3],values[0].values()):p[k]=v
        if len(values)>1:
            for k,v in zip(fields[3:6],values[1].values()):p[k]=v
        p[fields[-1]]=len(values)>1
    if p.get('outputs'):
        p['outputs']=[normalize(r) for r in p['outputs']]
    return p


def output_ref(output,index,multi=False):
    if not multi:return 'C_O'+str(index)
    suffix=chr(64+index) if index<=26 else '_'+str(index)
    return f'C_O{output}{suffix}'
