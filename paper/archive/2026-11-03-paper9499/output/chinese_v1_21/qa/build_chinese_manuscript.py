"""Build the complete Chinese reading edition with editable Word equations."""
from pathlib import Path
import copy
import json
import re
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / 'qa'
sys.path.insert(0, str(QA / 'deps'))
from latex2mathml.converter import convert
from lxml import etree
from docx import Document
from docx.shared import Inches, Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.opc.part import Part
from docx.opc.packuri import PackURI

SOURCE = ROOT.parent / 'camera_ready_v1_21/manuscript'
XSL = Path('C:/Program Files/Microsoft Office/root/Office16/MML2OMML.XSL')
transform = etree.XSLT(etree.parse(str(XSL)))
equations = []

def math_xml(tex):
    if r'\begin{aligned}' in tex:
        body=tex.replace(r'\begin{aligned}','').replace(r'\end{aligned}','').replace('&','')
        root=OxmlElement('m:oMath'); array=OxmlElement('m:eqArr')
        for line in body.split(r'\\'):
            if not line.strip(): continue
            entry=OxmlElement('m:e')
            for child in math_xml(line.strip()): entry.append(copy.deepcopy(child))
            array.append(entry)
        root.append(array)
        return root
    result = transform(etree.fromstring(convert(tex).encode('utf-8')))
    element = result.getroot()
    assert element is not None and etree.QName(element).localname == 'oMath', tex
    return copy.deepcopy(element)

def set_fonts(style, size, east='SimSun', bold=False):
    style.font.name = 'Times New Roman'
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = RGBColor(0, 0, 0)
    rpr = style.element.get_or_add_rPr()
    fonts = rpr.find(qn('w:rFonts'))
    if fonts is None:
        fonts = OxmlElement('w:rFonts'); rpr.insert(0, fonts)
    for key, value in {'ascii': 'Times New Roman', 'hAnsi': 'Times New Roman', 'eastAsia': east, 'cs': 'Times New Roman'}.items():
        fonts.set(qn('w:'+key), value)
    for key in ['asciiTheme', 'hAnsiTheme', 'eastAsiaTheme', 'cstheme']:
        fonts.attrib.pop(qn('w:'+key), None)
    lang = rpr.find(qn('w:lang'))
    if lang is None: lang = OxmlElement('w:lang'); rpr.append(lang)
    lang.set(qn('w:val'), 'en-US'); lang.set(qn('w:eastAsia'), 'zh-CN')

def add_inline(p, text):
    text=re.sub(r'(?<=\d) (?=(?:kWh|kW|MVA|min|s|h)(?:\b|/))','\u00a0',text)
    parts = re.split(r'(\$[^$]+\$|¹|ᵃ)', text)
    for token in parts:
        if not token: continue
        if token.startswith('$') and token.endswith('$'):
            p._p.append(math_xml(token[1:-1]))
        elif token == '¹':
            r = p.add_run(); r.style=doc.styles['Footnote Reference']; ref = OxmlElement('w:footnoteReference'); ref.set(qn('w:id'), '2'); r._r.append(ref)
        elif token == 'ᵃ':
            r = p.add_run('a'); r.font.superscript = True
        else:
            p.add_run(token)

def para(text='', style=None, center=False, keep=None):
    p = doc.add_paragraph(style=style)
    if center:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Pt(0)
    if keep is not None: p.paragraph_format.keep_with_next = keep
    add_inline(p, text)
    return p

def set_cell_margins(cell):
    pr = cell._tc.get_or_add_tcPr()
    margins = OxmlElement('w:tcMar')
    for side, val in [('top',65),('bottom',65),('left',90),('right',90)]:
        el = OxmlElement('w:'+side); el.set(qn('w:w'),str(val)); el.set(qn('w:type'),'dxa'); margins.append(el)
    pr.append(margins)

