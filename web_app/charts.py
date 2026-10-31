"""Headless figures: reuse desktop/report samples and reference drawings."""
from pathlib import Path

KINDS = {'topology','power','parasitics','switching','switching_real','outputs','capacitors','input_caps',
         'output_caps','losses','device_losses','output_losses','magnetics','magnetic_flux',
         'winding','loop','efficiency','clamp'}


def render(run, path, case_id, kind, output=1):
    if kind not in KINDS:
        raise ValueError('未知图表')
    import numpy as np
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib import rc_context
    from power_charts import POWER_CHART_STYLE
    from multi_output_charts import draw_output_power, draw_output_capacitors, draw_output_losses
    bundle = run.runtime_bundle()
    case = next((row for row in bundle['cases'] if row['id'] == case_id), None)
    if case is None or case.get('result') is None or case.get('error'):
        raise ValueError('该输入工况没有可绘制的结果')
    p, result = case['p'], case['result']
    op, wf = result['op'], result['wf']
    sizes = {'topology':(13.5,6.5), 'power':(12,6.7), 'switching':(12,4.2),
             'outputs':(11.2,6.0), 'output_caps':(11.2,7.2), 'loop':(12,6.5),
             'winding':(12,6.), 'capacitors':(12,9.), 'input_caps':(12,7.5),
             'clamp':(12,6.),'magnetic_flux':(12,5.5)}
    if op['topology'] == 'ACF-FORWARD':
        sizes['outputs'] = (11.2, 8.4)  # Six branch plots, not flyback's four.
    if kind=='parasitics':sizes[kind]=(12,2.8*max(1,len((op.get('parasitics') or {}).get('edges',[]))))
    with rc_context(dict(POWER_CHART_STYLE, **{'font.family':POWER_CHART_STYLE['font.sans-serif'], 'font.size':10})):
        fig = Figure(figsize=sizes.get(kind, (12,4.8)), dpi=120)
        FigureCanvasAgg(fig)
        if kind == 'topology':
            from topology_diagram import draw_topology
            draw_topology(fig.subplots(), p, op)
        elif kind == 'parasitics':
            from parasitic_ringing import draw
            draw(fig,op.get('parasitics') or {})
        elif kind == 'power':
            if result.get('outputs'):
                from multi_output_charts import draw_shared_power_signals
                draw_shared_power_signals(fig.subplots(2,2),op,wf)
            else:
                from power_charts import draw_power_signals
                draw_power_signals(fig.subplots(2,2), op['topology'], wf)
        elif kind in ('switching','switching_real'):
            from power_charts import draw_power_switching
            draw_power_switching(fig.subplots(1,2), op, p, result,real_time=kind=='switching_real')
        elif kind in ('outputs','output_caps','output_losses'):
            index = output-1
            if not 0 <= index < len(result.get('outputs', [])):
                raise ValueError('该输出支路不存在')
            branch = dict(result['outputs'][index], wf=wf['outputs'][index])
            fn = {'outputs':draw_output_power, 'output_caps':draw_output_capacitors,
                  'output_losses':draw_output_losses}[kind]
            fn(fig, branch, feedback=output == p['feedback_output'])
        elif kind in ('capacitors','input_caps'):
            caps = result['capacitors']
            sides = (('input','输入'),) if kind=='input_caps' else (('input','输入'),('output','输出'))
            rows = [(f'{name} C{i+1}',row,caps[side]['labels']) for side,name in sides for i,row in enumerate(caps[side]['caps'])]
            grid=fig.add_gridspec(1+(len(rows)+1)//2,2)
            ax=fig.add_subplot(grid[0,:]); values=[row['total'] for _,row,_ in rows]
            labels=[f"{name} · {row['C']*1e6:.3g} µF / {row['ESR']*1e3:.3g} mΩ" for name,row,_ in rows]
            bars=ax.barh(labels,values,color='#2676b9');ax.invert_yaxis();ax.bar_label(bars,fmt='%.3g A',padding=5)
            ax.set(xlabel='交流 RMS / A',title='电容纹波电流与全频带分量');ax.set_xlim(0,max(values+[.01])*1.3)
            for i,(name,row,bands) in enumerate(rows):
                ax=fig.add_subplot(grid[1+i//2,i%2]);x=np.arange(len(bands))
                ax.bar(x,row['bands'],color='#2f83ac');ticks=np.unique(np.r_[np.arange(0,max(len(bands)-4,1),4),len(bands)-1])
                ax.set_xticks(ticks,[bands[j] for j in ticks]);ax.set(title=name+' · 频带 RMS',ylabel='A');ax.margins(y=.2)
        elif kind == 'device_losses':
            axes=fig.subplots(1,2);semi=result['semi'];sw=semi['switch'];di=semi['diode']
            names=['导通','开通','关断','Coss','驱动'];values=[sw[key] for key in ('P_cond','P_sw_on','P_sw_off','P_coss','P_gate')]
            other=[('导通',di.get('P_cond',di.get('P_sr_cond',0))),('反向恢复',di.get('P_rr',0))]
            if semi.get('freewheel'):other += [('续流导通',semi['freewheel']['P_cond']),('续流恢复',semi['freewheel']['P_rr'])]
            if semi.get('auxiliary'):other += [('辅助 MOS',semi['auxiliary']['P_total'])]
            for ax,labels,values,title in ((axes[0],names,values,'Q1 损耗分解'),(axes[1],[r[0] for r in other],[r[1] for r in other],'整流 / 辅助器件损耗')):
                bars=ax.barh(labels,values,color='#2676b9');ax.invert_yaxis();ax.bar_label(bars,fmt='%.3g W',padding=4);ax.set(title=title,xlabel='W');ax.set_xlim(0,max(values+[.01])*1.3)
        elif kind in ('losses','magnetics'):
            if kind == 'losses':
                names, values = [], []
                for key,label in [('P_semi','半导体'),('P_mag','磁件'),('P_cap','输出电容'),('P_cap_in','输入电容'),
                                  ('P_sense','采样'),('P_rcd','RCD钳位'),('P_clamp','有源钳位'),('P_din','输入防反'),('P_dout','输出防反'),('P_controller','控制器'),('P_parasitic','布线 / RC 吸收电阻')]:
                    if result.get(key, 0) > 0:
                        names.append(label); values.append(result[key])
                ax = fig.subplots(); bars=ax.barh(names,values,color='#2676b9')
                ax.bar_label(bars, fmt='%.3g W', padding=5); ax.set(xlabel='损耗 / W', title='已计算损耗分配 · 不叠加重复项')
                ax.set_xlim(0,max(values+[.01])*1.3)
            else:
                md = result['mag']
                devices = [('T1 变压器', md['transformer'])] if (md.get('transformer') or {}).get('ok') else []
                if md.get('inductors'):
                    devices += [(f'L_O{i} 输出电感', device) for i,device in enumerate(md['inductors'],1) if device.get('ok')]
                elif (md.get('inductor') or {}).get('ok'):
                    devices.append(('输出电感', md['inductor']))
                if not devices:
                    raise ValueError(result['mag'].get('reason','磁件设计无有效结果'))
                axes=fig.subplots(1,2)
                labels=[label for label,dev in devices]
                copper=[dev['P_cu'] for label,dev in devices]; core=[dev['P_core'] for label,dev in devices]
                axes[0].bar(labels,copper,label='铜损',color='#2676b9'); axes[0].bar(labels,core,bottom=copper,label='磁芯损耗',color='#4aa996')
                axes[0].set(ylabel='W',title='磁件损耗'); axes[0].legend()
                bars=axes[1].bar(labels,[dev['dT'] for label,dev in devices],color='#d19b42'); axes[1].bar_label(bars,fmt='%.1f K',padding=5)
                axes[1].axhline(p['temp_rise_limit'],color='#c75353',ls='--',label='评审上限'); axes[1].set(ylabel='K',title='估算温升'); axes[1].legend()
        elif kind == 'magnetic_flux':
            ax=fig.subplots();md=result['mag'];tr=md.get('transformer') or {};ind=md.get('inductor') or {}
            if tr.get('ok'):
                current=wf['i_mag'] if op['topology']=='ACF-FORWARD' else wf['i_p']
                inductance=op['Lm_forward'] if op['topology']=='ACF-FORWARD' else op['L']
                ax.plot(wf['t']*1e6,inductance*np.asarray(current)/(tr['Np']*tr['Ae'])*1e3,label='T1 磁通')
            if md.get('inductors'):
                for index, device in enumerate(md['inductors']):
                    if not device.get('ok'):
                        continue
                    branch = result['outputs'][index]
                    branch_wf = wf['outputs'][index]
                    ax.plot(branch_wf['t']*1e6, branch['op']['L']*np.asarray(branch_wf['iL'])/(device['N']*device['Ae'])*1e3,
                        label=f'L_O{index+1} 磁通')
            elif ind.get('ok'):
                ax.plot(wf['t']*1e6,op['L']*np.asarray(wf['iL'])/(ind['N']*ind['Ae'])*1e3,label='输出电感磁通')
            from magnetic_plot import show_flux_range
            show_flux_range(ax,[line.get_ydata() for line in ax.lines],p['Bsat']*1e3)
            ax.set(title='磁通密度与饱和界限（沿用桌面波形关系）',xlabel='时间 / µs',ylabel='B / mT');ax.legend();ax.grid(alpha=.3)
        elif kind == 'clamp':
            axes=fig.subplots(1,2);t=np.asarray(wf['t'])
            if op['topology']=='ACF-FORWARD':
                from active_clamp import forward_waveforms
                signals=forward_waveforms(op,t)
                axes[0].plot(t*1e6,signals['v_sw'],label='Q1 Vds');axes[0].plot(t*1e6,signals['v_clamp'],label='钳位电容电压')
                axes[1].plot(t*1e6,signals['i_mag'],label='励磁电流');axes[1].plot(t*1e6,signals['i_aux'],label='辅助 MOS 电流')
            elif op['topology'] in ('FLYBACK','QR-FLYBACK'):
                from flyback_clamp import rcd_components,clamp_current
                rcd=rcd_components(op,p);voltage=np.full_like(t,rcd['V_clamp'])
                if rcd['C_snub']>0 and np.isfinite(rcd['R_snub']):
                    freq=np.fft.rfftfreq(len(t),float(t[1]-t[0]));z=rcd['R_snub']/(1+2j*np.pi*freq*rcd['R_snub']*rcd['C_snub']);z[0]=0
                    voltage+=np.fft.irfft(np.fft.rfft(clamp_current(t,op))*z,len(t))
                axes[0].plot(t*1e6,voltage,label='钳位电容 RC 小纹波');axes[0].axhline(rcd['V_clamp'],color='#c75353',ls='--',label='钳位基准')
                axes[1].plot(t*1e6,wf['v_sw'],label='Q1 Vds');axes[1].axhline(op['clamp']['V_plateau'],ls=':',label='反射平台');axes[1].axhline(op['clamp']['V_ceiling'],ls='--',label='Kc 应力上限')
            else:raise ValueError('当前拓扑无钳位模块')
            for ax,title,unit in zip(axes,('钳位电压','复位电流 / MOS 电压'),('V','A' if op['topology']=='ACF-FORWARD' else 'V')):
                ax.set(title=title,xlabel='时间 / µs',ylabel=unit);ax.legend();ax.grid(alpha=.3)
        elif kind == 'winding':
            from winding_layout import transformer_windings, assess_winding_window, draw_winding_cross_section
            assessment=assess_winding_window(transformer_windings(result),p.get('winding_config'))
            draw_winding_cross_section(fig.subplots(),assessment)
        elif kind == 'loop':
            loop=result.get('loop')
            if loop is None:
                raise ValueError(case.get('loop_error') or '当前模型未提供环路结果')
            axes=fig.subplots(2,2)
            for index,label in ((0,'对象 Gvc'),(1,'补偿器 Gc')):
                axes[0,0].semilogx(loop['f'],20*np.log10(np.maximum(abs(loop['gains'][index]),1e-300)),label=label)
                axes[0,1].semilogx(loop['f'],loop['phases'][index],label=label)
            axes[1,0].semilogx(loop['f'],20*np.log10(np.maximum(abs(loop['gains'][2]),1e-300)),label='开环增益'); axes[1,1].semilogx(loop['f'],loop['phases'][2],label='开环相位')
            for ax,title,ylabel in zip(axes.flat,('对象/补偿器幅频','对象/补偿器相频','开环幅频','开环相频'),('dB','deg','dB','deg')):
                ax.set(title=title,xlabel='Hz',ylabel=ylabel); ax.legend(); ax.grid(which='both',alpha=.2)
                if loop.get('fc'):
                    ax.axvline(loop['fc'],ls=':',color='#4aa996')
            axes[1,0].axhline(0,ls='--',color='#cf6666'); axes[1,1].axhline(-180,ls='--',color='#cf6666')
        elif kind == 'efficiency':
            curve=case.get('efficiency_curve')
            if not curve:
                raise ValueError('当前快照未准备效率扫描')
            ax=fig.subplots(); ax.plot(np.asarray(curve['fracs'])*100,np.asarray(curve['etas'])*100,'o-',color='#2676b9')
            ax.set(xlabel='负载比例 / %',ylabel='模型效率 / %',title=f"{case_id} · 同一套固定磁件下的模型效率")
            ax.axhline(p['target_eta']*100,ls='--',color='#d19b42',label='目标'); ax.legend()
        from matplotlib.text import Text
        for item in fig.findobj(Text):
            if item.get_text():item.set_fontsize(max(item.get_fontsize(),12))
        if kind not in ('outputs','output_caps','output_losses'):
            fig.tight_layout(pad=1.8)
        from design_theme import style_figure
        style_figure(fig)
        destination=Path(path); destination.parent.mkdir(parents=True,exist_ok=True)
        fig.savefig(destination, format='png', dpi=120, facecolor='white')
        fig.clear()
    return destination
