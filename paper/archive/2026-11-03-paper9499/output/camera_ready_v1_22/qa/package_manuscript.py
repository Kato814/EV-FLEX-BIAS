from pathlib import Path
import hashlib
import shutil
import zipfile

root = Path(__file__).resolve().parents[1]
evidence = root.parent / 'camera_ready_v1_19/evidence'
stage = root / 'source_package'
stage.mkdir(exist_ok=True)
files = []
for name in ['manuscript_v1_22.tex', 'references.tex', 'IEEEtran.cls']:
    files.append((root / 'manuscript' / name, name))
for name in ['fig1_network_feasibility_workflow.pdf', 'fig1_network_feasibility_workflow.svg',
             'fig2a_ieee13_topology.png', 'fig2b_lv906_topology.pdf', 'fig2b_lv906_topology.svg',
             'fig3_ieee13_scheduled_vs_feasible_offer.pdf', 'fig3_lv906_scheduled_vs_feasible_offer.pdf',
             'fig4_feasible_scaling_distribution.pdf', 'fig5_limiting_network_constraints.pdf']:
    files.append((root / 'manuscript/figures' / name, 'figures/' + name))
for name in ['fig3_scheduled_offer_data.csv', 'fig4_feasible_scaling_data.csv', 'fig5_boundary_data.csv']:
    files.append((root / 'manuscript/figures' / name, 'data/' + name))
for name in ['boundary_comparison.csv', 'case_table.csv', 'feeder_runtime_summary.csv']:
    files.append((evidence / name, 'data/' + name))
files.append((root / 'qa/rebuild_lv906_topology.py', 'qa/rebuild_lv906_topology.py'))
for name in ['Buscoords.txt', 'Lines.txt', 'Loads.txt', 'Transformers.txt', 'load_phase_map.csv']:
    files.append((root / 'qa/fig2b_source_data' / name, 'qa/fig2b_source_data/' + name))
files.append((root / 'README.txt', 'README.txt'))
manifest = []
for src, name in files:
    dst = stage / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    manifest.append(f'{hashlib.sha256(dst.read_bytes()).hexdigest()}  {name}')
(stage / 'SHA256SUMS.txt').write_text('\n'.join(manifest)+'\n', encoding='utf-8')
archive = root / 'paper9499_v1_22_LaTeX.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for _, name in files:
        z.write(stage / name, name)
    z.write(stage / 'SHA256SUMS.txt', 'SHA256SUMS.txt')
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert not any('response' in n.lower() for n in z.namelist())
    z.extractall(root / 'qa/zip_rebuild_source')
shutil.copy2(root / 'qa/paper_build/manuscript_v1_22.pdf', root / 'paper9499_camera_ready_v1_22.pdf')
print(f'{len(files)+1} package entries; ZIP integrity passed.')
