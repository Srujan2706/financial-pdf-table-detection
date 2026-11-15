
import pdfplumber
from pathlib import Path

import re
from collections import Counter


def detect_tables(pdf_path):
    """
    Detect tables using line-based and text-based
    layout analysis.
    """

    results = []

    strategies = {
        "lines": {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines"
        },
        "text": {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "min_words_vertical": 3,
            "min_words_horizontal": 1
        }
    }

    with pdfplumber.open(pdf_path) as pdf:

        for page_number, page in enumerate(pdf.pages, start=1):

            for strategy_name, settings in strategies.items():

                try:
                    tables = page.find_tables(
                        table_settings=settings
                    )

                    for table_index, table in enumerate(tables, start=1):

                        extracted_data = table.extract()

                        if not extracted_data:
                            continue

                        row_count = len(extracted_data)

                        column_count = max(
                            (len(row) for row in extracted_data if row),
                            default=0
                        )

                        results.append({
                            "page_number": page_number,
                            "strategy": strategy_name,
                            "table_index": table_index,
                            "bbox": table.bbox,
                            "rows": row_count,
                            "columns": column_count
                        })

                except Exception as error:
                    print(
                        f"Detection error on page {page_number}: "
                        f"{error}"
                    )

    return results


def inspect_all_pdfs(input_dir):

    pdf_files = list(Path(input_dir).glob("*.pdf"))

    for pdf_path in pdf_files:

        print("\n" + "=" * 65)
        print(f"Document: {pdf_path.name}")
        print("=" * 65)

        results = detect_tables(pdf_path)

        for result in results:
            print(
                f"Page {result['page_number']:3} | "
                f"Strategy: {result['strategy']:5} | "
                f"Rows: {result['rows']:3} | "
                f"Columns: {result['columns']:3} | "
                f"BBox: {result['bbox']}"
            )

        line_count = sum(
            r["strategy"] == "lines" for r in results
        )

        text_count = sum(
            r["strategy"] == "text" for r in results
        )

        print("\nDetection Summary:")
        print("Line-based candidates:", line_count)
        print("Text-based candidates:", text_count)
        print("Total candidates:", len(results))

def inspect_candidate_quality(pdf_path, page_number):

    strategies = {
        "lines": {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines"
        },
        "text": {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "min_words_vertical": 3,
            "min_words_horizontal": 1
        }
    }

    with pdfplumber.open(pdf_path) as pdf:

        page = pdf.pages[page_number - 1]

        page_area = page.width * page.height

        print(f"\nDocument: {Path(pdf_path).name}")
        print(f"Page: {page_number}")
        print("-" * 70)

        for strategy_name, settings in strategies.items():

            tables = page.find_tables(
                table_settings=settings
            )

            print(f"\nStrategy: {strategy_name}")
            print(f"Candidates: {len(tables)}")

            for index, table in enumerate(tables, start=1):

                data = table.extract()

                if not data:
                    continue

                bbox = table.bbox

                width = bbox[2] - bbox[0]
                height = bbox[3] - bbox[1]

                area_ratio = (
                    width * height / page_area
                )

                total_cells = sum(
                    len(row) for row in data
                )

                nonempty_cells = sum(
                    1
                    for row in data
                    for cell in row
                    if cell and cell.strip()
                )

                occupancy = (
                    nonempty_cells / total_cells
                    if total_cells else 0
                )

                columns = max(
                    (len(row) for row in data),
                    default=0
                )

                print(
                    f"\nCandidate {index}"
                    f"\nRows: {len(data)}"
                    f"\nColumns: {columns}"
                    f"\nArea ratio: {area_ratio:.3f}"
                    f"\nCell occupancy: {occupancy:.2%}"
                    f"\nBounding box: {bbox}"
                )
def analyze_table_structure(table):

    data = table.extract()

    if not data:
        return None

    row_cell_counts = []
    nonempty_cells = []
    numeric_cells = []

    for row in data:

        cells = [
            str(cell).strip()
            for cell in row
            if cell and str(cell).strip()
        ]

        row_cell_counts.append(len(cells))
        nonempty_cells.extend(cells)

        for cell in cells:
            if re.search(r"\d", cell):
                numeric_cells.append(cell)

    total_rows = len(data)
    total_cells = sum(len(row) for row in data)

    populated_cells = len(nonempty_cells)

    rows_with_multiple_cells = sum(
        count >= 2 for count in row_cell_counts
    )

    populated_rows = [
        count for count in row_cell_counts if count > 0
    ]

    width_distribution = Counter(populated_rows)

    most_common_width = (
        width_distribution.most_common(1)[0][1]
        if width_distribution else 0
    )

    return {
        "rows": total_rows,

        "columns": max(
            (len(row) for row in data),
            default=0
        ),

        "populated_cells": populated_cells,

        "cell_occupancy": (
            populated_cells / total_cells
            if total_cells else 0
        ),

        "multi_cell_row_ratio": (
            rows_with_multiple_cells / total_rows
            if total_rows else 0
        ),

        "row_consistency": (
            most_common_width / len(populated_rows)
            if populated_rows else 0
        ),

        "numeric_cell_ratio": (
            len(numeric_cells) / populated_cells
            if populated_cells else 0
        ),

        "row_width_distribution": dict(width_distribution)
    }

def inspect_structure(pdf_path, page_number):

    strategies = {
        "lines": {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines"
        },
        "text": {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "min_words_vertical": 3,
            "min_words_horizontal": 1
        }
    }

    with pdfplumber.open(pdf_path) as pdf:

        page = pdf.pages[page_number - 1]

        print(f"\n{Path(pdf_path).name} | Page {page_number}")
        print("-" * 65)

        for name, settings in strategies.items():

            tables = page.find_tables(
                table_settings=settings
            )

            for index, table in enumerate(tables, start=1):

                metrics = analyze_table_structure(table)

                if metrics is None:
                    continue

                print(
                    f"\n{name.upper()} | Candidate {index}"
                )

                for key, value in metrics.items():
                    print(f"{key}: {value:.3f}"
                          if isinstance(value, float)
                          else f"{key}: {value}")
def render_diagnostic(pdf_path, page_number, output_dir="data/output/diagnostics"):
    from pathlib import Path
    import pdfplumber

    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    strategies = {
        "lines": {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines"
        },
        "text": {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "min_words_vertical": 3,
            "min_words_horizontal": 1
        }
    }

    with pdfplumber.open(pdf_path) as pdf:
        if page_number < 1 or page_number > len(pdf.pages):
            raise ValueError(f"Invalid page number: {page_number}")

        page = pdf.pages[page_number - 1]
        image = page.to_image(resolution=120)

        for name, settings in strategies.items():
            tables = page.find_tables(table_settings=settings)

            rectangles = [table.bbox for table in tables]

            if name == "lines":
                image.draw_rects(
                    rectangles,
                    stroke="blue",
                    fill=None,
                    stroke_width=2
                )
            else:
                image.draw_rects(
                    rectangles,
                    stroke="red",
                    fill=None,
                    stroke_width=2
                )

        output_path = (
            output_dir /
            f"{pdf_path.stem}_page_{page_number}.png"
        )

        image.save(str(output_path))
        print(f"Diagnostic image saved: {output_path}")