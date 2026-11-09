Power Design - Desktop - Windows x64

Copy this ENTIRE folder to a Windows 10/11 x64 computer.
Double-click SwitchingPowerSupplyDesign_V0.exe.
The first screen is the editable system power-tree workspace. Add sources
and converter nodes, connect OUT to IN, and double-click a converter to
open the full calculator. Return to architecture saves the unit parameters.
Save a system JSON to keep all units, connections and node positions.
Original single-converter JSON files can also be imported.
OR-network edition: add named loads and diode-OR buses. Each output may
feed many modules/loads; each input may have multiple diode-isolated
branches. Select a connection to edit Vf or disable it.
System reports include topology and budgets.
Canvas Studio: all node types and diode cards can be dragged. Ctrl+wheel
zooms; drag blank canvas to pan; Fit Canvas shows the whole network.
Diode positions are saved with the system JSON and used in report diagrams.
Choose UI Font Size at the top; the preference is remembered locally.
The fixed blue Save Node/Branch Changes button commits property edits.
Save System Project exports the full JSON. Dragging updates only nearby wires.
Python, Node.js and Internet access are NOT required.

LDO edition: Add LDO opens an independent linear design.
Connect its input and loads, then enter voltage, current, dropout, Iq and
thermal conditions. Return saves unit parameters. LDO Word/Excel/JSON and
system reports use the same static model. See docs/LDO_DESIGN.md.

Do NOT copy only the EXE: the _internal folder is required.
Built-in examples, diagrams, documentation and report dependencies are
included. Word/WPS/compatible software is needed to read DOCX reports;
Excel/compatible software is needed to view XLSX. Export does not require
an Office installation.

Save your configuration/report in your own writable folder.
File > LTspice: configure frequency, soft start, Vcs and protection; export
native ASC or run the simulation/design comparison (Word + project ZIP).
Comparison requires LTspice installed separately; select LTspice.exe in
the settings dialog. MP6005 SSR is a configurable reference, not a full IC.
Export Reports > Joint Simulation combines transformer fields, leakage
margin, fixed-hardware design calculation and LTspice in one Word report.
Tool/model settings and independent debug exports share one centre.
Transformer fields require the separately configured local extractor and
Elmer. The default leakage factor 1.20 is an editable project assumption.
Automatic adoption affects the export copy; adopting into the current
canvas remains an explicit action. See docs/JOINT_SIMULATION.md.
The supplied examples are calculation examples, not qualified hardware.
Existing calculation/model limitations and hardware verification apply.
联合仿真便携配置：
程序已内置变压器提取内核，不需要安装Python或另带研究工程。
首次在“导出报告→联合报告→工具与模型”选择完整Elmer安装目录、LTspice及磁芯STEP/BREP。
磁芯装配、r0/z0与CAD坐标首次核对后可导出模型配置包，带到其他Windows x64电脑导入。
当前工程提供窗口、匝数、线材、层序、材料/磁导率、接线和气隙，提取JSON自动生成。
完整复制本程序目录及_internal；只读安装位置请用模型配置包带走用户目录中的CAD。
详见 _internal/docs/PORTABLE_SIMULATION.md；环境检查不代表场解收敛或方案合格。

