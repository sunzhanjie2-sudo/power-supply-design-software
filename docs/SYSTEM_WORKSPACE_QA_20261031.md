# 系统架构版验证记录

验证对象：`releases/Windows-x64/20261031-system-workspace/`，Windows 11 x64 本机。未冒充另一台实体电脑的兼容性验证。

- `system_workspace_check.py` 四项通过：旧配置与补偿元数据往返、级联功率预算和输入同步、循环拒绝、输出端口减少后的下级保留，以及实际 Tk 计算器多次打开与返回。测试包含反激和 Buck 独立参数。
- `pcs_workspace_check.py` 六项通过；共享网页框图模型检查通过。
- `web_app_check.py LocalSecurityChecks MetadataAndCurveChecks` 十三项通过，本机令牌、请求来源、白名单与曲线参数规则保留。
- `system_workspace_browser_check.cjs` 真实 Edge 通过首页、拖动连线、电压同步、两个完整计算器、删除撤销和 JSON 保存重开。报告测试实际输出两单元、四个输入端点的完整 Word/Excel；清单中两个单元均完成，电压接口不匹配仍明确列出。
- 系统总览 Word 用独立后台 LibreOffice 渲染并核对两页，无截断或表格干涉。
- `package_check.py` 验证桌面 EXE 首屏、22项资源及退出；本轮启动至响应窗口约0.75秒，首屏稳定后进程约59.7MiB。是本机本轮结果，不代表冷磁盘或不同电脑指标。
- `web_package_check.py` 验证冻结程序在隔离 PATH、中文工作目录下的真实计算、六类图表、补偿图、Word/Excel、内置文档、ASC 和实际 LTspice 对比。
- 用 computer-use 实际操作本批打包 EXE：点击节点进入完整计算，确认计算结果和拓扑页，点击“返回系统架构”后显示“单元设计已回存”，最后关闭本轮测试程序。测试使用独立数据目录。

主要证据位于 `artifacts/qa/system_workspace_20261031/` 与 `output/playwright/system-workspace/`；它们是可重建的本机 QA 产物，不混入运行包。原有电气模型边界保留，架构连接不构成整机动态仿真。