def table(rows, followed_by_note=False):
    widths = {3:[0.95,2.55,2.55],4:[0.75,0.65,1.85,2.8],6:[0.95,0.65,0.9,0.9,1.35,1.1]}[len(rows[0])]
    t = doc.add_table(rows=len(rows), cols=len(rows[0]))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER; t.autofit = False
    for col,w in zip(t.columns,widths): col.width=Inches(w)
    pr = t._tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for edge in ['top','left','bottom','right','insideH','insideV']:
        el=OxmlElement('w:'+edge); el.set(qn('w:val'),'single'); el.set(qn('w:sz'),'4'); el.set(qn('w:color'),'D9D9D9'); borders.append(el)
    pr.append(borders)
    for row_i, (row, values) in enumerate(zip(t.rows,rows)):
        trpr=row._tr.get_or_add_trPr(); trpr.append(OxmlElement('w:cantSplit'))
        if row_i==0: trpr.append(OxmlElement('w:tblHeader'))
        for cell,txt,w in zip(row.cells,values,widths):
            cell.width=Inches(w); cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER; set_cell_margins(cell)
            p=cell.paragraphs[0]; p.style=doc.styles['Table Text']; p.alignment=WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.keep_with_next = row_i < len(rows)-1 or followed_by_note
            add_inline(p,txt)
            if row_i==0:
                shade=OxmlElement('w:shd'); shade.set(qn('w:fill'),'F1F1F1'); cell._tc.get_or_add_tcPr().append(shade)
                for r in p.runs:r.bold=True
    after=doc.add_paragraph(); after.paragraph_format.space_after=Pt(0); after.paragraph_format.space_before=Pt(0)
    after.paragraph_format.line_spacing=Pt(2); after.add_run().font.size=Pt(2)
    after.paragraph_format.keep_with_next=followed_by_note

CAPTIONS = {
1:'图 1 固定充电调度方案的网络可行性评估',
2:'图 2 测试配电馈线。图（b）中带编号的标记表示 55 个负荷点；颜色和形状表示相别分配。',
3:'图 3 EV 充电的计划灵活性功率与经验证的可实施灵活性功率。',
4:r'图 4 经验证的可行缩放因子。箱体表示四分位距（IQR），箱内横线表示中位数；须线延伸至距箱体不超过 1.5 倍 IQR 范围内的最远观测值。符号表示按调用时刻区分的算例。虚线和点线分别标示 $\alpha=1$ 和 $0.95$。',
5:'图 5 相邻不可行采样点处首先起限制作用的网络约束。'}
FIGS={
1:[('fig1_network_feasibility_workflow.png',3.8)],
2:[('fig2a_ieee13_topology.png',2.75),('fig2b_lv906_topology.png',2.9)],
3:[('fig3_ieee13_scheduled_vs_feasible_offer.png',2.95),('fig3_lv906_scheduled_vs_feasible_offer.png',2.95)],
4:[('fig4_feasible_scaling_distribution.png',3.7)],
5:[('fig5_limiting_network_constraints.png',4.1)]}

def figure(n):
    p=para(center=True,keep=True)
    p.paragraph_format.space_before=Pt(5); p.paragraph_format.space_after=Pt(2)
    p.paragraph_format.line_spacing=1
    for idx,(name,w) in enumerate(FIGS[n]):
        if idx:p.add_run('  ')
        r=p.add_run(); r.add_picture(str(ROOT/'figures'/name),width=Inches(w))
    if n in [2,3]:
        panel=para(style='Panel Label',keep=True)
        panel.paragraph_format.tab_stops.add_tab_stop(Inches(1.52),WD_TAB_ALIGNMENT.CENTER)
        panel.paragraph_format.tab_stops.add_tab_stop(Inches(4.53),WD_TAB_ALIGNMENT.CENTER)
        labels=('（a）IEEE 13 节点馈线','（b）欧洲 906 节点低压馈线') if n==2 else ('（a）IEEE13','（b）LV906')
        panel.add_run('\t'+labels[0]+'\t'+labels[1])
    p=para(CAPTIONS[n],style='Caption')
    p.paragraph_format.keep_together=True

def display_equation(block):
    tex=block[2:-2].strip()
    match=re.search(r'\\tag\{(\d+)\}',tex); assert match
    number=match.group(1); tex=re.sub(r'\\tag\{\d+\}','',tex).strip()
    equations.append({'number':int(number),'latex':tex})
    p=doc.add_paragraph(style='Equation')
    p.paragraph_format.tab_stops.add_tab_stop(Inches(3.025),WD_TAB_ALIGNMENT.CENTER)
    p.paragraph_format.tab_stops.add_tab_stop(Inches(6.05),WD_TAB_ALIGNMENT.RIGHT)
    p.add_run('\t'); p._p.append(math_xml(tex)); p.add_run('\t('+number+')')

