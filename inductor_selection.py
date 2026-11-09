"""Purchased inductors: electrical inputs without invented winding geometry."""
import math

TOPOLOGIES = ('BUCK', 'BOOST', 'BUCK-BOOST')
DEFAULTS = dict(inductor_design_enabled=True, inductor_dcr=0.,
                inductor_rated_current=0., inductor_saturation_current=0.,
                inductor_extra_loss=0.)
FIELDS = tuple(key for key in DEFAULTS if key != 'inductor_design_enabled')
DESIGN_FIELDS = frozenset(('Bmax', 'Bsat', 'J', 'Ku', 'rho', 'k_core',
                           'a_core', 'b_core', 'MLT', 'h_conv', 'temp_rise_limit'))


def purchased(p):
    return p.get('topology') in TOPOLOGIES and p.get('inductor_design_enabled', True) is False


def validate(p):
    if not isinstance(p.get('inductor_design_enabled', True), bool):
        raise ValueError('inductor_design_enabled 必须为布尔值')
    if not purchased(p):
        return
    for key in FIELDS:
        value = p.get(key, DEFAULTS[key])
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(key+' 必须为有限非负数；0 表示未提供/暂不计入')


def design(op, p):
    """Only I_rms² DCR plus an explicitly supplied additional loss at this point.

    L is still owned by the power stage. Ratings do not clip the waveform or
    pretend to model L(I). A zero additional loss is unassessed, not evidence
    that a moulded inductor has zero core/AC loss.
    """
    validate(p)
    fixed = p.get('_fixed_inductor') or {}
    values = {key: float(fixed.get(key, p.get(key, DEFAULTS[key]))) for key in FIELDS}
    copper = float(op['I_L_rms'])**2 * values['inductor_dcr']
    extra = values['inductor_extra_loss']
    note = ('外购成品电感：不设计磁芯、匝数、气隙或线径。电感量 L 仍用于工作点、波形和环路；'
            '直流铜损为 Irms²×DCR，附加损耗为用户在当前工况的估算值，不自动缩放。'
            '未建模 L 随电流/温度变化；Isat/Irms 仅按厂家所填额定值初筛；磁密、绕制和温升未评估。')
    if values['inductor_dcr'] == 0:
        note += ' DCR 未提供，暂按 0 Ω，铜损未覆盖。'
    if extra == 0:
        note += ' 附加损耗未提供，磁芯及交流损耗未覆盖，效率可能偏高。'
    return dict(ok=True, design_enabled=False, core=None, core_label='外购成品电感',
                L=float(op['L']), I_pk=float(op['I_L_pk']), I_rms=float(op['I_L_rms']),
                R_dc=values['inductor_dcr'], P_cu=copper, P_core=None, P_extra=extra,
                P_total=copper+extra, B_pk=None, dB=None, dT=None, fill=None,
                DCR_source='成品电感 DCR 输入', thermal_model='not_evaluated',
                note=note, **values)


def hardware(device):
    if device.get('design_enabled') is False:
        return dict(design_enabled=False, L=device['L'],
                    **{key: device[key] for key in FIELDS})
    return {key: device[key] for key in ('core', 'core_geometry', 'MLT', 'MLT_source', 'N', 'd_wire')}
