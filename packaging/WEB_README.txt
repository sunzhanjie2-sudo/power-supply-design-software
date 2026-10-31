Power Design - Local Web - Windows x64

Copy this ENTIRE folder to a Windows 10/11 x64 computer.
Double-click StartWeb.cmd. Python and Node.js are NOT required.
The browser starts at an editable system architecture. Connect sources
and converter nodes; double-click a converter for its complete design.
Return to architecture retains its settings. Save the system JSON to keep
all unit parameters, node positions and connections together.
Named loads and diode-OR buses support real auxiliary supply networks.
Select edges to edit diode Vf, disable branches, or disconnect them.
The OR example demonstrates two competing sources and distributed loads.
Canvas Studio: drag any node or diode card, Ctrl+wheel to zoom, and drag
blank canvas to pan. Fit Canvas shows all objects. Diode positions are
saved with the system JSON and used in report diagrams.
UI font size is adjustable and remembered. The fixed blue Save Node/Branch
Changes button commits property edits; Save System Project exports the JSON.
A current Edge/Chrome/Firefox browser is required. No Internet is needed.
LDO units have a dedicated linear-regulator editor, upstream input follow,
four-corner dropout/loss/temperature checks and Word/Excel/JSON reports.
See docs/LDO_DESIGN.md for assumptions; no generic PSRR/transient prediction.
Keep the service window open. Press Ctrl+C or close it to stop.
Only http://127.0.0.1:8765 is served; this is not a LAN/cloud server.
For a busy port: PowerDesignWeb.exe --port 8766 --open

Do NOT copy only PowerDesignWeb.exe: _internal contains required libraries,
static UI, examples, diagrams and the Word formula reference.
Word/WPS/compatible software is needed to read DOCX; Excel/compatible
software is needed to view XLSX. Export itself does not require Office.
Save configurations and download reports before closing the service.
Each service instance holds one latest design. Not a multi-user product.
Report page: configure the generic controller and export a complete ASC.
Simulation/design comparison downloads a ZIP containing Word and logs.
Actual comparison requires separately installed LTspice. Use the desktop
settings dialog to save its executable path, or set LTSPICE_EXE.

The supplied examples are calculation examples, not qualified hardware.
Existing calculation/model limitations and hardware verification apply.
