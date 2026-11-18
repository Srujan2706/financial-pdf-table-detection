
import pdfplumber

import re


def calculate_candidate_metrics(table, page):

    data = table.extract()

    if not data:
        return None

    row_widths = []
    populated_cells = []
    numeric_cells = []

    for row in data:

        cells = [
            str(cell).strip()
            for cell in row
            if cell and str(cell).strip()
        ]

        row_widths.append(len(cells))
        populated_cells.extend(cells)

        for cell in cells:
            if re.search(r"\d", cell):
                numeric_cells.append(cell)

    total_cells = sum(len(row) for row in data)

    nonempty_count = len(populated_cells)

    populated_rows = [
        width for width in row_widths if width > 0
    ]

    multi_cell_rows = sum(
        width >= 2 for width in row_widths
    )

    page_area = page.width * page.height

    x0, top, x1, bottom = table.bbox

    candidate_area = (
        (x1 - x0) * (bottom - top)
    )

    return {
        "rows": len(data),

        "columns": max(
            (len(row) for row in data),
            default=0
        ),

        "populated_cells": nonempty_count,

        "cell_occupancy": (
            nonempty_count / total_cells
            if total_cells else 0
        ),

        "numeric_cell_ratio": (
            len(numeric_cells) / nonempty_count
            if nonempty_count else 0
        ),

        "multi_cell_row_ratio": (
            multi_cell_rows / len(data)
            if data else 0
        ),

        "area_ratio": (
            candidate_area / page_area
            if page_area else 0
        ),

        "row_width_distribution": dict(
            __import__("collections").Counter(populated_rows)
        )
    }



TABLE_SETTINGS = [
    {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines"
    },
    {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "min_words_vertical": 3,
        "min_words_horizontal": 1
    }
]



def detect_native_tables(pdf_path):

    results = []

    with pdfplumber.open(pdf_path) as pdf:

        for page_number, page in enumerate(pdf.pages, start=1):

            for strategy_index, settings in enumerate(TABLE_SETTINGS):

                strategy_name = (
                    "lines" if strategy_index == 0 else "text"
                )

                try:
                    tables = page.find_tables(
                        table_settings=settings
                    )

                    for table_index, table in enumerate(tables, start=1):

                        metrics = calculate_candidate_metrics(table, page)

                        if metrics is None:
                            continue

                        results.append({
                            "page_number": page_number,
                            "strategy": strategy_name,
                            "table_index": table_index,
                            "bbox": table.bbox,
                            **metrics
                        })

                except Exception as error:

                    print(
                        f"Error on page {page_number}, "
                        f"strategy {strategy_name}: {error}"
                    )

    return results
