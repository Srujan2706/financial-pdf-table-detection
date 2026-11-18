"""Command-line entry point."""
from __future__ import annotations
import argparse
from pathlib import Path
from .table_detector import detect_tables
from .result_exporter import export_results

def main():
    parser = argparse.ArgumentParser(
        description="Detect financial-statement tables and export their titles and page numbers."
    )
    parser.add_argument("input", help="PDF file or directory containing PDF files")
    parser.add_argument("-o", "--output", default="data/output", help="Output directory (default: data/output)")
    parser.add_argument("--no-ocr", action="store_true", help="Disable Tesseract OCR fallback")
    args = parser.parse_args()
    source = Path(args.input)
    if not source.exists():
        parser.error(f"Input path does not exist: {source}")
    files = [source] if source.is_file() else sorted(source.glob("*.pdf"))
    if not files:
        parser.error(f"No PDF files found in {source}")
    output = Path(args.output)
    for pdf in files:
        print(f"Processing {pdf.name}...", flush=True)
        try:
            rows = detect_tables(pdf, use_ocr=not args.no_ocr)
            csv_path, json_path = export_results(rows, output, pdf.stem)
            print(
                f"{pdf.name}: {len(rows)} table(s) -> "
                f"{csv_path.name}, {json_path.name}",
                flush=True,
            )
            for row in rows:
                print(
                    f"  Page {row['Page Number']}: {row['Table Title']}",
                    flush=True,
                )
        except Exception as exc:
            print(f"[ERROR] {pdf.name}: {exc}", flush=True)
    print(f"\nFinished. Output directory: {output.resolve()}", flush=True)

if __name__ == "__main__":
    main()
