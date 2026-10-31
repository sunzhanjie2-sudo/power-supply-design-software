"""Independent DC corner estimate for diode-rectified active-clamp forward.

Common duty, resistive port loads, CCM/DCM and first-order commutation loss.
This is NOT the full switched kij solver. The LTspice stage uses every kij;
this estimate separates primary/common and secondary leakage from k(P,Si).
"""
import numpy as np

NOTE = ('有源钳位正激独立直流近似：固定匝数、恒阻端口负载、整流/防反固定压降与绕组 DCR，'
        '共享占空比，由主路稳压。各路可进入 CCM/DCM；换流损失按主副边 k 的共同/支路漏感一阶估算。'
        '未拟合仿真结果；不是完整两两互感矩阵开关解，不含谐振、死区换流及控制器 PSM。')


def estimate(p, rails, geometry, kvals):
    from scipy.optimize import least_squares
    from voltage_nodes import input_drop,output_drop
    n=len(rails);fb=int(p.get('feedback_output',1))-1
    vin=float(p['V_in'])-input_drop(p);fs=float(p['f_sw'])
    ratios=np.array([w['Ns']/geometry['Np'] for w in geometry['windings']])
    resistance=np.array([r['V_out']**2/max(r['P_out'],1e-15) for r in rails])
    drops=np.array([r['Vf_diode']+output_drop(r) for r in rails])
    inductance=np.array([r['L'] for r in rails])
    rd=np.array([w['R_dc'] for w in geometry['windings']]);rp=geometry['R_dc_p']
    k=np.array([kvals[0][i+1] for i in range(n)])
    primary_leak=float(p['Lm_forward'])*(1-float(np.min(k)))
    secondary_leak=float(p['Lm_forward'])*ratios**2*(1-k)
    target=rails[fb]['V_out']
    def point(x):
        vo=x[:n];d=x[-1];io=vo/resistance;ip=float(np.dot(ratios,io))
        vs=np.maximum(ratios*(vin-rp*ip)-rd*io,1e-5)
        commute=fs*(primary_leak*ip+secondary_leak*io/ratios)/max(vin,1e-6)
        de=np.maximum(d-commute,1e-7)
        u=vo+drops
        critical=vs*de*(1-de)/(2*inductance*fs)
        ccm=io>=critical
        i_dcm=vs*np.maximum(vs-u,0)*de**2/(2*inductance*fs*np.maximum(u,1e-6))
        residual=np.where(ccm,vo-(de*vs-drops),resistance*(io-i_dcm))
        return residual,ccm,de,commute
    def residual(x):return np.r_[point(x)[0]/max(target,1), (x[fb]-target)/max(target,1)]
    initial=np.r_[[r['V_out'] for r in rails], min(.6,(target+drops[fb])/(vin*ratios[fb])+.05)]
    upper=np.r_[np.maximum(vin*ratios-drops, .1),min(float(p.get('forward_d_max',.7)),.95)]
    solved=least_squares(residual,np.minimum(initial,upper*.999),bounds=(np.r_[[1e-6]*n,1e-5],upper),
                         xtol=1e-11,ftol=1e-11,gtol=1e-11,max_nfev=400)
    error=float(np.max(np.abs(residual(solved.x))))
    if not solved.success or error>1e-5:raise ValueError(f'正激直流角点未收敛或占空比超限：残差 {error:g}')
    _,ccm,de,commute=point(solved.x)
    return dict(voltages=solved.x[:n].tolist(),duty=float(solved.x[-1]),
                modes=['CCM' if x else 'DCM' for x in ccm],effective_duty=de.tolist(),
                commutation_loss_duty=commute.tolist(),residual=error,note=NOTE)
