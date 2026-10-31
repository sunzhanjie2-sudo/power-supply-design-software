"""Small OOXML writer for offline report exports, not a spreadsheet solver.

The distributed application must not require Excel, Node, network services or
another heavyweight runtime. Only the standard library is used here. Values
are typed; plots are the existing PNGs from the engineering report renderer.
"""
from dataclasses import dataclass, field
import hashlib
import math
import os
from pathlib import Path
import re
import struct
import tempfile
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZipFile, ZIP_DEFLATED

S = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/package/2006/relationships'
D = 'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
WIDTHS = [20, 12, 12, 12, 12, 12, 12, 12, 3,
          20, 12, 12, 12, 12, 12, 12, 12]
SIDE_PX = sum(w * 7 + 5 for w in WIDTHS[:8])


def node(parent, tag, **attrs):
    return SubElement(parent, '{'+S+'}'+tag, {k: str(v) for k, v in attrs.items()})


def col_name(index):
    result = ''
    while index >= 0:
        index, digit = divmod(index, 26)
        result = chr(65+digit)+result
        index -= 1
    return result


def address(row, col):
    return col_name(col)+str(row)


def _clean(text):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(text))[:32767]


def _xml(element):
    return tostring(element, encoding='utf-8', xml_declaration=True)


def text_width(text):
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in str(text))


def fitted_height(text, width):
    lines = sum(max(1, math.ceil(text_width(line)/max(width-2, 1)))
                for line in str(text).split('\n'))
    return min(409, max(24, lines*15+9))


def number_format(number, unit=''):
    if unit == '%': return '0.00%'
    if number and (abs(number) < 1e-4 or abs(number) >= 1e7):
        fmt = '0.000E+00'
    else:
        decimals = max(0,min(6,3-math.floor(math.log10(abs(number))))) if number else 0
        fmt = '0'+('.'+'0'*decimals if decimals else '')
    return fmt+('" '+unit+'"' if unit else '')


def numeric_text(text):
    """Turn a single displayed engineering quantity into a numeric Excel cell.

    Composite values and identifiers remain literal text. Units stay in the
    number format, never stripped from the displayed number. Percentages use
    fractional underlying values as Excel expects.
    """
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return (float(text), number_format(text)) if math.isfinite(text) else ('未定义', None)
    match = re.fullmatch(r'\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([^\d\s]*)\s*', str(text))
    if not match:
        return str(text), None
    number, unit = float(match[1]), match[2]
    units = ('', '%', '°', 'K', 'T', 'dB', 'A/mm²', 'A/m²', 'Ω·m', 'W/(m²·K)', '百分点')
    if unit not in units and not re.fullmatch(r'[pnuμµmkMG]?(?:W|V|A|H|F|Ω|s|Hz|m|m²|m³|C)', unit):
        return str(text), None
    if not math.isfinite(number):
        return '未定义', None
    if unit == '%':
        return number/100, '0.0000000000%' if number and abs(number)<.01 else '0.00%'
    if not unit and re.fullmatch(r'[+-]?\d+',match[1]):
        return number,'0'
    return number, number_format(number,unit)


