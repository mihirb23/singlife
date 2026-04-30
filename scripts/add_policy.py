#!/usr/bin/env python3
# add_policy.py — extracts text from a PDF and drops it into knowledge_base/
# handy for quickly adding new SOPs or policy docs without going thru the UI
#
# usage:
#   python scripts/add_policy.py "some_policy.pdf"
#   python scripts/add_policy.py docs/policy.pdf --name aia_home_2024

import sys
import argparse
import re
from pathlib import Path

def extract_pdf_text(pdf_path: Path) -> str:
    try:
        import pypdf
    except ImportError:
        sys.exit("Error: pypdf is not installed. Run: pip install pypdf")

    if not pdf_path.exists():
        sys.exit(f"Error: File not found: {pdf_path}")

    if pdf_path.suffix.lower() != '.pdf':
        sys.exit(f"Error: Expected a .pdf file, got: {pdf_path.suffix}")

    reader = pypdf.PdfReader(str(pdf_path))
    total = len(reader.pages)
    print(f"  Reading {total} pages from '{pdf_path.name}'...")

    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        text = text.strip()
        if text:
            pages.append(text)
        if (i + 1) % 10 == 0:
            print(f"  ... processed {i + 1}/{total} pages")

    return "\n\n".join(pages)


def slugify(name: str) -> str:
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '_', name)
    return name.strip('_')


def main():
    parser = argparse.ArgumentParser(
        description="Extract text from an insurance PDF and add it to the knowledge base."
    )
    parser.add_argument('pdf', type=Path, help="Path to the PDF file")
    parser.add_argument('--name', '-n', type=str, default=None,
                        help="Output filename without .txt (defaults to PDF name)")
    args = parser.parse_args()

    pdf_path = args.pdf.resolve()
    out_name = slugify(args.name) if args.name else slugify(pdf_path.stem)
    if not out_name:
        out_name = "policy"

    # knowledge_base/ is one level up from scripts/
    kb_dir = Path(__file__).parent.parent / 'knowledge_base'
    kb_dir.mkdir(exist_ok=True)
    out_path = kb_dir / f"{out_name}.txt"

    # don't silently overwrite — bump the suffix if the file already exists
    if out_path.exists():
        counter = 2
        while (kb_dir / f"{out_name}_{counter}.txt").exists():
            counter += 1
        new_path = kb_dir / f"{out_name}_{counter}.txt"
        print(f"  Note: '{out_path.name}' exists — saving as '{new_path.name}' instead")
        out_path = new_path

    print(f"\nAdding policy to knowledge base")
    print(f"  Source : {pdf_path}")
    print(f"  Output : {out_path}\n")

    text = extract_pdf_text(pdf_path)

    if not text.strip():
        print("\nNo text extracted — PDF might be scanned/image-based.")
        print("Try OCR (e.g. Adobe Acrobat or tesseract) first.")
        sys.exit(1)

    # report a meaningful page count instead of the previous bogus formula
    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        page_count = len(reader.pages)
    except Exception:
        page_count = 'unknown'

    header = (
        f"# {pdf_path.stem}\n"
        f"Source file: {pdf_path.name}\n"
        f"Pages: {page_count}\n\n"
        f"{'─' * 80}\n\n"
    )
    try:
        out_path.write_text(header + text, encoding='utf-8')
    except OSError as e:
        sys.exit(f"\nError writing to {out_path}: {e}")

    print(f"  Done! {len(text):,} chars extracted")
    print(f"  Saved to: {out_path}")
    print(f"  The running server will pick this up via incremental indexing")
    print(f"  on its next /api/upload, restart, or any KB-changing request.\n")


if __name__ == '__main__':
    main()
