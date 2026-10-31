# 自适应布局与大字号

当前运行包：`releases/Windows-x64/20261031-adaptive-layout/`。桌面运行 `PowerDesignDesktop/SwitchingPowerSupplyDesign_V0.exe`，本地网页运行同级 `PowerDesignWeb/StartWeb.cmd`。

- 桌面参数区在折叠、筛选或窗口变化后重新核对内容高度；内容不足一屏时回到顶部，不保留负滚动原点。长参数表继续滚动，折叠状态不影响计算参数。
- 功率级、器件及电容总览图利用页面剩余高度。功率级根据宽度及字号使用三列、两列或单列；开通/关断标题分两行。图中文字跟随界面字号，多路输出卡片继续按可见区域绘制。
- 桌面和本地网页的字号范围均为12–40px，步长2px。偏好独立保存，不写入设计 JSON，不改变电气计算；旧字号会就近转为有效档位。
- 大字号下桌面工具栏可以换行，左侧参数栏适当加宽。网页输入框同步增高，参数行可换行，导航保留紧凑字号。4K 屏幕可先试24、28或32px，再按观看距离调整。

修正位置：`engineering_ui.py` 与 `parameter_panel.py` 管理参数滚动；`multi_output_results.py` 管理图表尺寸和文字；`main.py` 管理计算器标题栏。字号由 `ui_preferences.py` 及网页 `ui-font.ts` 管理。

回归包括折叠后顶部坐标、图表填满高窗口、12/28/40px参数标签不干涉、配置参数不变、13项通用滚动、8项延迟绘制及5项多路真实图表检查。最终网页需同时核对40px输入框与字号恢复；具体日志位于 `artifacts/qa/adaptive-*.log`。
