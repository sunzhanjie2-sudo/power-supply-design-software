"""Shared output/PSR display metadata; no GUI dependency."""
FIELDS = {
    'V_out':('端口电压（防反后）','V',1), 'P_out':('最大端口输出功率','W',1),
    'P_out_min':('最小输出功率','W',1),
    'C_out':('电容 A','μF',1e-6),'Rc':('ESR A','mΩ',1e-3),'ESL':('ESL A','nH',1e-9),
    'C_out2':('电容 B','μF',1e-6),'Rc2':('ESR B','mΩ',1e-3),'ESL2':('ESL B','nH',1e-9),
    'Vf_diode':('固定/换流 Vf','V',1),'Rd_diode':('整流 Rd（停用）','mΩ',1e-3),'Qrr':('整流 Qrr','nC',1e-9),
    'Vf_dout':('无曲线时防反 Vf','V',1),'Rd_dout':('防反 Rd（停用）','mΩ',1e-3),
    'ripple_target':('纹波目标','%',.01),'Ns':('副边匝数，0=自动','匝',1),
    'd_wire_s':('单股线径，0=自动','mm',1e-3),'n_strand_s':('单根线股数','股',1),
    'parallel_wires_s':('线圈并绕数（相同整根线）','根',1),
    'L':('正激输出电感','μH',1e-6), 'core_choice_L':('正激电感磁芯','型号',1),
    'psr_Na':('辅助绕组，0=自动','匝',1),'psr_aux_target':('辅助绕组目标电压','V',1),
    'psr_RfbH':('FB 上电阻','kΩ',1e3),'psr_RfbL':('FB 下电阻，0=自动','kΩ',1e3),
    'psr_Rreg':('SENSE 设置电阻','kΩ',1e3),'psr_Rcomp':('COMP 电阻','kΩ',1e3),
    'psr_Ccomp':('COMP 串联电容','nF',1e-9),'psr_Cpole':('COMP 并联电容','pF',1e-12),
    'psr_Vcc':('控制器供电 VCC','V',1),
}