def refs_plain(tex):
    tex=tex.replace(r"Mart\'inez",'Martínez').replace(r'Cese\~na','Ceseña')
    tex=re.sub(r'\\(?:emph|url)\{([^{}]+)\}',r'\1',tex)
    return tex.replace('``','“').replace("''",'”').replace('--','–').strip()

def build_footnotes():
    ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    root=etree.Element('{'+ns+'}footnotes',nsmap={'w':ns})
    for ident, kind in [('-1','separator'),('0','continuationSeparator')]:
        foot=etree.SubElement(root,'{'+ns+'}footnote',attrib={'{'+ns+'}id':ident,'{'+ns+'}type':kind})
        run=etree.SubElement(etree.SubElement(foot,'{'+ns+'}p'),'{'+ns+'}r'); etree.SubElement(run,'{'+ns+'}'+kind)
    for ident,text in [(1,'本研究得到智能电网国家科技重大专项（2025ZD0806600）资助。'),
                       (2,'https://github.com/Kato814/EV-FLEX-BIAS，提交版本 3475301。')]:
        foot=etree.SubElement(root,'{'+ns+'}footnote',attrib={'{'+ns+'}id':str(ident)})
        p=etree.SubElement(foot,'{'+ns+'}p'); ppr=etree.SubElement(p,'{'+ns+'}pPr')
        etree.SubElement(ppr,'{'+ns+'}pStyle',attrib={'{'+ns+'}val':'FootnoteText'})
        run=etree.SubElement(p,'{'+ns+'}r'); rpr=etree.SubElement(run,'{'+ns+'}rPr')
        etree.SubElement(rpr,'{'+ns+'}rStyle',attrib={'{'+ns+'}val':'FootnoteReference'})
        etree.SubElement(run,'{'+ns+'}footnoteRef')
        run=etree.SubElement(p,'{'+ns+'}r'); textel=etree.SubElement(run,'{'+ns+'}t'); textel.text=' '+text
        textel.set('{http://www.w3.org/XML/1998/namespace}space','preserve')
    part=Part(PackURI('/word/footnotes.xml'),'application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml',etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True),doc.part.package)
    doc.part.relate_to(part,'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes')

one=(QA/'translation_sections_1_2.md').read_text(encoding='utf-8')
two=(QA/'translation_sections_3_5.md').read_text(encoding='utf-8').split('\n## 图注')[0]
content=(one.strip()+'\n\n'+two.strip()).replace('基准调度','基线调度')
content=content.replace('预先计算的车辆级单向充电灵活性调度方案','预先计算的车辆级单向充电灵活性调度方案')
content=content.replace('夜间可用时窗始于末次到家时刻，终止于随后再次出现的该车辆日首次离家钟点。',
    '跨夜可用时窗从最后一次到家时刻开始，结束时刻取该车辆日首次离家钟点在到家之后的下一次出现。')
content=content.replace('预设的调查加权紧迫度秩','预设的调查加权紧迫度排序位置')
content=content.replace(
    '表 3 给出了串行执行时每个算例的运行时间。仅搜索时间包括粗网格扫描和局部细化。包含准备阶段的时间包括模型初始化、平衡模型目标调度生成、基线调度与网络准备，以及缩放因子搜索。完整的 501 点网格评估在 IEEE13 上的耗时中位数为 17.64 s，在 LV906 上为 1182.78 s。',
    '表 3 列出了串行执行时各算例的运行时间。仅搜索时间包括粗网格扫描和局部细化；包含准备阶段的总耗时还计入模型初始化、平衡模型目标调度生成及基线调度与网络准备。IEEE13 和 LV906 的完整 501 点网格评估耗时中位数分别为 17.64 s 和 1182.78 s。')
