"""Render only this test's own Tk window with PrintWindow, never the desktop."""
import ctypes
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch

from PIL import Image
import win32gui
import win32ui

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


def capture(root, path):
    root.update_idletasks()
    hwnd = win32gui.GetAncestor(root.winfo_id(), 2)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right-left, bottom-top
    window_dc = win32gui.GetWindowDC(hwnd)
    source = win32ui.CreateDCFromHandle(window_dc)
    memory = source.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source, width, height)
    previous = memory.SelectObject(bitmap)
    try:
        api = ctypes.windll.user32.PrintWindow
        api.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
        assert api(hwnd, memory.GetSafeHdc(), 2), 'Own window failed to render'
        image = Image.frombuffer('RGB', (width, height), bitmap.GetBitmapBits(True), 'raw', 'BGRX', 0, 1)
        assert any(lo != hi for lo, hi in image.getextrema()), 'Blank render'
        image.save(path)
    finally:
        memory.SelectObject(previous)
        win32gui.DeleteObject(bitmap.GetHandle())
        memory.DeleteDC()
        source.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)


def run():
    output = Path(__file__).resolve().parents[1]/'_tmp_parameter_layout_qa'
    output.mkdir(exist_ok=True)
    root = tk.Tk()
    root.attributes('-alpha', 0)
    with patch.object(main.PowerSupplyAnalyzer, 'schedule_update', return_value=None):
        app = main.PowerSupplyAnalyzer(root)
        root.unbind('<Configure>')
        for job in root.tk.splitlist(root.tk.call('after', 'info')):
            root.after_cancel(job)
        root.geometry('1400x880')
        root.update()
        main._apply_fonts(ttk.Style(root), .9)
        app._control_ready = True
        assert app.update_all()
        root.update()
        capture(root, output/'01_default.png')
        for section in ('device', 'capacitors', 'mag'):
            app._folded_sections = set(app._param_sections.values())-{app._param_sections[section]}
            app._filter_params()
            root.update()
            bbox = app.left_canvas.bbox('all')
            app.left_canvas.yview_moveto(app._param_sections[section]._section_container.winfo_y()/max(1, bbox[3]))
            root.update()
            capture(root, output/f'02_{section}.png')
        root.geometry('1000x700')
        main._apply_fonts(ttk.Style(root), .7)
        app._folded_sections.clear()
        app.param_search.set('Rg')
        root.update()
        capture(root, output/'03_small_search.png')
        app._closing = True
        for job in root.tk.splitlist(root.tk.call('after', 'info')):
            root.after_cancel(job)
        root.destroy()
    print(f'Own-window previews: {output}')


if __name__ == '__main__':
    run()
