"""Four user-entered Miller plateaus and zero-to-plateau charges, in SI."""
import math


def normalize_events(data,legacy=None):
    legacy=legacy or {}
    if not data:
        return {case:{edge:dict(Vgp=float(legacy.get('Vgp_'+edge,4.5)),Qgs=float(legacy.get('Qgs',2.5e-9)))
                      for edge in ('on','off')} for case in ('min','max')}
    if not isinstance(data,dict):raise ValueError('MOS 四事件参数须为对象')
    result={}
    for case in ('min','max'):
        result[case]={}
        for edge in ('on','off'):
            try:item=data[case][edge]
            except (KeyError,TypeError):raise ValueError('MOS 四事件缺少 '+case+'/'+edge) from None
            result[case][edge]={}
            for key in ('Vgp','Qgs'):
                raw=item.get(key) if isinstance(item,dict) else None
                try:
                    if isinstance(raw,bool):raise ValueError()
                    value=float(raw)
                    if not math.isfinite(value) or value<0:raise ValueError()
                except (ValueError,TypeError,OverflowError):raise ValueError(f'MOS {case}/{edge} 的 {key} 须为有限非负数') from None
                result[case][edge][key]=value
    return result


def manual_platform(p):
    if p.get('device_curve_settings'):
        from device_curve_sources import source_for,TRANSFER
        return source_for(p,TRANSFER)=='fixed'
    mode=p.get('mos_miller_mode','auto')
    return mode=='manual' or (mode=='auto' and float(p.get('gfs',0))==0)


def distinct_endpoints(p):
    events=p.get('mos_manual_events')
    return bool(events and manual_platform(p) and events.get('min')!=events.get('max'))
