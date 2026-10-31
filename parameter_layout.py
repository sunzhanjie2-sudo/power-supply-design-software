"""Presentation-only catalogue for the power-design parameter sidebar.

Keys and their stored SI values deliberately match ``main.PARAM_SPECS``.  This
module neither imports the GUI nor changes the calculation model.  A display
factor is applied only at the UI boundary (not when saving a configuration).
"""

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class FieldSpec:
    label: str
    symbol: str
    unit: str
    display_factor: float = 1.0
    advanced: bool = False
    required: bool = False
    auto: bool = False
    topologies: tuple[str, ...] = ()
    enabled_by: str = ''


SECTION_ORDER = ('spec', 'curves', 'stage', 'device', 'capacitors', 'drive', 'sense', 'mag', 'ctrl')
SECTION_TITLES = {
    'spec': '① 需求与方案',
    'curves': '器件计算方式与曲线',
    'stage': '② 功率级与钳位',
    'device': '③ MOS 与整流器件',
    'capacitors': '④ 输入/输出电容与防反',
    'drive': '⑤ 栅极驱动',
    'sense': '⑥ 电流采样与调制',
    'mag': '⑦ 磁件与温升',
    'ctrl': '⑧ 反馈与补偿',
}

# Non-numeric selectors (topology, controller type, core material/shape/model,
# multi-output/PSR) are placed by the GUI adjacent to these groups.  Keeping them
# out of this list preserves the numeric configuration contract.
GROUPS = {
    'curves': [],
    'spec': [
        ('电路需求', ('V_in_min', 'V_in_max', 'V_in', 'V_out', 'P_out', 'f_sw', 'eta_guess', 'ripple_target')),
    ],
    'stage': [
        ('储能与变比', ('L', 'N')),
        ('有源钳位正激', ('Lm_forward', 'C_clamp', 'ESR_clamp', 'forward_d_max')),
        ('电压应力', ('ring_margin',)),
        ('旧版兼容参数', ('Vf',)),
    ],
    'device': [
        ('Q1 · 主开关 MOS', ('Rds_on', 'Coss', 'Qg', 'Vth', 'gfs', 'mos_curve_vds', 'Vgp_on', 'Vgp_off',
                           'Qg_th', 'Qgs', 'Qgd', 'Rg', 'k_sw')),
        ('D1 · 输出整流器', ('Vf_diode', 'Rd_diode', 'Qrr')),
        ('Q2 · 钳位 MOS', ('Rds_aux', 'Qg_aux', 'Coss_aux')),
    ],
    'capacitors': [
        ('输入电容 1', ('Cin1', 'Rcin1', 'ESLin1')),
        ('输入电容 2（可选）', ('Cin2', 'Rcin2', 'ESLin2')),
        ('输出电容 1', ('C_out', 'Rc', 'ESL')),
        ('输出电容 2（可选）', ('C_out2', 'Rc2', 'ESL2')),
        ('输入防反二极管（可选）', ('Vf_din', 'Rd_din')),
        ('输出防反二极管（可选）', ('Vf_dout', 'Rd_dout')),
    ],
    'drive': [
        ('驱动电压与电阻', ('Vgs', 'Rg_drive', 'Rs_on', 'Rs_off')),
        ('正激驱动时序', ('forward_dead_time',)),
    ],
    'sense': [
        ('电流采样', ('Rs', 'A_sense')),
        ('PWM 与斜坡补偿', ('Vm', 'ma_slope')),
    ],
    'mag': [
        ('磁密与窗口约束', ('Bmax', 'Bsat', 'Ku')),
        ('绕组与导线', ('Np', 'Ns', 'd_wire_p', 'd_wire_s', 'n_strand_p',
                      'n_strand_s', 'MLT')),
        ('散热与温升', ('Rth_transformer', 'h_conv', 'temp_rise_limit')),
        ('材料与磁芯损耗系数', ('rho', 'k_core', 'a_core', 'b_core')),
    ],
    'ctrl': [
        ('补偿器零极点', ('KP', 'fz1', 'fz2', 'fp1', 'fp2')),
    ],
}

ISOLATED_TOPOLOGIES = ('FLYBACK', 'QR-FLYBACK', 'ACF-FORWARD')
FORWARD_TOPOLOGIES = ('ACF-FORWARD',)

