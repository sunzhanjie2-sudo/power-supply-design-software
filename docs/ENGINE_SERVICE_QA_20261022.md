# 内核接口整理验收记录

日期：2026-10-22。环境：Windows、Python 3.13；具体依赖见 `requirements*.txt`。

## 结论

多轮执行合并后，**27 个不同测试脚本的最终结果全部通过**。这不是宣称“一次执行无失败”：第一轮仍有一项旧测试只预期单工况导出，已按软件既有 Vinmin/Vinmax 行为修正并复测；历史失败日志保留。

| 范围 | 已验证内容 |
| --- | --- |
| 重构前基准 | 单路反激、Buck、DCM 反激、有源钳位正激、六路反激、三路耦合、MP6005 共 7 组指标保持一致 |
| 新服务合同 | 22 项测试通过；输入结构/单位、JSON Schema、所有权隔离、严格 JSON、来源信息、哈希、取消与旧 API 数值兼容 |
| 命令行 | 4 项测试通过；Schema/校验输出、错误退出码、真实快照和 Excel 导出 |
| 报告服务 | 最终 5 项测试通过；Word/Excel 实际导出不重算工作点/环路/检查，不修改快照；桌面调用共享服务；目标冻结、过期结果和无效参数处理 |
| 桌面与拓扑 | 已有工程评审、自定义磁芯、参数排列、输入范围、Excel 操作、六种拓扑保存回读继续通过 |
| 物理模型回归 | 效率预设、开关电荷、器件曲线、绕组耦合、磁件电参数、热阻/应力、多路环路与交叉调整率相关脚本通过 |
| 目录清理 | 临时曲线已移入正式 fixtures 并验证原文件哈希；耦合数值样例不再依赖导入 GUI 测试；补测两者通过 |

服务包单纯导入不加载 Tk、NumPy、SciPy、control、Matplotlib 或报告库；实际执行计算后也不会导入桌面 `main` 或 Tk。数值和报告库在需要时加载，不表示计算完全不需要这些依赖。

27 个脚本为：

```text
design_engine_check.py             engine_cli_check.py
input_voltage_range_check.py       api_check.py
forward_check.py                   efficiency_preset_check.py
gate_charge_check.py               diode_curves_check.py
mos_curves_check.py                mos_gate_charge_curve_check.py
winding_coupling_check.py           multi_output_check.py
multi_output_loop_check.py         cross_regulation_check.py
winding_electrical_check.py         thermal_stress_check.py
topology_calculation_check.py       engineering_check.py
custom_core_check.py               parameter_reorg_check.py
input_range_ui_check.py            excel_ui_check.py
engine_report_service_check.py     excel_report_check.py
input_range_report_check.py        coupled_integration_check.py
mos_simple_report_check.py
```

## 本地原始记录

路径均在 `artifacts/checks/`，每个目录有脚本日志和 `summary.json`：

- `20261022-212627`：首次广覆盖，24 个脚本；包含上述旧断言失败。
- `20261022-213427`：修正后的关键复测，8 个脚本通过。
- `20261022-213917`：服务/CLI 最终复测，以及耦合、迁移曲线报告补测，4 个脚本通过。
- `20261022-214141`：报告服务与输入范围界面的最终复测，2 个脚本通过。

日志是本地产物，不加入 Git。可再次运行 `python tools/check_engine.py --gui --reports` 生成新记录；不要把不同模型版本的结果直接合并成一次测试。

## 未宣称完成的事项

没有建立网页、HTTP 服务或公网部署；没有重打包 EXE；没有新增仿真软件连接器；没有改变电气公式或证明模型实测误差。快照 JSON 当前是审计记录，不是 Python 运行时对象的无损恢复格式。详见 `ENGINE_SERVICE.md` 的边界说明。
