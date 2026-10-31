"""Contact sheets and changed-page locators for the document render QA."""
from pathlib import Path
import sys
from PIL import Image, ImageDraw
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
folder=ROOT/'_tmp_thermal_stress_20261021/reference_render'
pages=sorted(folder.glob('page-*.png'),key=lambda p:int(p.stem.split('-')[-1]))
for start in range(0,len(pages),9):
    board=Image.new('RGB',(1050,1452),'#e8ecf0');draw=ImageDraw.Draw(board)
    for index,path in enumerate(pages[start:start+9]):
        picture=Image.open(path);picture.thumbnail((334,448))
        x=(index%3)*350+8;y=(index//3)*484+23
        board.paste(picture,(x,y));draw.text((x,y-18),path.stem,fill='black')
    board.save(folder/f'contact-{start+1}.png')
for index,page in enumerate(PdfReader(folder/'计算方法与公式说明.pdf').pages,1):
    text=page.extract_text()
    if any(word in text for word in ('7.5','Rth_transformer','Kc 定义','未考虑寄生尖峰','主开关电压应力')):
        print('Changed page',index)
print('Pages',len(pages))