META = {
    'V_in': FieldSpec('输入电压', 'Vin', 'V', required=True),
    'V_in_min': FieldSpec('输入电压下限', 'Vin,min', 'V', required=True),
    'V_in_max': FieldSpec('输入电压上限', 'Vin,max', 'V', required=True),
    'V_out': FieldSpec('端口电压（防反后）', 'Vout', 'V', required=True),
    'P_out': FieldSpec('输出功率', 'Pout', 'W', required=True),
    'f_sw': FieldSpec('开关频率', 'fsw', 'Hz', required=True),
    'eta_guess': FieldSpec('预设效率', 'η预设', '%', display_factor=100, required=True),
    'ripple_target': FieldSpec('输出纹波目标', 'ΔV/Vout', '%', display_factor=100),
    'L': FieldSpec('储能电感', 'L', 'H', required=True),
    'N': FieldSpec('原副边匝比', 'Np/Ns', '', required=True, topologies=ISOLATED_TOPOLOGIES),
    'Lm_forward': FieldSpec('变压器励磁电感', 'Lm', 'H', required=True,
                            topologies=FORWARD_TOPOLOGIES),
    'C_clamp': FieldSpec('低侧钳位电容', 'Cclamp', 'F', topologies=FORWARD_TOPOLOGIES),
    'ESR_clamp': FieldSpec('钳位电容 ESR', 'ESRclamp', 'Ω', topologies=FORWARD_TOPOLOGIES),
    'forward_d_max': FieldSpec('最大占空比', 'Dmax', '%', display_factor=100,
                               topologies=FORWARD_TOPOLOGIES),
    'ring_margin': FieldSpec('MOS 电压应力裕量', 'ΔV/V', '%', display_factor=100,
                            topologies=('BUCK', 'BOOST', 'BUCK-BOOST', 'ACF-FORWARD')),
    'Vf': FieldSpec('旧版压降（不叠加损耗）', 'Vf', 'V'),
    'Rds_on': FieldSpec('导通电阻', 'Rds(on)', 'Ω', required=True),
    'Coss': FieldSpec('输出电容', 'Coss', 'F', required=True),
    'Qg': FieldSpec('总栅极电荷', 'Qg', 'C', required=True),
    'Vth': FieldSpec('典型开启阈值', 'Vgs(th)', 'V', required=True),
    'gfs': FieldSpec('有效跨导（0 固定平台）', 'gfs', 'A/V'),
    'mos_curve_vds': FieldSpec('输出曲线读取电压', 'Vds,read', 'V'),
    'Vgp_on': FieldSpec('开通平台 / Qgs参考平台', 'Vgp,ref', 'V', required=True),
    'Vgp_off': FieldSpec('手动关断米勒平台', 'Vgp,off', 'V', required=True),
    'Qg_th': FieldSpec('门限栅极电荷', 'Qg(th)', 'C', required=True),
    'Qgs': FieldSpec('零伏至米勒平台电荷', 'Qgs', 'C', required=True),
    'Qgd': FieldSpec('米勒平台电荷', 'Qgd', 'C', required=True),
    'Rg': FieldSpec('MOS 内部栅阻', 'Rg,int', 'Ω', required=True),
    'k_sw': FieldSpec('开关损耗系数', 'ksw', ''),
    'Vf_diode': FieldSpec('固定 / 换流近似压降', 'Vf', 'V', required=True),
    'Rd_diode': FieldSpec('动态电阻', 'Rd', 'Ω'),
    'Qrr': FieldSpec('反向恢复电荷', 'Qrr', 'C'),
    'Rds_aux': FieldSpec('钳位 MOS 导通电阻', 'Rds(on),Q2', 'Ω', topologies=FORWARD_TOPOLOGIES),
    'Qg_aux': FieldSpec('钳位 MOS 总栅极电荷', 'Qg,Q2', 'C', topologies=FORWARD_TOPOLOGIES),
    'Coss_aux': FieldSpec('钳位 MOS 输出电容', 'Coss,Q2', 'F', topologies=FORWARD_TOPOLOGIES),
    'Cin1': FieldSpec('容量', 'Cin1', 'F', required=True),
    'Rcin1': FieldSpec('等效串联电阻', 'ESRin1', 'Ω'),
    'ESLin1': FieldSpec('等效串联电感', 'ESLin1', 'H'),
    'Cin2': FieldSpec('容量', 'Cin2', 'F', enabled_by='cin2_enable'),
    'Rcin2': FieldSpec('等效串联电阻', 'ESRin2', 'Ω', enabled_by='cin2_enable'),
    'ESLin2': FieldSpec('等效串联电感', 'ESLin2', 'H', enabled_by='cin2_enable'),
    'C_out': FieldSpec('容量', 'Cout1', 'F', required=True),
    'Rc': FieldSpec('等效串联电阻', 'ESRout1', 'Ω'),
    'ESL': FieldSpec('等效串联电感', 'ESLout1', 'H'),
    'C_out2': FieldSpec('容量', 'Cout2', 'F', enabled_by='cout2_enable'),
    'Rc2': FieldSpec('等效串联电阻', 'ESRout2', 'Ω', enabled_by='cout2_enable'),
    'ESL2': FieldSpec('等效串联电感', 'ESLout2', 'H', enabled_by='cout2_enable'),
    'Vf_din': FieldSpec('未导入曲线时压降', 'Vf,in', 'V', enabled_by='d_in_enable'),
    'Rd_din': FieldSpec('动态电阻', 'Rd,in', 'Ω', enabled_by='d_in_enable'),
    'Vf_dout': FieldSpec('未导入曲线时压降', 'Vf,out', 'V', enabled_by='d_out_enable'),
    'Rd_dout': FieldSpec('动态电阻', 'Rd,out', 'Ω', enabled_by='d_out_enable'),
    'Vgs': FieldSpec('栅极驱动电压', 'Vgs,drive', 'V', required=True),
    'Rg_drive': FieldSpec('驱动器内部电阻', 'Rg,drive', 'Ω', required=True),
    'Rs_on': FieldSpec('外部开通电阻', 'Rg,on', 'Ω', required=True),
    'Rs_off': FieldSpec('外部关断电阻', 'Rg,off', 'Ω', required=True),
    'forward_dead_time': FieldSpec('驱动死区时间', 'tdead', 's', topologies=FORWARD_TOPOLOGIES),
    # Rs also contributes a loss in voltage mode; never hide it with PCM fields.
    'Rs': FieldSpec('采样电阻', 'Rsense', 'Ω'),
    'A_sense': FieldSpec('采样放大增益', 'Asense', '倍', required=True),
    # Vm participates in voltage mode and in the DCM current-mode plant.
    'Vm': FieldSpec('调制斜坡幅值', 'Vm', 'V', required=True),
    'ma_slope': FieldSpec('输入电流等效斜坡', 'ma', 'A/s'),
    'Bmax': FieldSpec('设计最大磁密', 'Bmax', 'T', required=True),
    'Bsat': FieldSpec('饱和磁密', 'Bsat', 'T'),
    'Ku': FieldSpec('窗口填充系数', 'Ku', ''),
    'Np': FieldSpec('原边匝数', 'Np', '匝', auto=True, topologies=ISOLATED_TOPOLOGIES),
    'Ns': FieldSpec('副边匝数', 'Ns', '匝', auto=True, topologies=ISOLATED_TOPOLOGIES),
    'd_wire_p': FieldSpec('原边单股线径', 'dp', 'm', auto=True, topologies=ISOLATED_TOPOLOGIES),
    'd_wire_s': FieldSpec('副边单股线径', 'ds', 'm', auto=True, topologies=ISOLATED_TOPOLOGIES),
    'n_strand_p': FieldSpec('原边并绕股数', 'np', '股', topologies=ISOLATED_TOPOLOGIES),
    'n_strand_s': FieldSpec('副边并绕股数', 'ns', '股', topologies=ISOLATED_TOPOLOGIES),
    'MLT': FieldSpec('每匝平均长度', 'MLT', 'm', auto=True),
    'Rth_transformer': FieldSpec('变压器至环境热阻', 'Ri-a', 'K/W', required=True,
                                 topologies=ISOLATED_TOPOLOGIES),
    'h_conv': FieldSpec('电感对流换热系数', 'h', 'W/(m²·K)',
                        topologies=('BUCK', 'BOOST', 'BUCK-BOOST', 'ACF-FORWARD')),
    'temp_rise_limit': FieldSpec('温升评审上限', 'ΔTmax', 'K'),
    'rho': FieldSpec('导线电阻率', 'ρ', 'Ω·m'),
    'k_core': FieldSpec('Steinmetz 系数', 'k', 'mW/cm³·kHz⁻α·T⁻β'),
    'a_core': FieldSpec('频率指数', 'α', ''),
    'b_core': FieldSpec('磁密指数', 'β', ''),
    'KP': FieldSpec('补偿器增益', 'KP', '', required=True),
    'fz1': FieldSpec('零点 1', 'fz1', 'Hz'),
    'fz2': FieldSpec('零点 2', 'fz2', 'Hz'),
    'fp1': FieldSpec('极点 1', 'fp1', 'Hz'),
    'fp2': FieldSpec('极点 2', 'fp2', 'Hz'),
}


def applicable(key: str, topology: str, control_mode: str) -> bool:
    """Whether a field belongs to the selected model, independent of folding.

    Only the CSA gain and current-equivalent compensation slope are exclusive
    to PCM.  No condition silently changes a stored parameter value.
    """
    field = META[key]
    if field.topologies and topology not in field.topologies:
        return False
    if key in ('A_sense', 'ma_slope'):
        return control_mode in ('Peak Current Mode', 'PCM')
    return True


def visible(key: str, topology: str, control_mode: str, advanced: bool,
            flags: Mapping[str, bool]) -> bool:
    """Model/option visibility, before applying fold and search UI state.

    ``advanced`` is accepted for API compatibility but no longer hides fields.
    """
    if key in ('Rd_diode','Rd_din','Rd_dout'):return False
    field = META[key]
    return (applicable(key, topology, control_mode)
            and (not field.enabled_by or bool(flags.get(field.enabled_by, False))))
