# 可配置控制器与仿真对比核对

日期：2026-10-24；模型 GenericFlybackPWM-2.0；本机 LTspice 24.1.9。发布目录为 releases/Windows-x64/20261024-spice-controller-v2/，历史版保留。

## 真实瞬态结果

| 工况 | 仿真终点 | OUT1 平均电压 | 实际频率 | 完整性 |
|---|---:|---:|---:|---|
| 默认单路 + MP6005 SSR 参考，30 V | 18 ms | 29.99909 V | 250000 Hz | RAW 与 .meas 完整 |
| 用户 40W CCM 多路配置，20 V | 18 ms | 29.99521 V | 249999.91 Hz | RAW 与 .meas 完整 |
| 用户 40W CCM 多路配置，30 V | 18 ms | 29.99793 V | 250000 Hz | RAW 与 .meas 完整 |
| 原生三路 ASC，30 V | 18 ms | 29.99874 V | 250000 Hz | MCP 实际运行完整 |

前三项由应用的实际仿真流程直接调用本机 LTspice，Word/ZIP 中保留真实日志及 comparison.json。三路 20 V 时非反馈 OUT2/OUT3 约 12.08156 / 3.91908 V；30 V 时约 11.92203 / 3.87262 V。没有强制非反馈路为名义电压，偏差按真实结果标注，不能认为全部指标达标。

原生三路整机将 CS 限流阈值降至 80 mV 构造过载：约 9.99576 ms 触发故障关断，SS 随之复位。18 ms 的观察时间不能覆盖参考值 340 ms 关断后的重启，不宣称已完成该整机时长的验证。

## 独立保护台架

使用 tests/fixtures/spice_protection.cir，三组真实瞬态：SCP 打嗝、SCP 锁存、持续 OCP 触发 OLP。故障期间 FAULT=1；打嗝模式期满清零、锁存模式保持；关闭 EN 后清零；恢复 EN 后 SS 可重新完成。

台架为加速检查，将 TOFF 缩放到 2 ms、TOLP 缩放到 0.2 ms。验证的是状态转换，而不是声称 MP6005 完整内部实现或 340 ms 的实测时序。软件预设 TOFF=340 ms，独立 SCP 消隐标为模型假设。

## 电路、应用与报告

- 原生 1、3、6 路 ASC 的符号、连接布局与网表导出检查无失败；三路为 33 个元件、57 段连线，六路为 51 个元件、87 段连线。ASC 不是只显示控制器的占位图。
- 导出检查 10 项；RAW/日志/取消/缺少仿真器及结果合同检查 5 项；桌面独立窗口设置、保存与后台导出通过；Web 23 项合同、进程、绘图与既有报告检查通过；Vue 类型检查和构建通过。
- 引擎、CLI、输入范围及共用报告服务回归通过；没有更改电源设计物理公式或另建 JS 计算内核。
- Word 用原生 OMML 公式，保留真实 .meas 指标和 RAW 概览。缺测、失败、未稳态、保护和不同口径明确区别；尖峰/纹波不做机械百分比验收。样例经独立 LibreOffice 渲染逐页检查。

证据在 artifacts/qa/spice-controller-v2/；原生 ASC 与保护整机证据在 <本机路径，不随源码分发>。大 RAW 不放入发布包，报告 ZIP 自带可复现工程与日志。

## 复现入口

```powershell
.venv-web/Scripts/python.exe tests/spice_export_check.py
.venv-web/Scripts/python.exe tests/spice_runtime_check.py
.venv-web/Scripts/python.exe tests/spice_ui_check.py
.venv-web/Scripts/python.exe tests/web_app_check.py
.venv-web/Scripts/python.exe tools/qa_spice_controller_v2.py --multi "用户多路配置.json"
```

仿真对比需要已安装 LTspice；导出文件、查看既有报告不需要安装 Python、Node 或 MCP。通用固定频率 SSR 行为模型，不包含完整 MP6005 PSR、实际光耦/TL431、非线性磁芯、完整器件反向恢复或自动 FRA。
