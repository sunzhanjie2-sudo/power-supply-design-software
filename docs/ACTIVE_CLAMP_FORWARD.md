# 有源钳位正激：使用与计算范围

本次实现为低侧钳位的有源钳位正激（ACF-FORWARD），次级采用一只正向整流二极管和一只续流二极管。不是高侧钳位版本，也不是同步整流版本。

## 使用示例

源码运行 `python main.py`，在文件菜单选择“示例: 40W 有源钳位正激”。也可以打开 `examples/40W_ACF_FORWARD.json`。导入其它反激配置后切换拓扑时，必须重新设置输出电感和独立励磁参数。

示例沿用用户 40W CCM 反激的输入/输出/功率/频率、匝比和输入输出电容银行。未修改原配置文件。

| 参数 | 值 | 说明 |
|---|---:|---|
| Vin / Vout / Pout / fs | 30V / 30V / 40W / 250kHz | 与反激相同 |
| N = Np/Ns | 0.5 | 沿用6:12；实际匝数与Lm需按磁芯复核 |
| L | 68µH | 输出滤波电感，不是励磁电感 |
| Lm_forward | 220µH | 变压器励磁电感，独立输入 |
| C_clamp / ESR_clamp | 47nF / 30mΩ | 低侧钳位电容 |
| forward_d_max / forward_dead_time | 0.70 / 80ns | 占空比上限与死区可行性检查 |
| Rds_aux / Qg_aux / Coss_aux | 100mΩ / 10nC / 200pF | 辅助MOSFET估算参数 |
| fc / PM | 3kHz / 60° | 峰值电流模式预设补偿器目标 |

原反激的8µH励磁电感不适合作为该正激示例的输出电感，因此未照搬。示例只是计算起点，不代表器件、变压器励磁电感或ZVS已经验证可行；包括AL/磁导率、实际匝数、气隙、绕组布置、温升、死区和寄生参数，均需要选型与实物测量。

## 页面联动

- ① 输出电感CCM/DCM、占空比、主MOSFET/整流电流、纹波与常规设计检查。
- ② 主/辅助MOSFET及正向/续流二极管应力；损耗包括辅助管与续流管，选型考虑峰值电压裕量。
- ③ 变压器与独立输出电感的磁通、磁损/铜损、温升与填充率；输出电感可单独选择磁芯。
- ④ 低频VM/PCM环路近似、自动整定和钳位谐振带宽建议。
- ⑤ 总损耗、效率与扫描，包含钳位电容ESR，不计反激RCD电阻。
- ⑥ 输入/输出电容总RMS及各电容的频带RMS小图。
- ⑦ 自动从RCD页面切换为有源钳位电压、励磁电流、复位电压、钳位电容检查。
- ⑧ 继续使用现有环路补偿网络参数转换。

## 模型公式与假设

定义 `N=Np/Ns`，次级主导通电压 `Vs=Vin/N`。2026-10-11 起统一采用预设效率的一阶等效负担 `U=Vout/eta_guess`，保持 `Io=Pout/Vout`；预算已含整流损耗，不再另加旧 `Vf`。真实器件压降仍计入最终损耗；该模型不是逐器件非理想仿真。

CCM时：

```text
D = U / Vs
ΔIL = (Vs - U) D / (fs L)
Vclamp = Vin / (1-D)            低侧钳位电容稳态电压
Vreset = Vclamp - Vin           变压器原边反向复位电压
ΔImag = Vin D / (fs Lm)
Imag_pk = ΔImag / 2             理想对称励磁电流
i_main = iL/N + i_mag           主开关导通段
i_aux = i_mag                   复位段，理想化
ΔB = Vin D / (fs Np Ae)
Bpk = ΔB/2                     对称复位的正激变压器
```

轻载DCM按输出电感三角电流与负载平均值求D及续流时间；输出电感归零之后，变压器仍在整个OFF段复位。变压器励磁电流与输出电感电流分开计算。

采用TI小纹波近似的钳位电压隆起和谐振建议：

```text
Vhump = Vin D (1-D) / (8 Lm fs² Cclamp)
fres = 1 / (2π √(Lm Cclamp))
feffective = (1-D) fres
fc_recommended_max = min(fs/10, feffective/5)
```

示例结果约为D=0.512、Vclamp=61.4V、输出电感电流纹波0.883A、fc建议上限4.83kHz。自动整定会下调超过建议上限的目标fc；手动设置不会被无提示覆盖。配置保存/读取保留fc。

增大Cclamp会降低电压隆起，但也会降低谐振频率和建议环路带宽，不是越大越好。钳位隆起超过10%会提示小纹波近似不足；Cclamp最小值检查以隆起≤稳态钳位电压的5%为目标。

### 不包含的现象

- 未模拟漏感/Coss换流、体二极管、真实死区、钳位谐振的完整时域过程和非线性Coss。死区只做输入可行性与比例提醒，不改变有效D。
- 不默认判定ZVS；主开关保留硬开通/Coss损耗估算，辅助管计算导通、栅极及保守Coss损耗，未完整模拟辅助管换流重叠损耗。
- 环路按次级折算Buck派生模型，仅用于低于钳位谐振频率的初步估算；VM包含单输出电容的ESR，PCM和DCM为更简化近似，不包含完整并联电容/寄生网络。
- K因子整定在所选穿越点匹配目标；若有多个0dB穿越点，单一PM不代表完整稳定性保证，需检查全部穿越及Nyquist/开关级仿真。API同时给出下降穿越点列表。
- 总效率仍是主要损耗模型值，不是实物效率；控制/辅助电源、布局、温度、EMI等损耗和尖峰需要另外验证。

## 原始资料

- [TI SLUA535A：Understanding and Designing an Active Clamp Current Mode Controlled Converter Using UCC2897A](https://www.ti.com/lit/an/slua535a/slua535a.pdf)：第2节运行过程，第4.3节钳位电容，第6节电流模式环路与谐振带宽。
- [TI SLUP262：Incorporating Active-Clamp Technology to Maximize Efficiency](https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/234/slup262.pdf)：式3主/辅助管阻断电压、式11谐振频率、式12钳位隆起。

## 验证

```text
python tests/quick_check.py
python tests/api_check.py
python tests/forward_check.py
python tests/gui_chart_check.py --out _tmp_chart_qa/forward
```

新增回归覆盖伏秒平衡、CCM/DCM平均/RMS电流、输入功率平衡、钳位电容缩放、双磁件/四器件损耗加总、保守ZVS口径、VM/PCM整定、非法输入。GUI测试渲染实际图表、检查配置回读，并刷新全部八页。
