"""Layer-winding fit with equivalent round/flattened bundles, in SI units.

This is a user-controlled construction estimate, not a manufacturing or
insulation certification. No mechanical setting changes electrical strands,
copper area, DCR, losses, or the coupling matrix.
"""
import copy
import math


DEFAULT_WINDING_CONFIG = dict(window_width=0., window_height=0., margin_x=.25e-3,
    margin_y=.10e-3, diameter_allowance=.03e-3, layer_insulation=.05e-3,
    interwinding_insulation=.15e-3, wire_gap=0., order=[], overrides={},layer_plan=[])

MAX_MANUAL_LAYERS=1000
MAX_MATERIALIZED_LAYERS=12000
MAX_DETAILED_LAYERS=256

DEFAULT_WIRE_OVERRIDE = dict(outer_diameter=0., strand_columns=0,
    wire_type='auto', parallel_bundles=1, packing_factor=.75,
    bundle_diameter=0., flatten_ratio=1.5, winding_style='sparse',
    turns_per_layer=0)
_NEW_WIRE_KEYS=set(DEFAULT_WIRE_OVERRIDE)-{'outer_diameter','strand_columns'}


def _finite_number(value, label, *, minimum=0., maximum=None, integer=False):
    if (isinstance(value,bool) or not isinstance(value,(int,float)) or
        not math.isfinite(value) or value<minimum or
        (maximum is not None and value>maximum) or
        (integer and int(value)!=value)):
        raise ValueError(label+' 必须为范围内的有限'+('整数' if integer else '数值'))
    return int(value) if integer else float(value)


