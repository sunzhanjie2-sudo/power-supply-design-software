"""Contact sheets of rendered document pages for visual QA (not deliverables)."""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw


def build(folder):
    folder=Path(folder)
    pages=sorted(folder.glob('page-*.png'), key=lambda page: int(page.stem.split('-')[-1]))
    width,height=768,1024
    for start in range(0,len(pages),4):
        sheet=Image.new('RGB',(2*width,2*(height+30)),'#cbd5e1')
        draw=ImageDraw.Draw(sheet)
        for n,page in enumerate(pages[start:start+4]):
            with Image.open(page) as src:
                src.thumbnail((width-12,height),Image.Resampling.LANCZOS)
                x=(n%2)*width+(width-src.width)//2
                y=(n//2)*(height+30)+30
                sheet.paste(src,(x,y))
                draw.text(((n%2)*width+10,y-25),page.stem,fill='black')
        path=folder/f'preview-{start//4+1:02d}.png'
        sheet.save(path)
        print(path)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('folders',nargs='+')
    for folder in parser.parse_args().folders: build(folder)
