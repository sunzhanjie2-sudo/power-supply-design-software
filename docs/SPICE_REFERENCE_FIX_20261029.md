# 控制器参考按钮分支修复

## 用户报错原因

反激窗口点击“填入 MP6005 SSR 参考配置”时，报“请选择 LTC3864 参考 · Buck 峰值电流”。这是桌面回调的分支错误：在判断是否为 Buck/Boost 之前，就无条件调用非隔离原型解析函数。它将反激的峰值电流模式默认映射成 Buck 原型并因拓扑不符报错。

该调用是上次参考按钮改动中引入的回归。用户应按实际拓扑继续使用 MP6005 SSR、L6565 QR 或 MP6005 正激配置，不应根据这个误报把反激切成 Buck。

## 修复与验证

非隔离原型解析移入 Buck/Boost 分支。反激、QR、正激各自调用已有的参考值函数，不改变计算公式、SPICE 库或参数定义。

修复前新增实际 Tk 按钮测试，反激、QR、正激三个子工况精确复现相同错误；修复后六种拓扑/控制方式全部通过点击参考及应用按钮。

专项测试共 33 个方法通过：spice_ui_check 4、controller_logic_check 2、nonisolated_check 6、spice_export_check 10、qr_spice_check 4、acf_spice_check 7。覆盖 Buck/Boost 参考参数保留和实际工程导出，未重新运行不受此按钮分支影响的长时间原生 FRA。

日志在 `artifacts/qa/spice_reference_fix_20261029/`；新桌面程序在 `releases/Windows-x64/20261029-spice-reference-fix/`。网页版不调用此 Tk 回调，继续使用上一次网页包。
