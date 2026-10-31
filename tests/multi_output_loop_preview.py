"""Visual QA of a test-owned loop page at desktop and laptop sizes."""
from pathlib import Path
from tkinter import ttk

from multi_output_loop_ui_check import LoopUIChecks, main
from parameter_panel_preview import capture


def run():
    output=Path(__file__).resolve().parents[1]/'_tmp_multi_loop_qa'
    output.mkdir(exist_ok=True)
    LoopUIChecks.setUpClass()
    try:
        case=LoopUIChecks('test_background_loop_and_both_views_use_current_output_count')
        case.setUp(); case.test_background_loop_and_both_views_use_current_output_count()
        app,root=case.app,case.root
        app.loop_view.set('各路响应'); app.loop_load_output.set('OUT2')
        app._redraw_loop_view(); root.update()
        app.fig_loop.savefig(output/'all_output_response.png',dpi=120)
        capture(root,output/'loop_wide.png')
        root.geometry('1000x700'); main._apply_fonts(ttk.Style(root),.75)
        root.update(); app._redraw_loop_view(); root.update()
        capture(root,output/'loop_narrow.png')
        case.tearDown()
    finally:
        LoopUIChecks.tearDownClass()
    print(f'Test-owned loop previews: {output}')


if __name__=='__main__':
    run()
