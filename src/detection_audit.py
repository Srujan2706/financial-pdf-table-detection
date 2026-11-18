"""Generate page-level detection inventories and annotated PDF-page images."""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

from .table_detector import _overlap, detect_tables

_COLORS = ("#d62728", "#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd", "#17becf")


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _render_annotated_page(page, detections: list[dict], ids: list[str]) -> Image.Image:
    scale = 1.5
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    x_scale = image.width / page.rect.width
    y_scale = image.height / page.rect.height

    for index, (detection, detection_id) in enumerate(zip(detections, ids)):
        x0, y0, x1, y1 = detection["Bounding Box"]
        rectangle = (
            x0 * x_scale,
            y0 * y_scale,
            x1 * x_scale,
            y1 * y_scale,
        )
        color = _COLORS[index % len(_COLORS)]
        draw.rectangle(rectangle, outline=color, width=4)
        label = f"{detection_id}  {detection['Table Title'][:54]}"
        label_box = draw.textbbox((0, 0), label, font=font)
        label_width = label_box[2] - label_box[0]
        label_height = label_box[3] - label_box[1]
        label_x = max(0, min(rectangle[0], image.width - label_width - 8))
        label_y = max(0, rectangle[1] - label_height - 7)
        draw.rectangle(
            (label_x, label_y, label_x + label_width + 8, label_y + label_height + 6),
            fill=color,
        )
        draw.text((label_x + 4, label_y + 3), label, fill="white", font=font)
    return image


