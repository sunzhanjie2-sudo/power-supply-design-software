"""Windows QA fallback: private, invisible Word -> PDF -> bundled Poppler.

Does not attach to an existing Word session, modify input docs, add recent files,
enable macros, or close any user's document. Artifact Python/Poppler are bundled.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import win32com.client


def render(paths,out):
    root=Path(out).resolve(); root.mkdir(parents=True,exist_ok=True)
    deps=Path(sys.executable).resolve().parent.parent
    poppler=deps/'native'/'poppler'/'Library'/'bin'/'pdftoppm.exe'
    if not poppler.is_file():
        raise RuntimeError('Bundled Poppler not found: '+str(poppler))
    for path in paths:
        word=win32com.client.DispatchEx('Word.Application')
        word.Visible=False; word.DisplayAlerts=0; word.AutomationSecurity=3
        try:
            path=Path(path).resolve(); folder=root/path.stem; folder.mkdir(exist_ok=True)
            document=None
            try:
                document=word.Documents.Open(str(path),ReadOnly=True,AddToRecentFiles=False,Visible=False)
                document.Repaginate()
                pages=document.ComputeStatistics(2)
                pdf=folder/(path.stem+'.pdf')
                document.ExportAsFixedFormat(str(pdf),17,OpenAfterExport=False)
                print(f'Word rendered {path.name}: {pages} pages',flush=True)
            finally:
                if document is not None: document.Close(SaveChanges=0)
            subprocess.run([str(poppler),'-r','120','-png',str(pdf),str(folder/'page')],check=True)
        finally:
            # Some Word installations terminate their automation server when
            # its final document closes. Never attach/kill another instance.
            try:
                word.Quit(SaveChanges=0)
            except Exception:
                pass


if __name__=='__main__':
    a=argparse.ArgumentParser(); a.add_argument('paths',nargs='+'); a.add_argument('--out',required=True)
    args=a.parse_args(); render(args.paths,args.out)
