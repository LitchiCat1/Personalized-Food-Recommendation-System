"""Use Word for PDF export, then the packaged renderer for page images.

The Windows dependency bundle does not include LibreOffice. Word is available
on this host, so the document is exported read-only by an isolated COM instance.
"""

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess


RUNTIME = Path(r"C:\Users\botto\.cache\codex-runtimes\codex-primary-runtime")
RENDERER = RUNTIME / "plugins/openai-primary-runtime/plugins/documents/skills/documents/render_docx.py"
POPLER = RUNTIME / "dependencies/native/poppler/Library/bin"


def word_to_pdf(doc_path, user_profile, convert_tmp_dir, stem, *, verbose=False):
    del user_profile
    pdf_path = Path(convert_tmp_dir) / f"{stem}.pdf"
    process = subprocess.run(
        ["powershell.exe", "-NoProfile", "-File", str(Path(__file__).with_name("render_stress_report_word.ps1")),
         "-DocumentPath", str(Path(doc_path).resolve()), "-PdfPath", str(pdf_path)],
        capture_output=True, text=True, timeout=120,
    )
    log = process.stdout + process.stderr
    if process.returncode or not pdf_path.is_file():
        raise RuntimeError(f"Word export failed: {log}")
    if verbose:
        print("Read-only Word export completed")
    return str(pdf_path), log


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("document", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    os.environ["PATH"] = str(POPLER) + os.pathsep + os.environ.get("PATH", "")
    spec = importlib.util.spec_from_file_location("docx_renderer", RENDERER)
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.convert_to_pdf = word_to_pdf
    pages = renderer.rasterize(str(args.document), str(args.output_dir), dpi=150, verbose=True, emit_pdf=True)
    print(f"Rendered {len(pages)} pages")
    for page in pages:
        print(page)
