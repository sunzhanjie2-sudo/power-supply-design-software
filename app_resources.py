"""One resource map for source checkouts and legacy-layout frozen bundles.

Keep executable bundle paths stable while grouping source assets and manuals.
This module has no GUI/numerical imports and is safe in the web worker.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent


def resource_path(relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Resource must be a project-relative path')
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative
    if relative.parts and relative.parts[0] == 'comp_images':
        return ROOT / 'resources' / relative
    if relative.name in ('icon.png', 'icon.ico') and len(relative.parts) == 1:
        return ROOT / 'resources' / 'icons' / relative
    if str(relative) in ('计算方法与公式说明.docx', '自动计算参数依据.docx'):
        return ROOT / 'docs' / 'reference' / relative
    if str(relative) == '多路反激电源设计入门教程.docx':
        return ROOT / 'docs' / 'tutorials' / relative
    if str(relative) in ('MANUAL_ZH.md', '使用文档.md'):
        return ROOT / 'docs' / relative
    return ROOT / relative
