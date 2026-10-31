"""Readable teaching figures from the collected, unchanged calculation run."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from runtime_resources import configure_numeric_threads
configure_numeric_threads()
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, Rectangle

FOLDER = ROOT/'artifacts/tutorials/multi_flyback_20261023'
data = json.loads((FOLDER/'tutorial_data.json').read_text(encoding='utf-8'))
snap = json.loads((FOLDER/'engineering_snapshot.json').read_text(encoding='utf-8'))
plt.rcParams.update({'font.family':'Microsoft YaHei', 'axes.unicode_minus':False,
                     'font.size':11,'axes.titlesize':12,'axes.labelsize':11,
                     'figure.facecolor':'white','savefig.facecolor':'white',
                     'axes.spines.top':False,'axes.spines.right':False})
colors = ['#155c99','#cd632d','#268075','#8964a4']


def save(fig, name):
    fig.savefig(FOLDER/(name+'.png'), dpi=180, bbox_inches='tight', pad_inches=.12)
    plt.close(fig)


def main():
    # Current paths: one figure explains why input, primary and MOS RMS differ.
    fig, axes = plt.subplots(3,1,figsize=(7.3,6.9),sharex=True,layout='constrained')
    for c,color in zip(snap['cases'],colors):
        wf=c['result']['wf']; t=np.asarray(wf['t'])*1e6
        axes[0].plot(t,wf['i_sw'],label=f"{c['V_in']:g} V",color=color)
        axes[1].plot(t,wf['v_sw'],color=color)
        axes[2].plot(t,wf['i_clamp'],color=color)
    for ax,title,y in zip(axes,['Q1 导通电流','Q1 漏源电压和钳位尖峰','关断后钳位支路电流'],['A','V','A']):
        ax.set(title=title,ylabel=y);ax.grid(alpha=.25)
    axes[0].legend(ncol=2);axes[-1].set_xlabel('时间 / µs')
    save(fig,'tutorial_primary')
    # Compare branches at both endpoints without duplicating identical plots.
    fig, axes=plt.subplots(3,1,figsize=(7.3,7),sharex=True,layout='constrained')
    for j,ax in enumerate(axes):
        for c,color in zip(snap['cases'],colors):
            w=c['result']['wf']['outputs'][j]
            ax.plot(np.asarray(w['t'])*1e6,w['i_s'],label=f"{c['V_in']:g} V",color=color)
        mode=data['cases'][0]['display']['outputs'][j]['mode']
        ax.set(title=f'OUT{j+1} 绕组与整流电流  {mode}',ylabel='A');ax.grid(alpha=.25)
    axes[0].legend(ncol=2);axes[-1].set_xlabel('时间 / µs')
    save(fig,'tutorial_secondaries')
    fig,axes=plt.subplots(2,1,figsize=(7.3,5.6),sharex=True,layout='constrained')
    for j,co in enumerate(colors[:3]):
        w=snap['cases'][0]['result']['wf']['outputs'][j];t=np.asarray(w['t'])*1e6
        axes[0].plot(t,w['i_c'],label=f'OUT{j+1}',color=co)
        axes[1].plot(t,np.asarray(w['vout_ripple'])*1e3,color=co)
    axes[0].set(title='20 V 输入时各路电容组电流',ylabel='A');axes[0].legend(ncol=3)
    axes[1].set(title='电容和 ESR 重建的低频纹波  不含 ESL 尖峰',ylabel='mV',xlabel='时间 / µs')
    for ax in axes:ax.grid(alpha=.25)
    save(fig,'tutorial_ripple')
    # Native winding plan geometry, same dimensions as the calculator.
    a=data['cases'][0]['display']['winding_assessment'];cfg=a['config']
    fig,ax=plt.subplots(figsize=(7.3,3.5),layout='constrained')
    width,height=cfg['window_width']*1e3,cfg['window_height']*1e3
    ax.add_patch(Rectangle((0,0),width,height,fill=False,lw=1.4))
    byid={w['id']:w for w in a['windings']}
    for layer in a['physical_layers']:
        w=byid[layer['winding_id']];bwidth=w['bundle_width']*1e3;bh=w['bundle_height']*1e3
        turns=layer['turns'];left=layer['x']*1e3;span=layer['width']*1e3
        centers=np.linspace(left+bwidth/2,left+span-bwidth/2,turns) if turns>1 else [left+span/2]
        idx=['P','OUT1','OUT2','OUT3'].index(w['id'])
        for x in centers:
            ax.add_patch(Ellipse((x,(layer['y']+layer['height']/2)*1e3),bwidth,bh,
                                facecolor='none',edgecolor=colors[idx],lw=1.2))
        ax.text(width+.2,(layer['y']+layer['height']/2)*1e3,f"{w['id']}  {turns} 匝",va='center',fontsize=10)
    ax.set(xlim=(-.15,width+2.4),ylim=(-.1,height+.1),xlabel='窗口宽度 / mm',ylabel='堆叠高度 / mm',
           title='五层交错绕制横截面  横纵等比例')
    ax.set_aspect('equal');ax.grid(alpha=.2)
    save(fig,'tutorial_winding')
    # Curves with the four actual event points, never fabricated datasheet data.
    source=Path(__file__).resolve().parents[2]/'examples/40W_CCM_3OUT_FLYBACK.json'
    raw=json.loads(source.read_text(encoding='utf-8-sig'))
    transfer=np.asarray(raw['mos_miller_curve']['points']);charge=np.asarray(raw['mos_charge_curve']['points'])
    fig,axes=plt.subplots(1,2,figsize=(7.3,3.8),layout='constrained')
    axes[0].plot(transfer[:,0],transfer[:,1],color='#383838');axes[0].set(xlabel='Vgs / V',ylabel='Id / A',title='转移曲线  反查栅压')
    axes[1].plot(charge[:,0]*1e9,charge[:,1],color='#383838');axes[1].set(xlabel='Qg / nC',ylabel='Vgs / V',title='栅电荷曲线  读取电荷')
    gate=data['cases'][0]['display']['switch_loss']['gate']
    axes[1].plot([charge[-1,0]*1e9,gate['Qg_on']*1e9], [charge[-1,1],10],
                 color='#a14f32',ls='--',lw=1.2)
    axes[1].text(10.6,8.8,'端点外推',fontsize=9,color='#a14f32')
    for i,c in enumerate(data['cases']):
        g=c['display']['switch_loss']['gate']
        for event,marker in [('on','o'),('off','^')]:
            label=f"{c['voltage']:g}V {'开通' if event=='on' else '关断'}"
            axes[0].scatter(g['Vgp_'+event],g['I_'+event],color=colors[i],marker=marker,s=45,label=label,zorder=4)
            axes[1].scatter(g['Qgs_'+event]*1e9,g['Vgp_'+event],color=colors[i],marker=marker,s=45,zorder=4)
    axes[0].set_xlim(3.3,4.5);axes[0].set_ylim(0,15);axes[1].set_xlim(0,15);axes[1].set_ylim(0,10.4)
    axes[1].axvline(5.2,color='#999',ls=':',lw=1);axes[1].axvline(7.2,color='#999',ls=':',lw=1)
    for ax in axes:ax.grid(alpha=.25)
    axes[0].legend(fontsize=8,loc='upper left')
    save(fig,'tutorial_mos_curves')
    # Loop curves and capacitor/loss comparison are drawn from cached values.
    fig,axes=plt.subplots(2,1,figsize=(7.3,5.2),sharex=True,layout='constrained')
    for i,c in enumerate(snap['cases']):
        loop=c['result']['loop'];f=np.asarray(loop['f']);gain=np.asarray(loop['gains'][2])
        # Complex values are serialized by the engine as real/imag objects.
        if isinstance(loop['gains'][2],dict):
            gain=np.asarray(loop['gains'][2]['real'])+1j*np.asarray(loop['gains'][2]['imag'])
        if gain.dtype.kind not in 'fc':
            gain=np.array([complex(v['real'],v['imag']) if isinstance(v,dict) else complex(v) for v in loop['gains'][2]])
        axes[0].semilogx(f,20*np.log10(np.maximum(np.abs(gain),1e-30)),label=f"{c['V_in']:g} V",color=colors[i])
        axes[1].semilogx(f,loop['phases'][2],color=colors[i])
    axes[0].axhline(0,color='#888',ls=':');axes[1].axhline(-180,color='#888',ls=':')
    axes[0].set(ylabel='dB',title='同一补偿参数下的主反馈开环');axes[1].set(ylabel='相位 / °',xlabel='频率 / Hz',xlim=(10,1e5))
    axes[0].legend();[ax.grid(alpha=.25) for ax in axes]
    save(fig,'tutorial_loop')
    # The shared switching renderer in stage-unfolded mode stays legible at
    # print width. Two stacked panels avoid title/stage-label collisions.
    from design_engine.service import calculate
    from power_charts import draw_power_switching
    run=calculate(raw,analysis='endpoints',include_loop=False,include_cross_regulation=False)
    case=run.runtime_bundle()['cases'][0]
    assert abs(case['result']['semi']['switch']['P_total']-data['cases'][0]['display']['switch_loss']['P_total'])<1e-10
    fig,axes=plt.subplots(2,1,figsize=(7.3,5.3),layout='constrained')
    draw_power_switching(axes,case['result']['op'],case['p'],case['result'],real_time=False)
    from matplotlib.text import Text
    for obj in fig.findobj(Text):
        if obj.get_fontsize()<9:obj.set_fontsize(9)
    save(fig,'tutorial_switching')


if __name__=='__main__':
    main()
