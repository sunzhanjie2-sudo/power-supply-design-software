"""Local Matplotlib wire editor. Motion blits one artist; commits happen on release."""
import math
import numpy as np
from matplotlib.patches import Ellipse,Rectangle


class WindingDragController:
    def __init__(self,canvas,axis,commit,note,step,undo):
        self.canvas=canvas;self.axis=axis;self.commit=commit;self.note=note;self.step=step;self.undo=undo
        self.selected=None;self.points={};self.artists={};self.assessment=None
        self._drag=None;self._background=None;self._patch=None;self._original=None;self._x=None
        self._connections=[canvas.mpl_connect(name,handler) for name,handler in (
            ('button_press_event',self.press),('motion_notify_event',self.motion),
            ('button_release_event',self.release),('key_press_event',self.key))]

    def scene(self,assessment,artists):
        self._drag=self._background=self._patch=self._original=None
        self.assessment=assessment
        self.points={s['id']:s for s in assessment.get('cross_sections',[])} if assessment else {}
        self.artists=artists or {}
        if self.selected not in self.points:self.selected=None
        self._x=None
        if self.selected in self.artists:
            collection,index=self.artists[self.selected]
            colors=collection.get_edgecolors().copy()
            colors[index]=(.88,.42,.04,1.)
            collection.set_edgecolors(colors)
            widths=np.full(len(collection.get_paths()),1.1);widths[index]=2.3
            collection.set_linewidths(widths)
        self._describe()

    def _describe(self):
        p=self.points.get(self.selected)
        if not p:
            self.note.set('点选一匝线并左右拖动；画布获得焦点后用 ← / → 微调，Shift ×10，Alt ÷10；Ctrl+Z 撤销位置。')
            return
        x=self._x if self._x is not None else p['x']+p['width']/2
        self.note.set(f"已选 {p['section_id']} · 第 {p['turn']} 匝 · 并绕束 {p['bundle']}"
                      f"　中心 X={x*1e3:.5g} mm；Y={(p['y']+p['height']/2)*1e3:.5g} mm。")

    def press(self,event):
        if event.button!=1 or event.inaxes is not self.axis or event.xdata is None or event.ydata is None:return
        x,y=event.xdata/1e3,event.ydata/1e3
        def contains(p):
            if p.get('profile_type')=='rectangle':
                return p['x']<=x<=p['x']+p['width'] and p['y']<=y<=p['y']+p['height']
            return ((x-p['x']-p['width']/2)/(p['width']/2))**2+((y-p['y']-p['height']/2)/(p['height']/2))**2<=1.1
        hits=[p for p in self.points.values() if contains(p)]
        if not hits:return
        self.cancel()
        p=min(hits,key=lambda p:abs(x-p['x']-p['width']/2))
        self.selected=p['id'];self._x=p['x']+p['width']/2
        self.canvas.get_tk_widget().focus_set()
        self._drag=(x,self._x)
        self._begin();self._paint()

    def _begin(self):
        if self._background is not None:return
        p=self.points.get(self.selected);artist=self.artists.get(self.selected)
        if not p or not artist:return
        collection,index=artist
        path=collection.get_paths()[index]
        original=path.vertices.copy();path.vertices[:,0]=np.nan
        self._original=(path,original)
        if getattr(self.canvas,'_can_render',lambda:True)():
            self.canvas.draw()
            self._background=self.canvas.copy_from_bbox(self.axis.bbox)
        style=dict(facecolor='#dceeff',edgecolor='#0758ac',lw=2.,animated=True,zorder=20)
        if p.get('profile_type')=='rectangle':
            self._patch=Rectangle((p['x']*1e3,p['y']*1e3),p['width']*1e3,p['height']*1e3,**style)
        else:
            self._patch=Ellipse(((p['x']+p['width']/2)*1e3,(p['y']+p['height']/2)*1e3),
                p['width']*1e3,p['height']*1e3,**style)
        self.axis.add_patch(self._patch)

    def _paint(self):
        self._describe()
        if self._patch is None:return
        if isinstance(self._patch,Rectangle):self._patch.set_x((self._x-self.points[self.selected]['width']/2)*1e3)
        else:self._patch.center=(self._x*1e3,self._patch.center[1])
        if self._background is not None:
            self.canvas.restore_region(self._background)
            self.axis.draw_artist(self._patch)
            self.canvas.blit(self.axis.bbox)

    def _bounded(self,value):
        p=self.points[self.selected];cfg=self.assessment['config']
        low=cfg['margin_x']+p['width']/2;high=cfg['window_width']-cfg['margin_x']-p['width']/2
        return max(low,min(high,value)) if high>=low else value

    def motion(self,event):
        if self._drag is None or event.xdata is None or event.inaxes is not self.axis:return
        self._x=self._bounded(self._drag[1]+event.xdata/1e3-self._drag[0])
        self._paint()

    def release(self,event):
        if self._drag is None:return
        original=self._drag[1];self._drag=None
        if abs(self._x-original)>1e-15:self.commit(self.points[self.selected],self._x)
        else:self.cancel()

    def key(self,event):
        key=event.key or ''
        if key in ('ctrl+z','control+z'):self.cancel();self.undo();return
        if key=='escape':self.cancel();return
        if key.split('+')[-1] not in ('left','right') or self.selected not in self.points:return
        try:
            delta=float(self.step.get())/1e3
            if not math.isfinite(delta) or delta<=0:raise ValueError()
        except (TypeError,ValueError):self.note.set('移动步长需为大于 0 的有限数值（mm）。');return
        if 'shift+' in key:delta*=10
        if 'alt+' in key:delta/=10
        p=self.points[self.selected]
        if self._x is None:self._x=p['x']+p['width']/2
        value=self._bounded(self._x+delta*(-1 if key.endswith('left') else 1))
        if value==self._x:return
        self._begin()
        self._x=value;self._paint();self.commit(p,value)

    def cancel(self):
        if self._original:
            path,vertices=self._original;path.vertices[:]=vertices
        if self._patch is not None:
            try:self._patch.remove()
            except ValueError:pass
        self._drag=self._background=self._patch=self._original=None
        self._x=None
        self._describe()
        self.canvas.request_draw()