def validate_winding_config(raw=None):
    if raw is None:
        raw = {}
    if not isinstance(raw,dict):
        raise ValueError('winding_config 必须是参数字典')
    unknown=set(raw)-set(DEFAULT_WINDING_CONFIG)
    if unknown:
        raise ValueError('未知绕制参数：'+', '.join(sorted(unknown)))
    cfg=copy.deepcopy(DEFAULT_WINDING_CONFIG)
    cfg.update(copy.deepcopy(raw))
    for key in set(cfg)-{'order','overrides','layer_plan'}:
        value=cfg[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
            raise ValueError(key+' 必须为有限非负长度（SI：m）')
        cfg[key]=float(value)
    if not isinstance(cfg['order'],list) or any(not isinstance(x,str) for x in cfg['order']):
        raise ValueError('绕组顺序必须为绕组编号列表')
    if len(cfg['order'])!=len(set(cfg['order'])):
        raise ValueError('绕组顺序不能重复')
    if not isinstance(cfg['layer_plan'],list) or len(cfg['layer_plan'])>MAX_MANUAL_LAYERS:
        raise ValueError(f'手动逐层排布必须是列表，最多 {MAX_MANUAL_LAYERS} 层')
    for index,entry in enumerate(cfg['layer_plan'],1):
        if (not isinstance(entry,dict) or set(entry)-{'winding_id','turns','winding_style'} or
            not {'winding_id','turns'}<=set(entry)):
            raise ValueError(f'第 {index} 层必须指定 winding_id、turns，可选 winding_style')
        if not isinstance(entry['winding_id'],str) or not entry['winding_id'].strip():
            raise ValueError(f'第 {index} 层的绕组编号不能为空')
        entry['turns']=_finite_number(entry['turns'],f'第 {index} 层匝数',minimum=1,maximum=10000000,integer=True)
        if entry.get('winding_style','sparse') not in ('sparse','dense_left','dense_right'):
            raise ValueError(f'第 {index} 层绕法无效')
    if not isinstance(cfg['overrides'],dict):
        raise ValueError('逐绕组设置必须为参数字典')
    for key,entry in cfg['overrides'].items():
        if not isinstance(key,str) or not isinstance(entry,dict) or set(entry)-set(DEFAULT_WIRE_OVERRIDE):
            raise ValueError('逐绕组设置含未知参数')
        for name in ('outer_diameter','bundle_diameter'):
            if name in entry:
                entry[name]=_finite_number(entry[name],key+' '+name)
        for name in ('strand_columns','turns_per_layer','parallel_bundles'):
            if name in entry:
                entry[name]=_finite_number(entry[name],key+' '+name,
                    minimum=1 if name=='parallel_bundles' else 0,maximum=10000000,integer=True)
        if 'packing_factor' in entry:
            entry['packing_factor']=_finite_number(entry['packing_factor'],key+' 束内填充系数',minimum=1e-12,maximum=1.)
        if 'flatten_ratio' in entry:
            entry['flatten_ratio']=_finite_number(entry['flatten_ratio'],key+' 压扁宽度倍数',minimum=1.,maximum=100.)
        if entry.get('wire_type','auto') not in ('auto','solid','litz'):
            raise ValueError(key+' 线材类型无效')
        if entry.get('winding_style','sparse') not in ('sparse','dense_left','dense_right'):
            raise ValueError(key+' 绕法无效')
        if entry.get('strand_columns',0) and set(entry)&_NEW_WIRE_KEYS:
            raise ValueError(key+' 旧矩形束列数不能与等效线束参数混用；请先将 strand_columns 设为 0')
    return cfg


def transformer_windings(result):
    """Resolved turns/wire geometry; never use zero-valued auto placeholders."""
    tr=(result.get('mag') or {}).get('transformer') or {}
    if not tr.get('ok'):
        return []
    rows=[dict(id='P',name='原边 P',turns=tr['Np'],strands=tr['n_strand_p'],bare_diameter=tr['d_wire_p'])]
    if tr.get('windings'):
        rows += [dict(id=f"OUT{w['id']}",name=f"OUT{w['id']} · {w['name']}",
                      turns=w['Ns'],strands=w['n_strand_s'],bare_diameter=w['d_wire_s']) for w in tr['windings']]
    else:
        rows.append(dict(id='OUT1',name='副边 OUT1',turns=tr['Ns'],strands=tr['n_strand_s'],bare_diameter=tr['d_wire_s']))
    if tr.get('auxiliary'):
        aux=tr['auxiliary']
        rows.append(dict(id='AUX',name='PSR 辅助绕组',turns=aux['Na'],strands=1,bare_diameter=aux['d_wire']))
    return rows


def assess_winding_window(windings, config=None):
    cfg=validate_winding_config(config)
    width,height=cfg['window_width'],cfg['window_height']
    base=dict(config=cfg,configured=width>0 and height>0,windings=[],fits=None,
              status='not_configured',warnings=[],interleaved=bool(cfg['layer_plan']),
              physical_layers=[],total_layer_count=0)
    if not base['configured']:
        return base
    usable_width=width-2*cfg['margin_x']
    usable_height=height-2*cfg['margin_y']
    if usable_width<=0 or usable_height<=0:
        raise ValueError('窗口扣除两侧留边后，净宽和净高必须大于 0')
    if not windings:
        base.update(status='no_transformer',warnings=['当前没有有效的变压器几何参数'])
        return base
    by_id={r['id']:r for r in windings}
    if len(by_id)!=len(windings):
        raise ValueError('绕组编号不得重复')
    order=[key for key in cfg['order'] if key in by_id]
    order += [key for key in by_id if key not in order]
    cursor=cfg['margin_y']
    copper_area=outer_area=0.
    horizontal_ok=True
    for index,key in enumerate(order):
        source=by_id[key]
        turns,strands=source['turns'],source['strands']
        bare=float(source['bare_diameter'])
        for val,label in ((turns,'匝数'),(strands,'并绕股数')):
            if isinstance(val,bool) or not isinstance(val,(int,float)) or not math.isfinite(val) or int(val)!=val or not 1<=val<=10000000:
                raise ValueError(key+' '+label+' 必须为正整数且不超过 10⁷')
        if isinstance(source['bare_diameter'],bool) or not math.isfinite(bare) or bare<=0:
            raise ValueError(key+' 裸铜线径必须为有限正数')
        override=cfg['overrides'].get(key,{})
        outer=float(override.get('outer_diameter',0.) or bare+cfg['diameter_allowance'])
        if outer<bare-1e-15:
            raise ValueError(key+' 含漆外径不能小于裸铜直径')
        gap=cfg['wire_gap']
        wire=dict(DEFAULT_WIRE_OVERRIDE,**override)
        legacy=bool(override.get('strand_columns',0))
        bundles=wire['parallel_bundles']
        if strands%bundles:
            raise ValueError(key+' 并绕束数必须整除电气总股数；不能凭空增加或减少铜线')
        per_bundle=int(strands//bundles)
        kind=wire['wire_type']
        if kind=='auto':
            kind='litz' if per_bundle>1 else 'solid'
        if per_bundle==1:
            kind='solid'  # An individual copper wire must not be flattened.
        ratio=wire['flatten_ratio'] if kind=='litz' else 1.
        diameter=wire['bundle_diameter'] or (outer if per_bundle==1 else outer*math.sqrt(per_bundle/wire['packing_factor']))
        # Even an actual OD cannot be smaller than the area of its insulated
        # strands. This lower bound is necessary, not a complete packing test.
        if diameter+1e-15<outer*math.sqrt(per_bundle):
            raise ValueError(key+' 整束外径小于束内含漆线截面积的等效直径')
        cols=rows=0
        if legacy:
            cols=int(override['strand_columns'])
            if cols>strands:
                raise ValueError(key+' 束内列数不得大于并绕股数')
            rows=math.ceil(strands/cols)
            bundle_width=cols*outer+(cols-1)*gap
            bundle_height=rows*outer+(rows-1)*gap
            ratio=1.; bundles=1; per_bundle=int(strands)
        else:
            bundle_width=diameter*ratio
            bundle_height=diameter/ratio
            if bundle_height+1e-15<outer:
                raise ValueError(key+' 压扁后的束高小于单股含漆线径；请降低压扁倍数或确认整束外径')
        turn_width=bundles*bundle_width+(bundles-1)*gap
        capacity=max(0,int(math.floor((usable_width+gap)/(turn_width+gap)+1e-10)))
        horizontal_ok &= capacity>0
        requested=wire['turns_per_layer']
        if requested and requested>capacity:
            raise ValueError(key+f' 指定每层 {requested} 匝超过窗口容量 {capacity} 匝')
        per_layer=requested or capacity
        effective=max(1,per_layer)
        layers=math.ceil(turns/effective)
        buildup=layers*bundle_height+(layers-1)*cfg['layer_insulation']
        if index:
            cursor+=cfg['interwinding_insulation']
        top=cursor+buildup
        occupied=min(turns,effective)*turn_width+(min(turns,effective)-1)*gap
        style=wire['winding_style']
        span=usable_width if style=='sparse' and capacity>0 else occupied
        start_x=cfg['margin_x']
        if style=='dense_right' and capacity>0:
            start_x+=usable_width-occupied
        row=dict(source,outer_diameter=outer,strand_columns=cols,strand_rows=rows,
                 layout_model='legacy_rectangular' if legacy else 'equivalent',
                 wire_type=kind,parallel_bundles=bundles,strands_per_bundle=per_bundle,
                 packing_factor=wire['packing_factor'],bundle_diameter=diameter,
                 flatten_ratio=ratio,winding_style=style,capacity=capacity,
                 turns_per_layer=per_layer,layers=layers,bundle_width=bundle_width,
                 bundle_height=bundle_height,x=start_x,y=cursor,
                 top=top,buildup=buildup,width=span,turn_width=turn_width,
                 occupied_width=occupied,cluster_x=start_x,
                 horizontal_fit=capacity>0,vertical_fit=top<=height-cfg['margin_y']+1e-14,
                 conductor_count=int(turns*strands),bundle_count=int(turns*bundles),
                 stack_span=buildup,layer_layout=None,physical_layer_indices=None,layer_turns=None)
        base['windings'].append(row)
        copper_area+=turns*strands*math.pi*bare**2/4
        outer_area+=turns*strands*math.pi*outer**2/4
        cursor=top
    # Resolve physical layers only after all logical-wire geometries are known.
    # Electrical turns/strands and area above are counted once per winding,
    # independent of how often that winding reappears in the physical stack.
    rows_by_id={r['id']:r for r in base['windings']}
    if cfg['layer_plan']:
        totals={key:0 for key in rows_by_id}
        for index,entry in enumerate(cfg['layer_plan'],1):
            key=entry['winding_id']
            if key not in rows_by_id:
                raise ValueError(f'第 {index} 层引用不存在的绕组 {key}；请按当前输出重新排层')
            row=rows_by_id[key]
            if entry['turns']>row['turns_per_layer']:
                raise ValueError(f"第 {index} 层 {key} 的 {entry['turns']} 匝超过每层允许 {row['turns_per_layer']} 匝（窗口容量 {row['capacity']}）")
            totals[key]+=entry['turns']
        for key,row in rows_by_id.items():
            if totals[key]!=row['turns']:
                raise ValueError(f"手动排层 {key} 合计 {totals[key]} 匝，应为 {int(row['turns'])} 匝；请补齐或调整各层匝数")
        cursor=cfg['margin_y']
        previous=None
        physical=[]
        for index,entry in enumerate(cfg['layer_plan'],1):
            key=entry['winding_id']; row=rows_by_id[key]
            kind='none' if previous is None else ('layer' if previous==key else 'interwinding')
            tape=0. if previous is None else cfg['layer_insulation'] if previous==key else cfg['interwinding_insulation']
            cursor+=tape
            layer=_physical_layer(row,index,entry['turns'],cursor,tape,kind,
                entry.get('winding_style',row['winding_style']),cfg)
            physical.append(layer);cursor=layer['top'];previous=key
        for key,row in rows_by_id.items():
            entries=[layer for layer in physical if layer['winding_id']==key]
            _assign_layer_metadata(row,entries)
            row['layers']=len(entries)
            row['y']=entries[0]['y']; row['top']=entries[-1]['top']
            row['stack_span']=row['top']-row['y']
            row['buildup']=sum(e['height']+(e['insulation_before'] if e['insulation_kind']=='layer' else 0.) for e in entries)
            row['x']=min(e['x'] for e in entries)
            row['width']=max(e['x']+e['width'] for e in entries)-row['x']
            row['occupied_width']=max(e['occupied_width'] for e in entries)
            row['cluster_x']=row['x']
            row['vertical_fit']=all(e['vertical_fit'] for e in entries)
        base['physical_layers']=physical
        base['total_layer_count']=len(physical)
    else:
        count=sum(row['layers'] for row in base['windings'])
        base['total_layer_count']=count
        if count<=MAX_MATERIALIZED_LAYERS:
            physical=[]
            for row_index,row in enumerate(base['windings']):
                entries=[]; q=max(1,row['turns_per_layer'])
                for local in range(row['layers']):
                    n=min(q,int(row['turns'])-local*q)
                    y=row['y']+local*(row['bundle_height']+cfg['layer_insulation'])
                    kind='layer' if local else ('interwinding' if row_index else 'none')
                    tape=cfg['layer_insulation'] if local else cfg['interwinding_insulation'] if row_index else 0.
                    layer=_physical_layer(row,len(physical)+1,n,y,tape,kind,row['winding_style'],cfg)
                    physical.append(layer);entries.append(layer)
                _assign_layer_metadata(row,entries)
            base['physical_layers']=physical
        else:
            base['physical_layers']=None
    required=cursor+cfg['margin_y']
    fits=bool(horizontal_ok and required<=height+1e-14)
    base.update(status='fits' if fits else 'overflow',fits=fits,usable_width=usable_width,
        usable_height=usable_height,required_height=required,height_margin=height-required,
        copper_fill=copper_area/(width*height),insulated_wire_fill=outer_area/(width*height),
        conductor_count=sum(r['conductor_count'] for r in base['windings']),
        bundle_count=sum(r['bundle_count'] for r in base['windings']))
    if not horizontal_ok:
        base['warnings'].append('至少一匝完整并绕线束宽度大于有效窗口；请调整线束、压扁比例或骨架')
    if required>height+1e-14:
        base['warnings'].append(f'径向叠厚超出窗口 {(required-height)*1e3:.4g} mm')
    if any(r['layout_model']=='legacy_rectangular' for r in base['windings']):
        base['warnings'].append('包含旧配置的显式矩形束列数，沿用其宽高；切换等效线束前请清除旧列数。')
    base['warnings'].append('利兹线压扁按截面积不变估算；默认填充系数与压扁比例不是实测值。仅作分层几何预评估，不含引线、跨线、公差和安规认证，不回写 DCR、漏感或 kij。')
    return base


def _physical_layer(row,index,turns,y,tape,kind,style,cfg):
    wu=cfg['window_width']-2*cfg['margin_x']
    occupied=turns*row['turn_width']+(turns-1)*cfg['wire_gap']
    x=cfg['margin_x']
    if row['horizontal_fit']:
        if style=='dense_right':
            x+=wu-occupied
        elif style=='sparse' and turns==1:
            x+=(wu-row['turn_width'])/2
    span=wu if style=='sparse' and turns>1 and row['horizontal_fit'] else occupied
    top=y+row['bundle_height']
    return dict(layer_index=index,winding_id=row['id'],turns=turns,y=y,top=top,
        height=row['bundle_height'],bundle_height=row['bundle_height'],
        insulation_before=tape,insulation_kind=kind,winding_style=style,
        x=x,width=span,occupied_width=occupied,horizontal_fit=row['horizontal_fit'],
        vertical_fit=top<=cfg['window_height']-cfg['margin_y']+1e-14)


def _assign_layer_metadata(row,entries):
    row['layer_layout']=entries
    row['physical_layer_indices']=[e['layer_index'] for e in entries]
    row['layer_turns']=[e['turns'] for e in entries]


def build_automatic_layer_plan(windings,config=None):
    """Generate an editable, conserved physical plan without unbounded lists."""
    cfg=validate_winding_config(config)
    cfg['layer_plan']=[]
    assessment=assess_winding_window(windings,cfg)
    if not assessment['configured'] or not assessment['windings']:
        raise ValueError('请先填写有效净窗口并完成变压器计算，再生成逐层排布')
    if assessment['total_layer_count']>MAX_MANUAL_LAYERS:
        raise ValueError(f'自动方案超过 {MAX_MANUAL_LAYERS} 层，不能转为手动逐层编辑；请先修正窗口和线材')
    if any(not row['horizontal_fit'] for row in assessment['windings']):
        raise ValueError('完整匝束超出窗口宽度，不能生成有效逐层排布')
    return [dict(winding_id=e['winding_id'],turns=e['turns'],winding_style=e['winding_style'])
            for e in assessment['physical_layers']]


def iter_bundle_sections(row, config):
    """Yield equivalent bundle bounding boxes (x, y, w, h), all in metres.

    Complete parallel-bundle groups stay together in sparse winding. Only
    turns, not individual microscopic strands, are iterated.
    """
    count=int(row['turns']); q=max(1,row['turns_per_layer'])
    gap=config['wire_gap']; wu=config['window_width']-2*config['margin_x']
    layout=row.get('layer_layout')
    entries=layout if layout is not None else (
        dict(turns=min(q,count-layer*q),y=row['y']+layer*(row['bundle_height']+config['layer_insulation']),
             winding_style=row['winding_style']) for layer in range(row['layers']))
    for entry in entries:
        n=entry['turns']
        occupied=n*row['turn_width']+(n-1)*gap
        start=config['margin_x']; pitch=row['turn_width']+gap
        if row['horizontal_fit']:
            if entry['winding_style']=='dense_right':
                start+=wu-occupied
            elif entry['winding_style']=='sparse':
                if n==1:
                    start+=(wu-row['turn_width'])/2
                else:
                    pitch=(wu-row['turn_width'])/(n-1)
        y=entry['y']
        for turn in range(n):
            x=start+turn*pitch
            for bundle in range(row['parallel_bundles']):
                yield (x+bundle*(row['bundle_width']+gap),y,
                       row['bundle_width'],row['bundle_height'])


def draw_winding_cross_section(ax, assessment, max_circles=12000):
    """True equal-axis dimensions; overflow remains visible, not clipped."""
    from matplotlib.patches import Ellipse,Rectangle,Patch
    from matplotlib.collections import PatchCollection
    ax.clear()
    cfg=assessment['config']
    if not assessment['configured'] or not assessment['windings']:
        ax.text(.5,.5,'请输入骨架净窗口宽与高（mm）\n并完成有效的变压器计算',ha='center',va='center',transform=ax.transAxes,fontsize=11)
        ax.set_axis_off()
        return
    ax.set_axis_on()
    width,height=cfg['window_width']*1e3,cfg['window_height']*1e3
    mx,my=cfg['margin_x']*1e3,cfg['margin_y']*1e3
    colors=('#1558b0','#16866a','#b96b19','#8b52aa','#cb5660','#3b859e','#737744','#6e7484')
    # Flanges are illustrative, outside the user-entered net window. They do
    # not consume its dimensions or imply a measured bobbin-wall thickness.
    wall=max(.15,width*.045)
    ax.add_patch(Rectangle((-wall,-wall),width+2*wall,wall,facecolor='#e6e8eb',edgecolor='#334155',lw=1.1))
    for x in (-wall,width):
        ax.add_patch(Rectangle((x,0),wall,height+wall,facecolor='#e6e8eb',edgecolor='#334155',lw=1.1))
    ax.add_patch(Rectangle((0,0),width,height,facecolor='#f1f3f5',edgecolor='#334155',lw=1.1))
    ax.add_patch(Rectangle((mx,my),width-2*mx,height-2*my,facecolor='white',edgecolor='#66758a',ls='--',lw=.8))
    handles=[]
    detail=(assessment['bundle_count']<=max_circles and
            assessment['total_layer_count']<=MAX_DETAILED_LAYERS)
    x_extent=width
    by_id={r['id']:r for r in assessment['windings']}
    color_by_id={r['id']:colors[index%len(colors)] for index,r in enumerate(assessment['windings'])}
    for row in assessment['windings']:
        color=color_by_id[row['id']]
        wire_label='矩形束旧方案' if row['layout_model']=='legacy_rectangular' else ('利兹线' if row['wire_type']=='litz' else '圆铜线')
        style_label='逐层' if assessment['interleaved'] else {'sparse':'疏绕','dense_left':'密左','dense_right':'密右'}[row['winding_style']]
        positions=row['physical_layer_indices']
        placement=(('层 '+','.join(map(str,positions[:8]))+('…' if len(positions)>8 else ''))
                   if assessment['interleaved'] else f"{row['layers']}层")
        handles.append(Patch(facecolor=color,label=f"{row['id']}  {int(row['turns'])}T · {wire_label} · {style_label}\n{row['parallel_bundles']}束 × {row['strands_per_bundle']}股 · {placement}"))
    # Per-physical-layer envelopes prevent a split winding from painting over
    # another winding between its sections. Huge automatic layouts retain the
    # old constant-size logical block fallback, with no per-layer allocation.
    physical=assessment['physical_layers']
    if not assessment['interleaved'] and assessment['total_layer_count']>MAX_DETAILED_LAYERS:
        physical=None
    if physical is None:
        paint=[dict(winding_id=r['id'],x=r['x'],y=r['y'],width=r['width'],height=r['buildup'],
                    insulation_before=cfg['interwinding_insulation'] if i else 0.,
                    insulation_kind='interwinding',vertical_fit=r['vertical_fit'],
                    horizontal_fit=r['horizontal_fit']) for i,r in enumerate(assessment['windings'])]
    else:
        paint=physical
    bulk=len(paint)>128
    envelopes=[];envelope_colors=[];tapes=[];tape_colors=[];overflows=[]
    for layer in paint:
        row=by_id[layer['winding_id']]
        color=color_by_id[row['id']]
        x,y,w,h=[layer[k]*1e3 for k in ('x','y','width','height')]
        x_extent=max(x_extent,x+w)
        if bulk:
            envelopes.append(Rectangle((x,y),w,h));envelope_colors.append(color)
        else:
            ax.add_patch(Rectangle((x,y),w,h,facecolor=color,alpha=.13,edgecolor=color,lw=.8))
        tape=layer['insulation_before']*1e3
        if tape:
            tape_color='#d8bf89' if layer['insulation_kind']=='layer' else '#b6a27a'
            if bulk:
                tapes.append(Rectangle((mx,y-tape),width-2*mx,tape));tape_colors.append(tape_color)
            else:
                ax.add_patch(Rectangle((mx,y-tape),width-2*mx,tape,
                    facecolor=tape_color,edgecolor='none',alpha=.6))
        if physical is not None and len(physical)<=24:
            ax.text(width+wall+.06,y+h/2,f"L{layer['layer_index']} · {row['id']}",fontsize=7,color=color,va='center')
        if not layer['horizontal_fit'] or not layer['vertical_fit']:
            if bulk:
                overflows.append(Rectangle((x,y),w,h))
            else:
                ax.add_patch(Rectangle((x,y),w,h,fill=False,edgecolor='#c13535',lw=1.4,ls='--'))
    if bulk:
        ax.add_collection(PatchCollection(envelopes,facecolors=envelope_colors,edgecolors=envelope_colors,alpha=.13,lw=.8))
        if tapes:
            ax.add_collection(PatchCollection(tapes,facecolors=tape_colors,edgecolors='none',alpha=.6))
        if overflows:
            ax.add_collection(PatchCollection(overflows,facecolors='none',edgecolors='#c13535',lw=1.4,ls='--'))
    if detail:
        for row in assessment['windings']:
            color=color_by_id[row['id']]
            sections=[]
            for bx,by,bw,bh in iter_bundle_sections(row,cfg):
                if row['layout_model']=='legacy_rectangular':
                    sections.append(Rectangle((bx*1e3,by*1e3),bw*1e3,bh*1e3))
                else:
                    sections.append(Ellipse(((bx+bw/2)*1e3,(by+bh/2)*1e3),bw*1e3,bh*1e3))
            ax.add_collection(PatchCollection(sections,facecolor='white',edgecolor=color,lw=1.1))
    required=assessment['required_height']*1e3
    extent_y=max(height,required)
    padding=max(.3,max(width,extent_y)*.07)
    ax.set_xlim(-padding,x_extent+padding)
    ax.set_ylim(-padding,extent_y+padding)
    ax.set_aspect('equal',adjustable='box')
    ax.set_xlabel('轴向窗口宽度 / mm',fontsize=9)
    ax.set_ylabel('径向窗口高度 / mm',fontsize=9)
    ax.tick_params(labelsize=8)
    ax.grid(alpha=.15)
    label='当前层绕方案可放下' if assessment['fits'] else '当前层绕方案超限'
    ax.set_title(f'{width:g} × {height:g} mm 净窗口 · {label}'+('（截面过多，仅画层包络）' if not detail else ''),fontsize=10,pad=12)
    ax.legend(handles=handles,loc='upper left',bbox_to_anchor=(1.11,1.),fontsize=7,frameon=False)
