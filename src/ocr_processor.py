"""OCR fallback for scanned PDF pages using Tesseract."""
from __future__ import annotations
from collections import defaultdict
import re
from PIL import Image
import pymupdf
from .title_extractor import (
    _clean,
    _is_plausible_caption,
    STRUCTURAL_HEADING,
    PRIMARY_STATEMENT_HEADING,
    NUMBERED_SECTION_HEADING,
    GENERIC_HEADER,
    GENERIC_NOTES_BANNER,
    RUNNING_NAV_BANNER,
    KNOWN_SCHEDULE_HEADING,
)


def ocr_page_layout(pdf_path, page_number: int, dpi: int = 220) -> dict:
    """OCR one 1-based page and return text lines and table-like aligned regions."""
    import pytesseract
    from pytesseract import Output
    with pymupdf.open(pdf_path) as doc:
        page = doc[page_number - 1]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72), alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    data = pytesseract.image_to_data(image, output_type=Output.DICT, config="--psm 6")
    lines = defaultdict(list)
    n = len(data["text"])
    for i in range(n):
        text = str(data["text"][i]).strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if not text or conf < 20:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        x, y = int(data["left"][i]), int(data["top"][i])
        w, h = int(data["width"][i]), int(data["height"][i])
        lines[key].append({
            "text": text,
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "confidence": conf,
        })
    ordered = []
    for words in lines.values():
        words.sort(key=lambda item: item["x"])
        ordered.append({
            "text": " ".join(w["text"] for w in words),
            "x": min(w["x"] for w in words),
            "y": min(w["y"] for w in words),
            "right": max(w["x"] + w["w"] for w in words),
            "bottom": max(w["y"] + w["h"] for w in words),
            "word_count": len(words),
            "confidence": sum(word["confidence"] for word in words) / len(words),
            "words": words,
        })
    ordered.sort(key=lambda line: (line["y"], line["x"]))
    return {"image_size": image.size, "lines": ordered}


