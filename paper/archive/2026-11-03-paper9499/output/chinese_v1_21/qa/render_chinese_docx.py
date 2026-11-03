"""Use the packaged DOCX renderer with Microsoft Word as the Windows PDF backend.

The selected runtime does not bundle LibreOffice on Windows. This uses Word,
never the user's desktop LibreOffice, and retains the packaged PNG QA workflow.
"""
from pathlib import Path
import importlib.util
import subprocess
import sys

QA=Path(__file__).resolve().parent
skill=Path('C:/Users/Administrator/.codex/plugins/cache/openai-primary-runtime/documents/26.1013.11914/skills/documents/render_docx.py')
spec=importlib.util.spec_from_file_location('packaged_render_docx',skill)
renderer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)

def word_pdf(doc_path,user_profile,convert_tmp_dir,stem,verbose):
    destination=Path(convert_tmp_dir)/(stem+'.pdf')
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(QA/'export_word_pdf.ps1'),
                           '-DocInput',doc_path,'-PdfOutput',str(destination)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180)
    log=result.stdout+'\n'+result.stderr
    if verbose:print(log)
    return (str(destination) if result.returncode==0 and destination.exists() else '',log)

renderer.convert_to_pdf=word_pdf
renderer.main()
