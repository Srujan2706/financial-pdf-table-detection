"""Validation script for Financial PDF Table Detection output files.

Validates schema compliance, CSV/JSON record parity, page number bounds,
and title quality across generated output files.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

try:
    import pymupdf
except ImportError:
    pymupdf = None


REQUIRED_FIELDS = ["Table Title", "Page Number"]

# Patterns that indicate an invalid or uncleaned title
UNWANTED_TITLE_PATTERNS = [
    re.compile(r"^\s*\|\s*"),
    re.compile(r"\|\s*$"),
    re.compile(r"^\d+\s*\|\s*"),
    re.compile(r"^\s*[-–—:]+\s*"),
    re.compile(r"\b(?:we\s+have\s+audited|management\s+is\s+responsible|in\s+our\s+opinion)\b", re.I),
]


def validate_document_outputs(
    stem: str,
    output_dir: Path,
    input_dir: Path | None = None,
) -> dict:
    """Validate CSV and JSON output files for a single document stem."""
    csv_path = output_dir / f"{stem}_tables.csv"
    json_path = output_dir / f"{stem}_tables.json"
    pdf_path = (input_dir / f"{stem}.pdf") if input_dir else None

    errors = []
    warnings = []

    # 1. Existence Check
    if not csv_path.is_file():
        errors.append(f"Missing CSV output: {csv_path.name}")
    if not json_path.is_file():
        errors.append(f"Missing JSON output: {json_path.name}")

    if errors:
        return {
            "stem": stem,
            "table_count": 0,
            "passed": False,
            "errors": errors,
            "warnings": warnings,
        }

    # 2. Read and Validate CSV
    csv_records = []
    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != REQUIRED_FIELDS:
                errors.append(
                    f"CSV header mismatch: expected {REQUIRED_FIELDS}, got {reader.fieldnames}"
                )
            for idx, row in enumerate(reader, start=1):
                csv_records.append(row)
    except Exception as exc:
        errors.append(f"Error reading CSV {csv_path.name}: {exc}")

    # 3. Read and Validate JSON
    json_records = []
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            errors.append(f"JSON root must be an array of objects: {json_path.name}")
        else:
            json_records = data
            for idx, row in enumerate(json_records, start=1):
                if not isinstance(row, dict):
                    errors.append(f"JSON record #{idx} is not an object")
                elif list(row.keys()) != REQUIRED_FIELDS:
                    errors.append(
                        f"JSON record #{idx} keys mismatch: expected {REQUIRED_FIELDS}, got {list(row.keys())}"
                    )
    except Exception as exc:
        errors.append(f"Error reading JSON {json_path.name}: {exc}")

    # 4. CSV and JSON Parity Check
    if len(csv_records) != len(json_records):
        errors.append(
            f"Record count mismatch: CSV has {len(csv_records)}, JSON has {len(json_records)}"
        )
    else:
        for idx, (c_row, j_row) in enumerate(zip(csv_records, json_records), start=1):
            if c_row.get("Table Title") != str(j_row.get("Table Title")):
                errors.append(
                    f"Row #{idx} title mismatch: CSV={repr(c_row.get('Table Title'))} vs JSON={repr(j_row.get('Table Title'))}"
                )
            if str(c_row.get("Page Number")) != str(j_row.get("Page Number")):
                errors.append(
                    f"Row #{idx} page mismatch: CSV={repr(c_row.get('Page Number'))} vs JSON={repr(j_row.get('Page Number'))}"
                )

    # 5. Page Count and Bounds Check
    total_pages = None
    if pdf_path and pdf_path.is_file() and pymupdf is not None:
        try:
            with pymupdf.open(pdf_path) as doc:
                total_pages = len(doc)
        except Exception as exc:
            warnings.append(f"Could not open source PDF {pdf_path.name}: {exc}")

    for idx, row in enumerate(csv_records, start=1):
        # Validate Page Number
        try:
            page_num = int(row.get("Page Number", ""))
            if page_num < 1:
                errors.append(f"Row #{idx}: Page Number must be positive (got {page_num})")
            elif total_pages is not None and page_num > total_pages:
                errors.append(
                    f"Row #{idx}: Page Number {page_num} exceeds PDF total pages ({total_pages})"
                )
        except ValueError:
            errors.append(f"Row #{idx}: Invalid integer for Page Number: {repr(row.get('Page Number'))}")

        # Validate Table Title
        title = row.get("Table Title", "")
        if not title:
            errors.append(f"Row #{idx}: Table Title cannot be empty")
        elif title != "Untitled table":
            for pat in UNWANTED_TITLE_PATTERNS:
                if pat.search(title):
                    warnings.append(f"Row #{idx}: Suspicious pattern in title: {repr(title)}")
                    break

    passed = len(errors) == 0
    return {
        "stem": stem,
        "table_count": len(csv_records),
        "passed": passed,
        "errors": errors,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser(description="Validate Financial PDF Table Detection output files.")
    parser.add_argument("-o", "--output", default="data/output", help="Output directory containing CSV/JSON files")
    parser.add_argument("-i", "--input", default="data/input", help="Input directory containing source PDF files")
    parser.add_argument("--strict", action="store_true", help="Fail if any warnings are detected")
    args = parser.parse_args()

    output_dir = Path(args.output)
    input_dir = Path(args.input) if Path(args.input).is_dir() else None

    if not output_dir.is_dir():
        print(f"[ERROR] Output directory not found: {output_dir.resolve()}", file=sys.stderr)
        sys.exit(1)

    # Discover document stems
    stems = set()
    for f in output_dir.glob("*_tables.csv"):
        stem = f.name[:-len("_tables.csv")]
        stems.add(stem)
    for f in output_dir.glob("*_tables.json"):
        stem = f.name[:-len("_tables.json")]
        stems.add(stem)

    if not stems:
        print(f"[ERROR] No generated table output files found in {output_dir.resolve()}", file=sys.stderr)
        sys.exit(1)

    sorted_stems = sorted(stems)
    results = [validate_document_outputs(stem, output_dir, input_dir) for stem in sorted_stems]

    print("\n" + "=" * 78)
    print("FINANCIAL PDF TABLE DETECTION — OUTPUT VALIDATION REPORT")
    print("=" * 78)
    print(f"{'Document':<24} | {'Tables':<8} | {'Parity':<8} | {'Integrity':<11} | {'Status':<8}")
    print("-" * 78)

    total_tables = 0
    all_passed = True
    any_warnings = False

    for r in results:
        total_tables += r["table_count"]
        parity = "OK" if not any("parity" in e.lower() or "mismatch" in e.lower() for e in r["errors"]) else "FAIL"
        integrity = "OK" if not r["errors"] else "FAIL"
        status = "PASS" if r["passed"] else "FAIL"
        if not r["passed"]:
            all_passed = False
        if r["warnings"]:
            any_warnings = True
            if status == "PASS":
                status = "WARN"

        print(f"{r['stem']:<24} | {r['table_count']:<8} | {parity:<8} | {integrity:<11} | {status:<8}")

    print("-" * 78)
    print(f"{'Total':<24} | {total_tables:<8} | {'':<8} | {'':<11} | {'ALL PASS' if all_passed else 'FAILED'}")
    print("=" * 78 + "\n")

    # Detailed issue reports if any
    for r in results:
        if r["errors"]:
            print(f"[FAIL] {r['stem']}:")
            for err in r["errors"]:
                print(f"  - Error: {err}")
        if r["warnings"]:
            print(f"[WARN] {r['stem']}:")
            for warn in r["warnings"]:
                print(f"  - Warning: {warn}")

    if all_passed and (not any_warnings or not args.strict):
        print("Validation successful: all documents passed schema, parity, and integrity checks.\n")
        sys.exit(0)
    else:
        print("Validation failed with errors or strict warnings.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
