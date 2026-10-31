"""Lightweight system-architecture entry; load the numerical GUI on demand."""
import multiprocessing


def main():
    multiprocessing.freeze_support()
    # Keep native text sharp and geometry in physical pixels on high-DPI PCs.
    import sys
    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    import tkinter as tk
    from system_workspace_ui import SystemWorkspace
    root = tk.Tk()
    SystemWorkspace(root)
    root.mainloop()


if __name__ == '__main__':
    main()
