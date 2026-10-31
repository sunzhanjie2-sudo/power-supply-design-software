# Buck / Boost 环路显示修复 · 2026-10-29

## 原因

用户截图中的 `'feedback_output'` 是程序字段访问错误。新 Buck/Boost 模型在环路元数据中明确记录 `feedback_output=1`，单路工作点没有多路输出字段。桌面环路页错误地从工作点强制取值，在说明文字生成阶段触发 `KeyError`，随后错误处理清空了已经计算成功的频响。

因此这次提示不能解释为参数错误、环路不稳定或自动整定不可行。

## 修复

- 桌面从环路模型元数据读取反馈路编号，兼容旧单路工作点；显示“反馈路：OUT1”。
- 共用模型元数据与多路输出能力分别判断：仅多个输出时生成各路响应数据和界面切换。
- 报告摘要支持只有一个输出的物理模型，缺少负载响应矩阵时记为空值。
- 窗口版本文字改为“V0.0.0 · 20261029 环路修正版”，便于辨别运行包。

没有调整周期求解、功率级状态方程、补偿器公式及元件配置；本次未重新运行耗时的 LTspice FRA。

## 源码验证

先用原界面复现，断言失败信息正是 `'feedback_output'`。修复后通过以下 45 个测试方法：

| 脚本 | 数量 | 范围 |
|---|---:|---|
| nonisolated_desktop_loop_check.py | 1 | 实际 Tk 界面；三种原型 × Vinmin/Vinmax；打开、重绘、整定、四图数据、缺失字段兼容及单路隐藏切换 |
| nonisolated_check.py | 5 | 数值边界、两颗电容、六组工况、模型及报告 JSON 序列化 |
| nonisolated_report_check.py | 1 | 三种原型各导出双输入端点 Word/Excel，共六份文件 |
| multi_output_loop_check.py | 17 | 原有多路矩阵、反馈、稳定性与响应 |
| multi_output_loop_ui_check.py | 4 | 原有多路后台计算、视图、整定与失败处理 |
| example_catalog_check.py | 4 | 示例入口与载入 |
| qr_loop_check.py | 4 | QR 模型回归 |
| output_capacitors_check.py | 9 | 并联 C/ESR 状态与阻抗 |

GUI 图形证据：`artifacts/qa/loop_ui_fix_20261029/boost_loop_fixed.png`。测试日志在同一 QA 目录及 `artifacts/qa/nonisolated_desktop_loop_green.log`。

最终便携包位于 `releases/Windows-x64/20261029-loop-ui-fix/`；其中《验证说明.md》记录冻结程序和归档验证结果。
