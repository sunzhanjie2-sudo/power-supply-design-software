"""Native lightweight Canvas diagram; no images, plot engine or polling loop."""
import tkinter as tk
from tkinter import ttk
from controller_logic import NODES, EDGES, HELP, SHORT_LABELS, display_value, state_note
from spice_export import SETTINGS
from scrollable_results import ScrollableResults


class ControllerLogicPanel(ttk.Frame):
    def __init__(self,parent,*,values,design):
        super().__init__(parent,padding=(12,0,0,0))
        self.values=values;self.design=design;self.active_key='qr_cds_pf' if design.get('topology')=='QR-FLYBACK' else 'frequency_hz';self._job=None;self._reveal=True
        from controller_logic import definition,qr_definition,acf_definition,nonisolated_definition
        self.definition=nonisolated_definition() if design.get('topology') in ('BUCK','BOOST') else qr_definition() if design.get('topology')=='QR-FLYBACK' else acf_definition() if design.get('topology')=='ACF-FORWARD' else definition()
        self.nodes=self.definition['nodes']
        self.help={k:(v['node'],v['purpose'],v['meaning']) for k,v in self.definition['parameters'].items()}
        self._timer_root=self._root()
        self.columnconfigure(0,weight=1);self.rowconfigure(4,weight=1)
        ttk.Label(self,text='控制器内部逻辑与参数去向',font=('',12,'bold')).grid(row=0,column=0,sticky='w',pady=(0,6))
        self.heading=ttk.Label(self,foreground='#135bb0',font=('',11,'bold'))
        self.heading.grid(row=1,column=0,sticky='ew',pady=(0,6))
        self.description=ttk.Label(self,justify='left',wraplength=600)
        self.description.grid(row=2,column=0,sticky='ew')
        self.condition=ttk.Label(self,foreground='#9a5b00',justify='left',wraplength=600)
        self.condition.grid(row=3,column=0,sticky='ew',pady=(4,8))
        self.view=ScrollableResults(self,background='#f4f8ff');self.view.grid(row=4,column=0,sticky='nsew')
        self.canvas=tk.Canvas(self.view.content,background='#f4f8ff',highlightthickness=0,width=660,height=1030)
        self.canvas.pack(fill='x',expand=True)
        ttk.Label(self,text='点选框图模块查看说明；蓝色表示当前参数所在模块。\n框图随当前拓扑切换；外部补偿、寄生与试验单独分区。',wraplength=600,justify='left',foreground='#52647a').grid(row=5,column=0,sticky='ew',pady=(8,0))
        self.canvas.bind('<Configure>',self._schedule)
        self.view.canvas.bind('<Configure>',self._schedule,add='+')
        self.bind('<Configure>',self._wrap)
        self.bind('<Destroy>',self._destroy,add='+')
        self._schedule()

    def _wrap(self,event):
        if event.widget is self:
            for label in (self.heading,self.description,self.condition,*self.grid_slaves(row=5,column=0)):
                label.configure(wraplength=max(180,event.width-20))

    def select(self,key):
        if key in self.help:self.active_key=key;self._reveal=True
        self._schedule()

    def refresh(self):self._schedule()

    def _schedule(self,_event=None):
        if _event is not None and _event.widget is self.view.canvas:self._reveal=True
        if self._job is not None:self._timer_root.after_cancel(self._job)
        self._job=self._timer_root.after(80,self._draw)

    def _destroy(self,event):
        if event.widget is self and self._job is not None:
            self._timer_root.after_cancel(self._job);self._job=None

    def _draw(self):
        self._job=None
        values=self.values();key=self.active_key;node,purpose,meaning=self.help[key]
        self.heading.configure(text=SETTINGS[key][3]+'  ·  '+display_value(key,values,self.design))
        self.description.configure(text=purpose+'\n'+meaning)
        self.condition.configure(text=state_note(key,values))
        c=self.canvas;width=max(320,self.view.canvas.winfo_width());scale=width/720
        c.configure(width=width,height=round(1100*scale));c.delete('all')
        def rect(x,y,w,h,**kw):return c.create_rectangle(x*scale,y*scale,(x+w)*scale,(y+h)*scale,**kw)
        def text(x,y,body,*,size=15,bold=False,w=0,color='#23364d',anchor='nw'):
            return c.create_text(x*scale,y*scale,text=body,anchor=anchor,fill=color,
                font=('Microsoft YaHei UI',-max(11,round(size*scale)),'bold' if bold else 'normal'),width=w*scale)
        rect(32,164,656,628,fill='#eaf2fd',outline='#9db8da',dash=(5,3),width=1)
        text(48,174,'芯片内部控制逻辑 · 通用可配置等效',size=16,bold=True,color='#315b8a')
        for points in EDGES:
            c.create_line(*(v*scale for p in points for v in p),arrow='last',arrowshape=(7,9,4),fill='#6a85a6',width=1.6)
        for row in self.nodes:
            selected=node==row['id'];external=row['scope']!='chip'
            box=rect(row['x'],row['y'],row['w'],row['h'],fill='#dbeafe' if selected else '#fff8ec' if external else '#ffffff',
                outline='#1763bb' if selected else '#dbbb81' if external else '#b7c9df',width=2 if selected else 1)
            title=text(row['x']+12,row['y']+10,row['title'],size=17,bold=True,w=row['w']-24,color='#164f96' if selected else '#23364d')
            body=text(row['x']+12,row['y']+39,'\n'.join(row['body']),size=14,w=row['w']-24)
            summary='  /  '.join(SHORT_LABELS.get(k,k)+' '+display_value(k,values,self.design,compact=True) for k in row['values'])
            value=text(row['x']+12,row['y']+row['h']-29,summary,size=14,w=row['w']-24,color='#1763bb')
            parameter=next((k for k,v in self.help.items() if v[0]==row['id']),self.active_key)
            for item in (box,title,body,value):
                c.tag_bind(item,'<Button-1>',lambda _e,k=parameter:self.select(k))
        self.view.sync()
        if self._reveal:
            target=next(row for row in self.nodes if row['id']==node)
            self.view.canvas.yview_moveto(max(0,(target['y']-60)/1100))
            self._reveal=False
