"""Explicit settings used by the L6565-inspired, event-driven QR model."""
QR_SETTINGS = {
    'qr_cds_pf': (470., 0., 100000., '漏极有效谐振电容，0=使用设计 Coss', 'pF'),
    'qr_aux_ratio': (.1, .001, 2., 'ZCD 辅助绕组匝比 Naux/Np', ''),
    'qr_zcd_r': (22000., 1., 1e7, 'ZCD 串联电阻', 'Ω'),
    'qr_zcd_c_pf': (5., .1, 10000., 'ZCD 等效输入电容（假设）', 'pF'),
    'qr_zcd_delay_ns': (-1., -1., 10000., 'ZCD 附加延时，-1=四分之一谐振周期估算', 'ns'),
    'qr_zcd_arm_v': (2.1, .3, 5., 'ZCD 上升沿预备阈值', 'V'),
    'qr_zcd_trigger_v': (1.6, .25, 4.9, 'ZCD 下降沿触发阈值', 'V'),
    'qr_off_min_us': (3.5, .1, 100., '重载最短关断消隐时间', 'µs'),
    'qr_off_light_us': (18., .1, 200., '轻载关断消隐时间（COMP=2.5 V）', 'µs'),
    'qr_starter_us': (400., 20., 2000., '无 ZCD 时启动定时器', 'µs'),
    'qr_vcc_v': (15., 10.4, 18., '外部理想 VCC 供电', 'V'),
    'qr_uvlo_on_v': (13.5, 10.4, 18., 'VCC 启动阈值', 'V'),
    'qr_uvlo_off_v': (9.5, 1., 15., 'VCC 关断阈值', 'V'),
    'qr_vff_v': (0., 0., 2.9, '线电压前馈 VFF（固定测试值）', 'V'),
    'qr_cs_clamp_v': (1.4, .01, 2., 'VFF=0 时逐周期 CS 钳位', 'V'),
    'qr_ocp_v': (2., .1, 5., '异常 CS 故障锁存阈值', 'V'),
    'qr_max_on_us': (100., 1., 1000., '最长导通看门狗（模型安全约束）', 'µs'),
}
COMMON = {'blanking_ns','min_on_ns','delay_ns','driver_resistance','soft_start_ms',
    'stop_ms','step_ms','load_after','feedback_scale','cs_filter_ns','kp','fz1','fp1','fz2','fp2',
    'include_cap_esl','diode_cj_pf','short_test','short_output','short_start_ms','short_duration_ms',
    'short_resistance','simulation_timeout_s','simulation_threads','comparison_tolerance_pct',
    'cycle_tolerance_pct','fra_enabled','fra_start_hz','fra_stop_hz','fra_oct','fra_amplitude_pct',
    'fra_cycles','fra_timeout_s'}


def applicable_keys(topology):
    from spice_export import ordered_setting_keys
    if topology=='QR-FLYBACK':return [k for k in ordered_setting_keys() if k in COMMON or k in QR_SETTINGS]
    keys=[k for k in ordered_setting_keys() if k not in QR_SETTINGS and (topology=='ACF-FORWARD' or not k.startswith('acf_')) and (topology in ('BUCK','BOOST') or not k.startswith('niso_'))]
    if topology in ('BUCK','BOOST'):
        hidden={'comp_offset_v','feedback_scale','short_output','cross_enabled','cross_mode','cross_hold_ms','cross_timeout_s'}
        hidden.update({'niso_lm_cs_resistor'} if topology=='BUCK' else {'niso_ramp_ratio','niso_ith_gain'})
        keys=[k for k in keys if k not in hidden]
    return keys


def l6565_preset(current=None):
    from spice_export import normalize_settings
    s=dict(current or {})
    s.update({k:v[0] for k,v in QR_SETTINGS.items()})
    s.update(soft_start_ms=20.,step_ms=80.,stop_ms=100.,blanking_ns=50.,min_on_ns=100.,
        delay_ns=200.,driver_resistance=3.,cs_filter_ns=200.,fra_start_hz=100.,fra_stop_hz=4000.,
        fra_cycles=300.,fra_enabled=1.,cross_enabled=0.,short_mode=0.,frequency_hz=0.)
    return normalize_settings(s)
