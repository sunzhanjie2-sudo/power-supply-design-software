"""Shared engineering scope notes for GUI and both report formats."""

DIODE_STRESS_NOTE = ('整流二极管反压未考虑寄生尖峰应力，具体应力需实测；'
                     '建议选型时留有耐压余量，并核对温度降额及反向恢复。')
FLYBACK_STRESS_NOTE = ('反激 MOS 钳位应力上限按 Vin + Kc×Vreflect 计算，'
                       '不再叠加振铃裕度；波形峰值可低于此上限。'
                       'Kc 为钳位电压与反射电压之比，不是 MOS 耐压降额系数；实际尖峰需实测。')
