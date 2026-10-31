"""Shared PyInstaller data map; only runtime resources, never private projects."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = [(str(ROOT/'resources/comp_images'),'comp_images'),
        (str(ROOT/'resources/spice'),'resources/spice'),
        (str(ROOT/'resources/icons/icon.png'),'.'),
        (str(ROOT/'docs/MANUAL_ZH.md'),'.'),
        (str(ROOT/'docs/reference/计算方法与公式说明.docx'),'.'),
        (str(ROOT/'docs/tutorials/多路反激电源设计入门教程.docx'),'.'),
        (str(ROOT/'examples'),'examples')]
DATA += [(str(path),'docs') for path in (ROOT/'docs').glob('*.md')]
EXCLUDES = ['torch','PyQt5','PyQt6','PySide2','PySide6','IPython','jedi','parso',
    'zmq','notebook','nbformat','lark','plotly','pandas','pytest','cv2',
    'sklearn','dask','jupyter','prompt_toolkit','pygments']
