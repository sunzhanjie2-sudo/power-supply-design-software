# 第二阶段：本地网页版入口

本阶段新增本机浏览器工作台，继续复用第一阶段的 `design_engine`，不发布公网，不替换原桌面 EXE，也不另写一套 JavaScript 电气公式。

项目位置：`<本机路径，不随源码分发>`。

完整的启动、单位 / 曲线导入、报告、临时数据、多窗口行为、API 与限制说明，统一维护在 [web_app/README.md](../web_app/README.md)。

## 快速启动

首次在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\setup_web.ps1
```

随后双击根目录的 `启动网页版.cmd`，默认打开 `http://127.0.0.1:8765`。保留启动窗口；按 `Ctrl+C` 停止。首次依赖安装需要可访问软件包源，日常计算与导出在本机完成。

## 本阶段交付边界

- 左侧适用参数、多路输出与器件曲线入口，右侧模块结果及 Vinmin / Vinmax 工况切换。
- 已补齐自动整定、四类补偿网络正反推与电路参考图、效率扫描 / 目标查找 / 小预算优化、固定硬件角点和冻结 A/B；候选显式应用后仍需重算。
- 磁件页可编辑疏密绕、利兹线、分束、绝缘和交错层序；补充器件应力、电容频带、磁通 / 饱和、MP6005 与 RCD / 有源钳位结果。
- 支持 16 / 18 / 20 字号、导入 / 已存曲线预览、二极管按位号显式复用，以及下载内置 Word 公式说明。
- FastAPI 本机传输、独立串行数值进程、按需图表、共用快照的 Word / Excel / JSON 导出。
- 修改参数需重新计算；关闭服务前应保存配置并下载所需报告。一个服务共用一个最新作业，不支持多用户或多窗口独立设计会话。
- 新增角点 / A/B 表格与图表尚未追加进原 Word / Excel 报告章节；A/B 可另存 JSON，刷新浏览器会清除尚未另存的冻结方案。不声明完全覆盖 EXE，差异见 [桌面与网页功能核对](WEB_DESKTOP_PARITY_20261023.md)。

## 相关入口

- 共用计算接口与 JSON 约定：[ENGINE_SERVICE.md](ENGINE_SERVICE.md)。
- Web 无浏览器检查：根目录运行 `.\.venv-web\Scripts\python.exe -X utf8 .\tests\web_app_check.py`。
- 高级动作检查：`.\.venv-web\Scripts\python.exe -X utf8 .\tests\web_actions_check.py`；真实 Vue 挂载交互检查位于 `web_app/frontend/tests/`。
- 前端类型检查 / 构建：进入 `web_app/frontend`，运行 `npm.cmd run check` / `npm.cmd run build`。
- 当前功能补齐的实际测试与浏览器记录：[网页补齐验收](WEB_PARITY_QA_20261023.md)。

本文件仅提供入口，不重复维护使用细节或未经验证的性能、测试通过数量。