def detect_ocr_table_regions(layout: dict) -> list[dict]:
    """Identify runs of OCR lines with repeated column alignment."""
    lines = layout.get("lines", [])
    full_page_text = " ".join(_clean(l["text"], is_ocr=True).lower() for l in lines)
    if any(
        phrase in full_page_text
        for phrase in (
            "we communicate with those charged with governance",
            "basis for opinion",
            "auditor's responsibilities for the audit",
            "responsibilities for audit of financial statements",
            "report on other legal and regulatory requirements",
        )
    ):
        return []

    candidates = []
    run = []
    caption_pattern = re.compile(
        r"^(?:notes?\s*(?:no\.?\s*)?\d+[a-zA-Z]?\s*[:.\-–]?|"
        r"balance\s+sheet|statement\s+of|cash\s+flow|profit\s+and\s+loss|"
        r"notes?\s+(?:to|on|forming)|\d{1,2}\.?\s+additional\s+information)",
        re.I,
    )
    stamp_or_footer = re.compile(
        r"chartered\s+accountants|m\.?\s*no\.?\s*\d+|membership|"
        r"in\s+terms\s+of\s+our\s+attached\s+report|for\s+and\s+on\s+behalf|"
        r"din\s*:\s*\d+|udin\s*:|place\s*:\s*|date\s*:\s*|p\.?\s*o\.?\b|dist\s*:",
        re.I,
    )

    header_evidence = re.compile(
        r"\b(particulars|description|amount|balance|as\s+at|year\s+ended|"
        r"period\s+ended|debit|credit|quantity|number\s+of\s+shares|"
        r"name\s+of\s+(?:transaction|shareholders?)|relationship)\b",
        re.I,
    )
    caption_indexes = set()
    for index, line in enumerate(lines):
        text = _clean(line["text"], is_ocr=True)
        if caption_pattern.search(text):
            caption_indexes.add(index)
            continue
        if re.match(
            r"^(?:\(?[A-Za-zivxIVX]+\)|[A-Za-z]\.)\s+(?:the|this|that)\b",
            text,
            re.I,
        ):
            continue
        numbered_subsection = bool(
            re.match(r"^\d{1,2}\s*\.\s*\d{1,2}\.?\s+", text)
        )
        is_date_heading = bool(re.match(
            r"^(?:as\s+at|for\s+the\s+(?:year|period)\s+ended)\s+\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4}\b",
            text,
            re.I,
        ))
        prefix = re.split(
            r"\b(?:as\s+at|for\s+the\s+(?:year|period)\s+ended|"
            r"year\s+ended|period\s+ended|particulars|description)\b",
            text,
            maxsplit=1,
            flags=re.I,
        )[0].strip(" :-–—")
        following = lines[index + 1:index + 5]
        previous = lines[index - 1] if index else None
        header_before = bool(
            previous
            and 0 <= line["y"] - previous["bottom"] <= 30
            and header_evidence.search(_clean(previous["text"], is_ocr=True))
        )
        has_header = bool(header_evidence.search(text)) or any(
            header_evidence.search(_clean(item["text"], is_ocr=True))
            for item in following
        ) or header_before
        has_full_table_header = any(
            re.search(r"\bparticulars\b", _clean(item["text"], is_ocr=True), re.I)
            and re.search(r"\b(?:as\s+at|amount|year\s+ended)\b",
                          " ".join(
                              _clean(candidate["text"], is_ocr=True)
                              for candidate in following
                          ), re.I)
            for item in following
        )
        numeric_rows = sum(
            bool(re.search(r"\b\d[\d,]*(?:\.\d+)?%?\b", item["text"]))
            for item in following
        )
        low_confidence_short_heading = (
            1 <= len(text.split()) <= 6
            and float(line.get("confidence", 100.0)) < 70.0
            and has_full_table_header
        )
        if not (
            numbered_subsection
            or is_date_heading
            or (2 <= len(prefix.split()) <= 16 and _is_plausible_caption(prefix))
            or low_confidence_short_heading
        ):
            continue
        if has_header or numeric_rows >= 2 or low_confidence_short_heading:
            caption_indexes.add(index)

    def save_run(current):
        if len(current) >= 3:
            candidates.append(current)
        elif (
            len(current) >= 2
            and any(header_evidence.search(row["text"]) for row in current)
            and any(re.search(r"\d", row["text"]) for row in current)
        ):
            candidates.append(current)

    for index, line in enumerate(lines):
        text = _clean(line["text"], is_ocr=True)
        if stamp_or_footer.search(text):
            save_run(run)
            run = []
            continue
        running_banner_line = bool(
            line["y"] < layout.get("image_size", (0, 0))[1] * 0.16
            and (
                GENERIC_NOTES_BANNER.search(text)
                or RUNNING_NAV_BANNER.search(text)
                or re.search(
                    r"\b(?:overview|reports|financial statements|to the financial statements|"
                    r"standalone|consolidated|annual report|all amounts in)\b",
                    text,
                    re.I,
                )
            )
            and not re.search(r"\b(?:particulars|description)\b", text, re.I)
        )
        if running_banner_line:
            save_run(run)
            run = []
            continue
        unstructured_long_line = (
            line["word_count"] > 13
            and not re.search(r"\d", text)
            and not header_evidence.search(text)
            and not re.search(
                r"\b(particulars|description|amount|balance|total|assets?|liabilities)\b",
                text,
                re.I,
            )
        )
        if unstructured_long_line:
            save_run(run)
            run = []
            continue
        is_caption = index in caption_indexes and line["word_count"] <= 18
        if is_caption:
            pending_header = []
            if run and header_evidence.search(run[-1]["text"]):
                gap = line["y"] - run[-1]["bottom"]
                if 0 <= gap <= 30:
                    pending_header.append(run.pop())
            if header_evidence.search(text):
                pending_header.append(line)
            save_run(run)
            run = pending_header
        elif line["word_count"] >= 1 and (
            line["word_count"] >= 3
            or re.search(r"\d", text)
            or (
                line["word_count"] <= 2
                and run
                and any(header_evidence.search(row["text"]) for row in run)
            )
        ):
            run.append(line)
        else:
            save_run(run)
            run = []
    save_run(run)

    regions = []
    for run in candidates:
        if len(run) < 2:
            continue
        long_lines = sum(
            line["word_count"] > 13
            and not header_evidence.search(line["text"])
            for line in run
        )
        word_dense_lines = sum(
            line["word_count"] > 10
            and not header_evidence.search(line["text"])
            for line in run
        )
        if long_lines / len(run) > 0.40 or word_dense_lines / len(run) > 0.35:
            continue
        joined_text = " ".join(line["text"] for line in run).lower()
        if any(marker in joined_text for marker in (
            "place :", "date:", "for our attached report", "for and on behalf",
            "chartered accountants", "membership no", "partner",
            "independent auditor", "basis for opinion", "key audit matters"
        )):
            continue
        starts = sorted(w["x"] for row in run for w in row["words"])
        clusters = []
        for x in starts:
            if not clusters or x - clusters[-1][-1] > 28:
                clusters.append([x])
            else:
                clusters[-1].append(x)
        stable_columns = sum(1 for c in clusters if len(c) >= max(2, len(run) * 0.35))
        numeric_rows = sum(
            bool(re.search(r"\b\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\b|\b\d+\.\d{2}\b|\b\d{1,4}\b", row["text"]))
            for row in run
        )
        has_table_header = bool(
            re.search(r"\b(particulars|description)\b", joined_text, re.I)
            and re.search(
                r"\b(amount|balance|as at|year ended|debit|credit|quantity|"
                r"number of shares)\b",
                joined_text,
                re.I,
            )
        ) or (len(run) >= 3 and bool(header_evidence.search(joined_text)))
        narrative_run = (
            not has_table_header
            and sum(
                bool(re.search(r"\b(?:the|and|to|of|for|with|in|by|from|as|are|were|these|is|was)\b", line["text"], re.I))
                for line in run
            ) >= len(run) * 0.60
        )
        if narrative_run:
            continue
        if stable_columns >= 2 and (
            numeric_rows >= max(1, len(run) // 4)
            or (
                has_table_header
                and len(run) >= 3
                and (numeric_rows > 0 or len(run) >= 4)
            )
        ):
            image_height = layout.get("image_size", (0, 0))[1]
            region_top = min(r["y"] for r in run)
            region_bottom = max(r["bottom"] for r in run)
            if image_height and region_top > image_height * 0.76 and len(run) <= 4 and not has_table_header:
                continue
            if image_height and region_bottom < image_height * 0.16:
                if any(
                    re.search(
                        r"\b(?:overview|reports|financial statements|standalone|consolidated|"
                        r"annual report|to the financial statements|all amounts in)\b",
                        r["text"],
                        re.I,
                    )
                    or GENERIC_NOTES_BANNER.search(r["text"])
                    or RUNNING_NAV_BANNER.search(r["text"])
                    for r in run
                ) and numeric_rows < 2:
                    continue
                if not has_table_header and numeric_rows < 2:
                    continue
            regions.append({
                "bbox": (
                    min(r["x"] for r in run),
                    min(r["y"] for r in run),
                    max(r["right"] for r in run),
                    max(r["bottom"] for r in run),
                ),
                "rows": len(run),
                "columns": stable_columns,
                "ocr_lines": run,
            })
    return regions


def extract_ocr_caption(layout: dict, table_bbox: tuple[float, float, float, float]) -> str:
    """Find a concise OCR caption above a table region using general caption validation."""
    y_top = table_bbox[1]
    raw_lines = layout.get("lines", [])

    merged = []
    i = 0
    while i < len(raw_lines):
        curr = raw_lines[i]
        curr_text = _clean(curr["text"], is_ocr=True)
        if re.fullmatch(r"(?:note|notes|schedule)\s*\d+[a-zA-Z]?\s*[:.\-–]\s*$", curr_text, re.I):
            matched_offset = None
            for offset in (1, 2):
                if i + offset < len(raw_lines):
                    cand = raw_lines[i + offset]
                    cand_text = _clean(cand["text"], is_ocr=True)
                    gap = cand["y"] - curr["bottom"]
                    if 0 <= gap <= 55 and not GENERIC_HEADER.search(cand_text) and 1 <= len(cand_text.split()) <= 10:
                        matched_offset = offset
                        break
            if matched_offset is not None:
                cand = raw_lines[i + matched_offset]
                cand_text = _clean(cand["text"], is_ocr=True)
                combined = _clean(f"{curr_text.rstrip(':.-– ')} : {cand_text}", is_ocr=True)
                merged.append({
                    "text": combined,
                    "y": curr["y"],
                    "bottom": cand["bottom"],
                })
                i += matched_offset + 1
                continue
        merged.append({"text": curr_text, "y": curr["y"], "bottom": curr["bottom"]})
        i += 1

    candidates = []
    for line in merged:
        distance = y_top - line["bottom"]
        text = re.sub(
            r"\s+(?:as\s*at|asat|for\s+the\s+(?:year|period)\s+ended|"
            r"year\s+ended|period\s+ended)\s+.*$",
            "",
            line["text"],
            flags=re.I,
        ).strip(" ,;:-–—")
        if not text:
            continue
        if re.match(r"^\(?[a-z]\)\s+", text, re.I):
            continue
        if distance < -65 or distance > 150 or not _is_plausible_caption(text):
            continue
        score = max(distance, 0)
        if distance < 0:
            score += 20
        if KNOWN_SCHEDULE_HEADING.search(text):
            score -= 110
        elif PRIMARY_STATEMENT_HEADING.match(text):
            score -= 120
        elif STRUCTURAL_HEADING.match(text) or NUMBERED_SECTION_HEADING.match(text):
            score -= 105
        elif GENERIC_NOTES_BANNER.match(text):
            score += 60
        candidates.append((score, text))

    if not candidates:
        return "Untitled table"
    candidates.sort(key=lambda item: (item[0], len(item[1])))
    return candidates[0][1][:140].rstrip(" ,;:-")

import pymupdf


FULL_PAGE_IMAGE_THRESHOLD = 0.80


def classify_page(page):

    page_area = page.rect.width * page.rect.height

    largest_image_coverage = 0.0

    for image in page.get_images(full=True):

        xref = image[0]

        for rect in page.get_image_rects(xref):

            # Restrict the image area to the visible page.
            visible_rect = rect & page.rect

            if visible_rect.is_empty:
                continue

            image_area = (
                visible_rect.width * visible_rect.height
            )

            coverage = image_area / page_area

            largest_image_coverage = max(
                largest_image_coverage,
                coverage
            )

    words = page.get_text("words")

    if largest_image_coverage >= FULL_PAGE_IMAGE_THRESHOLD:

        if words:
            page_type = "IMAGE_BACKED_WITH_TEXT"
        else:
            page_type = "SCANNED_WITHOUT_TEXT"

    elif words:
        page_type = "NATIVE_TEXT"

    else:
        page_type = "SCANNED_WITHOUT_TEXT"

    return {
        "page_type": page_type,
        "word_count": len(words),
        "image_coverage": largest_image_coverage,
        "drawing_count": len(page.get_drawings())
    }


def classify_document(pdf_path):

    results = []

    with pymupdf.open(pdf_path) as doc:

        for page_number, page in enumerate(doc, start=1):

            result = classify_page(page)

            result["page_number"] = page_number

            results.append(result)

    return results

import pymupdf
import pdfplumber
from pathlib import Path


def inspect_pdf(pdf_path):
    """
    Inspect a PDF and collect basic information
    about its pages, text, and images.
    """

    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    results = []

    doc = pymupdf.open(pdf_path)

    print(f"\n{'=' * 60}")
    print(f"Document: {pdf_path.name}")
    print(f"Total Pages: {len(doc)}")
    print(f"{'=' * 60}")

    with pdfplumber.open(pdf_path) as pdf:

        for page_number, page in enumerate(pdf.pages, start=1):

            text = page.extract_text() or ""
            words = page.extract_words()

            image_count = len(page.images)

            page_info = {
                "page_number": page_number,
                "text_length": len(text),
                "word_count": len(words),
                "image_count": image_count,
                "has_extractable_text": len(text.strip()) > 0
            }

            results.append(page_info)

            print(
                f"Page {page_number:3} | "
                f"Characters: {len(text):5} | "
                f"Words: {len(words):4} | "
                f"Images: {image_count:3}"
            )

            if page_number == 1:
                print("\nFirst page text preview:")
                print(text[:1000] if text else "No extractable text")

    doc.close()

    return results
