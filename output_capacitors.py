"""Passive output filters: each enabled capacitor keeps its own series ESR.

The load is a resistor. Input is net injected current (rectifier average
minus an extra sinking-current disturbance); output is the capacitor-terminal
voltage. No ESL or switching-ripple approximation is hidden in this network.
"""
from dataclasses import dataclass

import numpy as np


@dataclass
class OutputFilters:
    A: np.ndarray
    B: np.ndarray
    C: np.ndarray
    D: np.ndarray
    state_labels: list
    banks: list


def branches(rail):
    from capacitor_banks import bank
    values=[(r['C'],r['ESR']) for r in bank(rail)]
    if any(not np.isfinite(c) or c<=0 or not np.isfinite(r) or r<0 for c,r in values):
        raise ValueError('启用的输出电容要求 C>0、ESR≥0，且数值有限')
    return values


def build_output_filters(rails,loads,voltages):
    """Block-diagonal RC banks, with voltage-normalized internal states.

    Zero-ESR capacitors share one ideal voltage state, with summed C. A finite
    ESR branch retains its own state even in parallel with an ideal capacitor.
    This avoids dividing by an artificial minimum ESR or adding phantom poles.
    """
    count=len(rails)
    if len(loads)!=count or len(voltages)!=count:
        raise ValueError('输出电容网络与负载数量不一致')
    blocks=[];labels=[];banks=[]
    for j,(rail,load,voltage) in enumerate(zip(rails,loads,voltages),1):
        load,voltage=float(load),float(voltage)
        if not np.isfinite(load) or load<=0 or not np.isfinite(voltage) or voltage<=0:
            raise ValueError('输出电容网络要求正的负载电阻及工作点电压')
        caps=branches(rail)
        finite=[(k,c,r) for k,(c,r) in enumerate(caps,1) if r>0]
        ideal=sum(c for c,r in caps if r==0)
        size=len(finite)+(1 if ideal else 0)
        a=np.zeros((size,size));b=np.zeros(size);c=np.zeros(size)
        if ideal:
            # V is itself a state. Finite-ESR branches exchange current with
            # the shared ideal capacitor through their actual resistances.
            a[0,0]=-(1/load+sum(1/r for _,_,r in finite))/ideal
            b[0]=1/ideal;c[0]=1.;d=0.
            state_names=[f'OUT{j}.C_ideal']
            for k,(number,cap,esr) in enumerate(finite,1):
                a[0,k]=1/(ideal*esr)
                a[k,0]=1/(esr*cap);a[k,k]=-1/(esr*cap)
                state_names.append(f'OUT{j}.C{number}')
        else:
            conductance=np.array([1/r for _,_,r in finite])
            inverse_time=np.array([1/(r*cap) for _,cap,r in finite])
            d=1/(1/load+sum(conductance))
            c=conductance*d
            a=inverse_time[:,None]*(c[None,:]-np.eye(size))
            b=inverse_time*d
            state_names=[f'OUT{j}.C{k}' for k,_,_ in finite]
        # All states in this rail use its own DC voltage as normalization.
        blocks.append((a,b/voltage,c*voltage,d));labels.extend(state_names)
        total=sum(cap for cap,_ in caps)
        low_esr=sum(esr*cap**2 for cap,esr in caps)/total**2
        banks.append(dict(output=j,branches=[dict(C=cap,ESR=esr) for cap,esr in caps],
            states=size,state_labels=state_names,capacitance=total,low_frequency_esr=low_esr,
            esr_zero_estimate_hz=1/(2*np.pi*total*low_esr) if low_esr else None))
    states=sum(len(a) for a,_,_,_ in blocks)
    a=np.zeros((states,states));b=np.zeros((states,count))
    c=np.zeros((count,states));d=np.zeros((count,count));offset=0
    for j,(ab,bb,cb,db) in enumerate(blocks):
        size=len(ab);where=slice(offset,offset+size)
        a[where,where]=ab;b[where,j]=bb;c[j,where]=cb;d[j,j]=db;offset+=size
    return OutputFilters(a,b,c,d,labels,banks)
