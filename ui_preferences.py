"""Local presentation preferences, deliberately separate from design JSON."""
import json
import os
from pathlib import Path

DEFAULT_FONT = 14
FONT_MIN,FONT_MAX,FONT_STEP = 12,40,2
FONT_SIZES = tuple(range(FONT_MIN,FONT_MAX+1,FONT_STEP))


def normalize_font_size(value):
    return max(FONT_MIN,min(FONT_MAX,FONT_MIN+FONT_STEP*round((float(value)-FONT_MIN)/FONT_STEP)))


def preferences_path():
    return Path(os.environ.get('LOCALAPPDATA',Path.home()))/'PowerDesign'/'ui-preferences.json'


def font_size():
    try:
        value=int(json.loads(preferences_path().read_text(encoding='utf-8'))['font_px'])
        return normalize_font_size(value)
    except (OSError,ValueError,TypeError,KeyError):return DEFAULT_FONT


def save_font_size(value):
    value=normalize_font_size(value)
    path=preferences_path();path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'font_px':value}),encoding='utf-8')
    os.replace(temporary,path)
    return value


def font_control(parent,command,*,style='',side='right'):
    from tkinter import ttk
    import tkinter as tk
    frame=ttk.Frame(parent)
    frame.pack(side=side,padx=8)
    ttk.Label(frame,text='界面字号',font=('Microsoft YaHei UI',-12)).pack(side='left',padx=(0,5))
    choice=tk.StringVar(value=str(font_size()))
    box=ttk.Combobox(frame,textvariable=choice,values=FONT_SIZES,width=3,state='readonly',font=('Microsoft YaHei UI',-13))
    box.pack(side='left')
    box.bind('<<ComboboxSelected>>',lambda e:command(int(choice.get())))
    return choice


def apply_studio_fonts(root,size):
    """Scope architecture fonts; leave the calculator's own ttk styles alone."""
    from tkinter import ttk, font
    k=size/14;style=ttk.Style(root)
    for name,base,bold in [('System.TLabel',14,False),('System.TButton',13,False),('SystemToolbar.TButton',14,False),('SystemPrimary.TButton',13,True),('SystemMini.TButton',12,False),('System.TCheckbutton',13,False)]:
        style.configure(name,font=('Microsoft YaHei UI',-round(base*k),'bold' if bold else 'normal'))
    def walk(w):
        if 'font' in w.keys() and str(w.cget('font')):
            if not hasattr(w,'_studio_base_font'):
                raw=w.cget('font');parts=root.tk.splitlist(raw)
                f=font.Font(root=root,font=raw);base=f.actual()
                try:configured=int(parts[1])
                except (IndexError,ValueError):configured=int(root.tk.call('font','configure',raw,'-size'))
                # font actual reports points, even for negative pixel sizes.
                base['pixels']=abs(configured) if configured<0 else configured*float(root.tk.call('tk','scaling'))
                w._studio_base_font=base
            base=w._studio_base_font
            w.configure(font=(base['family'],-max(9,round(base['pixels']*k)),base['weight']))
        for child in w.winfo_children():walk(child)
    walk(root)
