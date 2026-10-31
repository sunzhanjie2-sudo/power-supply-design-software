"""Start the local Web UI. Never binds a LAN or public interface."""
import argparse
import multiprocessing
from pathlib import Path
import threading
import time
import webbrowser


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--open',action='store_true',help='Open the local UI in the default browser')
    parser.add_argument('--pcs-root', type=Path, help='Serve a local PCS shelf with the shared auxiliary-power engine')
    parser.add_argument('--desktop-event', help=argparse.SUPPRESS)
    args=parser.parse_args()
    if not 1024<=args.port<=65535:
        parser.error('port must be between 1024 and 65535')
    if not (Path(__file__).parent/'web_app/static/index.html').is_file():
        parser.error('前端未构建：进入 web_app/frontend，执行 npm ci && npm run build')
    from runtime_resources import configure_numeric_threads
    configure_numeric_threads()
    try:
        import uvicorn
        from web_app.server import create_app
    except ImportError as exc:
        parser.error('缺少 Web 依赖，请在隔离环境安装 requirements-web.txt：'+str(exc))
    url=f'http://127.0.0.1:{args.port}'+('/pcs/index.html#aux' if args.pcs_root else '')
    server=uvicorn.Server(uvicorn.Config(create_app(pcs_root=args.pcs_root),host='127.0.0.1',port=args.port,
                                        workers=1,access_log=False))
    if args.desktop_event:
        # The native host owns this event. Normal window close asks Uvicorn to
        # finish lifespan cleanup; its Windows Job Object handles a host crash.
        import ctypes
        import re
        if not re.fullmatch(r'Local\\PCSDesignStop-[0-9a-f]{32}', args.desktop_event):
            parser.error('Invalid desktop lifecycle event')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenEventW.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.OpenEventW.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        event = kernel.OpenEventW(0x00100000, False, args.desktop_event)
        if not event:
            parser.error('Desktop host is no longer running')
        def close_when_signaled():
            try:
                if kernel.WaitForSingleObject(event, 0xffffffff) == 0:
                    server.should_exit = True
            finally:
                kernel.CloseHandle(event)
        threading.Thread(target=close_when_signaled, daemon=True).start()
    if args.open:
        def open_when_ready():
            for _ in range(100):
                if server.should_exit:
                    return
                if server.started:
                    webbrowser.open(url)
                    return
                time.sleep(.2)
        threading.Thread(target=open_when_ready,daemon=True).start()
    print('Power Design · 本地网页版：'+url,flush=True)
    print('仅本机可访问；关闭此窗口或按 Ctrl+C 停止。',flush=True)
    try:
        server.run()
    except KeyboardInterrupt:
        pass  # Uvicorn has completed lifespan cleanup; normal console shutdown.


if __name__=='__main__':
    multiprocessing.freeze_support()
    main()
