from pathlib import Path
from collections import Counter
import hashlib
import json
import re
import shutil
import zipfile
from lxml import etree
from docx import Document
from PIL import Image, ImageChops

root=Path(__file__).resolve().parents[1]
qa=root/'qa'
english=root.parent/'camera_ready_v1_21'
source=(english/'manuscript/manuscript_v1_21.tex').read_text(encoding='utf-8')
chinese=(qa/'manuscript_zh_reading.md').read_text(encoding='utf-8')
summary=json.loads((qa/'build_summary.json').read_text(encoding='utf-8'))
docx=root/'paper9499_v1_21_中文阅读稿.docx'
rendered=qa/'rendered_pdfa/paper9499_v1_21_中文阅读稿.pdf'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def normalized_eq(x):return re.sub(r'\s+','',re.sub(r'\\label\{[^}]+\}','',x))
original_equations=re.findall(r'\\begin\{equation\}(.*?)\\end\{equation\}',source,re.S)
assert len(original_equations)==5
assert all(normalized_eq(a)==normalized_eq(b['latex']) for a,b in zip(original_equations,summary['equations']))
en_body=source.split(r'\begin{abstract}')[1].split(r'\IEEEtriggeratref')[0]
en_body=re.sub(r'\\begin\{figure\}.*?\\end\{figure\}','',en_body,flags=re.S)
decimals=lambda s:Counter(re.findall(r'(?<!\d)\d+\.\d+(?!\d)',s))
assert decimals(en_body)==decimals(chinese),{'missing':decimals(en_body)-decimals(chinese),'extra':decimals(chinese)-decimals(en_body)}
doc=Document(docx)
expected=[
 [['IEEE13','22','173 [65–337]','940 [237–1942]'],['LV906','24','29.5 [11–54]','174 [11–261]']],
 [['IEEE13','22','0.834','0.999','9','11'],['LV906','24','0.540','0.446','21','21'],['总体','46','0.681','0.719','30','32']],
 [['IEEE13','1.80 [1.36–3.90]','8.76 [4.88–31.41]'],['LV906','119.14 [24.28–146.39]','124.86 [29.51–153.46]']]
]
assert len(doc.tables)==3 and len(doc.inline_shapes)==7
for tab,rows in zip(doc.tables,expected):assert [[c.text for c in r.cells] for r in tab.rows[1:]]==rows
with zipfile.ZipFile(docx) as z:
    xml=etree.fromstring(z.read('word/document.xml'))
    styles=etree.fromstring(z.read('word/styles.xml'))
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','m':'http://schemas.openxmlformats.org/officeDocument/2006/math'}
    assert len(xml.xpath('//m:oMath',namespaces=ns))==51
    assert not styles.xpath('//w:style[@w:styleId="Title"]//w:pBdr',namespaces=ns)
    notes=etree.fromstring(z.read('word/footnotes.xml'))
    all_notes=''.join(notes.xpath('//w:t/text()',namespaces=ns))
    assert '2025ZD0806600' in all_notes and '3475301' in all_notes
    ref_paras=[p.text for p in doc.paragraphs if p.style.name=='Reference Text']
    assert len(ref_paras)==14 and all(t.startswith(f'[{i}]') for i,t in enumerate(ref_paras,1))

helper=root.parent/'camera_ready_v1_19/qa/verify_delivery.py'
namespace={'__file__':str(__file__)}
exec(helper.read_text(encoding='utf-8').split('\npaper = inspect_pdf(')[0],namespace)
pdf_check=namespace['inspect_pdf'](rendered)
assert pdf_check['pages']==8 and pdf_check['all_fonts_embedded']
assert not pdf_check['type3_fonts'] and not pdf_check['characters_outside_page']
assert all(abs(w-595.3)<1 and abs(h-841.9)<1 for w,h in pdf_check['page_sizes_pt'])
english_report=json.loads((english/'qa/final_verification.json').read_text(encoding='utf-8'))
assert sha(english/'paper9499_camera_ready_v1_21.pdf')==english_report['pdf']['sha256']
assert sha(english/'paper9499_v1_21_LaTeX.zip')==english_report['source_zip_sha256']
with zipfile.ZipFile(english/'paper9499_v1_21_LaTeX.zip') as z:
    assert z.read('manuscript_v1_21.tex')==(english/'manuscript/manuscript_v1_21.tex').read_bytes()

changed=[]
for n in range(1,9):
    a=Image.open(qa/f'rendered_v2/page-{n}.png').convert('RGB')
    b=Image.open(qa/f'rendered_pdfa/page-{n}.png').convert('RGB')
    if a.size!=b.size or ImageChops.difference(a,b).getbbox():changed.append(n)
destination=root/'paper9499_v1_21_中文阅读稿.pdf'
shutil.copy2(rendered,destination)
report={'status':'PASS','source_version':'v1.21','source_english_unchanged':True,
        'all_five_equations_match':True,'all_body_decimal_values_and_multiplicities_match':True,
        'three_tables_match':True,'figures':5,'embedded_images':7,'editable_math_objects':51,'references':14,
        'pdf':pdf_check,'changed_render_pages_since_previous_visual_review':changed,
        'artifacts':{p.name:sha(p) for p in [docx,destination]}}
(qa/'chinese_delivery_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
(root/'SHA256SUMS.txt').write_text('\n'.join(f'{value}  {key}' for key,value in report['artifacts'].items())+'\n',encoding='utf-8')
print(json.dumps({'status':'PASS','pages':8,'equations':5,'tables':3,'figures':5,'references':14,'changed_pages':changed},ensure_ascii=False))
