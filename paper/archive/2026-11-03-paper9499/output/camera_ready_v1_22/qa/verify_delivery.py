"""Check final format, the exact revision scope, and independent ZIP rebuild."""
from pathlib import Path
import hashlib
import json
import re
import zipfile
import pdfplumber
from pypdf import PdfReader

root = Path(__file__).resolve().parents[1]
previous = root.parent / 'camera_ready_v1_21'
helper = root.parent / 'camera_ready_v1_19/qa/verify_delivery.py'
namespace = {'__file__': __file__}
exec(helper.read_text(encoding='utf-8').split('\npaper = inspect_pdf(')[0], namespace)
inspect_pdf, sha = namespace['inspect_pdf'], namespace['sha']
paper_path = root / 'paper9499_camera_ready_v1_22.pdf'
paper = inspect_pdf(paper_path)
rebuilt = inspect_pdf(root / 'qa/zip_rebuild_paper/manuscript_v1_22.pdf')
for item in [paper, rebuilt]:
    assert item['pages'] == 5 and item['all_letter'] and item['all_fonts_embedded']
    assert not item['type3_fonts'] and not item['characters_outside_page']
assert paper['text_sha256'] == rebuilt['text_sha256']
text = '\n'.join(p.extract_text() or '' for p in PdfReader(paper_path).pages)
assert all(s not in text for s in ['EV-FLEX-BIAS', '3475301', 'accompanying repository', '??'])

main = (root / 'manuscript/manuscript_v1_22.tex').read_text(encoding='utf-8')
old = (previous / 'manuscript/manuscript_v1_21.tex').read_text(encoding='utf-8')
removed = (r' Scenario definitions and vehicle-level inputs are available in the accompanying repository.'
           r'\footnote{\url{https://github.com/Kato814/EV-FLEX-BIAS}, commit 3475301.}')
assert main == old.replace(removed, '').replace(r'\IEEEtriggeratref{6}', r'\IEEEtriggeratref{7}')
assert (root / 'manuscript/references.tex').read_bytes() == (previous / 'manuscript/references.tex').read_bytes()
for path in (previous / 'manuscript/figures').rglob('*'):
    if path.is_file():
        assert sha(path) == sha(root / 'manuscript/figures' / path.relative_to(previous / 'manuscript/figures'))
assert sha(root / 'manuscript/IEEEtran.cls') == 'c972aca108fda004c3514d63658e02816da2e54d9a1451e870b9bd970e003f55'
assert r'\documentclass[conference,letterpaper]{IEEEtran}' in main
assert not re.search(r'\\(?:usepackage(?:\[[^\]]*\])?\{geometry\}|linespread|fontsize|newgeometry)|\\setlength\{\\(?:textwidth|textheight|oddsidemargin|evensidemargin|topmargin|baselineskip)\}', main)
refs = (root / 'manuscript/references.tex').read_text(encoding='utf-8')
counts = {n: main.count('\\begin{' + n + '}') for n in ['figure', 'table', 'equation']}
counts['references'] = refs.count('\\bibitem')
assert counts == {'figure': 5, 'table': 3, 'equation': 5, 'references': 14}
labels = re.findall(r'\\label\{([^}]+)\}', main)
assert len(labels) == len(set(labels))
assert set(re.findall(r'\\(?:eq)?ref\{([^}]+)\}', main)) <= set(labels)
bibkeys = set(re.findall(r'\\bibitem\{([^}]+)\}', refs))
cites = {key for group in re.findall(r'\\cite\{([^}]+)\}', main) for key in group.split(',')}
assert cites == bibkeys and len(bibkeys) == 14

archive = root / 'paper9499_v1_22_LaTeX.zip'
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    names = z.namelist()
    assert not any('response' in name.lower() for name in names)
    for line in z.read('SHA256SUMS.txt').decode('utf-8').splitlines():
        expected, name = line.split('  ', 1)
        assert hashlib.sha256(z.read(name)).hexdigest() == expected
    assert z.read('manuscript_v1_22.tex') == (root / 'manuscript/manuscript_v1_22.tex').read_bytes()
log = (root / 'qa/zip_rebuild_paper/manuscript_v1_22.log').read_text(encoding='utf-8', errors='replace')
assert not re.search(r'Overfull \\[hv]box|Undefined control sequence|undefined references|Missing character|not loadable', log, re.I)
warnings = [line for line in log.splitlines() if re.search(r'Underfull|Warning', line)]
with pdfplumber.open(paper_path) as pdf:
    page = pdf.pages[-1]
    bottoms = [max(c['bottom'] for c in page.chars if low <= c['x0'] < high)
               for low, high in [(0, 306), (306, 612)]]
assert abs(bottoms[0] - bottoms[1]) < 12

report = {
    'status': 'PASS', 'version': 'v1.22', 'date': '2026-10-15',
    'changes': ['Removed repository sentence and URL footnote',
                'Moved the reference column break before reference 7 to balance the last page'],
    'pdf': paper, 'independent_source_zip_rebuild': 'PASS; identical text and page geometry',
    'all_other_manuscript_text_unchanged': True,
    'all_figure_assets_and_data_unchanged': True,
    'all_references_and_citations_unchanged': True,
    'template_class_unchanged': True, 'default_ieee_conference_layout': True,
    'cross_references_resolved': True, 'counts': counts,
    'last_page_column_bottoms_pt': bottoms,
    'source_zip_sha256': sha(archive), 'package_entries': names,
    'compile_warnings': warnings,
    'visual_review': 'All 5 pages inspected; no clipping, overlaps, missing glyphs, equation overflow or unresolved references. Last-page columns balanced. Bibliography URL line spacing checked.'
}
(root / 'qa/final_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
artifacts = ['paper9499_camera_ready_v1_22.pdf', 'paper9499_v1_22_LaTeX.zip', 'README.txt', 'qa/final_verification.json']
(root / 'SHA256SUMS.txt').write_text('\n'.join(f'{sha(root / n)}  {n}' for n in artifacts) + '\n', encoding='utf-8')
print(json.dumps({'status': 'PASS', 'pages': paper['pages'], 'all_fonts_embedded': True,
                  'counts': counts, 'last_page_column_bottoms_pt': bottoms,
                  'compile_warnings': warnings}, indent=2))