@dataclass
class Sheet:
    name: str
    cells: dict = field(default_factory=dict)
    heights: dict = field(default_factory=dict)
    merges: list = field(default_factory=list)
    images: list = field(default_factory=list)
    breaks: list = field(default_factory=list)

    def cell(self, row, col, value, style=0, fmt=None):
        self.cells[row, col] = (value, style, fmt)

    def span(self, row, col, count, value, style=0, fmt=None):
        for offset in range(count):
            self.cell(row, col+offset, value if offset == 0 else '', style, fmt if offset == 0 else None)
        if count > 1:
            self.merges.append(f'{address(row,col)}:{address(row,col+count-1)}')

    def image(self, row, col, blob, caption, width=SIDE_PX, dx=0):
        if blob[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError('报告图片必须为 PNG')
        w, h = struct.unpack('>II', blob[16:24])
        height = width*h/w
        self.images.append(dict(row=row, col=col, blob=blob, caption=caption,
                                width=width, height=height, dx=dx))
        return height


def _styles(formats):
    root = Element('{'+S+'}styleSheet')
    custom = node(root, 'numFmts', count=len(formats))
    for index, fmt in enumerate(formats, 164):
        node(custom, 'numFmt', numFmtId=index, formatCode=fmt)
    fonts = node(root, 'fonts', count=5)
    for size, bold, color in [(10, False, '172B4D'), (16, True, '172B4D'),
                              (11, True, 'FFFFFF'), (11, True, '172B4D'),
                              (9, False, '596579')]:
        f = node(fonts, 'font'); node(f, 'sz', val=size)
        node(f, 'name', val='Microsoft YaHei'); node(f, 'color', rgb='FF'+color)
        if bold: node(f, 'b')
    fills = node(root, 'fills', count=7)
    from design_theme import is_pcs
    pcs = is_pcs()
    for pattern, color in [('none', None), ('gray125', None), ('solid', '2068A0'),
                           ('solid', 'B76B1E'), ('solid', 'EAF1F8'),
                           ('solid', 'F6F8FB'), ('solid', 'FFF0D6')]:
        f = node(fills, 'fill'); pat = node(f, 'patternFill', patternType=pattern)
        if color:
            if pcs: color={'2068A0':'2376E5','B76B1E':'0D1726','EAF1F8':'EAF3FF','F6F8FB':'F3F6FA','FFF0D6':'FFF5DF'}.get(color,color)
            node(pat, 'fgColor', rgb='FF'+color); node(pat, 'bgColor', indexed=64)
    borders = node(root, 'borders', count=2)
    node(borders, 'border')
    b = node(borders, 'border')
    edge = node(b, 'bottom', style='hair'); node(edge, 'color', rgb='FFD9E0EA')
    masters = node(root, 'cellStyleXfs', count=1)
    node(masters, 'xf', numFmtId=0, fontId=0, fillId=0, borderId=0)
    xfs = node(root, 'cellXfs', count=10+2*len(formats))
    base = [(0,0,1,'left'), (1,0,0,'left'), (2,2,0,'left'),
            (2,3,0,'left'), (3,4,0,'left'), (2,2,0,'center'),
            (0,5,1,'left'), (4,0,0,'left'), (3,6,0,'left'), (0,0,0,'left')]
    for font, fill, border, align in base:
        xf = node(xfs, 'xf', numFmtId=0, fontId=font, fillId=fill,
                  borderId=border, xfId=0, applyAlignment=1)
        node(xf, 'alignment', horizontal=align, vertical='center', wrapText=1, indent=0 if font==1 else 1)
    for index in range(len(formats)):
        for fill in (0, 5):
            xf = node(xfs, 'xf', numFmtId=164+index, fontId=0, fillId=fill,
                      borderId=1, xfId=0, applyNumberFormat=1, applyAlignment=1)
            node(xf, 'alignment', horizontal='right', vertical='center', wrapText=1, indent=1)
    styles = node(root, 'cellStyles', count=1)
    node(styles, 'cellStyle', name='Normal', xfId=0, builtinId=0)
    return root


def save_workbook(path, sheets):
    """Atomically write an xlsx with typed cells, fixed panes and image anchors."""
    formats = list(dict.fromkeys(fmt for sheet in sheets for _, _, fmt in sheet.cells.values() if fmt))
    media = {}
    root = Element('{'+S+'}workbook', {'xmlns:r': R})
    views = node(root, 'bookViews'); node(views, 'workbookView', activeTab=0)
    listing = node(root, 'sheets')
    names = set()
    for index, sheet in enumerate(sheets, 1):
        if len(sheet.name) > 31 or re.search(r'[\\/*?:\[\]]', sheet.name) or sheet.name in names:
            raise ValueError('无效或重复的 Excel 页签名称：'+sheet.name)
        names.add(sheet.name)
        node(listing, 'sheet', name=sheet.name, sheetId=index, **{'{'+R+'}id':f'rId{index}'})
    definitions = node(root, 'definedNames')
    for index, sheet in enumerate(sheets):
        quoted = "'"+sheet.name.replace("'", "''")+"'!"
        end = max(sheet.heights.keys() | {r for r, _ in sheet.cells}, default=4)
        node(definitions, 'definedName', name='_xlnm.Print_Area', localSheetId=index).text = quoted+f'$A$1:$Q${end}'
        node(definitions, 'definedName', name='_xlnm.Print_Titles', localSheetId=index).text = quoted+'$1:$4'
    node(root, 'calcPr', calcId=191029, fullCalcOnLoad=1)
    relationships = Element('Relationships', xmlns=P)
    for index in range(1, len(sheets)+1):
        SubElement(relationships, 'Relationship', Id=f'rId{index}', Type=R+'/worksheet', Target=f'worksheets/sheet{index}.xml')
    SubElement(relationships, 'Relationship', Id='styles', Type=R+'/styles', Target='styles.xml')
    content = Element('Types', xmlns='http://schemas.openxmlformats.org/package/2006/content-types')
    for ext, mime in [('rels','application/vnd.openxmlformats-package.relationships+xml'),
                       ('xml','application/xml'), ('png','image/png')]:
        SubElement(content, 'Default', Extension=ext, ContentType=mime)
    def override(part, kind):
        SubElement(content, 'Override', PartName='/'+part, ContentType=kind)
    override('xl/workbook.xml', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml')
    override('xl/styles.xml', 'application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml')
    target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.report-', suffix='.xlsx', dir=target.parent)
    os.close(fd)
    try:
        with ZipFile(temporary, 'w', compression=ZIP_DEFLATED) as archive:
            archive.writestr('xl/workbook.xml', _xml(root))
            archive.writestr('xl/_rels/workbook.xml.rels', _xml(relationships))
            archive.writestr('xl/styles.xml', _xml(_styles(formats)))
            for index, sheet in enumerate(sheets, 1):
                ws = Element('{'+S+'}worksheet', {'xmlns:r':R})
                from design_theme import is_pcs
                props = node(ws, 'sheetPr'); node(props, 'tabColor', rgb='FF2376E5' if is_pcs() else 'FF2068A0')
                node(props, 'pageSetUpPr', fitToPage=1)
                end = max(sheet.heights.keys() | {r for r, _ in sheet.cells}, default=4)
                node(ws, 'dimension', ref=f'A1:Q{end}')
                sv = node(node(ws, 'sheetViews'), 'sheetView', workbookViewId=0, showGridLines=0, zoomScale=75)
                node(sv, 'pane', ySplit=4, topLeftCell='A5', activePane='bottomLeft', state='frozen')
                node(sv, 'selection', pane='bottomLeft', activeCell='A5', sqref='A5')
                node(ws, 'sheetFormatPr', defaultRowHeight=24)
                cols = node(ws, 'cols')
                for c, width in enumerate(WIDTHS, 1): node(cols, 'col', min=c, max=c, width=width, customWidth=1)
                data = node(ws, 'sheetData')
                by_row = {}
                for (r,c), cell in sheet.cells.items(): by_row.setdefault(r, []).append((c, cell))
                for r in range(1, end+1):
                    row = node(data, 'row', r=r, ht=sheet.heights.get(r,24), customHeight=1)
                    for c, (value, style, fmt) in sorted(by_row.get(r, [])):
                        if fmt: style = 10+formats.index(fmt)*2+(style == 6)
                        numeric = isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
                        cell = node(row, 'c', r=address(r,c), s=style, t='n' if numeric else 'inlineStr')
                        if numeric:
                            node(cell, 'v').text = repr(float(value))
                        else:
                            txt = node(node(cell,'is'), 't', **{'{http://www.w3.org/XML/1998/namespace}space':'preserve'})
                            txt.text = _clean(value)
                if sheet.merges:
                    merges = node(ws, 'mergeCells', count=len(sheet.merges))
                    for ref in sheet.merges: node(merges, 'mergeCell', ref=ref)
                node(ws, 'printOptions', horizontalCentered=1)
                node(ws, 'pageMargins', left=.25, right=.25, top=.4, bottom=.4, header=.15, footer=.15)
                node(ws, 'pageSetup', paperSize=8, orientation='landscape', fitToWidth=1, fitToHeight=0)
                hf = node(ws,'headerFooter'); node(hf,'oddFooter').text = '&L'+sheet.name+'&R&P / &N'
                if sheet.breaks:
                    breaks = node(ws,'rowBreaks', count=len(sheet.breaks), manualBreakCount=len(sheet.breaks))
                    for row in sheet.breaks: node(breaks, 'brk', id=row-1, min=0, max=16, man=1)
                if sheet.images:
                    node(ws, 'drawing', **{'{'+R+'}id':'drawing'})
                    rel = Element('Relationships', xmlns=P)
                    SubElement(rel, 'Relationship', Id='drawing', Type=R+'/drawing', Target=f'../drawings/drawing{index}.xml')
                    archive.writestr(f'xl/worksheets/_rels/sheet{index}.xml.rels', _xml(rel))
                    draw = Element('{'+D+'}wsDr')
                    draw_rels = Element('Relationships', xmlns=P)
                    for pic_id, pic in enumerate(sheet.images, 1):
                        digest = hashlib.sha256(pic['blob']).hexdigest()
                        if digest not in media:
                            media[digest] = f'image{len(media)+1}.png'
                            archive.writestr('xl/media/'+media[digest], pic['blob'])
                        rid = f'rId{pic_id}'
                        SubElement(draw_rels,'Relationship',Id=rid,Type=R+'/image',Target='../media/'+media[digest])
                        def dnode(parent, tag, **attrs): return SubElement(parent,'{'+D+'}'+tag,{k:str(v) for k,v in attrs.items()})
                        anchor = dnode(draw,'oneCellAnchor')
                        start = dnode(anchor,'from')
                        for tag, val in [('col',pic['col']),('colOff',int(pic['dx']*9525)),('row',pic['row']-1),('rowOff',0)]:
                            dnode(start,tag).text=str(val)
                        cx, cy = int(pic['width']*9525), int(pic['height']*9525)
                        dnode(anchor,'ext',cx=cx,cy=cy)
                        picture = dnode(anchor,'pic'); nv = dnode(picture,'nvPicPr')
                        dnode(nv,'cNvPr',id=pic_id,name='图'+str(pic_id),descr=pic['caption'])
                        SubElement(dnode(nv,'cNvPicPr'),'{'+A+'}picLocks',noChangeAspect='1')
                        fill = dnode(picture,'blipFill')
                        SubElement(fill,'{'+A+'}blip',{'{'+R+'}embed':rid})
                        SubElement(SubElement(fill,'{'+A+'}stretch'),'{'+A+'}fillRect')
                        sp = dnode(picture,'spPr')
                        transform=SubElement(sp,'{'+A+'}xfrm')
                        SubElement(transform,'{'+A+'}off',x='0',y='0'); SubElement(transform,'{'+A+'}ext',cx=str(cx),cy=str(cy))
                        SubElement(SubElement(sp,'{'+A+'}prstGeom',prst='rect'),'{'+A+'}avLst')
                        dnode(anchor,'clientData')
                    archive.writestr(f'xl/drawings/drawing{index}.xml', _xml(draw))
                    archive.writestr(f'xl/drawings/_rels/drawing{index}.xml.rels', _xml(draw_rels))
                    override(f'xl/drawings/drawing{index}.xml','application/vnd.openxmlformats-officedocument.drawing+xml')
                archive.writestr(f'xl/worksheets/sheet{index}.xml', _xml(ws))
                override(f'xl/worksheets/sheet{index}.xml','application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml')
            rel = Element('Relationships', xmlns=P)
            SubElement(rel,'Relationship',Id='workbook',Type=R+'/officeDocument',Target='xl/workbook.xml')
            archive.writestr('_rels/.rels', _xml(rel))
            archive.writestr('[Content_Types].xml', _xml(content))
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
