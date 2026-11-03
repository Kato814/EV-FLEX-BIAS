"""Compile paper and poster sources into generated/pdfs without replacing final PDFs."""
from pathlib import Path
import argparse
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', help='Path to pdfLaTeX; otherwise search PATH and common MiKTeX locations')
    parser.add_argument('--target', choices=['paper', 'poster', 'both'], default='both')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    candidates = [args.compiler, shutil.which('pdflatex')]
    candidates.extend(str(p) for p in [
        Path.home() / 'AppData/Local/Programs/MiKTeX/miktex/bin/x64/pdflatex.exe',
        Path('C:/Program Files/MiKTeX/miktex/bin/x64/pdflatex.exe')])
    compiler = next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), None)
    if compiler is None:
        parser.error('Install a TeX distribution or provide --compiler /path/to/pdflatex')
    for name, tex in [('paper', 'manuscript.tex'), ('poster', 'poster.tex')]:
        if args.target not in ['both', name]:
            continue
        output = root / 'generated/pdfs' / name
        output.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            process = subprocess.run([compiler, '-interaction=nonstopmode', '-halt-on-error',
                '-file-line-error', '-output-directory=' + str(output), tex],
                cwd=root / name, capture_output=True, text=True, errors='replace')
            if process.returncode:
                raise RuntimeError(process.stdout[-6000:] + process.stderr[-2000:])
        print(output / Path(tex).with_suffix('.pdf'))


if __name__ == '__main__':
    main()
