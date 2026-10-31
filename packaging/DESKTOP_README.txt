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
The supplied examples are calculation examples, not qualified hardware.
Existing calculation/model limitations and hardware verification apply.
