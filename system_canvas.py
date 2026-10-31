"""Native architecture drawing, kept separate from electrical and UI state."""
import math
from network_layout import diode_point, endpoints, scene_bounds
from power_network import analyze as model_review
MUTED_COLOR='#71849d'

PALETTE={'bus':'#18a8bd','unit':'#3979e6','junction':'#8664ce','load':'#119c83'}


def draw_network(ui):
    c=ui.canvas;z=ui.zoom;c.delete('all');ui.hits={}
    current_tag='grid'
    ui._edge_items={};ui._incident_edges={};ui._drawn_positions={}
    def tagged(item,hit):
        c.addtag_withtag(current_tag,item)
        ui.hits[item]=hit
        return item
    def text(x,y,value,size=12,color='#71849d',anchor='w',bold=False,hit=None):
        item=c.create_text(x,y,text=value,anchor=anchor,fill=color,font=('Microsoft YaHei UI',-max(7,round(size*z)),'bold' if bold else 'normal'))
        c.addtag_withtag(current_tag,item)
        if hit:tagged(item,hit)
        return item
    def rounded(x,y,w,h,fill,outline='',width=1,hit=None,r=12):
        pts=(x+r,y,x+w-r,y,x+w,y,x+w,y+r,x+w,y+h-r,x+w,y+h,x+w-r,y+h,x+r,y+h,x,y+h,x,y+h-r,x,y+r,x,y)
        item=c.create_polygon(pts,smooth=True,splinesteps=10,fill=fill,outline=outline,width=width*z)
        c.addtag_withtag(current_tag,item)
        if hit:tagged(item,hit)
        return item
    def curve(a,b,color,hit,dashed=False):
        bend=max(20,abs(b[0]-a[0])*.48)
        return tagged(c.create_line(a[0],a[1],a[0]+bend,a[1],b[0]-bend,b[1],b[0],b[1],smooth=True,splinesteps=22,
                             fill=color,width=2*z,dash=(5,4) if dashed else (),arrow='last',arrowshape=(7*z,8*z,3*z)),hit)
    # Grid is viewport-only, never a 10000×10000 allocation.
    left,top=c.canvasx(0)/z,c.canvasy(0)/z
    step=24 if z>=.7 else 48
    for x in range(math.floor(left/step)*step,int(left+max(1,c.winfo_width())/z)+step,step):
        for y in range(math.floor(top/step)*step,int(top+max(1,c.winfo_height())/z)+step,step):
            c.create_oval(x,y,x+1,y+1,fill='#d8e1ed',outline='')
    for edge in ui.project['connections']:
        current_tag='wire:'+edge['id']
        source=edge['source'];key=source['kind']+':'+source['id']
        ui._incident_edges.setdefault(key,[]).append(edge)
        target=next(key for key,(kind,node,point) in ui.nodes.items() if node['id']==edge['target'])
        ui._incident_edges.setdefault(target,[]).append(edge)
        a,b=endpoints(ui.project,edge)
        color='#d29132' if ui.selected==('edge',edge['id']) else '#4b7ec7' if edge['enabled'] else '#b5bfcd'
        hit=('edge',edge['id'])
        if edge['mode']=='diode':
            p=diode_point(ui.project,edge)
            items=[curve(a,(p['x']-44,p['y']),color,hit,not edge['enabled']),curve((p['x']+44,p['y']),b,color,hit,not edge['enabled'])]
        else:
            items=[curve(a,b,color,hit,not edge['enabled'])]
        ui._edge_items[edge['id']]=items
    for key,(kind,n,p) in ui.nodes.items():
        current_tag='node:'+key
        ui._drawn_positions[current_tag]=dict(p)
        x,y=p['x'],p['y'];h=158+26*max(0,len(n.get('rails',[]))-1)
        hit=(kind,n['id']);dark=kind=='bus';accent=PALETTE[kind]
        rounded(x,y+5,288,h,'#e5ebf4',r=14)
        rounded(x,y,288,h,'#10243b' if dark else '#ffffff',accent if ui.selected==hit else '#d9e3ef',2 if ui.selected==hit else 1,hit,r=14)
        rounded(x,y+18,4,32,accent,r=2)
        text(x+18,y+23,n['id']+'  ·  '+{'bus':'INPUT SOURCE','unit':'CONVERTER','junction':'DIODE OR BUS','load':'LOAD'}[kind],10,'#66c7dc' if dark else accent,bold=True,hit=hit)
        name=n['name'][:12]+('…' if len(n['name'])>12 else '')
        text(x+18,y+54,name,18,'#ffffff' if dark else '#1c334f',bold=True,hit=hit)
        tagged(c.create_oval(x+249,y+17,x+255,y+23,fill='#24ae91' if n['enabled'] else '#d29338',outline=''),hit)
        text(x+271,y+20,'×',20,'#8b9fb5',anchor='center',hit=('delete',key))
        if kind=='bus':value=f"{n['min']:g}–{n['max']:g} V  ·  {n['capacity']:g} W"
        elif kind=='unit':value=(f"LDO · {n['spec']['V_out']:g}V / {n['spec']['I_out_max']*1000:g}mA" if n['spec']['topology']=='LDO' else f"{n['spec']['topology']}  ·  {sum(r['P_out'] for r in n['rails']):g} W")
        elif kind=='junction':value=f"二极管竞争母线  ·  {n['capacity']:g} W"
        else:value=f"{n['power']:g} W  ·  "+(f"{n['min']:g}–{n['max']:g} V" if n['max'] else '允许电压未限定')
        text(x+18,y+79,value,12,'#acc4d9' if dark else '#7b8da3',hit=hit)
        if not dark:
            count=sum(e['enabled'] for e in ui.project['connections'] if e['target']==n['id'])
            text(x+16,y+96,'IN'+(f'  ·  OR ×{count}' if count>1 else ''),10,hit=hit)
            tagged(c.create_oval(x-8,y+86,x+8,y+102,fill='white',outline=accent,width=2*z),('input',n['id']))
        rails=n.get('rails',[]) if kind=='unit' else ([{}] if kind in ('bus','junction') else [])
        for i,r in enumerate(rails,1):
            yy=y+(102 if dark else 119+26*(i-1))
            label='DC OUTPUT' if dark else 'OR BUS' if kind=='junction' else f"OUT{i}  {r['V_out']:.4g} V"
            text(x+270,yy,label,11,'#69cbdf' if dark else accent,anchor='e',hit=hit)
            tagged(c.create_oval(x+280,yy-8,x+296,yy+8,fill=accent,outline='white',width=2*z),('output',dict(kind=kind,id=n['id'],output=i)))
        if kind=='unit':
            if n['spec']['topology']=='LDO':
                if ui._review is None:ui._review=model_review(ui.project)
                r=next((r for r in ui._review.get('ldo',[]) if r['unit']==n['id']),None)
                if r:text(x+158,y+h-19,('Pd '+f"{r['max_loss']:.3g}"+'W' if r['max_loss'] is not None else '压差需核对'),11,MUTED_COLOR,hit=hit)
            rounded(x+14,y+h-31,126,23,'#eef4ff',hit=('open',n['id']),r=6)
            text(x+24,y+h-19,'进入单元设计  →',11,accent,bold=True,hit=('open',n['id']))
        else:text(x+18,y+h-18,'终端负载' if kind=='load' else '可向多个后级分配',11,'#91a6bc' if dark else '#94a2b5',hit=hit)
    for edge in ui.project['connections']:
        if edge['mode']!='diode':continue
        current_tag='diode:'+edge['id']
        p=diode_point(ui.project,edge);x,y=p['x'],p['y'];hit=('diode',edge['id'])
        ui._drawn_positions[current_tag]=dict(p)
        selected=ui.selected==('edge',edge['id'])
        rounded(x-44,y-21,88,50,'#e5ebf4',r=10)
        rounded(x-44,y-25,88,50,'white','#d29132' if selected else '#a9bcd6',2 if selected else 1,hit,r=10)
        text(x,y-14,edge['id'],8,'#7a8da5',anchor='center',hit=hit)
        tagged(c.create_polygon(x-23,y-5,x-10,y+2,x-23,y+9,fill='#eaf0ff',outline='#3f6bad',width=1.7*z),hit)
        tagged(c.create_line(x-8,y-7,x-8,y+11,fill='#3f6bad',width=1.7*z),hit)
        text(x+17,y+2,f"{edge['vf']:g} V",11,'#2d4562',anchor='center',bold=True,hit=hit)
        text(x,y+19,'OR-ING' if edge['enabled'] else '停用',8,'#96a4b7',anchor='center',hit=hit)
    if not ui.nodes:text(60,100,'从上方增加输入源、电源模块、汇流节点或负载',17)
    if z!=1:c.scale('all',0,0,z,z)
    a,b,right,bottom=scene_bounds(ui.project)
    c.configure(scrollregion=(0,0,max(right+70,ui.canvas.winfo_width()/z)*z,max(bottom+70,ui.canvas.winfo_height()/z)*z))


def update_drag(ui,key,kind):
    """Retain canvas objects. Only move the selected object and adjacent wires."""
    c,z=ui.canvas,ui.zoom
    def move(tag,p):
        old=ui._drawn_positions[tag]
        c.move(tag,(p['x']-old['x'])*z,(p['y']-old['y'])*z)
        ui._drawn_positions[tag]=dict(p)
    def wire(item,a,b):
        bend=max(20,abs(b[0]-a[0])*.48)
        c.coords(item,*[v*z for v in (a[0],a[1],a[0]+bend,a[1],b[0]-bend,b[1],b[0],b[1])])
    if kind=='node':
        move('node:'+key,ui.project['layout']['nodes'][key])
        edges=ui._incident_edges.get(key,[])
    else:edges=[next(e for e in ui.project['connections'] if e['id']==key)]
    for edge in edges:
        a,b=endpoints(ui.project,edge);items=ui._edge_items[edge['id']]
        if edge['mode']=='diode':
            p=diode_point(ui.project,edge);move('diode:'+edge['id'],p)
            wire(items[0],a,(p['x']-44,p['y']));wire(items[1],(p['x']+44,p['y']),b)
        else:wire(items[0],a,b)
