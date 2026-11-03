"""Create the final formatting revision without altering scientific content."""
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
previous = root.parent / 'camera_ready_v1_21'
manuscript = root / 'manuscript'
manuscript.mkdir(exist_ok=True)
for name in ['IEEEtran.cls', 'references.tex']:
    shutil.copy2(previous / 'manuscript' / name, manuscript / name)
shutil.copytree(previous / 'manuscript/figures', manuscript / 'figures', dirs_exist_ok=True)
removed = (r' Scenario definitions and vehicle-level inputs are available in the accompanying repository.'
           r'\footnote{\url{https://github.com/Kato814/EV-FLEX-BIAS}, commit 3475301.}').encode('utf-8')
old = (previous / 'manuscript/manuscript_v1_21.tex').read_bytes()
assert old.count(removed) == 1
(manuscript / 'manuscript_v1_22.tex').write_bytes(
    old.replace(removed, b'').replace(b'\\IEEEtriggeratref{6}', b'\\IEEEtriggeratref{7}'))
shutil.copy2(previous / 'qa/rebuild_lv906_topology.py', root / 'qa/rebuild_lv906_topology.py')
shutil.copytree(previous / 'qa/fig2b_source_data', root / 'qa/fig2b_source_data', dirs_exist_ok=True)
package = (previous / 'qa/package_manuscript.py').read_text(encoding='utf-8').replace('v1_21', 'v1_22')
(root / 'qa/package_manuscript.py').write_text(package, encoding='utf-8')
readme = (previous / 'README.txt').read_text(encoding='utf-8').replace('v1.21', 'v1.22').replace('v1_21', 'v1_22')
start, end = readme.index('本次修改'), readme.index('编译')
readme = readme[:start] + ('本次修改\n删除正文中的仓库网址脚注及对应的仓库说明句。\n'
    '调整末页参考文献的分栏位置，使两栏高度接近一致。\n'
    '其余正文、公式、图表、数据与参考文献均与 v1.21 一致。保留原版本供对照。\n\n') + readme[end:]
readme = readme.replace('基于 v1.20', '基于 v1.21').replace('图表核对后的论文 PDF。', '最终格式检查后的论文 PDF。')
(root / 'README.txt').write_text(readme, encoding='utf-8')
print('Prepared v1.22: repository sentence and footnote removed; reference columns balanced.')
