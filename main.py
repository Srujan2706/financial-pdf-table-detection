
import pdfplumber
import re
import csv
import json
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

PDF_PATH = "data/input/Document2.pdf"

OUTPUT_DIR = Path("data/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

CSV_PATH = OUTPUT_DIR / "Document2_products.csv"
JSON_PATH = OUTPUT_DIR / "Document2_products.json"


# Column boundaries for Document2 invoice
COLUMN_BOUNDARIES = [
    28.05,
    83.10,
    137.85,
    222.25,
    308.05,
    376.30,
    418.05,
    490.55,
    567.65
]

HEADERS = [
    "Carton",
    "Order No",
    "Part Number",
    "Description",
    "Unit Price",
    "Qty",
    "Sales Value",
    "Customs Value",
    "Country of Origin",
    "Commodity Code"
]


# ============================================================
# TEXT PROCESSING
# ============================================================

def group_words_into_lines(words, tolerance=3):

    lines = []

    words = sorted(
        words,
        key=lambda word: (word["top"], word["x0"])
    )

    for word in words:

        placed = False

        for line in lines:

            if abs(line["top"] - word["top"]) <= tolerance:

                line["words"].append(word)
                placed = True
                break

        if not placed:

            lines.append({
                "top": word["top"],
                "words": [word]
            })

    for line in lines:
        line["words"].sort(key=lambda word: word["x0"])

    lines.sort(key=lambda line: line["top"])

    return lines


def get_line_text(line):

    return " ".join(
        word["text"] for word in line["words"]
    ).strip()


def get_column_text(words, column_index):

    left = COLUMN_BOUNDARIES[column_index]
    right = COLUMN_BOUNDARIES[column_index + 1]

    selected = [
        word for word in words
        if left <= (word["x0"] + word["x1"]) / 2 < right
    ]

    selected.sort(
        key=lambda word: (word["top"], word["x0"])
    )

    return " ".join(
        word["text"] for word in selected
    ).strip()


# ============================================================
# PRODUCT NUMBER VALIDATION
# ============================================================

def is_valid_part_number(value):

    value = value.strip()

    return (
        len(value) >= 5
        and bool(re.search(r"\d", value))
        and bool(
            re.fullmatch(
                r"[A-Z0-9][A-Z0-9./-]*",
                value,
                re.IGNORECASE
            )
        )
    )


# ============================================================
# FIND ACTUAL PRODUCT LINE
# ============================================================

def find_product_line(lines):

    for index, line in enumerate(lines):

        part_number = get_column_text(
            line["words"], 2
        )

        if is_valid_part_number(part_number):

            return index

    return None


# ============================================================
# DETECT PRODUCT ROW BOUNDARIES
# ============================================================

def detect_product_row_boundaries(page):

    words = page.extract_words(
        x_tolerance=2,
        y_tolerance=3
    )

    lines = group_words_into_lines(words)

    header_index = None

    for index, line in enumerate(lines):

        text = get_line_text(line).lower()

        if "carton" in text and "part number" in text:

            header_index = index
            break

    if header_index is None:
        return []

    header_top = lines[header_index]["top"]

    horizontal_edges = []

    for edge in page.edges:

        if edge.get("orientation") != "h":
            continue

        if edge["top"] <= header_top:
            continue

        if edge["width"] >= 500:

            if edge["x0"] <= 35 and edge["x1"] >= 560:

                horizontal_edges.append(edge["top"])

    horizontal_edges = sorted(set(horizontal_edges))

    product_intervals = []

    for index in range(len(horizontal_edges) - 1):

        top = horizontal_edges[index]
        bottom = horizontal_edges[index + 1]

        if bottom - top < 8:
            continue

        row_words = [
            word for word in words
            if top <= word["top"] < bottom
        ]

        row_lines = group_words_into_lines(row_words)

        if find_product_line(row_lines) is not None:

            product_intervals.append({
                "top": top,
                "bottom": bottom
            })

    return product_intervals


# ============================================================
# PARSE INDIVIDUAL PRODUCT ROW
# ============================================================

def parse_row(row_words, top, bottom):

    lines = group_words_into_lines(row_words)

    main_index = find_product_line(lines)

    if main_index is None:
        return None

    main_line = lines[main_index]
    main_words = main_line["words"]

    product = {}

    # Extract the main product fields
    for index, header in enumerate(HEADERS[:8]):

        product[header] = get_column_text(
            main_words,
            index
        )

    # --------------------------------------------------------
    # Description continuation
    # --------------------------------------------------------

    description_parts = []

    if product["Description"]:
        description_parts.append(product["Description"])

    for line in lines[main_index + 1:]:

        line_text = get_line_text(line)

        if not line_text:
            continue

        lower_text = line_text.lower()

        # Stop description at country metadata
        if "country of origin" in lower_text:
            break

        # Ignore export-control disclaimer lines
        if (
            "this item is not controlled" in lower_text
            or "export control regulations" in lower_text
            or "controlled under" in lower_text
        ):
            continue

        # Only use words inside the description column
        continuation = get_column_text(
            line["words"],
            3
        )

        if continuation:
            description_parts.append(continuation)

    product["Description"] = " ".join(
        description_parts
    ).strip()

    # --------------------------------------------------------
    # Fill missing numeric fields from nearby words
    # This handles vertically shifted values in page 6.
    # --------------------------------------------------------

    numeric_fields = {
        "Unit Price": 4,
        "Qty": 5,
        "Sales Value": 6,
        "Customs Value": 7
    }

    main_top = main_line["top"]

    for field, column_index in numeric_fields.items():

        if product[field]:
            continue

        left = COLUMN_BOUNDARIES[column_index]
        right = COLUMN_BOUNDARIES[column_index + 1]

        candidates = []

        for word in row_words:

            word_center = (
                word["x0"] + word["x1"]
            ) / 2

            if not (left <= word_center < right):
                continue

            if abs(word["top"] - main_top) > 8:
                continue

            value = word["text"].strip()

            if re.fullmatch(r"[\d,.]+", value):

                candidates.append(word)

        candidates.sort(
            key=lambda word: abs(word["top"] - main_top)
        )

        if candidates:

            product[field] = " ".join(
                word["text"] for word in sorted(
                    candidates,
                    key=lambda word: word["x0"]
                )
            )

    # --------------------------------------------------------
    # Extract Country of Origin only from its labelled line
    # --------------------------------------------------------

    product["Country of Origin"] = ""

    for line in lines:

        line_text = get_line_text(line)

        match = re.search(
            r"Country of Origin\s*:\s*(.*)",
            line_text,
            re.IGNORECASE
        )

        if match:

            product["Country of Origin"] = match.group(1).strip()
            break

    # --------------------------------------------------------
    # Extract Commodity Code
    # --------------------------------------------------------

    product["Commodity Code"] = ""

    for line in lines:

        line_text = get_line_text(line)

        match = re.search(
            r"Commodity Code\s*:?\s*(\d+)",
            line_text,
            re.IGNORECASE
        )

        if match:

            product["Commodity Code"] = match.group(1)
            break

    # --------------------------------------------------------
    # Remove empty or duplicate spaces
    # --------------------------------------------------------

    for key in product:

        product[key] = re.sub(
            r"\s+",
            " ",
            product[key]
        ).strip()

    return product


# ============================================================
# EXTRACT PRODUCTS FROM A PAGE
# ============================================================

def extract_page_products(page, page_number):

    words = page.extract_words(
        x_tolerance=2,
        y_tolerance=3
    )

    intervals = detect_product_row_boundaries(page)

    products = []

    for interval in intervals:

        top = interval["top"]
        bottom = interval["bottom"]

        row_words = [
            word for word in words
            if top <= word["top"] < bottom
        ]

        product = parse_row(
            row_words,
            top,
            bottom
        )

        if product:

            product["Page Number"] = page_number

            products.append(product)

    return products


# ============================================================
# EXPORT CSV
# ============================================================

def export_csv(products):

    fieldnames = HEADERS + ["Page Number"]

    with open(
        CSV_PATH,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()
        writer.writerows(products)

    print(f"CSV saved: {CSV_PATH}")


# ============================================================
# EXPORT JSON
# ============================================================

def export_json(products):

    with open(
        JSON_PATH,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            products,
            file,
            indent=4,
            ensure_ascii=False
        )

    print(f"JSON saved: {JSON_PATH}")


# ============================================================
# VALIDATION SUMMARY
# ============================================================

def validate_products(products):

    print("\nVALIDATION CHECK")

    missing_count = 0

    for product in products:

        missing = [
            field
            for field in HEADERS
            if not product.get(field)
        ]

        if missing:

            missing_count += 1

            print(
                f"Page {product['Page Number']} | "
                f"Part: {product.get('Part Number')} | "
                f"Missing: {', '.join(missing)}"
            )

    if missing_count == 0:

        print("No missing fields detected.")

    else:

        print(
            f"\nProducts with missing fields: {missing_count}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    all_products = []
    page_summary = []

    print("Starting Document2 extraction...\n")

    with pdfplumber.open(PDF_PATH) as pdf:

        for page_number, page in enumerate(
            pdf.pages,
            start=1
        ):

            products = extract_page_products(
                page,
                page_number
            )

            page_summary.append({
                "page": page_number,
                "count": len(products)
            })

            all_products.extend(products)

    # Page-wise summary
    print("PAGE-WISE SUMMARY")
    print("-----------------")

    for item in page_summary:

        print(
            f"Page {item['page']}: "
            f"{item['count']} products"
        )

    print("\n-----------------")
    print("TOTAL PRODUCTS:", len(all_products))
    print("-----------------")

    # Export files
    export_csv(all_products)
    export_json(all_products)

    # Validate
    validate_products(all_products)

    print("\nExtraction completed.")


if __name__ == "__main__":
    main()