def _save_contact_sheets(
    pdf_stem: str,
    pages: list[Image.Image],
    page_detection_counts: dict[int, int],
    output_dir: Path,
) -> None:
    cell_size = (300, 410)
    columns = 4
    batch_size = 24
    font = ImageFont.load_default()
    for batch_start in range(0, len(pages), batch_size):
        batch = pages[batch_start:batch_start + batch_size]
        rows = (len(batch) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * cell_size[0], rows * cell_size[1]), "#dddddd")
        for offset, page_image in enumerate(batch):
            page_number = batch_start + offset + 1
            page_image.thumbnail((cell_size[0] - 12, cell_size[1] - 34))
            cell = Image.new("RGB", cell_size, "white")
            cell.paste(page_image, ((cell_size[0] - page_image.width) // 2, 26))
            count = page_detection_counts.get(page_number, 0)
            label = f"{pdf_stem} p.{page_number} | {count} detection(s)"
            ImageDraw.Draw(cell).text((5, 6), label, fill="black", font=font)
            sheet.paste(
                cell,
                ((offset % columns) * cell_size[0], (offset // columns) * cell_size[1]),
            )
        batch_number = batch_start // batch_size + 1
        sheet.save(output_dir / f"{pdf_stem}_annotated_contact_{batch_number}.jpg", quality=90)


def generate_detection_audit(
    input_dir: str | Path,
    baseline_dir: str | Path,
    output_dir: str | Path,
) -> dict:
    input_dir = Path(input_dir)
    baseline_dir = Path(baseline_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    detection_fields = [
        "Detection ID", "PDF", "Page Number", "Table Title",
        "bbox_x0", "bbox_top", "bbox_x1", "bbox_bottom",
        "Strategy", "Rows", "Columns", "Overlapping Detection IDs",
        "Overlap Score", "Physical Table Status", "Duplicate Of",
        "Fragment Of", "Merged Region", "Title Correct",
    ]
    page_fields = [
        "PDF", "Page Number", "Baseline Count", "Latest Count",
        "Baseline Titles", "Latest Detection IDs and Titles",
    ]
    detection_rows = []
    page_rows = []
    summary = []

    for pdf_path in sorted(input_dir.glob("*.pdf")):
        records = detect_tables(pdf_path, include_diagnostics=True)
        grouped: dict[int, list[dict]] = defaultdict(list)
        for record in records:
            grouped[int(record["Page Number"])].append(record)

        baseline_records = _read_csv(baseline_dir / f"{pdf_path.stem}_tables.csv")
        baseline_by_page: dict[int, list[str]] = defaultdict(list)
        for record in baseline_records:
            baseline_by_page[int(record["Page Number"])].append(record["Table Title"])

        page_ids: dict[int, list[str]] = {}
        sequence = 0
        for page_number, page_records in sorted(grouped.items()):
            ids = []
            for record in page_records:
                sequence += 1
                detection_id = f"{pdf_path.stem}-P{page_number:03d}-T{sequence:03d}"
                ids.append(detection_id)
            page_ids[page_number] = ids

            for index, (record, detection_id) in enumerate(zip(page_records, ids)):
                peers = []
                scores = []
                for other_index, other in enumerate(page_records):
                    if other_index == index:
                        continue
                    score = _overlap(record["Bounding Box"], other["Bounding Box"])
                    if score > 0.05:
                        peers.append(ids[other_index])
                        scores.append(f"{ids[other_index]}={score:.3f}")
                x0, top, x1, bottom = record["Bounding Box"]
                metrics = record["Metrics"]
                detection_rows.append({
                    "Detection ID": detection_id,
                    "PDF": pdf_path.name,
                    "Page Number": page_number,
                    "Table Title": record["Table Title"],
                    "bbox_x0": x0,
                    "bbox_top": top,
                    "bbox_x1": x1,
                    "bbox_bottom": bottom,
                    "Strategy": record["Strategy"],
                    "Rows": metrics.get("rows", ""),
                    "Columns": metrics.get("columns", ""),
                    "Overlapping Detection IDs": "; ".join(peers),
                    "Overlap Score": "; ".join(scores),
                    "Physical Table Status": "pending visual review",
                    "Duplicate Of": "",
                    "Fragment Of": "",
                    "Merged Region": "",
                    "Title Correct": "pending visual review",
                })

        with pymupdf.open(pdf_path) as document:
            page_count = len(document)
            pages_for_sheet = []
            page_detection_counts = {page: len(items) for page, items in grouped.items()}
            for page_index, page in enumerate(document):
                page_number = page_index + 1
                current = grouped.get(page_number, [])
                ids = page_ids.get(page_number, [])
                annotated = _render_annotated_page(page, current, ids)
                if current:
                    annotated.save(
                        output_dir / f"{pdf_path.stem}_page_{page_number:03d}.png"
                    )
                pages_for_sheet.append(annotated)
                page_rows.append({
                    "PDF": pdf_path.name,
                    "Page Number": page_number,
                    "Baseline Count": len(baseline_by_page.get(page_number, [])),
                    "Latest Count": len(current),
                    "Baseline Titles": " | ".join(baseline_by_page.get(page_number, [])),
                    "Latest Detection IDs and Titles": " | ".join(
                        f"{id_}: {row['Table Title']}"
                        for id_, row in zip(ids, current)
                    ),
                })
            _save_contact_sheets(
                pdf_path.stem, pages_for_sheet, page_detection_counts, output_dir
            )

        summary.append({
            "PDF": pdf_path.name,
            "Baseline": len(baseline_records),
            "Latest": len(records),
            "Pages": page_count,
        })

    _write_csv(output_dir / "detection_audit.csv", detection_fields, detection_rows)
    _write_csv(output_dir / "page_comparison.csv", page_fields, page_rows)
    with (output_dir / "summary.md").open("w", encoding="utf-8") as handle:
        handle.write("# Detection audit\n\n")
        handle.write("Bounding boxes are PDF-point coordinates. Baseline files contain no bounding boxes.\n")
        handle.write("Overlap scores are review flags only; they do not prove duplication.\n\n")
        handle.write("| PDF | Baseline | Latest | Change |\n|---|---:|---:|---:|\n")
        for item in summary:
            handle.write(
                f"| {item['PDF']} | {item['Baseline']} | {item['Latest']} "
                f"| {item['Latest'] - item['Baseline']:+} |\n"
            )
        handle.write(
            f"| **Total** | **{sum(x['Baseline'] for x in summary)}** "
            f"| **{sum(x['Latest'] for x in summary)}** "
            f"| **{sum(x['Latest'] - x['Baseline'] for x in summary):+}** |\n\n"
        )
        handle.write(
            "Per-detection physical-table, duplicate, fragment, merge, and title judgments "
            "remain marked pending until visually reviewed.\n"
        )
    return {
        "detections": len(detection_rows),
        "pages": len(page_rows),
        "summary": summary,
        "output_dir": output_dir,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/input", help="Directory containing input PDFs")
    parser.add_argument("--baseline", required=True, help="Directory containing baseline CSV files")
    parser.add_argument("--output", default="data/output/diagnostics", help="Diagnostic output directory")
    args = parser.parse_args()
    result = generate_detection_audit(args.input, args.baseline, args.output)
    print(
        f"Audited {result['detections']} detections over {result['pages']} pages; "
        f"diagnostics written to {Path(result['output_dir']).resolve()}"
    )


if __name__ == "__main__":
    main()
