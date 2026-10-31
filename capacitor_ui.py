"""Compact virtual rows: editing many capacitors does not create many Tk fields."""
import copy
import tkinter as tk
from tkinter import ttk
from capacitor_banks import validate


class BankEditor(ttk.Frame):
    def __init__(self,parent,values,changed=lambda:None):
        super().__init__(parent)
        self.changed=changed;self.index=0;self.busy=False
        self.values=validate(values)
        self.columnconfigure(0,weight=1)
        top=ttk.Frame(self);top.grid(row=0,column=0,sticky='ew')
        ttk.Label(top,text='电容数量').pack(side='left')
        self.count=tk.StringVar(value=str(len(self.values)))
        ttk.Spinbox(top,from_=1,to=1000,textvariable=self.count,width=5).pack(side='left',padx=4)
        ttk.Button(top,text='设置数量',command=self.resize).pack(side='left')
        self.tree=ttk.Treeview(self,columns=('C','ESR','ESL'),show='tree headings',height=4,selectmode='browse')
        self.tree.heading('#0',text='序号');self.tree.column('#0',width=40,stretch=False)
        for key,unit in (('C','µF'),('ESR','mΩ'),('ESL','nH')):
            self.tree.heading(key,text=key+' / '+unit);self.tree.column(key,width=76,minwidth=55)
        self.tree.grid(row=1,column=0,sticky='ew',pady=3)
        bar=ttk.Scrollbar(self,orient='vertical',command=self.tree.yview);bar.grid(row=1,column=1,sticky='ns')
        self.tree.configure(yscrollcommand=bar.set)
        form=ttk.Frame(self);form.grid(row=2,column=0,sticky='ew')
        self.variables={k:tk.StringVar() for k in ('C','ESR','ESL')}
        for j,(key,unit) in enumerate((('C','µF'),('ESR','mΩ'),('ESL','nH'))):
            ttk.Label(form,text=key+' / '+unit).grid(row=0,column=j)
            entry=ttk.Entry(form,textvariable=self.variables[key],width=9)
            entry.grid(row=1,column=j,sticky='ew',padx=2);form.columnconfigure(j,weight=1)
            entry.bind('<KeyRelease>',lambda _e:self.changed())
            entry.bind('<FocusOut>',lambda _e:self.commit())
        actions=ttk.Frame(self);actions.grid(row=3,column=0,sticky='ew',pady=3)
        ttk.Button(actions,text='增加一颗',command=self.add).pack(side='left')
        ttk.Button(actions,text='删除选中',command=self.remove).pack(side='left',padx=4)
        self.note=tk.StringVar(value='选中行修改；同一端口全部并联，逐颗计算分流和损耗。')
        ttk.Label(self,textvariable=self.note,wraplength=330).grid(row=4,column=0,sticky='w')
        self.tree.bind('<<TreeviewSelect>>',self.select)
        self.load(self.values)

    def load(self,values):
        self.busy=True;self.values=validate(values);self.index=0
        self.tree.delete(*self.tree.get_children())
        for i,row in enumerate(self.values):
            self.tree.insert('', 'end',iid=str(i),text=str(i+1),values=self.display(row))
        self.count.set(str(len(self.values)));self.tree.selection_set('0');self.populate();self.busy=False

    @staticmethod
    def display(row):return tuple(f'{row[k]/scale:.10g}' for k,scale in (('C',1e-6),('ESR',1e-3),('ESL',1e-9)))

    def populate(self):
        for k,v in zip(self.variables,self.display(self.values[self.index])):self.variables[k].set(v)

    def commit(self,strict=False):
        try:
            data={k:float(self.variables[k].get())*scale for k,scale in (('C',1e-6),('ESR',1e-3),('ESL',1e-9))}
            old=self.values[self.index]
            for k,shown in zip(self.variables,self.display(old)):
                if self.variables[k].get()==shown:data[k]=old[k]
            row=validate([data])[0];self.values[self.index]=row
            self.tree.item(str(self.index),values=self.display(row))
            self.note.set('全部并联；逐颗计算分流、纹波及 ESR 损耗。')
            return True
        except (ValueError,tk.TclError) as exc:
            self.note.set(str(exc))
            if strict:raise ValueError(str(exc)) from exc
            return False

    def select(self,_event=None):
        if self.busy or not self.tree.selection():return
        new=int(self.tree.selection()[0])
        if new==self.index:return
        if not self.commit():
            self.tree.selection_set(str(self.index));return
        self.index=new;self.populate()

    def get(self):
        self.commit(True)
        return copy.deepcopy(self.values)

    def resize(self):
        try:
            count=int(self.count.get())
            if count<1:raise ValueError('至少保留一颗电容')
            rows=self.get();rows=(rows+[copy.deepcopy(rows[-1]) for _ in range(max(0,count-len(rows)))])[:count]
            self.load(rows);self.changed()
        except ValueError as exc:self.note.set(str(exc))

    def add(self):self.count.set(str(len(self.values)+1));self.resize()

    def remove(self):
        if len(self.values)==1:self.note.set('至少保留一颗电容');return
        rows=copy.deepcopy(self.values);rows.pop(self.index);self.load(rows);self.changed()
