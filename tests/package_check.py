"""Smoke-test only the executable started by this test, plus bundled resources.

The startup number is process launch -> responsive Tk window, not cold-disk
startup or completion of all tabs. No user application/window is inspected.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import subprocess
import time


def check(folder):
    folder=Path(folder).resolve()
    source=Path(__file__).resolve().parents[1]
    import sys
    sys.path.insert(0,str(source))
    from app_resources import resource_path
    resources=folder/'_internal'
    paths=[Path('计算方法与公式说明.docx'),Path('多路反激电源设计入门教程.docx'),Path('自动计算参数依据.docx'),
           Path('MANUAL_ZH.md'),Path('examples/40W_CCM_FLYBACK.json'),
           Path('examples/40W_ACF_FORWARD.json'),Path('examples/6_OUTPUT_FLYBACK_SSR.json'),
           Path('examples/MP6005_PSR_FLYBACK.json'),Path('docs/PARAMETER_PANEL.md'),
           Path('examples/3_OUTPUT_COUPLED_FLYBACK.json'),Path('docs/COUPLED_FLYBACK.md'),
           Path('docs/WINDING_WINDOW.md'),Path('docs/PERFORMANCE.md'),Path('docs/TRANSFORMER_ELECTRICAL.md'),
           Path('docs/MULTI_OUTPUT_LOOP.md'), Path('docs/INPUT_VOLTAGE_RANGE.md'),Path('docs/EXCEL_REPORT.md')]
    paths.extend(Path('comp_images')/p.name for p in resource_path('comp_images').glob('*.png'))
    for relative in paths:
        expected=resource_path(relative); actual=resources/relative
        assert actual.is_file(),f'Missing bundle resource: {relative}'
        assert hashlib.sha256(actual.read_bytes()).digest()==hashlib.sha256(expected.read_bytes()).digest(),f'Stale bundle resource: {relative}'

    user32=ctypes.WinDLL('user32',use_last_error=True)
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user32.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]
    user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user32.SendMessageTimeoutW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,
        wintypes.LPARAM,wintypes.UINT,wintypes.UINT,ctypes.POINTER(ctypes.c_size_t)]
    user32.SendMessageTimeoutW.restype=wintypes.LPARAM
    user32.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    startup=subprocess.STARTUPINFO()
    startup.dwFlags=subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow=0  # request hidden startup; never foreground the test
    exe=folder/'SwitchingPowerSupplyDesign_V0.exe'
    start=time.perf_counter()
    process=subprocess.Popen([str(exe)],cwd=folder,startupinfo=startup)
    owned_window=None
    windows=[]

    def get_owned_windows():
        windows.clear()
        @callback_type
        def collect(hwnd,_):
            pid=wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value==process.pid:
                title=ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd,title,len(title))
                if title.value:
                    windows.append((hwnd,title.value))
            return True
        user32.EnumWindows(collect,0)
        return list(windows)

    try:
        deadline=start+30
        while time.perf_counter()<deadline:
            assert process.poll() is None,f'Package exited during startup: {process.returncode}'
            for hwnd,title in get_owned_windows():
                assert 'unhandled exception' not in title.lower(),title
                if title.startswith(('Switching Power Supply Design & Loop Analyzer', '开关电源系统设计')):
                    result=ctypes.c_size_t()
                    if user32.SendMessageTimeoutW(hwnd,0,0,0,2,500,ctypes.byref(result)):
                        owned_window=hwnd
                        break
            if owned_window:
                break
            time.sleep(.05)
        assert owned_window is not None,'No responsive Tk window within 30 seconds'
        responsive_s=time.perf_counter()-start
        # Let the initial design settle; watch only
        # this test's process for any startup exception dialogs.
        settle_deadline=time.perf_counter()+4
        while time.perf_counter()<settle_deadline:
            assert process.poll() is None,'Package exited during initial calculation'
            assert all('unhandled exception' not in title.lower() for _,title in get_owned_windows())
            time.sleep(.1)
        import psutil
        memory = psutil.Process(process.pid)
        rss_mib = round(memory.memory_info().rss / 2**20, 1)
        thread_count = memory.num_threads()
        assert user32.PostMessageW(owned_window,0x0010,0,0),'Could not close own test window'
        exit_code=process.wait(timeout=10)
        assert exit_code==0,f'Package did not close normally: {exit_code}'
        print(json.dumps(dict(bundle=str(folder),resources_verified=len(paths),
                              responsive_window_seconds=round(responsive_s,3),rss_mib=rss_mib,
                              thread_count=thread_count,exit_code=exit_code),ensure_ascii=False))
    finally:
        if process.poll() is None:
            if owned_window:
                user32.PostMessageW(owned_window,0x0010,0,0)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Exact subprocess created above only; never touch other apps.
                process.terminate(); process.wait(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('folder')
    check(parser.parse_args().folder)
