"""Tk architecture editor. No converter solve is run while dragging a node."""
import copy
import json
import multiprocessing
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from network_layout import diode_point, scene_bounds

import system_workspace as model
from config_io import decode_config

BG, INK, BLUE, MUTED = '#f2f5fa', '#172c46', '#226de0', '#6b7e94'
NAMES = {'FLYBACK': 'CCM 反激', 'QR-FLYBACK': '准谐振反激', 'BUCK': 'Buck 降压',
         'BOOST': 'Boost 升压', 'BUCK-BOOST': '反相升降压', 'ACF-FORWARD': '有源钳位正激'}


class SystemWorkspace:
    def __init__(self, root, *, recovery=True):
        self.root, self.use_recovery = root, recovery
        self.project = model.fresh_project()
        self.path, self.selected, self.link, self.drag, self.removal = None, None, None, None, None
        self.calculator = None
        self.report_process = None
        self.initialized = False
        self.zoom=1.0
        self._draw_job=None
        self._drag_dirty=False
        self._review=None
        self._edit_dirty=False
        self._commit_edit=None
        self._inspector_vars=[]
        self._panning=False
        self._toolbar_layout_job=None
        root.title('开关电源系统设计 · 自由画布工作区')
        root.geometry(f'{min(1560, root.winfo_screenwidth()-50)}x{min(960, root.winfo_screenheight()-90)}')
        root.minsize(1080, 700)
        root.configure(bg=BG)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('System.TFrame', background=BG)
        style.configure('System.TLabel', background=BG, foreground=INK, font=('Microsoft YaHei UI', -14))
        style.configure('System.TButton', padding=(13, 8), font=('Microsoft YaHei UI', -13),background='white',foreground=INK,bordercolor='#dce5f0',lightcolor='white',darkcolor='#dce5f0',relief='flat')
        style.map('System.TButton',background=[('active','#eaf1fc')])
        style.configure('SystemToolbar.TButton', padding=(18,12), font=('Microsoft YaHei UI',-14), background='white',foreground=INK,bordercolor='#dce5f0',lightcolor='white',darkcolor='#dce5f0',relief='flat')
        style.map('SystemToolbar.TButton',background=[('active','#eaf1fc')])
        style.configure('SystemPrimary.TButton',padding=(14,8),font=('Microsoft YaHei UI',-13,'bold'),background=BLUE,foreground='white',bordercolor=BLUE)
        style.map('SystemPrimary.TButton',background=[('active','#185bc3')])
        style.configure('SystemCard.TFrame',background='white')
        style.configure('System.TEntry',padding=7,fieldbackground='white',bordercolor='#d8e3ef',font=('Microsoft YaHei UI',-14))
        style.configure('SystemMini.TButton',padding=(9,5),font=('Microsoft YaHei UI',-12),background='white',foreground=INK,bordercolor='#dce5f0')
        style.configure('System.TCheckbutton',background='white',foreground=INK,font=('Microsoft YaHei UI',-13))
        style.configure('System.TCombobox',padding=7,fieldbackground='white',bordercolor='#d8e3ef')
        head = tk.Frame(root, bg='#10243b', padx=24, pady=15)
        head.pack(fill='x')
        brand=tk.Frame(head,bg='#10243b');brand.pack(side='left')
        tk.Label(brand,text='POWER DESIGN  /  SYSTEM STUDIO',bg='#10243b',fg='#67bdcf',font=('Segoe UI',-10,'bold')).pack(anchor='w')
        tk.Label(brand, text='辅源架构设计工作区', bg='#10243b', fg='white', font=('Microsoft YaHei UI', -26, 'bold')).pack(anchor='w')
        tk.Label(head, text='01  架构配置     02  单元设计     03  工程交付', bg='#10243b', fg='#a9c2da', font=('Microsoft YaHei UI', -13)).pack(side='right')
        bar = ttk.Frame(root, style='System.TFrame', padding=(18, 12))
        bar.pack(fill='x')
        filebar=ttk.Frame(bar,style='System.TFrame');filebar.grid(row=0,column=0,sticky='w')
        for i,(text, command) in enumerate([('新建工程', self.new), ('打开工程 / 原配置', self.open_file), ('保存系统工程', self.save)]):
            filebar.columnconfigure(i,weight=1,uniform='project-actions')
            ttk.Button(filebar, text=text, command=command, style='SystemToolbar.TButton').grid(row=0,column=i,sticky='ew',padx=(0,10))
        self.metrics=tk.StringVar(value='本机工作区 · 架构编辑不触发电气求解')
        utilities=ttk.Frame(bar,style='System.TFrame');utilities.grid(row=0,column=1,sticky='e')
        ttk.Label(utilities, textvariable=self.metrics, style='System.TLabel').pack(anchor='e')
        from ui_preferences import font_control
        self._font_choice=font_control(utilities,self.choose_font)
        self._projectbar=bar;self._project_filebar=filebar;self._project_utilities=utilities;self._project_toolbar_rows=None
        bar.columnconfigure(0,weight=1);bar.bind('<Configure>',self.layout_project_toolbar)
        nodebar = ttk.Frame(root, style='System.TFrame', padding=(18, 0, 18, 12))
        nodebar.pack(fill='x')
        self._nodebar=nodebar;self._node_buttons=[];self._node_columns=0
        for text, command in [('增加输入源', self.add_bus), ('增加电源模块', self.add_unit),
                              ('增加 LDO',self.add_ldo),
                              ('增加 OR 汇流', lambda:self.add_node('junction')), ('增加负载', lambda:self.add_node('load')),
                              ('自动排列', self.arrange), ('撤销删除', self.undo)]:
            self._node_buttons.append(ttk.Button(nodebar, text=text, command=command, style='SystemToolbar.TButton'))
        nodebar.bind('<Configure>',self.layout_node_toolbar)
        self.layout_node_toolbar()
        self.title = tk.StringVar(value=self.project['title'])
        titlebar = ttk.Frame(root, style='System.TFrame', padding=(24, 0, 24, 10))
        titlebar.pack(fill='x')
        ttk.Label(titlebar, text='工程名称', style='System.TLabel').pack(side='left')
        entry = ttk.Entry(titlebar, textvariable=self.title, width=37,style='System.TEntry', font=('Microsoft YaHei UI', -14))
        entry.pack(side='left', padx=10)
        entry.bind('<FocusOut>', lambda e: self.rename_project())
        entry.bind('<Return>', lambda e: self.rename_project())
        self.report_button = ttk.Button(titlebar, text='生成系统报告包', command=self.export_report, style='SystemPrimary.TButton')
        self.report_button.pack(side='right', padx=8)
        ttk.Button(titlebar,text='查看系统预算',command=self.show_checks,style='System.TButton').pack(side='right',padx=8)
        split = ttk.Panedwindow(root, orient='horizontal')
        split.pack(fill='both', expand=True, padx=22)
        board = ttk.Frame(split,style='SystemCard.TFrame')
        split.add(board, weight=4)
        tools=tk.Frame(board,bg='white',padx=12,pady=10);tools.grid(row=0,column=0,columnspan=2,sticky='ew')
        tk.Label(tools,text='供电网络画布',bg='white',fg=INK,font=('Microsoft YaHei UI',-15,'bold')).pack(side='left')
        for text,command in [('适应画布',self.fit_canvas),('＋',lambda:self.set_zoom(self.zoom*1.2)),('－',lambda:self.set_zoom(self.zoom/1.2))]:
            ttk.Button(tools,text=text,command=command,style='SystemMini.TButton').pack(side='right',padx=3)
        self.zoom_text=tk.StringVar(value='100%')
        tk.Label(tools,textvariable=self.zoom_text,bg='white',fg=MUTED,font=('Segoe UI',-13)).pack(side='right',padx=10)
        self.canvas = tk.Canvas(board, bg='#f9fbfe', highlightthickness=1, highlightbackground='#dce5ef')
        sx = ttk.Scrollbar(board, orient='horizontal', command=self.canvas.xview)
        sy = ttk.Scrollbar(board, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
        self.canvas.grid(row=1, column=0, sticky='nsew')
        sy.grid(row=1, column=1, sticky='ns')
        sx.grid(row=2, column=0, sticky='ew')
        board.rowconfigure(1, weight=1)
        board.columnconfigure(0, weight=1)
        side = ttk.Frame(split, width=340,style='SystemCard.TFrame')
        split.add(side, weight=1)
        tk.Label(side,text='属性检查器',bg='white',fg=INK,font=('Microsoft YaHei UI',-16,'bold'),anchor='w',padx=18,pady=15).pack(fill='x')
        footer=ttk.Frame(side,style='SystemCard.TFrame',padding=12);footer.pack(side='bottom',fill='x')
        self.edit_state=tk.StringVar(value='选择节点或支路后编辑')
        self.inspector_save=ttk.Button(footer,text='保存节点修改',style='SystemPrimary.TButton',command=self.save_inspector,state='disabled')
        self.inspector_save.pack(fill='x')
        ttk.Label(footer,textvariable=self.edit_state,wraplength=290,font=('Microsoft YaHei UI',-12),background='white',foreground=MUTED).pack(fill='x',pady=(8,0))
        scroll = tk.Canvas(side, highlightthickness=0, bg='white', width=320)
        self.inspector_scroll=scroll
        vs = ttk.Scrollbar(side, orient='vertical', command=scroll.yview)
        scroll.configure(yscrollcommand=vs.set)
        vs.pack(side='right', fill='y')
        scroll.pack(side='left', fill='both', expand=True)
        self.inspector = ttk.Frame(scroll, padding=18,style='SystemCard.TFrame')
        inner = scroll.create_window((0, 0), window=self.inspector, anchor='nw')
        self.inspector.bind('<Configure>', lambda e: scroll.configure(scrollregion=scroll.bbox('all')))
        scroll.bind('<Configure>', lambda e: scroll.itemconfigure(inner, width=e.width))
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.motion)
        self.canvas.bind('<ButtonRelease-1>', self.release)
        self.canvas.bind('<Double-1>', self.double)
        self.canvas.bind('<Delete>', lambda e: self.delete_selected())
        self.canvas.bind('<Escape>', lambda e: self.cancel_link())
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.canvas.bind('<ButtonPress-2>',self.pan_start)
        self.canvas.bind('<B2-Motion>',self.pan_motion)
        self.canvas.bind('<ButtonRelease-2>',self.end_pan)
        self.canvas.bind('<Motion>',self.hover)
        self.status = tk.StringVar(value='正在准备架构…')
        ttk.Label(root, textvariable=self.status, style='System.TLabel', padding=(24, 9)).pack(fill='x')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<Control-Return>',lambda e:self.save_inspector())
        root.bind('<Destroy>',self.cancel_toolbar_layout,add='+')
        root.after(30, self.initialize)

    def initialize(self):
        if self.initialized:
            return
        self.initialized = True
        try:
            if self.use_recovery and model.recovery_path().is_file():
                self.project = model.load_project(model.recovery_path())
                self.status.set('已恢复上次系统工程。保存系统工程可生成独立 JSON 文件。')
            else:
                self.project = model.normalize_project(self.project)
                self.status.set('先配置供电架构，再双击主电源进入完整计算。')
        except Exception as error:
            self.project = model.normalize_project(model.fresh_project())
            self.status.set('上次工程未能恢复，已显示默认示例：' + str(error))
        self.title.set(self.project['title'])
        self.render()
        self.root.after_idle(self.fit_canvas)

    def changed(self, note='架构已更新；各模块计算参数独立保存。'):
        if self.use_recovery:
            try:
                model.save_project(self.project, model.recovery_path())
            except Exception as error:
                self.status.set('自动恢复文件写入失败，请手动保存：' + str(error))
                return
        self.status.set(note)

    def rename_project(self):
        if self.title.get().strip():
            self.project['title'] = self.title.get().strip()[:120]
            self.changed()

    def render(self):
        self._review=None
        positions = self.project.setdefault('layout', {}).setdefault('nodes', {})
        if not positions:
            model.auto_layout(self.project)
            positions = self.project['layout']['nodes']
        self.nodes = {}
        for kind, collection in model.COLLECTIONS.items():
            for i, item in enumerate(self.project[collection]):
                key = kind + ':' + item['id']
                if key not in positions:
                    point=dict(x={'bus':40,'unit':425,'junction':810,'load':1195}[kind],y=50+i*240)
                    while any(abs(p['x']-point['x'])<320 and abs(p['y']-point['y'])<210 for p in positions.values()):
                        point['y']+=240
                    positions[key]=point
                self.nodes[key] = (kind, item, positions[key])
        self.metrics.set(f"{len(self.project['sources'])} 个输入源   /   {len(self.project['units'])} 个模块   /   {len(self.project['loads'])} 个负载")
        self.draw()
        self.show_inspector()

    def draw(self):
        from system_canvas import draw_network
        draw_network(self)

    def choose_font(self,value):
        from ui_preferences import save_font_size,apply_studio_fonts
        value=save_font_size(value);self._font_choice.set(str(value));apply_studio_fonts(self.root,value)
        if self._toolbar_layout_job:self.root.after_cancel(self._toolbar_layout_job)
        def layout():
            self._toolbar_layout_job=None
            self.layout_node_toolbar();self.layout_project_toolbar()
        self._toolbar_layout_job=self.root.after_idle(layout)
        self.status.set(f'界面字号已设为 {value}px，下次启动保留；图内文字可用画布缩放调整。')

    def layout_node_toolbar(self,event=None):
        minimum=max(140,max(b.winfo_reqwidth() for b in self._node_buttons))
        columns=next((n for n in (7,5,3,2) if self._nodebar.winfo_width()>=n*(minimum+10)+36),1)
        if columns==self._node_columns:return
        self._node_columns=columns
        for column in range(7):self._nodebar.columnconfigure(column,weight=1 if column<columns else 0,minsize=0,uniform='node-actions' if column<columns else '')
        for i,button in enumerate(self._node_buttons):button.grid(row=i//columns,column=i%columns,sticky='ew',padx=5,pady=5)

    def layout_project_toolbar(self,event=None):
        width=self._projectbar.winfo_width()
        if width<100:return
        split=self._project_filebar.winfo_reqwidth()+self._project_utilities.winfo_reqwidth()+50>width
        if split==self._project_toolbar_rows:return
        self._project_toolbar_rows=split
        self._project_filebar.grid(columnspan=2 if split else 1,sticky='ew' if split else 'w')
        self._project_utilities.grid(row=1 if split else 0,column=0 if split else 1,columnspan=2 if split else 1,sticky='e',pady=(8,0) if split else 0)

    def cancel_toolbar_layout(self,event):
        if event.widget is self.root and self._toolbar_layout_job:
            self.root.after_cancel(self._toolbar_layout_job);self._toolbar_layout_job=None

    def mark_edit_dirty(self,*_):
        self._edit_dirty=True
        self.inspector_save.configure(state='normal')
        self.edit_state.set('有未保存修改 · 点击上方按钮或按 Ctrl+Enter')

    def save_inspector(self):
        if not self._edit_dirty or self._commit_edit is None:return True
        return self._commit_edit() is not False

    def request_draw(self):
        if self._draw_job is None:
            self._draw_job=self.root.after(16,self.flush_draw)

    def flush_draw(self):
        if self._draw_job is not None:
            try:self.root.after_cancel(self._draw_job)
            except tk.TclError:pass
        self._draw_job=None
        if self._drag_dirty and self.drag:
            from system_canvas import update_drag
            update_drag(self,self.drag['key'],self.drag['kind']);self._drag_dirty=False
        else:self.draw()

    def world_point(self,e):
        return self.canvas.canvasx(e.x)/self.zoom,self.canvas.canvasy(e.y)/self.zoom

    def set_zoom(self,value,anchor=None):
        x,y=anchor or (self.canvas.winfo_width()/2,self.canvas.winfo_height()/2)
        wx,wy=self.canvas.canvasx(x)/self.zoom,self.canvas.canvasy(y)/self.zoom
        self.zoom=max(.35,min(2.2,value));self.zoom_text.set(f'{self.zoom:.0%}')
        self.draw()
        region=self.canvas.bbox('all')
        scroll=self.canvas.cget('scrollregion').split()
        if region and len(scroll)==4:
            self.canvas.xview_moveto(max(0,(wx*self.zoom-x)/float(scroll[2])))
            self.canvas.yview_moveto(max(0,(wy*self.zoom-y)/float(scroll[3])))
        self.draw()

    def fit_canvas(self):
        if not self.initialized:return
        self.canvas.update_idletasks()
        left,top,right,bottom=scene_bounds(self.project)
        z=min((self.canvas.winfo_width()-60)/max(1,right-left+70),(self.canvas.winfo_height()-60)/max(1,bottom-top+70),1.25)
        self.zoom=max(.35,z);self.zoom_text.set(f'{self.zoom:.0%}');self.draw()
        scroll=self.canvas.cget('scrollregion').split()
        self.canvas.xview_moveto(max(0,(left-35)*self.zoom/float(scroll[2])))
        self.canvas.yview_moveto(max(0,(top-35)*self.zoom/float(scroll[3])))
        self.draw()

    def wheel(self,e):
        if e.state & 4:self.set_zoom(self.zoom*(1.12 if e.delta>0 else 1/1.12),(e.x,e.y))
        else:
            (self.canvas.xview_scroll if e.state&1 else self.canvas.yview_scroll)(-int(e.delta/120),'units')
            self.request_draw()
        return 'break'

    def pan_start(self,e):
        self._panning=True;self.canvas.scan_mark(e.x,e.y)

    def pan_motion(self,e):
        if self._panning:self.canvas.scan_dragto(e.x,e.y,gain=1)

    def end_pan(self,e=None):
        self._panning=False;self.draw()

    def hover(self,e):
        if self.drag or self._panning:return
        hit=self.hit(e)
        kind=hit[0] if hit else ''
        self.canvas.configure(cursor='crosshair' if kind in ('input','output') else 'hand2' if kind in ('open','delete') else 'fleur' if kind in (*model.COLLECTIONS,'diode') else 'arrow')

    def hit(self, e):
        x, y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        items = self.canvas.find_overlapping(x - 5, y - 5, x + 5, y + 5)
        return next((self.hits[i] for i in reversed(items) if i in self.hits), None)

    def press(self, e):
        self.canvas.focus_set()
        self.drag=None
        hit = self.hit(e)
        if self._edit_dirty:
            if not self.save_inspector():return
        if not hit:
            self.selected = None
            self.pan_start(e)
            self.draw();self.show_inspector()
            return
        kind, identity = hit
        if kind == 'delete':
            self.selected = tuple(identity.split(':', 1))
            self.delete_selected()
        elif kind == 'open':
            self.open_unit(identity)
        elif kind == 'output':
            self.link = identity
            self.status.set('点击或拖到目标模块的 IN 端口；Esc 取消连线。')
        elif kind == 'input':
            if self.link:
                self.finish_link(identity)
        elif kind=='diode':
            self.selected=('edge',identity)
            edge=next(v for v in self.project['connections'] if v['id']==identity)
            p=diode_point(self.project,edge);x,y=self.world_point(e)
            self.drag=dict(key=identity,kind='diode',x=x,y=y,original=p,moved=False)
            self.draw();self.show_inspector()
        else:
            self.selected = hit
            if kind in model.COLLECTIONS:
                p = self.project['layout']['nodes'][kind + ':' + identity]
                x,y=self.world_point(e)
                self.drag = dict(key=kind + ':' + identity,kind='node', x=x,y=y, original=dict(p), moved=False)
            self.draw()
            self.show_inspector()

    def motion(self, e):
        x, y = self.world_point(e)
        if self.drag:
            d = self.drag
            p = self.project['layout'].setdefault('diodes',{}).setdefault(d['key'],dict(d['original'])) if d['kind']=='diode' else self.project['layout']['nodes'][d['key']]
            p.update(x=max(48 if d['kind']=='diode' else 24, min(10000, d['original']['x'] + x - d['x'])), y=max(32 if d['kind']=='diode' else 24, min(10000, d['original']['y'] + y - d['y'])))
            d['moved'] = True
            self._drag_dirty=True
            self.request_draw()
        elif self.link:
            self.canvas.delete('pending')
            source = self.nodes[self.link['kind'] + ':' + self.link['id']][2]
            yy = source['y'] + (102 if self.link['kind'] == 'bus' else 119 + 26 * (self.link['output'] - 1))
            self.canvas.create_line((source['x']+288)*self.zoom, yy*self.zoom, x*self.zoom, y*self.zoom, width=2, dash=(6, 3), fill=BLUE, tags='pending')
        elif self._panning:self.pan_motion(e)

    def release(self, e):
        was_panning=self._panning
        if self.drag and self.drag['moved']:
            self.flush_draw()
            self.draw() # Update viewport bounds once, after the gesture.
            self.changed('二极管位置已保存，连线随位置更新。' if self.drag['kind']=='diode' else '节点位置已保存。拖动不触发电源计算。')
        self.drag = None
        self._panning=False
        if was_panning:self.draw()
        hit = self.hit(e)
        if self.link and hit and hit[0] == 'input':
            self.finish_link(hit[1])

    def double(self, e):
        hit = self.hit(e)
        if hit and hit[0] == 'unit':
            self.drag = None
            self.open_unit(hit[1])
        else:
            # Tk replaces the single-press binding on the second click. Keep
            # non-calculator objects draggable even after a rapid double-click.
            self.press(e)

    def finish_link(self, target):
        try:
            model.connect(self.project, target, self.link)
            self.changed('已新增供电关系，原连接保留。多源接入已按二极管 OR 配置；点连线编辑 Vf。')
        except Exception as error:
            self.status.set(str(error))
        self.link = None
        self.render()

    def cancel_link(self):
        self.link = None
        self.canvas.delete('pending')
        self.status.set('连线已取消。')

    def show_inspector(self):
        self._edit_dirty=False;self._commit_edit=None;self._inspector_vars=[]
        self.inspector_save.configure(state='disabled',text='保存支路修改' if self.selected and self.selected[0]=='edge' else '保存节点修改')
        self.edit_state.set('已保存到当前工程；顶部“保存系统工程”导出 JSON。' if self.selected else '选择节点或支路后编辑')
        for w in self.inspector.winfo_children():
            w.destroy()
        def label(text):
            tk.Label(self.inspector, text=text, bg='white',fg=INK,wraplength=280,justify='left', font=('Microsoft YaHei UI', -13)).pack(anchor='w', pady=(0, 10))
        self.inspector_scroll.yview_moveto(0)
        if not self.selected:
            label('选择对象，编辑设计属性')
            label('输入源、电源模块、OR 汇流节点、负载均可从卡片标题或空白区域拖动。')
            label('竞争二极管也可独立拖动。连线自动跟随，位置随工程保存。')
            label('从输出端口拖到输入端口建立供电关系；双击电源模块进入详细计算。')
        if self.selected:
            kind, identity = self.selected
            if kind == 'edge':
                edge = next(e for e in self.project['connections'] if e['id']==identity)
                label(identity + ' · 供电支路')
                if edge['mode']=='diode':label('抓住画布中的二极管卡片，可自由调整位置。')
                label(f"{edge['source']['id']} / OUT{edge['source']['output']} → {edge['target']}")
                mode=tk.StringVar(value='二极管隔离 / OR' if edge['mode']=='diode' else '直连')
                vf=tk.StringVar(value=str(edge['vf']))
                enabled=tk.BooleanVar(value=edge['enabled'])
                ttk.Combobox(self.inspector,textvariable=mode,values=['直连','二极管隔离 / OR'],state='readonly').pack(fill='x',pady=8)
                label('二极管压降 Vf / V')
                ttk.Entry(self.inspector,textvariable=vf).pack(fill='x',pady=6)
                ttk.Checkbutton(self.inspector,text='启用此供电支路',variable=enabled).pack(anchor='w',pady=8)
                def apply_edge():
                    try:
                        candidate=copy.deepcopy(self.project)
                        item=next(e for e in candidate['connections'] if e['id']==identity)
                        item.update(mode='diode' if mode.get()!='直连' else 'direct',vf=float(vf.get()),enabled=enabled.get())
                        self.project=model.normalize_project(candidate)
                        self.changed('支路设置已更新。多源竞争不假定均流。')
                        self.render()
                        return True
                    except Exception as error:
                        messagebox.showerror('供电支路',str(error),parent=self.root)
                        return False
                self._commit_edit=apply_edge;self._inspector_vars=[mode,vf,enabled]
                if edge['mode']=='diode':
                    def reset_diode():
                        self.project['layout'].setdefault('diodes',{}).pop(identity,None)
                        self.changed('二极管已恢复自动布置。');self.render()
                    ttk.Button(self.inspector,text='重置二极管位置',command=reset_diode).pack(fill='x',pady=6)
                ttk.Button(self.inspector, text='断开连接', command=lambda: self.disconnect(identity)).pack(fill='x')
            else:
                item = next((n for n in self.project[model.COLLECTIONS[kind]] if n['id'] == identity), None)
                if item:
                    label(identity + ' · 节点配置')
                    fields = [('name', '名称')] + ([('min', '最小电压 / V'), ('max', '最大电压 / V'), ('capacity', '输入容量 / W')] if kind == 'bus' else [])
                    if kind=='load':
                        fields += [('power','负载功耗 / W'),('min','允许输入下限 / V（0=不限）'),('max','允许输入上限 / V（0=不限）')]
                    elif kind=='junction':
                        fields += [('capacity','OR 母线容量 / W')]
                    variables = {}
                    for key, text in fields:
                        label(text)
                        v = tk.StringVar(value=str(item[key]))
                        ttk.Entry(self.inspector, textvariable=v,style='System.TEntry', font=('Microsoft YaHei UI', -14)).pack(fill='x', pady=(0, 10))
                        variables[key] = v
                    enabled=tk.BooleanVar(value=item['enabled'])
                    ttk.Checkbutton(self.inspector,text='启用节点（取消可模拟掉电）',variable=enabled).pack(anchor='w',pady=8)
                    def apply():
                        try:
                            candidate = copy.deepcopy(self.project)
                            obj = next(n for n in candidate[model.COLLECTIONS[kind]] if n['id'] == identity)
                            obj.update({k: v.get() if k == 'name' else float(v.get()) for k, v in variables.items()})
                            obj['enabled']=enabled.get()
                            self.project = model.normalize_project(candidate)
                            self.changed()
                            self.render()
                            return True
                        except Exception as error:
                            messagebox.showerror('节点配置', str(error), parent=self.root)
                            return False
                    self._commit_edit=apply;self._inspector_vars=[*variables.values(),enabled]
                    if kind != 'bus':
                        label('新增供电关系（保留现有支路）')
                        values, sources = ['选择上游输出…'], [None]
                        for bus in self.project['sources']:
                            values.append(bus['id'] + ' · DC')
                            sources.append(dict(kind='bus', id=bus['id'], output=1))
                        for unit in self.project['units']:
                            if unit['id'] == identity:
                                continue
                            for i, rail in enumerate(unit['rails'], 1):
                                values.append(f"{unit['id']} · OUT{i} · {rail['V_out']:.4g}V")
                                sources.append(dict(kind='unit', id=unit['id'], output=i))
                        for junction in self.project['junctions']:
                            if junction['id']!=identity:
                                values.append(junction['id']+' · OR BUS')
                                sources.append(dict(kind='junction',id=junction['id'],output=1))
                        box = ttk.Combobox(self.inspector, values=values, state='readonly', width=27)
                        box.current(0)
                        box.pack(fill='x', pady=(0, 10))
                        box.bind('<<ComboboxSelected>>', lambda e: self.choose_source(identity, sources[box.current()]) if box.current()>0 else None)
                        for edge in model.incoming(self.project,identity):
                            text=f"{edge['source']['id']} · "+(f"D {edge['vf']:g}V" if edge['mode']=='diode' else '直连')+(' [停用]' if not edge['enabled'] else '')
                            def edit_branch(eid=edge['id']):
                                self.selected=('edge',eid)
                                self.render()
                            ttk.Button(self.inspector,text=text+' · 编辑',command=edit_branch).pack(fill='x',pady=4)
                    if kind == 'unit':
                        ttk.Button(self.inspector, text='沿用上游电压', command=lambda: self.sync(identity)).pack(fill='x', pady=6)
                        ttk.Button(self.inspector, text='进入完整设计 →', command=lambda: self.open_unit(identity)).pack(fill='x', pady=6)
                    ttk.Button(self.inspector, text='删除节点', command=self.delete_selected).pack(fill='x', pady=6)
        ttk.Separator(self.inspector).pack(fill='x',pady=15)
        try:
            if self._review is None:self._review=model.checks(self.project)
            check = self._review
            issues=sum(not r['ok'] for r in check['capacity'])+sum(not r['ok'] or bool(r['unavailable']) for r in check['interfaces'])
            label(('⚠ '+str(issues)+' 项需核对' if issues else '✓ 当前预算与接口未发现超限')+'\n'+str(len(self.project['connections']))+' 条供电连接')
        except Exception as error:
            label('检查未完成：' + str(error))
        ttk.Button(self.inspector,text='查看完整系统检查',command=self.show_checks,style='System.TButton').pack(fill='x',pady=6)
        for widget in self.inspector.winfo_children():
            if isinstance(widget,ttk.Button):widget.configure(style='System.TButton')
            elif isinstance(widget,ttk.Combobox):widget.configure(style='System.TCombobox',font=('Microsoft YaHei UI',-14))
            elif isinstance(widget,ttk.Entry):widget.configure(style='System.TEntry',font=('Microsoft YaHei UI',-14))
            elif isinstance(widget,ttk.Checkbutton):widget.configure(style='System.TCheckbutton')
        for variable in self._inspector_vars:variable.trace_add('write',self.mark_edit_dirty)
        from ui_preferences import apply_studio_fonts,font_size
        self._font_choice.set(str(font_size()))
        apply_studio_fonts(self.root,font_size())

    def show_checks(self):
        try:check=model.checks(self.project)
        except Exception as error:
            messagebox.showerror('系统检查',str(error),parent=self.root);return
        window=tk.Toplevel(self.root);window.title('系统供电预算与接口检查');window.geometry('1000x620')
        book=ttk.Notebook(window);book.pack(fill='both',expand=True,padx=16,pady=16)
        def page(title,headers,rows):
            frame=ttk.Frame(book);book.add(frame,text=title)
            tree=ttk.Treeview(frame,columns=tuple(range(len(headers))),show='headings',selectmode='browse')
            vs=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);tree.configure(yscrollcommand=vs.set)
            tree.pack(side='left',fill='both',expand=True);vs.pack(side='right',fill='y')
            for i,h in enumerate(headers):tree.heading(i,text=h);tree.column(i,width=145,anchor='w')
            tree.tag_configure('warn',background='#fff4e5',foreground='#976122')
            for values,ok in rows:tree.insert('', 'end', values=values,tags=() if ok else ('warn',))
        page('功率预算',['端口','正常 / W','已评估最大 / W','配置容量 / W','状态'],[
            ((r['port'],f"{r['normal']:.4g}",f"{r['allocated']:.4g}",f"{r['capacity']:.4g}",'未超容量' if r['ok'] else '需核对'),r['ok']) for r in check['capacity']])
        page('电压与失电',['节点','可用电压 / V','允许范围 / V','状态'],[
            ((r['name'],'无供电' if r['source_min'] is None else f"{r['source_min']:.4g}–{r['source_max']:.4g}",f"{r['design_min']:.4g}–{r['design_max']:.4g}",r['note']),r['ok'] and not r['unavailable']) for r in check['interfaces']])
        tk.Label(window,text='固定 Vf 稳态预算；OR 高压优先，同压不假定均流。完整参数与工况见报告。',anchor='w',padx=20,pady=10,fg=MUTED).pack(fill='x')

    def choose_source(self, identity, source):
        self.link = source
        self.finish_link(identity)

    def disconnect(self, identity):
        model.disconnect(self.project, identity)
        self.selected=None
        self.changed('供电连接已断开，单元设计参数已保留。')
        self.render()

    def sync(self, identity):
        try:
            lo, hi = model.sync_input(self.project, identity)
            self.changed(f'输入范围已更新为 {lo:g}–{hi:g} V。')
            self.render()
        except Exception as error:
            messagebox.showerror('更新输入电压', str(error), parent=self.root)

    def add_bus(self):
        self.add_node('bus')

    def add_unit(self):
        self.add_node('unit')

    def add_ldo(self):
        if len(self.project['units'])>=24:return
        from ldo import DEFAULTS
        identity=model.next_id(self.project,'LDO')
        self.project['units'].append(dict(id=identity,name='新增 LDO 线性稳压器',spec=copy.deepcopy(DEFAULTS),enabled=True))
        self.project=model.normalize_project(self.project);self.selected=('unit',identity);self.changed('LDO 已增加，连接上游后进入专用线性稳压设计。');self.render()

    def load_ldo_example(self):
        self._geometry_origin=None
        from app_resources import resource_path
        self.project=model.load_project(resource_path('examples/SYSTEM_LDO.json'));self.selected=None;self.changed('已载入通用 LDO 示例，型号及额定资料待核对。');self.render();self.fit_canvas()

    def add_node(self,kind):
        collection=model.COLLECTIONS[kind]
        if len(self.project[collection]) >= (24 if kind in ('bus','unit') else 48):
            return
        identity = model.next_id(self.project, {'bus':'BUS','unit':'PSU','junction':'OR','load':'LOAD'}[kind])
        item=dict(id=identity,name={'bus':'新增输入源','unit':'新增电源','junction':'二极管竞争供电母线','load':'自定义负载'}[kind],enabled=True)
        if kind=='bus':item.update(min=20,max=30,capacity=100)
        elif kind=='unit':item.update(spec=model.fresh_project()['units'][0]['spec'])
        elif kind=='junction':item.update(capacity=100)
        else:item.update(power=1,min=0,max=0)
        self.project[collection].append(item)
        self.project = model.normalize_project(self.project)
        self.selected = (kind, identity)
        self.changed()
        self.render()

    def delete_selected(self):
        if not self.selected:
            return
        kind, identity = self.selected
        if kind == 'edge':
            return self.disconnect(identity)
        self.removal = model.remove_node(self.project, kind, identity)
        self.selected = None
        self.changed('节点已删除，下级输入已断开。可撤销删除。')
        self.render()

    def undo(self):
        if self.removal:
            try:
                model.restore_node(self.project, self.removal)
                self.removal = None
                self.changed('已撤销删除。')
                self.render()
            except Exception as error:
                self.status.set(str(error))

    def arrange(self):
        model.auto_layout(self.project)
        self.changed('已按供电层级排列。')
        self.render()

    def new(self):
        self._geometry_origin=None
        self.project = model.normalize_project(model.fresh_project())
        self.title.set(self.project['title'])
        self.path, self.selected, self.removal = None, None, None
        self.changed('已创建新系统工程。上次编辑保留在手动保存的 JSON 中。')
        self.render()

    def load_example(self):
        self._geometry_origin=None
        from pathlib import Path
        self.project=model.load_project(Path(__file__).parent/'examples/SYSTEM_AUX_ORING.json')
        self.title.set(self.project['title'])
        self.path,self.selected,self.removal=None,None,None
        self.changed('已载入双源 OR 供电、控制电源和三组负载示例。')
        self.render()
        self.root.after_idle(self.fit_canvas)

    def open_file(self):
        path = filedialog.askopenfilename(parent=self.root, title='打开系统工程或原电源配置', filetypes=[('JSON', '*.json')])
        if not path:
            return
        try:
            from pathlib import Path
            source=Path(path).read_bytes()
            raw=json.loads(source.decode('utf-8-sig'))
            self.project = model.load_project_data(raw)
            self._geometry_origin=None
            if not raw.get('schema_version') and not raw.get('schema') and len(self.project['units'])==1:
                self._geometry_origin=(self.project,self.project['units'][0]['id'],(Path(path).name,source))
            self.path = path if raw.get('schema_version') == model.SCHEMA else None
            self.title.set(self.project['title'])
            self.selected, self.removal = None, None
            self.changed('工程已打开。原电源 JSON 作为一个独立电源模块导入。')
            self.render()
        except Exception as error:
            messagebox.showerror('打开工程', str(error), parent=self.root)

    def save(self):
        if not self.save_inspector():return
        self.rename_project()
        path = filedialog.asksaveasfilename(parent=self.root, title='保存完整系统工程', initialfile=self.project['title'] + '.json', defaultextension='.json', filetypes=[('JSON', '*.json')])
        if path:
            try:
                model.save_project(self.project, path)
                self.path = path
                self.status.set('系统工程已保存：' + path)
            except Exception as error:
                messagebox.showerror('保存工程', str(error), parent=self.root)

    def open_unit(self, identity):
        if not self.save_inspector():return
        if self.calculator or (self.report_process and self.report_process.is_alive()):
            return
        self.root.configure(cursor='watch')
        self.root.update_idletasks()
        window = None
        try:
            unit = model.prepare_unit(self.project, identity)
            from ldo import is_ldo
            if is_ldo(unit['spec']):
                from ldo_ui import LdoDesigner as Designer
            else:
                from main import PowerSupplyAnalyzer as Designer
            self.project['activeUnit'] = identity
            window = tk.Toplevel(self.root)
            self.calculator = Designer(window, initial_config=copy.deepcopy(unit['spec']), on_return=lambda app: self.return_from_unit(identity, app))
            origin=getattr(self,'_geometry_origin',None)
            if origin and origin[0] is self.project and origin[1]==identity:
                self.calculator._geometry_source=origin[2]
            window.title(identity + ' · ' + unit['name'] + ' · 完整电源设计')
            self.root.withdraw()
        except Exception as error:
            if window:
                window.destroy()
            self.calculator = None
            messagebox.showerror('打开电源设计', str(error), parent=self.root)
        finally:
            self.root.configure(cursor='')

    def return_from_unit(self, identity, app):
        try:
            detached = model.set_unit_config(self.project, identity, app._config_dict())
        except Exception as error:
            messagebox.showerror('请先修正单元参数', '当前参数未能保存到系统工程：\n' + str(error), parent=app.root)
            return False
        self.calculator = None
        self.root.deiconify()
        self.selected = ('unit', identity)
        self.changed('单元设计已回存。' + ('输出端口减少，已断开：' + '、'.join(detached) if detached else ''))
        self.render()
        return True

    def close(self):
        if not self.save_inspector():return
        if self.report_process and self.report_process.is_alive():
            self.report_stop.set()
            self.report_process.terminate()
            self.report_process.join(timeout=1)
        self.rename_project()
        self.root.destroy()

    def export_report(self):
        if self.report_process and self.report_process.is_alive():
            self.report_stop.set()
            self.status.set('正在取消报告，当前单元完成后停止。')
            return
        if not list(model.all_nodes(self.project)):
            self.status.set('请先增加至少一个节点。')
            return
        path = filedialog.asksaveasfilename(parent=self.root, title='导出系统与所有电源模块报告', initialfile=self.project['title'] + '报告包.zip', defaultextension='.zip', filetypes=[('ZIP', '*.zip')])
        if not path:
            return
        from system_report_worker import export_system_report
        ctx = multiprocessing.get_context('spawn')
        self.report_events, self.report_stop = ctx.Queue(), ctx.Event()
        self.report_process = ctx.Process(target=export_system_report, args=(copy.deepcopy(self.project), path, self.report_events, self.report_stop), daemon=True)
        self.report_process.start()
        self.report_button.configure(text='取消报告')
        self.status.set('后台生成系统总览与各单元 Word / Excel；可继续查看架构。')
        self.root.after(150, self.poll_report)

    def poll_report(self):
        finished = False
        try:
            while True:
                kind, payload = self.report_events.get_nowait()
                if kind == 'progress':
                    self.status.set('报告生成：' + payload)
                elif kind == 'done':
                    finished = True
                    self.status.set(f"报告已导出：{payload['successful']}/{payload['total']} 个单元完整；{payload['path']}")
                elif kind in ('error', 'cancelled'):
                    finished = True
                    self.status.set('报告：' + str(payload))
        except queue.Empty:
            pass
        if not finished and self.report_process.is_alive():
            self.root.after(200, self.poll_report)
        else:
            if not finished:
                self.status.set('报告进程已结束，请检查输出或重试。')
            self.report_button.configure(text='生成系统报告包')
            self.report_process.join(timeout=.1)
