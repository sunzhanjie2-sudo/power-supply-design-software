"""Presentation of the actual B swing; never changes a magnetic calculation."""
import numpy as np


def _finite_fluxes(waveforms):
    values=[np.asarray(v,dtype=float).ravel() for v in waveforms]
    values=[v[np.isfinite(v)] for v in values if v.size]
    values=[v for v in values if v.size]
    return values


def flux_view_limits(waveforms):
    values=_finite_fluxes(waveforms)
    if not values:return None
    low=min(float(v.min()) for v in values);high=max(float(v.max()) for v in values)
    span=max(high-low,max(abs(low),abs(high))*.02,1e-9)
    margin=span*.15
    return low-margin,high+margin


def show_flux_range(ax,waveforms,saturation,*,unit='mT'):
    waveforms=_finite_fluxes(waveforms)
    limits=flux_view_limits(waveforms)
    if limits is None:return
    low,high=limits
    limit=abs(float(saturation))
    ax.axhline(limit,color='#c75353',ls='--',lw=1,label=f'±Bsat={limit:.4g} {unit}')
    ax.axhline(-limit,color='#c75353',ls='--',lw=.8)
    if high>limit:ax.axhspan(max(low,limit),high,color='#c75353',alpha=.1)
    if low<-limit:ax.axhspan(low,min(high,-limit),color='#c75353',alpha=.1)
    # Retain the criterion even when it lies outside this zoomed data range.
    peak=max(float(np.max(np.abs(v))) for v in waveforms)
    ax.text(.99,.98,f'±Bsat={limit:.4g} {unit}'+(' · 超出饱和限值' if peak>limit else ''),
            transform=ax.transAxes,ha='right',va='top',fontsize=8,
            color='#b03a2e' if peak>limit else '#6b7e94',
            bbox=dict(facecolor='white',edgecolor='none',alpha=.85,pad=2))
    ax.set_ylim(low,high)
