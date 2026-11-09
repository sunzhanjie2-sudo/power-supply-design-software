# 示例器件初选与数据依据

2026-11-08：覆盖 `examples/` 内19份JSON，包括6个菜单示例、其他回归/兼容示例和两份系统工程内的单元。修改的是随软件交付的示例，不自动覆盖用户已保存的画布或工程。

## 在哪里看

加载示例后，在“关键器件BOM与降额”查看各位号厂家、订货型号、封装、耐压/纹波/功率及依据。Word/Excel的关键器件表消费同一份资料。新补的 `U_CTRL` 是控制器型号参考；图中独立框说明未展开引脚、驱动和偏置。PSR已有 `U_PSR` 不重复计件。

型号与计算标量一起更新：Q1的Rds、Qg/Qgs/Qgd、Vth、门限电荷、平台参考、内栅阻、Coss；正激Q2的辅助参数；各路二极管Vf及已知Qrr；每颗电容C/ESR/ESL；采样电阻；成品电感DCR/额定电流。输入两端采用同一份器件资料，不能在Vinmin/Vinmax悄悄换一组器件。

## 主要选型

| 场景 | 真实器件参考 | 采用条件和限制 |
| --- | --- | --- |
| 低压反激/正激主开关、Boost | Infineon BSC500N20NS3-G | 200V N沟道；10V驱动数据。MP6005若用10V需外部门驱动/偏置，不冒称内部8.5V直驱的保证值 |
| 两种Buck控制器原型 | Diodes DMP6023LE-13 | 60V P沟道；软件以电压/电流绝对幅值近似，图注说明极性。8V驱动例按4.5V保证点的Rds保守取值，Qg仍有测试条件差异 |
| MP6005 PSR直接8.5V驱动 | Vishay Si7450DP-T1-GE3 | 200V N沟道，采用6V保证Rds上限；8.5V电荷/平台存在图估读，非四事件独立实测 |
| 有源钳位Q2 | Vishay IRF9640PbF | 200V P沟道；负栅外驱动参考，恢复及真实电平转换未完整建模 |
| 高压QR与220V反激 | ST STP80N340K6 | 800V N沟道；Coss输入采用Co(tr)99pF时间等效常量，QR总有效C参数同步；未知绕组/布局电容未自动伪填 |
| 隔离低压整流/续流 | Vishay ES3D-M3/57T；ACF主路用STTH8L06D | 正激主路模型反压超过200V，采用600V整流/续流；其他低应力路用ES3D。副边各路Vf/Qrr独立绑定，未将MOS体二极管Qrr当整流管Qrr |
| Buck/Boost整流 | ST STPS5H100B-TR | 100V肖特基；未填的恢复/结电容表示未覆盖，不是物理为零 |
| 低压防反 | Vishay SS3H10-E3/57T | 100V/3A，最大压降参考；实际小电流压降应通过曲线进一步细化 |
| 高压整流/输入/RCD | STTH8L06D、STTH3R06S、US3M | 分别保留具体封装与测试电流/温度；反压仍需核对实测寄生尖峰 |
| 成品电感 | Coilcraft XAL7070-473MEC / -223MEC | 非隔离示例改为成品电感入口，感值保留47µH或22µH；Isat对应30%降感典型条件，模型不自动模拟L(I) |
| 5V→3.3V LDO | TI TLV75533PDBVR | DBV/SOT-23-5；压差、推荐输入、精度、热阻及外围条件按资料填入。热阻不是实板认证，空载IGND上限不能冒称满载保证 |

控制器采用 MP6005GK-Z/MSOP10、L6565D/SO8、TPS40200D/SO8、LTC3864EMSE#PBF/MSOP12、LM5022MM/NOPB/VSSOP10。控制模式和原工程频率等设定保持，通用行为控制器不会因填入型号而自动成为原厂精确芯片模型。

220V旧反激简规格中的MP6005仅作为当前通用算法原型；其VIN最高80V，不能接到220V母线，尚未完成实装控制器匹配，需要独立低压供电/启动/输入接口。TL431反馈参考的阴极也不能直接跨接60V输出，实际偏置与限流必须单独设计。

## 电容和电阻

