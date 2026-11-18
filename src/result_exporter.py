"""CSV and JSON export for table title/page results."""
from __future__ import annotations
import csv
import json
from pathlib import Path

FIELDS = ["Table Title", "Page Number"]

def export_results(results: list[dict], output_dir: str | Path, stem: str) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized = [{field: row.get(field, "") for field in FIELDS} for row in results]
    csv_path = output_dir / f"{stem}_tables.csv"
    json_path = output_dir / f"{stem}_tables.json"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(normalized)
    json_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    return csv_path, json_path