content=content.replace('从 $\\alpha=0$ 开始的一段连续网格点','从 $\\alpha=0$ 开始的一段连续网格点')
content=re.sub(r'^图1 固定充电调度方案的网络可行性评估。$', '[[FIG1]]', content, flags=re.M)
content=content.replace('图 2 展示了两个测试系统。','图 2 展示了两个测试系统。\n\n[[FIG2]]')
content=content.replace('相近的计划灵活性功率可能对应差异较大的经验证可实施灵活性功率。',
    '相近的计划灵活性功率可能对应差异较大的经验证可实施灵活性功率。\n\n[[FIG3]]')
content=content.replace('| 总体 | 46 | 0.681 | 0.719 | 30 | 32 |','| 总体 | 46 | 0.681 | 0.719 | 30 | 32 |\n\n[[FIG4]]')
content=content.replace('不足以表征其车辆级功率分配能否实施。','不足以表征其车辆级功率分配能否实施。\n\n[[FIG5]]')
content=re.sub(r'^¹ \[配套代码仓库\].*$', '', content, flags=re.M)
content=re.sub(r'\n{3,}','\n\n',content)
assert all(content.count(f'[[FIG{i}]]')==1 for i in range(1,6))
(QA/'manuscript_zh_reading.md').write_text(content+'\n',encoding='utf-8')

doc=Document()
sec=doc.sections[0]; sec.page_width=Cm(21); sec.page_height=Cm(29.7)
sec.top_margin=Cm(2.0); sec.bottom_margin=Cm(2.0); sec.left_margin=Cm(2.4); sec.right_margin=Cm(2.4)
sec.header_distance=Cm(.8); sec.footer_distance=Cm(.9)
grid=sec._sectPr.find(qn('w:docGrid'))
if grid is not None: sec._sectPr.remove(grid)
styles=doc.styles
for border in styles.element.xpath('.//w:pBdr'):
    border.getparent().remove(border)
for name,size,east,bold in [('Normal',11,'SimSun',False),('Title',16,'SimHei',True),('Subtitle',10,'SimSun',False),
                           ('Heading 1',13,'SimHei',True),('Heading 2',11.5,'SimHei',True),('Caption',9.5,'SimSun',False)]:
    set_fonts(styles[name],size,east,bold)
for name,size in [('Table Text',10),('Panel Label',9.5),('Equation',11),('Reference Text',9.5),('Footnote Text',9)]:
    if name not in styles:styles.add_style(name,1)
    set_fonts(styles[name],size)
if 'Footnote Reference' not in styles: styles.add_style('Footnote Reference',2)
styles['Footnote Reference'].font.superscript=True
styles['Footnote Reference'].font.size=Pt(9)
styles['Subtitle'].font.italic=False
normal=styles['Normal'].paragraph_format
normal.line_spacing=1.25; normal.space_after=Pt(5); normal.first_line_indent=Pt(22); normal.widow_control=True
for name in ['Heading 1','Heading 2']:
    pf=styles[name].paragraph_format; pf.keep_with_next=True; pf.first_line_indent=Pt(0); pf.space_before=Pt(10); pf.space_after=Pt(5)
for name in ['Title','Subtitle','Caption','Table Text','Panel Label','Equation','Reference Text','Footnote Text']:
    pf=styles[name].paragraph_format; pf.first_line_indent=Pt(0); pf.space_before=Pt(0); pf.space_after=Pt(4); pf.line_spacing=1.15
styles['Table Text'].paragraph_format.space_after=Pt(0)
styles['Equation'].paragraph_format.space_before=Pt(4); styles['Equation'].paragraph_format.space_after=Pt(7)
styles['Equation'].paragraph_format.keep_together=True
styles['Caption'].paragraph_format.space_after=Pt(7)
styles['Caption'].paragraph_format.keep_with_next=False
styles['Reference Text'].paragraph_format.left_indent=Pt(20); styles['Reference Text'].paragraph_format.first_line_indent=Pt(-20)
styles['Reference Text'].paragraph_format.space_after=Pt(5)
styles['Footnote Text'].paragraph_format.line_spacing=1

