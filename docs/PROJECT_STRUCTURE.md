# 项目结构与源码维护

本仓库保存个人电源计算器的源码、算例、计算说明与运行资源。目录均相对于仓库根目录，不依赖作者的磁盘路径。

| 路径 | 职责 |
| --- | --- |
| `desktop_entry.py`、`main.py` | 桌面系统画布与单元设计入口 |
| `design_engine/` | 数据合同、计算调度与结果快照 |
| `power_stage.py`、`loss_model.py`、`plants.py` | 功率级、损耗与小信号模型 |
| `system_workspace.py`、`power_network.py` | 供电架构与预算 |
| `shared/power_architecture.js` | 个人网页版共用的图形与连接交互 |
| `web_app/frontend/` | Vue 界面与 TypeScript 计算模块 |
| `resources/`、`examples/` | 参考图、SPICE 资源与可复用配置 |
| `docs/`、`tests/` | 说明、教程和回归检查 |
| `packaging/`、`tools/` | 构建配置与维护脚本 |

## 开发入口

桌面运行 `python desktop_entry.py`。本地网页版先执行 `tools/setup_web.ps1`，再运行 `python run_web.py --open`。依赖清单与完整命令见根目录 README。

前端在 `web_app/frontend` 执行 `npm ci`、`npm run build`。计算模型放在内核模块中，界面消费计算快照，不应在图表或组件里另写一套不一致的公式。

## 发布

`tools/build_release.ps1 -Target all -ReleaseId <新版本号>` 生成独立 Windows 运行包。已有版本不会覆盖；复制完整程序文件夹，保留 `_internal`。`tools/release_manifest.ps1` 校验文件，`tools/zip_release.ps1` 生成 ZIP。

`releases/`、`artifacts/`、`output/`、`user_data/`、虚拟环境和个人设置不进 Git。第三方资料、独立子项目、外部组织的部署与验收资料不属于本公开仓库。公开版本只保留已获得授权的通用画布代码，其他集成材料继续在本地维护。

## 验证

修改数值模型时先运行对应拓扑、损耗、环路或磁件检查，再验证图表和报告。修改界面依赖时执行前端构建与相关画布检查。发布前核对运行包模块、资源与源码；仿真、实测及工程验收应分别记录。
