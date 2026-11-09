# 变压器磁导率与气隙估算

个人桌面和本地 Python 网页在磁件参数中提供 `mu_r`。`mu_r=0` 跟随材料手册初始磁导率，正数为用户指定的相对磁导率。内置示例统一使用 DMR44、μi=2400。有效磁路长度固定由 `le=Ve/Ae` 派生，在结果中只读显示，不再设置左侧输入。旧 `le_core` 字段保留读取兼容，但不覆盖 Ve/Ae。平均每匝线长 MLT 用于铜阻，气隙计算使用 le。

| 材料 | 初始相对磁导率 μi | 手册条件与公差 |
| --- | ---: | --- |
| N87 | 2200 | 25 °C，±25% |
| DMR44 | 2400 | 25 °C、10 kHz、B < 0.25 mT，±25% |
| PC40 | 2300 | 25 °C，±25% |
| 3C90 | 2300 | 25 °C、≤10 kHz、0.25 mT，±20% |
| 3F3 | 2000 | 25 °C、≤10 kHz、0.25 mT，±20% |
| N27 | 2000 | 25 °C，±25% |

Custom 和未知材料需要填写 μr。初始磁导率是在小信号下测得的材料参数，用于初版线性磁路估算。手动输入可用于厂家给出的相应工况参数，需自行保存其依据。μr 为无量纲相对值，真空磁导率 μ0 由程序使用 4π×10⁻⁷ H/m。

## 计算关系

磁芯与等效空气隙的磁阻串联，统一采用 SI。

```text
Rcore = le / (μ0 × μr × Ae)
Rgap  = lg / (μ0 × Ae)
Lm    = Np² / (Rcore + Rgap)
AL    = Lm / Np²
L0    = μ0 × μr × Ae × Np² / le
lg    = μ0 × Ae × Np² / Lm − le / μr
```

反激和准谐振使用输入的原边电感 L，正激变压器使用 Lm_forward。一次设计的输入电压与负载角点共用相同 Lm、匝数、μr、le 和气隙。正激的独立输出滤波电感使用既有电感模型。

若 Lm > L0，lg 的原始值为负，结果标记 `infeasible`，有效 `gap_m` 为 null，工程检查提示复核 μr、le、原边匝数和磁芯。Custom 未填写 μr 时标记 `unavailable`。只有磁路可实现时提供非负气隙值。结果状态表示当前线性估算覆盖范围。

## 三路 CCM 反激例程

使用 `examples/40W_CCM_3OUT_FLYBACK.json` 已确定的硬件。磁材为 DMR44、Np=6 匝、Lm=8 µH、Ae=62 mm²、Ve=2814.8 mm³。

```text
le = 2814.8 / 62 = 45.4 mm
μr = 2400
AL = 8 µH / 6² = 222.222 nH/匝²
L0 = 148.272 µH
lg = 0.350602 − 0.018917 = 0.331685 mm
```

20 V 和 30 V 两端输出相同的磁路结果。气隙是折算到 Ae 的总等效长度，单处中柱开隙可用作加工初值。整副磁芯垫开时，中心与外柱会同时形成气隙，需按实际截面积与磁路计算，不能把 lg 直接当作垫片厚度。边缘磁通、接合残隙、温度和偏磁会影响实物电感，加工时应按目标 AL 测量调整。

## 界面 报告和建模数据

磁件结果显示 μr 及来源、le 及来源、目标 AL、无气隙电感及等效气隙。Word 与 Excel 的磁件模块消费同一份 `gap_design`。公式说明与多路反激教程采用原生 Word 数学公式。

桌面报告用分组参数表显示磁芯、每个绕组、损耗温升及气隙，可拖动分隔条分配图表和报告宽度，报告区独立纵向滚动。结论置顶并加粗：绿色为通过、红色为超限、琥珀色为待复核。气隙估算可实现仍需按加工后 AL 测量核对；未计算项不会显示通过。本地 Python 网页使用同一份显示数据。

三维建模 ZIP 的 `design_targets.air_gap` 附带本次估算、来源和状态。实际磁芯磨隙/垫片及位置由建模设置的 `core.gap_geometry` 描述。只有补充实际加工方案与位置后，研究侧才能建立相应实体。已有 v1 包仍可读取。

## 原厂资料

- 有限磁导率气隙公式与边缘磁通说明见 TI UCC2863x SLUSBW3D，第 61 页式 45。[TI 数据手册](https://www.ti.com/lit/ds/symlink/ucc28630.pdf)
- 同一计算关系及近似式见 MPS AN069，§F-4 式 30–31。[MPS 应用笔记](https://media.monolithicpower.com/mps_cms_document/a/n/an069_r1.0_1.pdf)
- 中柱开隙与整副垫片的区别见 TI SLUP076，第 5 步。[TI 磁件设计说明](https://www.ti.com/lit/ml/slup076/slup076.pdf)
- N87、N27 的初始磁导率见 TDK 材料特性表。[N87](https://www.tdk-electronics.tdk.com/download/528882/3226013b0ed82a6a2af3666f537cbf83/pdf-n87.pdf) [N27](https://www.tdk-electronics.tdk.com/download/528850/3a7f957d754f899aec42cd946598c5c4/pdf-n27.pdf)
- DMR44 的初始磁导率与条件见 DMR44 Rev.B。[DMR44](https://www.dmegc.de/uploads/20230401/DMR44%20Material%20Characteristics.pdf)
- PC40 初始磁导率见 TDK 材料目录。[TDK](https://product.tdk.com/en/system/files?file=dam%2Fdoc%2Fproduct%2Fferrite%2Fferrite%2Fferrite-core%2Fcatalog%2Fferrite_material_characteristics_en.pdf)
- 3C90、3F3 初始磁导率见 Ferroxcube 材料规格页。[Ferroxcube 材料手册](https://www.ferroxcube.com/en-global/download/download/11)
