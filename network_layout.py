"""Presentation geometry shared by the native editor and network reports."""
WIDTH = 288
DIODE_HALF_WIDTH = 44


def endpoints(project, edge):
    points=project['layout']['nodes']
    source=edge['source']
    a=points[source['kind']+':'+source['id']]
    target=next((kind,n) for kind,key in {'bus':'sources','unit':'units','junction':'junctions','load':'loads'}.items()
                for n in project.get(key,[]) if n['id']==edge['target'])
    b=points[target[0]+':'+target[1]['id']]
    return (a['x']+WIDTH,a['y']+(102 if source['kind']=='bus' else 119+26*(source['output']-1))), (b['x'],b['y']+94)


def diode_point(project, edge):
    saved=project.get('layout',{}).get('diodes',{}).get(edge['id'])
    if saved is not None:return dict(saved)
    a,b=endpoints(project,edge)
    return dict(x=(a[0]+b[0])/2,y=(a[1]+b[1])/2)


def scene_bounds(project):
    points=project.get('layout',{}).get('nodes',{})
    rects=[]
    for kind,key in {'bus':'sources','unit':'units','junction':'junctions','load':'loads'}.items():
        for n in project.get(key,[]):
            p=points.get(kind+':'+n['id'])
            if p:
                h=158+26*max(0,len(n.get('rails',[]))-1)
                rects.append((p['x'],p['y'],p['x']+WIDTH,p['y']+h))
    for e in project.get('connections',[]):
        if e['mode']=='diode':
            p=diode_point(project,e);rects.append((p['x']-44,p['y']-25,p['x']+44,p['y']+25))
    return (min([r[0] for r in rects]+[24]),min([r[1] for r in rects]+[24]),
            max([r[2] for r in rects]+[600]),max([r[3] for r in rects]+[380]))
