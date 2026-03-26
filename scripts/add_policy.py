#!/usr/bin/env python3
"""
Singlife — Add Policy to Knowledge Base
=========================================
Extracts text from an insurance PDF and saves it to knowledge_base/
so that the AI assistant automatically includes it on next startup.

Usage
-----
  # From the project root:
  python scripts/add_policy.py <path/to/policy.pdf> [--name output-name]

Examples
--------
  python scripts/add_policy.py "AIA Home Insurance 2024.pdf"
  python scripts/add_policy.py docs/ntuc_home.pdf --name ntuc_home_2024
  python scripts/add_policy.py "Great Eastern Policy.pdf" --name great_eastern_home_sg

Output
------
  knowledge_base/<name>.txt   ← ready for the AI to load on next server restart

Requirements
------------
  pypdf  (already in requirements.txt)
  pip install pypdf
"""

import sys
import argparse
import re
from pathlib import Path

def extract_pdf_text(pdf_path: Path) -> str:
    try:
        import pypdf
    except ImportError:
        sys.exit(
            "Error: pypdf is not installed.\n"
            "Run: pip install pypdf"
        )

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
    """Convert a string to a safe filename slug."""
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '_', name)
    name = name.strip('_')
    return name


def main():
    parser = argparse.ArgumentParser(
        description="Extract an insurance PDF and add it to the Singlife knowledge base."
    )
    parser.add_argument(
        'pdf',
        type=Path,
        help="Path to the insurance policy PDF file."
    )
    parser.add_argument(
        '--name', '-n',
        type=str,
        default=None,
        help=(
            "Output filename (without .txt extension). "
            "Defaults to the PDF filename. "
            "Example: --name aia_home_2024"
        )
    )
    args = parser.parse_args()

    pdf_path = args.pdf.resolve()

    # Determine output filename
    if args.name:
        out_name = slugify(args.name)
    else:
        out_name = slugify(pdf_path.stem)

    if not out_name:
        out_name = "policy"

    # Locate knowledge_base/ relative to this script (scripts/ → root)
    kb_dir = Path(__file__).parent.parent / 'knowledge_base'
    kb_dir.mkdir(exist_ok=True)
    out_path = kb_dir / f"{out_name}.txt"

    print(f"\nSinglife — Add Policy to Knowledge Base")
    print(f"{'─' * 44}")
    print(f"  Source : {pdf_path}")
    print(f"  Output : {out_path}")
    print()

    # Extract
    text = extract_pdf_text(pdf_path)

    if not text.strip():
        print(
            "\nWarning: No text could be extracted from this PDF.\n"
            "The PDF may be image-based (scanned). For scanned PDFs,\n"
            "you will need an OCR tool such as Adobe Acrobat or tesseract\n"
            "to first convert it to a text-based PDF, then run this script again."
        )
        sys.exit(1)

    # Write output
    header = (
        f"# {pdf_path.stem}\n"
        f"Source file: {pdf_path.name}\n"
        f"Pages extracted: {text.count(chr(12)) + len(text.split(chr(10) * 2))}\n"
        f"Added via: scripts/add_policy.py\n\n"
        f"{'─' * 80}\n\n"
    )
    out_path.write_text(header + text, encoding='utf-8')

    char_count = len(text)
    word_count = len(text.split())

    print(f"  Done!")
    print(f"  Extracted : {char_count:,} characters | {word_count:,} words")
    print(f"  Saved to  : {out_path}")
    print()
    print(f"  Next step: Restart the Singlife server to load this policy.")
    print(f"  The AI will automatically include '{pdf_path.stem}' in its knowledge base.")
    print()


if __name__ == '__main__':
    main()