- 330µF/50V采用 Panasonic EEUFR1H331L；220µF低压采用EEUFR1H221，QR60V输出采用100V的EEUFS2A221；470µF统一采用EEUFR1H471，50V/2.26A；100µF采用EEUFR1H101。440µF原聚合值拆成两颗220µF，BOM与计算列表同步。
- 高压输入10µF采用TDK B32774D4106K000/450V；低压10µF旁路采用B32522C0106K000/63V。后者缺公开单型号额定纹波，保持“待核”，不捏造能力。额定纹波只对应厂家规定频率/温度，不能无条件延伸。
- 220V旧反激简规格的输入电容由未明确选型的默认430µF改为两颗10µF/450V膜电容，总20µF；属于重新选型，不是同容量替换。跨调专例输入额外并联一颗330µF以改善纹波电流余量。470µF输出改为50V/2.26A的同容量FR型号。输入电容数量、容量及原厂额定变化均进入复算。
- 耦合反激与交叉调整率专例的OUT3原单颗470µF纹波仍超限，另加一颗同型号470µF并联，保留旁路膜电容，逐颗分流重新计算；不把降低ESR等同于电容电流必然变小。
- 电解ESR使用原厂100kHz阻抗上限作电阻代理，不冒充独立测量ESR；其中5nH ESL为工程假设。部分薄膜ESR/ESL为原厂典型值，另一些仍是假设，每条均区分。更准确的频率/偏压特性需要导入曲线或实测。
- 采样使用原厂有效阻值范围内的WSLP2010、WFM及Bourns PWR221T-30-R330F，保持原Rs。检查实际平均耗散≤额定20%。WFM端子温度条件和Bourns自由空气2.25W条件明确保留，不能套用散热器30W。
- RCD的R/C仍由现行K/Kc模型派生。PR03串联组合和标准nF高压膜电容只明确作为选型候选；若与派生值不一致，不宣称实装一致。PSR尚未落成标准值的补偿阻容也标为系列/派生参考。此部分不是完整可采购BOM。
- 自绕变压器和正激输出电感保留各例的磁芯、整数匝数、线材、并绕及排布，标为“项目定制绕制/DMEGC磁芯”。DMR44材料表与项目Steinmetz拟合/热阻假设分别说明，不编造商品变压器型号。

## 曲线、精度和验证

示例中原来没有绑定到新器件的匿名/演示MOS及二极管曲线已解除绑定，显式选择固定参考值；没有伪造任何自动提取曲线。历史原始输入保留在本轮验证资料中。平台、Qg(th)的图估读及测试电流/电压不匹配均写在器件条件里；相同参考平台用于四事件不表示四个工况都已测量。

本轮补的是工程初选数据。额定值存在不代表所有检查都通过。未知纹波额定、实际PCB散热、寄生尖峰、磁材损耗拟合、启动、驱动偏置和负载角点需要各自验证。之前QR联合报告的启动Vds超限与T1温升问题没有因为更新示例而自动解决；新器件配置不能沿用旧仿真结果宣称通过。

公式说明、教程与历史报告中的已冻结算例保留原输入和原结果；本次更换器件后，应从当前示例重新计算，不能直接套用历史数值。新示例的规格和绕组需求保持，派生电压、损耗、纹波与环路随真实参考参数变化。

数据维护入口：`resources/components/example_semiconductor_parts.json`、`example_passive_parts.json`、`example_support_parts.json`保存逐型号来源和条件；`tools/populate_example_parts.py`用于维护时显式生成，不在程序启动时更改用户工程。原厂PDF不混入程序包。

## 原厂资料入口

- [Infineon BSC500数据手册](https://www.infineon.com/assets/row/public/documents/24/49/infineon-bsc500n20ns3-g-datasheet-en.pdf)、[Diodes DMP6023LE](https://www.diodes.com/datasheet/download/DMP6023LE.pdf)、[ST STP80N340K6](https://www.st.com/resource/en/datasheet/stp80n340k6.pdf)。
- [Panasonic FR系列](https://industrial.panasonic.com/cdbs/www-data/pdf/RDF0000/ABA0000C1259.pdf)、[TDK B32774–778](https://www.tdk-electronics.tdk.com/inf/20/20/db/fc_2009/MKP_B32774_778.pdf)。
- [Vishay WSLP](https://www.vishay.com/docs/30122/wslp.pdf)、[Bourns PWR221T-30](https://www.bourns.com/docs/product-datasheets/pwr221t-30.pdf)、[Coilcraft XAL7070](https://www.coilcraft.com/getmedia/1ba55433-bcc8-4838-9b21-382f497e12e0/xal7070.pdf)。
- [TI TLV755P](https://www.ti.com/lit/ds/symlink/tlv755p.pdf)、[MPS MP6005](https://www.monolithicpower.com/en/mp6005.html)、[DMEGC DMR44](https://www.dmegc.de/uploads/20230401/DMR44%20Material%20Characteristics.pdf)。
