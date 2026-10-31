# 图表 DPI 与 B 轴显示修正

运行包：`releases/Windows-x64/20261031-chart-ui-fix/`。桌面窗口标题包含“图表DPI与B轴修正版”。字号仍为12–40px，每档2px。

## 三项修正

1. **B 轴使用实际摆幅。** 纵轴覆盖所有当前 B(t) 波形的最小值和最大值，并留15%摆幅边距；恒定磁密使用小范围显示。不会为显示 ±Bsat 强行引入大段负值区域。限值落在图外时仍保留数值提示；超限区域和超限文字继续显示。桌面、本地网页及新导出 Word 图使用同一范围逻辑。
2. **修正总览波形过扁。** 应用窗口尺寸和字号使用原生像素，图表不再额外叠加 Tk 的高 DPI 比例。总览绘图区保留最小高度，窄窗口通过换列和滚动保留可读性。
3. **修正多路标题逐次放大。** 每路图表滚出视口后会释放并重建 Canvas；原 Matplotlib Canvas 初始化会把已经放大的 DPI 再记录为新基准。现在为 Figure 保留固定基准 DPI，反复滚动、切页、重建均不再累乘。字号调整后重新计算分路标题、图例和页脚的空间。

这次不修改 B(t)、匝数、电流、损耗、控制环路或任何电气计算。Bsat 仍按输入值参与原检查，图轴缩放仅改变显示。

## 验证

- `tests/canvas_resources_check.py`：模拟150%缩放并反复释放/重建图表，DPI保持100，文字高度不增长；原缓冲释放、合并重绘和PNG导出检查继续通过。
- `tests/canvas_edit_check.py`：有直流偏置、双极性、恒定及超限磁密的图轴范围；20/32/40px下总览每张绘图区大于120px，分段标签不重叠。
- `tests/multi_output_lazy_check.py`、`multi_output_results_check.py`、`multi_output_charts_check.py`：输出数据/损耗账本一致、六路可达、只分配可见图表、窄窗和重复绘制。

实现位置：`resource_canvas.py` 管理像素/DPI生命周期，`magnetic_plot.py` 管理 B 轴显示，`multi_output_charts.py` 和 `multi_output_results.py` 管理分路图排版。日志位于 `artifacts/qa/chart-ui-*.log`。