title='平衡模型生成的电动汽车充电灵活性调度在三相不平衡配电网中的可行性评估'
p=para(title,'Title',center=True,keep=True)
r=p.add_run(); r.style=styles['Footnote Reference']; note=OxmlElement('w:footnoteReference'); note.set(qn('w:id'),'1'); r._r.append(note)
para('中文阅读稿 v1.21','Subtitle',center=True,keep=True)
para('Junxing Tan，Jun Wu，Shiting Cui，Chaofan Yang，Jiangcheng Wang',center=True,keep=True)
para('武汉大学电气与自动化学院  中国武汉',center=True,keep=True)
for text in ['2570734125@qq.com；byronwu@whu.edu.cn；406385846@qq.com',
             '552391450@qq.com；2383669292@qq.com']:
    p=para(text,center=True,keep=True)
    for r in p.runs:r.font.size=Pt(9)

blocks=re.split(r'\n\s*\n',content)
section_no=0
for block_index,block in enumerate(blocks):
    block=block.strip()
    if not block:continue
    if block.startswith('$$'):
        doc.paragraphs[-1].paragraph_format.keep_with_next=True
        display_equation(block)
    elif block.startswith('[[FIG'):
        figure(int(re.search(r'FIG(\d+)',block).group(1)))
    elif block.startswith('### '):
        titletext=re.sub(r'^[A-Z]\.?(?:\s+)', '', block[4:])
        letter=re.match(r'^([A-Z])',block[4:]).group(1)
        para(f'{section_no}.{ord(letter)-64} {titletext}','Heading 2')
    elif block.startswith('## '):
        h=block[3:]; match=re.match(r'^(I|II|III|IV|V)\s+(.+)$',h)
        if match:
            section_no={'I':1,'II':2,'III':3,'IV':4,'V':5}[match.group(1)]; h=f'{section_no} {match.group(2)}'
        para(h,'Heading 1')
    elif block.startswith('|'):
        rows=[]
        for line in block.splitlines():
            cells=[s.strip() for s in line.strip().strip('|').split('|')]
            if all(re.fullmatch(r':?-+:?',x) for x in cells):continue
            rows.append(cells)
        next_block=blocks[block_index+1].strip() if block_index+1 < len(blocks) else ''
        table(rows,followed_by_note=next_block.startswith(('ᵃ','表中数值')))
    elif block in ['表 1 V1G 研究算例','表 2 经验证的最大可行缩放因子','表 3 每个算例的计算时间（s）']:
        para(block,'Caption',center=True,keep=True)
    elif block.startswith(('ᵃ','表中数值')):
        p=para(block,'Caption'); p.paragraph_format.space_after=Pt(5)
        if block.startswith('表中数值'):p.paragraph_format.keep_with_next=True
    else:
        para(block.replace('\n',' '))

para('参考文献','Heading 1')
reference_source=(SOURCE/'references.tex').read_text(encoding='utf-8')
ref_entries=re.findall(r'\\bibitem\{([^}]+)\}\s*(.*?)(?=\n\\bibitem|\n\\end\{thebibliography\})',reference_source,re.S)
assert len(ref_entries)==14
for idx,(_,text) in enumerate(ref_entries,1):para(f'[{idx}] {refs_plain(text)}','Reference Text')
build_footnotes()
footer=sec.footer.paragraphs[0]; footer.alignment=WD_ALIGN_PARAGRAPH.CENTER
footer.paragraph_format.first_line_indent=Pt(0)
run=footer.add_run(); fld=OxmlElement('w:fldSimple'); fld.set(qn('w:instr'),'PAGE'); run._r.addnext(fld)
doc.core_properties.title=title
doc.core_properties.subject='英文终稿 v1.21 的中文阅读稿'
doc.core_properties.author='Junxing Tan; Jun Wu; Shiting Cui; Chaofan Yang; Jiangcheng Wang'
doc.core_properties.comments=''
path=ROOT/'paper9499_v1_21_中文阅读稿.docx'
doc.save(path)
record={'output':str(path),'source_version':'v1.21','equations':equations,'tables':len(doc.tables),'images':len(doc.inline_shapes),'references':len(ref_entries),
        'body_blocks':len(blocks),'math_objects':len(doc.element.xpath('.//m:oMath'))}
assert [x['number'] for x in equations]==[1,2,3,4,5]
assert record['tables']==3 and record['images']==7
(QA/'build_summary.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in record.items() if k!='equations'},ensure_ascii=False))
