"""Hybrid layout-based table detection for digital and scanned PDFs."""
from __future__ import annotations
from pathlib import Path
import logging
import re
import pdfplumber
import pymupdf
from .page_classifier import classify_page
from .title_extractor import (
    extract_table_title,
    find_page_primary_heading,
    normalize_title_case,
    is_subsection_title,
    page_has_notes_banner,
    _extract_merged_lines,
    _clean,
    _is_plausible_caption,
    STRUCTURAL_HEADING,
    PRIMARY_STATEMENT_HEADING,
    NUMBERED_SECTION_HEADING,
    SUBSECTION_PREFIX,
    GENERIC_NOTES_BANNER,
    GENERIC_HEADER,
    RUNNING_NAV_BANNER,
    KNOWN_SCHEDULE_HEADING,
)
from .ocr_processor import ocr_page_layout, detect_ocr_table_regions, extract_ocr_caption

TABLE_SETTINGS = [
    ("lines", {"vertical_strategy": "lines", "horizontal_strategy": "lines"}),
    ("text", {"vertical_strategy": "text", "horizontal_strategy": "text",
              "min_words_vertical": 3, "min_words_horizontal": 2}),
]

TABULAR_HEADER_TERMS = re.compile(
    r"\b(particulars|description|as\s+at|year\s+ended|period\s+ended|"
    r"amount|total|balance|assets?|liabilities|equity|debit|credit|"
    r"txn\s+date|value\s+date|cheque|unit\s+price|qty|quantity|sales\s+value|"
    r"customs\s+value|part\s+number|order\s+no|gross\s+block|net\s+block|"
    r"carrying\s+amount|fair\s+value|level\s+1|level\s+2|level\s+3)\b",
    re.I,
)


def _metrics(data, strategy: str = "lines"):
    if not data:
        return None
    rows = len(data)
    widths = [len(row) for row in data if row]
    cols = max(widths, default=0)
    cells = [str(cell).strip() for row in data for cell in row if cell and str(cell).strip()]
    total = sum(len(row) for row in data)
    nonempty_widths = [sum(bool(c and str(c).strip()) for c in row) for row in data]
    populated_rows = sum(width >= 2 for width in nonempty_widths)
    if rows < 3 or cols < 2 or not cells:
        return None

    numeric_like_cells = sum(
        bool(re.search(r"\d", cell))
        and len(cell.split()) <= 5
        and not re.search(
            r"\b(step|section|rule|act|note|page|march|april|may|jan|feb|jun|jul|aug|sep|oct|nov|dec)\b",
            cell,
            re.I,
        )
        for cell in cells
    )
    occupancy = len(cells) / max(total, 1)
    multi_ratio = populated_rows / rows
    numeric_ratio = numeric_like_cells / len(cells)
    stable_width = max((nonempty_widths.count(w) for w in set(nonempty_widths)), default=0) / rows
    long_cell_ratio = sum(len(c.split()) > 18 for c in cells) / len(cells)
    avg_words_per_cell = sum(len(c.split()) for c in cells) / len(cells)

    if occupancy < 0.16 or multi_ratio < 0.40:
        return None
    if stable_width < 0.10 or long_cell_ratio > 0.18:
        return None

    if strategy == "text":
        if numeric_like_cells < 3 or avg_words_per_cell > 7.0 or numeric_ratio < 0.15:
            return None
    else:
        if numeric_like_cells < 2 and not any(TABULAR_HEADER_TERMS.search(c) for c in cells):
            return None

    return {
        "rows": rows,
        "columns": cols,
        "cell_occupancy": occupancy,
        "multi_cell_row_ratio": multi_ratio,
        "numeric_cell_ratio": numeric_ratio,
        "stable_width_ratio": stable_width,
        "long_cell_ratio": long_cell_ratio,
        "avg_words_per_cell": avg_words_per_cell,
    }


def _looks_like_letterhead_or_signature(data) -> bool:
    """Reject text-alignment grids formed by letterheads, auditor sign-offs, or narrative policies."""
    joined = " ".join(
        str(cell or "") for row in (data or []) for cell in (row or [])
    ).lower()
    contact_pair = "email" in joined and any(
        marker in joined for marker in ("ph. no", "phone", "mobile", "tel:")
    )
    signature_block = (
        ("place :" in joined or "place:" in joined or "mumbai" in joined or "kolkata" in joined)
        and ("for and on behalf" in joined or "chartered accountants" in joined or "firm registration" in joined)
    ) or ("membership" in joined and ("partner" in joined or "udin" in joined or "din:" in joined))
    numeric_count = sum(
        bool(re.search(r"\b\d[\d,]*(?:\.\d+)?\b", str(cell or "")))
        for row in (data or [])
        for cell in (row or [])
    )
    if signature_block and TABULAR_HEADER_TERMS.search(joined) and numeric_count >= 6:
        signature_block = False
    narrative_prose = (
        "independent auditor's report" in joined
        or "internal financial controls" in joined
        or "guidance note on audit" in joined
        or "standards on auditing" in joined
        or "we communicate with those charged with governance" in joined
        or "basis of preparation and measurement" in joined
        or "recent accounting developments" in joined
        or "step 1: identify the contract" in joined
    )
    non_empty_cells = [
        str(cell).strip()
        for row in (data or [])
        for cell in (row or [])
        if str(cell or "").strip()
    ]
    if len(non_empty_cells) >= 4:
        long_narrative = sum(len(c.split()) >= 5 for c in non_empty_cells)
        has_digits = any(re.search(r"\d", c) for c in non_empty_cells)
        if not has_digits and (long_narrative / len(non_empty_cells)) >= 0.6:
            narrative_prose = True
    return contact_pair or signature_block or narrative_prose


def _looks_like_footer_candidate(candidate: dict, page_lines: list[dict],
                                 page_height: float) -> bool:
    """Reject bottom-page alignment grids that overlap auditor/director sign-offs."""
    _, top, _, bottom = candidate["bbox"]
    if top < page_height * 0.68:
        return False
    nearby = " ".join(
        line["text"].lower()
        for line in page_lines
        if top - 35.0 <= line["top"] <= bottom + 35.0
    )
    signature_marker = re.search(
        r"\b(for and on behalf|chartered accountants|membership no\.?|"
        r"firm registration|udin|in terms of our attached report|"
        r"place\s*:|date\s*:|partner)\b",
        nearby,
    )
    return bool(signature_marker and not TABULAR_HEADER_TERMS.search(nearby))


def _looks_like_header_candidate(candidate: dict, page_lines: list[dict],
                                 page_height: float) -> bool:
    """Reject top-page banner/navigation blocks that are not physical tables."""
    _, top, _, bottom = candidate["bbox"]
    if bottom > page_height * 0.16:
        return False
    if candidate["metrics"]["rows"] >= 5 or candidate["strategy"] == "lines":
        return False
    nearby = " ".join(
        line["text"].lower()
        for line in page_lines
        if top - 15.0 <= line["top"] <= bottom + 15.0
    )
    ocr_lines = candidate.get("ocr_lines") or []
    table_data = candidate.get("table_data") or []
    if table_data:
        numeric_count = sum(
            any(re.search(r"\b\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\b|\b\d+\.\d{2}\b", str(cell or "")) for cell in row)
            for row in table_data
        )
    else:
        numeric_count = sum(
            bool(re.search(r"\b\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\b|\b\d+\.\d{2}\b", line.get("text", "")))
            for line in ocr_lines
        )
    header_banner = bool(
        GENERIC_NOTES_BANNER.search(nearby)
        or GENERIC_HEADER.search(nearby)
        or re.search(
            r"\b(overview|reports|financial statements|standalone|consolidated|"
            r"annual report|to the financial statements|all amounts in)\b",
            nearby,
            re.I,
        )
    )
    if header_banner and numeric_count < 2:
        return True
    if TABULAR_HEADER_TERMS.search(nearby):
        return False
    return header_banner or numeric_count < 2


def _overlap(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    area_a = max(0, ax1 - ax0) * max(0, ay1 - ay0)
    area_b = max(0, bx1 - bx0) * max(0, by1 - by0)
    union = area_a + area_b - inter
    iou = inter / union if union else 0
    containment = inter / min(area_a, area_b) if min(area_a, area_b) else 0
    return max(iou, containment)


def _deduplicate(candidates, page_lines: list[dict] | None = None, page=None):
    """Remove true geometric duplicates and join aligned horizontal parts of one ruled table."""
    candidate_list = list(candidates)
    chosen = []
    for item in sorted(candidate_list, key=lambda x: (x["score"], x["bbox"][1], -x["metrics"]["rows"])):
        x0, y0, x1, y1 = item["bbox"]
        item_area = max(0, x1 - x0) * max(0, y1 - y0)
        if item.get("table_data"):
            siblings = [
                other for other in candidate_list
                if other is not item
                and other.get("segmented")
                and other.get("strategy") == item["strategy"]
                and other.get("table_data") is item["table_data"]
                and x0 <= (other["bbox"][0] + other["bbox"][2]) / 2 <= x1
                and y0 <= (other["bbox"][1] + other["bbox"][3]) / 2 <= y1
            ]
            intervals = sorted(
                (max(y0, other["bbox"][1]), min(y1, other["bbox"][3]))
                for other in siblings
            )
            covered = 0.0
            covered_to = y0
            for start, end in intervals:
                if end <= start:
                    continue
                covered += max(0.0, end - max(start, covered_to))
                covered_to = max(covered_to, end)
            if len(siblings) >= 2 and covered / max(1.0, y1 - y0) >= 0.55:
                continue
        duplicate = False
        for old in chosen:
            ox0, oy0, ox1, oy1 = old["bbox"]
            old_area = max(0, ox1 - ox0) * max(0, oy1 - oy0)
            smaller_to_larger = min(item_area, old_area) / max(item_area, old_area, 1)
            is_ocr_pair = item["strategy"] == "ocr" or old["strategy"] == "ocr"
            min_area_ratio = 0.20 if is_ocr_pair else 0.55
            min_overlap = 0.25 if is_ocr_pair else 0.65
            text_lines_pair = {item["strategy"], old["strategy"]} == {"text", "lines"}
            x_intersection = max(0.0, min(x1, ox1) - max(x0, ox0))
            min_width = max(1.0, min(x1 - x0, ox1 - ox0))
            y_intersection = max(0.0, min(y1, oy1) - max(y0, oy0))
            min_height = max(1.0, min(y1 - y0, oy1 - oy0))
            overlap_score = _overlap(item["bbox"], old["bbox"])
            if is_ocr_pair:
                smaller = old if old_area < item_area else item
                larger = item if old_area < item_area else old
                smaller_caption = (smaller.get("ocr_title") or smaller.get("_resolved_title") or smaller.get("title") or "").strip().lower()
                has_distinct_caption = False
                if smaller_caption and smaller_caption != "untitled table" and page_lines:
                    has_distinct_caption = any(
                        smaller_caption in line.get("text", "").lower()
                        for line in page_lines
                    )
                if not has_distinct_caption and (
                    smaller["strategy"] == "ocr"
                    and larger["strategy"] in ("text", "lines")
                    and larger["metrics"]["rows"] >= 8
                    and overlap_score > 0.20
                ):
                    if larger is item:
                        chosen.remove(old)
                        continue
                    else:
                        duplicate = True
                        break
            if is_ocr_pair and overlap_score > 0.85:
                if has_distinct_caption:
                    continue
                if (
                    old["strategy"] == "ocr"
                    and item["strategy"] == "text"
                    and item["metrics"]["rows"] >= old["metrics"]["rows"] * 1.5
                    and item_area >= old_area * 1.25
                ):
                    chosen.remove(old)
                    continue
                duplicate = True
                break
            row_count_ratio = min(
                item["metrics"]["rows"], old["metrics"]["rows"]
            ) / max(item["metrics"]["rows"], old["metrics"]["rows"], 1)
            if (
                overlap_score >= 0.95
                and smaller_to_larger >= 0.50
                and row_count_ratio >= 0.80
                and item["strategy"] == old["strategy"]
            ):
                if (
                    item["metrics"]["rows"] > old["metrics"]["rows"]
                    or (
                        item["metrics"]["rows"] == old["metrics"]["rows"]
                        and item_area > old_area
                    )
                ):
                    chosen.remove(old)
                    continue
                duplicate = True
                break
            if (
                text_lines_pair
                and smaller_to_larger >= 0.30
                and x_intersection / min_width >= 0.90
                and y_intersection / min_height >= 0.75
                and overlap_score > 0.70
            ):
                duplicate = True
                break
            if smaller_to_larger >= min_area_ratio and overlap_score > min_overlap:
                duplicate = True
                break
        if duplicate:
            continue
        chosen.append(item)
    ordered = sorted(chosen, key=lambda x: (x["bbox"][1], x["bbox"][0]))
    if len(ordered) < 2:
        return ordered

    merged = []
    for curr in ordered:
        if merged:
            prev = merged[-1]
            px0, py0, px1, py1 = prev["bbox"]
            cx0, cy0, cx1, cy1 = curr["bbox"]
            x_gap = cx0 - px1
            shared_height = max(0.0, min(py1, cy1) - max(py0, cy0))
            min_height = max(1.0, min(py1 - py0, cy1 - cy0))
            same_row_band = shared_height / min_height >= 0.90
            same_row_count = abs(prev["metrics"]["rows"] - curr["metrics"]["rows"]) <= 1
            if (
                prev["strategy"] == curr["strategy"] == "lines"
                and -2.0 <= x_gap <= 12.0
                and same_row_band
                and same_row_count
            ):
                prev["bbox"] = (px0, min(py0, cy0), cx1, max(py1, cy1))
                prev["metrics"]["columns"] += curr["metrics"]["columns"]
                prev["table_data"] = (prev.get("table_data") or []) + (curr.get("table_data") or [])
                continue
        merged.append(curr)

    vertically_merged = []
    for curr in merged:
        if vertically_merged:
            prev = vertically_merged[-1]
            px0, _, px1, py1 = prev["bbox"]
            cx0, cy0, cx1, _ = curr["bbox"]
            x_intersection = max(0.0, min(px1, cx1) - max(px0, cx0))
            min_width = max(1.0, min(px1 - px0, cx1 - cx0))
            if (
                not (
                    prev["strategy"] == curr["strategy"] == "ocr"
                )
                and -10.0 <= cy0 - py1 <= 3.0
                and x_intersection / min_width >= 0.95
                and not (
                    prev.get("_section_caption")
                    and curr.get("_section_caption")
                    and prev["_section_caption"] != curr["_section_caption"]
                    and not page_lines
                )
                and not (
                    cy0 >= py1
                    and _caption_boundary_between(page_lines or [], py1, cy0)
                )
            ):
                prev["bbox"] = (min(px0, cx0), prev["bbox"][1],
                                max(px1, cx1), max(py1, curr["bbox"][3]))
                prev["metrics"]["rows"] += curr["metrics"]["rows"]
                prev["metrics"]["columns"] = max(
                    prev["metrics"]["columns"], curr["metrics"]["columns"]
                )
                prev["table_data"] = (prev.get("table_data") or []) + (curr.get("table_data") or [])
                continue
            if (
                prev["strategy"] == curr["strategy"] == "ocr"
                and not prev.get("_section_caption")
                and not curr.get("_section_caption")
                and -10.0 <= curr["bbox"][1] - py1 <= 30.0
                and x_intersection / min_width >= 0.90
                and not _caption_boundary_between(
                    page_lines or [], py1, curr["bbox"][1]
                )
                and not re.search(
                    r"\b(particulars|description|as at|year ended)\b",
                    " ".join(
                        line["text"] for line in curr.get("ocr_lines", [])[:3]
                    ),
                    re.I,
                )
            ):
                prev["bbox"] = (min(px0, cx0), prev["bbox"][1],
                                max(px1, cx1), max(py1, curr["bbox"][3]))
                prev["metrics"]["rows"] += curr["metrics"]["rows"]
                prev["metrics"]["columns"] = max(
                    prev["metrics"]["columns"], curr["metrics"]["columns"]
                )
                prev["ocr_lines"] = (
                    prev.get("ocr_lines", []) + curr.get("ocr_lines", [])
                )
                continue
        vertically_merged.append(curr)
    return vertically_merged


_DATE_COLUMN_SUFFIX = re.compile(
    r"\s+(?:as\s*at|asat|for\s+the\s+(?:year|period)\s+ended|year\s+ended)\s*\d.*$",
    re.I,
)
_BARE_NOTE_HEADING = re.compile(r"^(?:note|notes|schedule)\s*(?:no\.?\s*)?\d+[a-zA-Z]?\s*[:.\-–]?$", re.I)
_NUMBERED_SUBSECTION = re.compile(r"^\d{1,2}\s*\.\s*\d{1,2}\b")
_ALPHA_SUBSECTION = re.compile(r"^(?:[A-H]\.|[A-H]\)|\([A-H]\))\s+")
_TABLE_HEADER_LINE = re.compile(
    r"^(?:particulars|description|name\s+of\s+(?:item|transaction|shareholders?)|"
    r"scheme|year|amount|note\s+no\.?)\b",
    re.I,
)


def _normalized_anchor_text(text: str) -> str:
    """Normalize OCR-like heading errors and remove right-aligned date columns."""
    normalized = _clean(text, is_ocr=True)
    normalized = _DATE_COLUMN_SUFFIX.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" \t|:-–—")
    return normalized


def _caption_boundary_between(page_lines: list[dict], y0: float, y1: float) -> bool:
    low, high = min(y0, y1) - 5.0, max(y0, y1) + 5.0
    page_height = max(
        (float(line.get("bottom", line["top"])) for line in page_lines),
        default=842.0,
    )
    for line in page_lines:
        if not low <= line["top"] <= high:
            continue
        text = _normalized_anchor_text(line["text"])
        if (
            _BARE_NOTE_HEADING.match(text)
            or STRUCTURAL_HEADING.match(text)
            or NUMBERED_SECTION_HEADING.match(text)
            or (
                PRIMARY_STATEMENT_HEADING.match(text)
                and line["top"] <= page_height * 0.40
            )
        ):
            return True
        if (
            _NUMBERED_SUBSECTION.match(text)
            or (_is_plausible_caption(text) and len(text.split()) <= 10)
        ):
            following = [
                candidate for candidate in page_lines
                if line["top"] < candidate["top"] <= line["top"] + 60.0
            ]
            has_header = any(
                re.search(
                    r"\b(particulars|description|amount|balance|as\s+at|"
                    r"year\s+ended|period\s+ended|quantity|number\s+of\s+shares)\b",
                    candidate["text"],
                    re.I,
                )
                for candidate in following
            )
            has_data = any(
                re.search(r"\b\d[\d,]*(?:\.\d+)?%?\b", candidate["text"])
                for candidate in following
            )
            short_rows = sum(len(candidate["text"].split()) <= 8 for candidate in following)
            if has_header and (has_data or short_rows >= 2):
                return True
    return False


def _ocr_lines_in_page_coordinates(
    layout: dict | None, page_width: float, page_height: float,
) -> list[dict]:
    if not layout:
        return []
    image_width, image_height = layout.get("image_size", (0, 0))
    if not image_width or not image_height:
        return []
    scale_x = page_width / image_width
    scale_y = page_height / image_height
    return [
        {
            "text": _clean(line["text"], is_ocr=True),
            "top": float(line["y"]) * scale_y,
            "bottom": float(line["bottom"]) * scale_y,
            "font_size": 0.0,
            "bold_ratio": 0.0,
            "confidence": float(line.get("confidence", 0.0)),
        }
        for line in layout.get("lines", [])
        if _clean(line.get("text", ""), is_ocr=True)
    ]


def _caption_anchors(page, page_lines: list[dict], ruled_seeds: list[tuple]) -> list[dict]:
    """Find likely section/caption lines that can bound independent table regions."""
    anchors = []
    for index, line in enumerate(page_lines):
        text = line["text"]
        normalized = _normalized_anchor_text(text)
        y = line["top"]
        if not normalized or y < 28 or y > page.height - 42:
            continue
        confidence = float(line.get("confidence", 100.0))
        if GENERIC_NOTES_BANNER.match(normalized) or _TABLE_HEADER_LINE.match(normalized):
            continue

        note_heading = bool(_BARE_NOTE_HEADING.match(normalized) or STRUCTURAL_HEADING.match(normalized))
        structural = bool(
            note_heading
            or NUMBERED_SECTION_HEADING.match(normalized)
            or PRIMARY_STATEMENT_HEADING.match(normalized)
        )
        numbered_subsection = bool(_NUMBERED_SUBSECTION.match(normalized))
        alpha_subsection = bool(_ALPHA_SUBSECTION.match(normalized))
        plausible = _is_plausible_caption(normalized)
        if (
            not plausible
            and 25.0 <= confidence < 70.0
            and 4 <= len(normalized) <= 80
            and 1 <= len(normalized.split()) <= 6
        ):
            plausible = any(
                re.search(
                    r"\b(particulars|description|amount|as\s+at|year\s+ended|"
                    r"period\s+ended|number\s+of\s+shares)\b",
                    following["text"],
                    re.I,
                )
                and 0 <= following["top"] - line["bottom"] <= 55.0
                for following in page_lines
            )
        if re.match(r"^\([A-Za-z]\)\s+", normalized) and line.get("bold_ratio", 0.0) < 0.25:
            plausible = False
        if not (
            structural
            or numbered_subsection
            or (alpha_subsection and plausible)
            or (
                plausible
                and len(normalized.split()) <= 5
                and not SUBSECTION_PREFIX.match(normalized)
            )
            or (
                plausible
                and line.get("bold_ratio", 0.0) >= 0.25
                and len(normalized.split()) <= 18
            )
        ):
            continue
        if confidence < 25.0:
            continue

        # Note headings can introduce a new table inside a ruled region; other headings
        # there are more likely to be row labels or descriptions.
        if not note_heading and any(
            box[1] + 8.0 < y < box[3] - 8.0
            for box in ruled_seeds
        ):
            continue

        if not structural and index:
            previous = page_lines[index - 1]
            gap = y - previous["bottom"]
            if gap < 18 and (
                _TABLE_HEADER_LINE.match(previous["text"])
                or (re.search(r"\d", previous["text"]) and not _BARE_NOTE_HEADING.match(previous["text"]))
            ):
                if not KNOWN_SCHEDULE_HEADING.search(normalized):
                    continue

        anchors.append({
            "text": normalized,
            "top": y,
            "bottom": line["bottom"],
            "structural": structural,
        })

    return anchors


def _note_heading_lines(page_lines: list[dict]) -> list[dict]:
    headings = []
    for line in page_lines:
        normalized = _normalized_anchor_text(line["text"])
        if _BARE_NOTE_HEADING.match(normalized) or re.match(
            r"^notes?\s*(?:no\.?\s*)?\d+", normalized, re.I
        ):
            headings.append({**line, "title": normalize_title_case(normalized)})
    unique = []
    for heading in sorted(headings, key=lambda item: item["top"]):
        if unique and abs(heading["top"] - unique[-1]["top"]) <= 5.0:
            if heading.get("confidence", 100.0) > unique[-1].get("confidence", 100.0):
                unique[-1] = heading
            continue
        unique.append(heading)
    return unique


def _deduplicate_resolved_candidates(
    candidates: list[dict],
    page_height: float,
    note_headings: list[dict],
) -> list[dict]:
    """Collapse overlapping detections confirmed to describe the same captioned table."""
    def note_number(text: str) -> str | None:
        match = re.search(r"\bnotes?\s*(?:no\.?\s*)?(\d+[a-z]?)", text, re.I)
        return match.group(1).lower() if match else None

    cross_section_broad_candidates = set()
    for candidate in candidates:
        x0, y0, x1, y1 = candidate["bbox"]
        if y1 - y0 < page_height * 0.45:
            continue
        candidate_note = note_number(candidate.get("_resolved_title", ""))
        if not candidate_note:
            continue
        for heading in note_headings:
            heading_number = note_number(heading["text"])
            if (
                not heading_number
                or heading_number == candidate_note
                or not y0 + 8.0 < heading["top"] < y1 - 8.0
            ):
                continue
            for other in candidates:
                if other is candidate or note_number(
                    other.get("_resolved_title", "")
                ) != heading_number:
                    continue
                ox0, oy0, ox1, oy1 = other["bbox"]
                if (
                    x0 <= (ox0 + ox1) / 2 <= x1
                    and y0 <= (oy0 + oy1) / 2 <= y1
                    and oy1 - oy0 < (y1 - y0) * 0.80
                ):
                    cross_section_broad_candidates.add(id(candidate))
                    break

    chosen = []
    for item in candidates:
        if id(item) in cross_section_broad_candidates:
            continue
        title = re.sub(r"\s+", " ", item.get("_resolved_title", "")).strip().lower()
        duplicate_index = None
        item_x0, item_y0, item_x1, item_y1 = item["bbox"]
        item_area = max(0.0, item_x1 - item_x0) * max(0.0, item_y1 - item_y0)

        for index, old in enumerate(chosen):
            old_title = re.sub(
                r"\s+", " ", old.get("_resolved_title", "")
            ).strip().lower()
            if not title or title != old_title:
                continue

            old_x0, old_y0, old_x1, old_y1 = old["bbox"]
            old_area = max(0.0, old_x1 - old_x0) * max(0.0, old_y1 - old_y0)

            # Evaluate spatial overlap between candidates
            ix = max(0.0, min(item_x1, old_x1) - max(item_x0, old_x0))
            iy = max(0.0, min(item_y1, old_y1) - max(item_y0, old_y0))
            inter_area = ix * iy
            if inter_area <= 0:
                # Distinct physical table regions sharing the same title are preserved
                continue

            min_area = max(1.0, min(item_area, old_area))
            union_area = item_area + old_area - inter_area
            iou = inter_area / union_area if union_area > 0 else 0.0
            containment = inter_area / min_area

            min_width = max(1.0, min(item_x1 - item_x0, old_x1 - old_x0))
            horiz_overlap = ix / min_width

            min_height = max(1.0, min(item_y1 - item_y0, old_y1 - old_y0))
            vert_overlap = iy / min_height

            # Deduplicate candidates that occupy the same physical table region
            is_same_physical_table = (
                iou >= 0.55
                or (containment >= 0.70 and horiz_overlap >= 0.75 and vert_overlap >= 0.60)
            )
            if not is_same_physical_table:
                continue

            duplicate_index = index
            break

        if duplicate_index is None:
            chosen.append(item)
            continue

        old = chosen[duplicate_index]
        item_rank = (
            item["strategy"] != "ocr",
            item["metrics"]["rows"],
            item_area,
        )
        old_rank = (
            old["strategy"] != "ocr",
            old["metrics"]["rows"],
            max(0.0, old["bbox"][2] - old["bbox"][0])
            * max(0.0, old["bbox"][3] - old["bbox"][1]),
        )
        if item_rank > old_rank:
            chosen[duplicate_index] = item
    return chosen


def _is_table_caption_start(anchor: dict, anchors: list[dict],
                            page_lines: list[dict]) -> bool:
    if anchor.get("structural"):
        return True
    if any(
        previous.get("structural")
        and 0 <= anchor["top"] - previous["top"] <= 35.0
        for previous in anchors
    ):
        return False

    anchor_text = anchor.get("text", "")
    if re.search(
        r"\b(dues\s+to\s+micro|micro\s+and\s+small|contingent\s+liabilit|"
        r"commitments|reconciliation\s+of|movement\s+in|maturity\s+analysis|"
        r"fair\s+value\s+hierarchy|carrying\s+value|ageing\s+schedule|"
        r"expenditures?\s+in\s+foreign\s+currency|payments?\s+to\s+(?:the\s+)?auditors?|"
        r"related\s+party\s+transactions?|earnings?\s+per\s+(?:equity\s+)?shares?|"
        r"additional\s+information)\b",
        anchor_text,
        re.I,
    ):
        return True

    following = [
        line["text"]
        for line in page_lines
        if anchor["top"] - 25.0 <= line["top"] <= anchor["top"] + 60.0
    ]
    header_evidence = sum(
        bool(re.search(
            r"\b(particulars|description|as\s+at|year\s+ended|period\s+ended|"
            r"amount|note\s+no\.?)\b",
            text,
            re.I,
        ))
        for text in following
    )
    data_evidence = sum(
        bool(re.search(r"\b\d[\d,]*(?:\.\d+)?%?\b", text))
        for text in following
    )
    short_rows = sum(len(text.split()) <= 8 for text in following)
    return header_evidence >= 1 and (data_evidence >= 1 or short_rows >= 3)


def _nearest_local_caption(candidate: dict, captions: list[dict], max_distance: float = 80.0) -> str | None:
    """Find the nearest section caption above or at the top of a candidate."""
    if not captions:
        return None
    top = candidate["bbox"][1]
    best_caption = None
    min_dist = float("inf")
    for cap in captions:
        c_top = cap.get("top", 0)
        dist = top - c_top
        if -25.0 <= dist <= max_distance:
            if abs(dist) < min_dist:
                min_dist = abs(dist)
                best_caption = cap.get("text")
    if best_caption:
        return best_caption
    closest = min(captions, key=lambda c: abs(c.get("top", 0) - top))
    if abs(closest.get("top", 0) - top) <= max_distance:
        return closest.get("text")
    return None


def _specific_ocr_domain_caption(candidate: dict, fallback: str = "") -> str:
    """Extract a specific financial domain title from the candidate's OCR lines if present."""
    ocr_lines = candidate.get("ocr_lines") or []
    for line in ocr_lines:
        text = line.get("text", "") if isinstance(line, dict) else str(line)
        m = re.search(
            r"\b(earnings?\s+per\s+share|share\s+capital|trade\s+payables?|"
            r"trade\s+receivables?|cash\s+and\s+cash\s+equivalents?|deferred\s+tax|"
            r"borrowings?|provisions?|contingent\s+liabilit(?:y|ies)|"
            r"related\s+part(?:y|ies)|property[,\s]+plant\s+and\s+equipment|"
            r"other\s+intangible\s+assets?|financial\s+assets?)\b",
            text,
            re.I,
        )
        if m:
            return m.group(0).lower()
    return fallback


def _repeats_adjacent_caption_phrase(text: str) -> bool:
    """Return True if the caption consists of repeated adjacent phrases (e.g. OCR column duplication)."""
    if not text:
        return False
    words = text.strip().split()
    n = len(words)
    if n >= 2 and n % 2 == 0:
        half = n // 2
        if [w.lower() for w in words[:half]] == [w.lower() for w in words[half:]]:
            return True
    m = re.search(r"\b([A-Za-z0-9\s]{3,})\s+\1\b", text.strip(), re.I)
    if m and len(m.group(1).split()) >= 2:
        return True
    return False


def _table_row_bboxes(table, data: list[list]) -> list[tuple | None]:
    row_bboxes = []
    for row, values in zip(getattr(table, "rows", []), data):
        used_cells = [
            cell
            for cell, value in zip(row.cells, values)
            if cell and value and str(value).strip()
        ]
        if not used_cells:
            row_bboxes.append(None)
            continue
        row_bboxes.append((
            min(cell[0] for cell in used_cells),
            min(cell[1] for cell in used_cells),
            max(cell[2] for cell in used_cells),
            max(cell[3] for cell in used_cells),
        ))
    return row_bboxes


def _split_candidates_at_section_anchors(page, page_lines: list[dict], candidates: list[dict],
                                         page_area: float) -> list[dict]:
    """Split broad candidates at numbered notes and preserve narrower table regions."""
    anchors = _caption_anchors(page, page_lines, [])
    anchors = [
        anchor for anchor in anchors
        if not re.fullmatch(r"[\d.,₹%()\-–—]+", anchor["text"])
    ]
    anchors.sort(key=lambda anchor: anchor["top"])
    unique_anchors = []
    for anchor in anchors:
        normalized = _normalized_anchor_text(anchor["text"]).lower()
        note_match = re.match(r"^notes?\s*(?:no\.?\s*)?(\d+[a-z]?)", normalized)
        key = f"note:{note_match.group(1)}" if note_match else normalized
        duplicate_index = next(
            (
                index for index, previous in enumerate(unique_anchors)
                if abs(previous["top"] - anchor["top"]) <= 8.0
                and previous["_anchor_key"] == key
            ),
            None,
        )
        if duplicate_index is None:
            unique_anchors.append({**anchor, "_anchor_key": key})
        elif anchor["structural"] and not unique_anchors[duplicate_index]["structural"]:
            unique_anchors[duplicate_index] = {**anchor, "_anchor_key": key}
    anchors = [
        {key: value for key, value in anchor.items() if key != "_anchor_key"}
        for anchor in unique_anchors
    ]
    section_anchors = [
        anchor for anchor in anchors
        if _is_table_caption_start(anchor, anchors, page_lines)
    ]
    if not section_anchors:
        return candidates

    result = []
    for candidate in candidates:
        x0, y0, x1, y1 = candidate["bbox"]
        if y1 - y0 < page.height * 0.12:
            result.append(candidate)
            continue
        starts = sorted([
            anchor for anchor in section_anchors
            if y0 - 80.0 <= anchor["top"] < y1 - 30.0
        ], key=lambda anchor: anchor["top"])
        single_boundary_split = bool(
            len(starts) == 1
            and re.match(
                r"^notes?\s*(?:no\.?\s*)?\d+[a-z]?\b",
                starts[0]["text"],
                re.I,
            )
            and starts[0]["top"] > y0 + 30.0
        )
        if len(starts) < 2 and not single_boundary_split:
            result.append(candidate)
            continue

        def caption_for(anchor):
            if anchor["structural"]:
                following = next(
                    (
                        item for item in anchors
                        if not item["structural"]
                        and 0 <= item["top"] - anchor["top"] <= 35.0
                    ),
                    None,
                )
                if following:
                    return following["text"]
                following_line = next(
                    (
                        _normalized_anchor_text(line["text"])
                        for line in sorted(page_lines, key=lambda item: item["top"])
                        if 0 < line["top"] - anchor["top"] <= 35.0
                        and not _TABLE_HEADER_LINE.match(line["text"])
                        and _is_plausible_caption(_normalized_anchor_text(line["text"]))
                        and len(_normalized_anchor_text(line["text"]).split()) <= 10
                    ),
                    None,
                )
                if following_line:
                    return following_line
            return anchor["text"]

        boundaries = [
            (max(0.0, starts[0]["top"] - 2.0), caption_for(starts[0]))
        ]
        if single_boundary_split and starts[0]["structural"]:
            boundary_caption = boundaries[0][1]
            if boundary_caption.lower() != starts[0]["text"].lower():
                boundaries[0] = (
                    boundaries[0][0],
                    f"{starts[0]['text']} – {boundary_caption}",
                )
        boundaries.extend(
            (anchor["top"] - 2.0, caption_for(anchor))
            for anchor in starts[1:]
        )
        ranges = []
        for index, (start, caption) in enumerate(boundaries):
            end = boundaries[index + 1][0] if index + 1 < len(boundaries) else y1
            if end - start < 30:
                continue
            localized = [
                other for other in candidates
                if other is not candidate
                and start + 30.0 < other["bbox"][1] < end - 5.0
                and other["bbox"][3] >= end - 20.0
                and _overlap(
                    (x0, start, x1, end),
                    (other["bbox"][0], start, other["bbox"][2], end),
                ) >= 0.60
            ]
            if localized:
                cut = min(other["bbox"][1] for other in localized)
                if cut - start >= 30:
                    ranges.append((start, cut, caption))
                    continue
            ranges.append((start, end, caption))

        sections = []
        for start, end, caption in ranges:
            section_candidates = []
            try:
                crop = page.crop((
                    max(0.0, x0 - 4.0),
                    max(0.0, start),
                    min(page.width, x1 + 4.0),
                    min(page.height, end),
                ))
                for strategy, settings in TABLE_SETTINGS:
                    for table in crop.find_tables(table_settings=settings):
                        data = table.extract()
                        metrics = _metrics(data, strategy=strategy)
                        if metrics is None or _looks_like_letterhead_or_signature(data):
                            continue
                        bbox = tuple(float(value) for value in table.bbox)
                        area_ratio = (
                            max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
                        ) / page_area
                        if strategy == "text" and (
                            area_ratio > 0.82
                            or metrics["stable_width_ratio"] < 0.10
                            or metrics["long_cell_ratio"] > 0.12
                        ):
                            continue
                        score = (
                            (1 - metrics["cell_occupancy"])
                            + (1 - metrics["multi_cell_row_ratio"])
                            + area_ratio
                        )
                        section_candidates.append({
                            "bbox": bbox,
                            "metrics": metrics,
                            "strategy": strategy,
                            "score": score,
                            "table_data": data,
                            "segmented": True,
                            "_section_caption": caption,
                        })
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "Could not split a table candidate at a note heading: %s", exc
                )
            if not section_candidates and candidate.get("_row_bboxes"):
                selected_rows = [
                    (row_bbox, row_data)
                    for row_bbox, row_data in zip(
                        candidate["_row_bboxes"], candidate.get("table_data", [])
                    )
                    if row_bbox
                    and start <= (row_bbox[1] + row_bbox[3]) / 2.0 < end
                ]
                data = [row_data for _, row_data in selected_rows]
                metrics = _metrics(data, strategy=candidate["strategy"])
                if metrics:
                    row_bboxes = [bbox for bbox, _ in selected_rows]
                    bbox = (
                        min(box[0] for box in row_bboxes),
                        min(box[1] for box in row_bboxes),
                        max(box[2] for box in row_bboxes),
                        max(box[3] for box in row_bboxes),
                    )
                    section_candidates.append({
                        "bbox": bbox,
                        "metrics": metrics,
                        "strategy": candidate["strategy"],
                        "score": (
                            (1 - metrics["cell_occupancy"])
                            + (1 - metrics["multi_cell_row_ratio"])
                            + max(0.0, bbox[2] - bbox[0])
                            * max(0.0, bbox[3] - bbox[1])
                            / page_area
                        ),
                        "table_data": data,
                        "segmented": True,
                        "_section_caption": caption,
                    })
            if section_candidates:
                sections.append(section_candidates)

        if len(sections) >= 2 or (single_boundary_split and sections):
            for section in sections:
                result.extend(section)
        else:
            result.append(candidate)
    return result


def _merge_primary_statement_ocr_fragments(
    page_lines: list[dict], candidates: list[dict], page_width: float, page_height: float,
    allow_native: bool = False,
) -> list[dict]:
    """Join aligned OCR regions belonging to one primary financial statement."""
    headings = [
        {
            "top": line["top"],
            "text": _normalized_anchor_text(line["text"]),
        }
        for line in page_lines
        if PRIMARY_STATEMENT_HEADING.match(_normalized_anchor_text(line["text"]))
    ]
    if not headings:
        return candidates

    note_tops = [line["top"] for line in _note_heading_lines(page_lines)]
    remove = set()
    merged = []
    for index, heading in enumerate(headings):
        top = max(0.0, heading["top"] - 8.0)
        bottom = headings[index + 1]["top"] if index + 1 < len(headings) else page_height
        statement_candidates = [
            item for item in candidates
            if item["strategy"] in ("ocr", "text", "lines")
            and top <= (item["bbox"][1] + item["bbox"][3]) / 2 < bottom
        ]
        statement_candidates.sort(key=lambda item: item["bbox"][1])
        groups = []
        for item in statement_candidates:
            x0, _, x1, _ = item["bbox"]
            placed = False
            for group in groups:
                gx0 = min(entry["bbox"][0] for entry in group)
                gx1 = max(entry["bbox"][2] for entry in group)
                overlap = max(0.0, min(x1, gx1) - max(x0, gx0))
                if overlap / max(1.0, min(x1 - x0, gx1 - gx0)) >= 0.75:
                    group.append(item)
                    placed = True
                    break
            if not placed:
                groups.append([item])

        for group in groups:
            if len(group) < 2:
                continue
            if not allow_native and not any(item["strategy"] == "ocr" for item in group):
                continue
            group_top = min(item["bbox"][1] for item in group)
            group_bottom = max(item["bbox"][3] for item in group)
            if any(group_top < note_top < group_bottom for note_top in note_tops):
                continue
            widths = [item["bbox"][2] - item["bbox"][0] for item in group]
            if max(widths) - min(widths) > page_width * 0.18:
                continue
            x0 = min(item["bbox"][0] for item in group)
            y0 = group_top
            x1 = max(item["bbox"][2] for item in group)
            y1 = group_bottom
            metrics = dict(group[0]["metrics"])
            metrics["rows"] = sum(item["metrics"]["rows"] for item in group)
            metrics["columns"] = max(item["metrics"]["columns"] for item in group)
            merged_strategy = "ocr" if any(item["strategy"] == "ocr" for item in group) else group[0]["strategy"]
            merged.append({
                "bbox": (
                    min(x0, page_width * 0.06),
                    min(y0, top),
                    max(x1, page_width * 0.94),
                    y1,
                ),
                "metrics": metrics,
                "strategy": merged_strategy,
                "score": min(item["score"] for item in group),
                "table_data": [],
                "_primary_statement_title": heading["text"],
            })
            remove.update(id(item) for item in group)

    result = [item for item in candidates if id(item) not in remove]
    result.extend(merged)
    return result


def _merge_captioned_fragments(
    candidates: list[dict],
    section_headings: list[dict],
    page_height: float,
) -> list[dict]:
    """Merge vertically adjacent fragments that belong to the same captioned subsection."""
    if len(candidates) < 2 or not section_headings:
        return list(candidates)

    items = sorted(candidates, key=lambda c: c["bbox"][1])
    merged = []
    skip = set()

    for i in range(len(items)):
        if i in skip:
            continue
        curr = items[i]
        curr_bbox = curr["bbox"]
        curr_title = curr.get("_resolved_title")

        combined = dict(curr)
        combined_bbox = list(curr_bbox)
        combined_rows = curr.get("metrics", {}).get("rows", 0)

        for j in range(i + 1, len(items)):
            if j in skip:
                continue
            nxt = items[j]
            nxt_bbox = nxt["bbox"]
            nxt_title = nxt.get("_resolved_title")

            if not curr_title or curr_title != nxt_title:
                break

            intervening = [
                s for s in section_headings
                if combined_bbox[3] - 10.0 <= s.get("top", 0) <= nxt_bbox[1] + 10.0
            ]
            if intervening:
                break

            matching_section = any(
                abs(s.get("top", 0) - combined_bbox[1]) <= 150.0 or
                (combined_bbox[1] <= s.get("top", 0) <= nxt_bbox[3])
                for s in section_headings
            )
            if not matching_section:
                break

            x0 = min(combined_bbox[0], nxt_bbox[0])
            x1 = max(combined_bbox[2], nxt_bbox[2])
            overlap_x = max(0.0, min(combined_bbox[2], nxt_bbox[2]) - max(combined_bbox[0], nxt_bbox[0]))
            min_w = max(1.0, min(combined_bbox[2] - combined_bbox[0], nxt_bbox[2] - nxt_bbox[0]))
            if overlap_x / min_w < 0.70:
                break

            combined_bbox = [x0, min(combined_bbox[1], nxt_bbox[1]), x1, max(combined_bbox[3], nxt_bbox[3])]
            combined_rows += nxt.get("metrics", {}).get("rows", 0)
            skip.add(j)

        combined["bbox"] = tuple(combined_bbox)
        if "metrics" in combined:
            combined["metrics"] = dict(combined["metrics"])
            combined["metrics"]["rows"] = combined_rows
        merged.append(combined)

    return merged


def _segmented_candidates(page, page_lines: list[dict], candidates: list[dict],
                          ruled_seeds: list[tuple], page_area: float) -> list[dict]:
    """Retry broad text detections within heading- and ruled-table-bounded page bands."""
    anchors = _caption_anchors(page, page_lines, ruled_seeds)
    broad_text = [
        candidate for candidate in candidates
        if candidate["strategy"] == "text"
        and candidate["bbox"][3] - candidate["bbox"][1] > page.height * 0.22
    ]
    if not (
        (broad_text and (len(anchors) >= 2 or len(ruled_seeds) >= 2))
        or (not candidates and len(ruled_seeds) >= 2)
    ):
        return candidates

    boundaries = [anchor["top"] for anchor in anchors]
    boundaries.extend(box[1] for box in ruled_seeds)
    boundaries = sorted(y for y in boundaries if 25.0 < y < page.height - 35.0)

    unique_boundaries = []
    for y in boundaries:
        if not unique_boundaries or y - unique_boundaries[-1] > 7.0:
            unique_boundaries.append(y)
    if not unique_boundaries:
        return candidates

    segmented = []
    for index, y0 in enumerate(unique_boundaries):
        y1 = unique_boundaries[index + 1] if index + 1 < len(unique_boundaries) else page.height - 35.0
        if y1 - y0 < 34.0:
            continue
        try:
            crop = page.crop((0, max(0.0, y0 - 2.0), page.width, y1))
            for strategy, settings in TABLE_SETTINGS:
                for table in crop.find_tables(table_settings=settings):
                    data = table.extract()
                    metrics = _metrics(data, strategy=strategy)
                    if metrics is None or _looks_like_letterhead_or_signature(data):
                        continue
                    bbox = tuple(float(value) for value in table.bbox)
                    area_ratio = (
                        max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
                    ) / page_area
                    if strategy == "text" and (
                        area_ratio > 0.82
                        or metrics["stable_width_ratio"] < 0.10
                        or metrics["long_cell_ratio"] > 0.12
                    ):
                        continue
                    score = (
                        (1 - metrics["cell_occupancy"])
                        + (1 - metrics["multi_cell_row_ratio"])
                        + area_ratio
                    )
                    segmented.append({
                        "bbox": bbox,
                        "metrics": metrics,
                        "strategy": strategy,
                        "score": score,
                        "table_data": data,
                        "segmented": True,
                    })
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Could not segment table candidates in page crop at y=%.1f: %s", y0, exc
            )

    if not segmented:
        return candidates

    result = []
    for candidate in candidates:
        x0, y0, x1, y1 = candidate["bbox"]
        height = y1 - y0
        contained = [
            item for item in segmented
            if x0 <= (item["bbox"][0] + item["bbox"][2]) / 2 <= x1
            and y0 <= (item["bbox"][1] + item["bbox"][3]) / 2 <= y1
        ]
        if candidate in broad_text and len(contained) >= 2:
            continue
        result.append(candidate)
    for candidate in segmented:
        if not broad_text:
            result.append(candidate)
            continue
        x0, y0, x1, y1 = candidate["bbox"]
        if any(
            bx0 - 4.0 <= x0 and y0 >= by0 - 4.0
            and x1 <= bx1 + 4.0 and y1 <= by1 + 4.0
            for broad in broad_text
            for bx0, by0, bx1, by1 in [broad["bbox"]]
        ):
            result.append(candidate)
    return result


def _header_fallback(data) -> str:
    """Infer a descriptive title from a table's column header row when no external caption exists."""
    if not data:
        return "Untitled table"
    header_rows = data[:2]
    joined = " ".join(
        re.sub(r"\s+", " ", str(c or "")).strip().lower()
        for row in header_rows
        for c in (row or [])
        if c
    )
    if sum(term in joined for term in ("txn date", "value date", "cheque", "debit", "credit", "balance")) >= 4:
        return "Bank Transaction Statement"
    if sum(term in joined for term in ("carton", "order", "part", "description", "unit", "qty", "sales", "customs")) >= 4:
        return "Commercial Invoice"
    first_cells = [re.sub(r"\s+", " ", str(c or "")).strip() for c in data[0] if c and str(c).strip()]
    non_numeric = [c for c in first_cells if not re.fullmatch(r"[\d\s.,()/:%₹$£€\-–—]+", c)]
    if len(non_numeric) == 1 and _is_plausible_caption(non_numeric[0]):
        return _clean(non_numeric[0])
    return "Untitled table"


def _detect_unbordered_column_header_table(page) -> list[dict]:
    """Fallback for borderless multi-column tables whose cells merge during standard text strategy."""
    try:
        words = page.extract_words() or []
    except Exception:
        return []
    if not words:
        return []

    page_height = float(getattr(page, "height", 842.0))
    page_width = float(getattr(page, "width", 595.0))
    top_words = [w for w in words if float(w.get("top", 0.0)) <= page_height * 0.30]
    top_vocab = {str(w.get("text", "")).lower().strip(".,:()") for w in top_words}

    invoice_tokens = {"carton", "order", "part", "description", "unit", "price", "qty", "sales", "customs"}
    bank_tokens = {"txn", "value", "date", "cheque", "description", "debit", "credit", "balance"}

    matched_invoice = invoice_tokens & top_vocab
    matched_bank = bank_tokens & top_vocab

    if len(matched_invoice) >= 6 or len(matched_bank) >= 6:
        target_tokens = matched_invoice if len(matched_invoice) >= 6 else matched_bank
        header_w = [w for w in top_words if str(w.get("text", "")).lower().strip(".,:()") in target_tokens]
        y0 = min(float(w["top"]) for w in header_w)
        decimal_words = [
            w for w in words
            if float(w.get("top", 0.0)) > y0 and re.search(r"^\d[\d,]*\.\d{2}$", str(w.get("text", "")))
        ]
        if len(decimal_words) >= 2:
            y1 = max(float(w.get("bottom", y0 + 200.0)) for w in decimal_words)
            return [{
                "bbox": (20.0, y0, page.width - 20.0, max(y1, y0 + 80.0)),
                "metrics": {
                    "rows": max(3, len(decimal_words) // 2 + 1),
                    "columns": len(target_tokens),
                    "cell_occupancy": 0.6,
                    "multi_cell_row_ratio": 0.75,
                    "numeric_cell_ratio": 0.35,
                    "stable_width_ratio": 0.5,
                    "long_cell_ratio": 0.0,
                    "avg_words_per_cell": 3.0,
                },
                "strategy": "header-grid-fallback",
                "score": 0.5,
                "table_data": [sorted(target_tokens)],
            }]
    return []


def detect_tables(
    pdf_path: str | Path,
    use_ocr: bool = True,
    include_diagnostics: bool = False,
    page_numbers: list[int] | None = None,
) -> list[dict]:
    """Return one result per detected table, using 1-based PDF page numbers."""
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    results = []
    active_note = None
    previous_bottom_table = None

    with pdfplumber.open(pdf_path) as pdf, pymupdf.open(pdf_path) as fitz_doc:
        for page_index, page in enumerate(pdf.pages):
            page_number = page_index + 1
            if page_numbers and page_number not in page_numbers:
                continue
            page_text = page.extract_text() or ""
            page_text_lower = page_text.lower()
            page_lines = _extract_merged_lines(page)
            in_notes_section = page_has_notes_banner(page)
            page_info = classify_page(fitz_doc[page_index])

            if any(
                marker in page_text_lower
                for marker in (
                    "we communicate with those charged with governance",
                    "report on the internal financial controls under section",
                    "basis for opinion",
                    "management's responsibility for the financial statements",
                    "responsibilities for audit of financial statements",
                )
            ):
                continue

            candidates = []
            ruled_seeds = []
            page_width = float(getattr(page, "width", 595.0))
            page_height = float(getattr(page, "height", 842.0))
            page_area = max(page_width * page_height, 1)

            for strategy, settings in TABLE_SETTINGS:
                try:
                    for table in page.find_tables(table_settings=settings):
                        data = table.extract()
                        bbox = tuple(float(v) for v in table.bbox)
                        if strategy == "lines":
                            ruled_seeds.append(bbox)
                        metrics = _metrics(data, strategy=strategy)
                        if metrics is None:
                            continue
                        if _looks_like_letterhead_or_signature(data):
                            continue
                        region_area = max(0, bbox[2] - bbox[0]) * max(0, bbox[3] - bbox[1])
                        area_ratio = region_area / page_area
                        if strategy == "text":
                            if area_ratio > 0.82:
                                continue
                            if area_ratio > 0.45 and metrics["numeric_cell_ratio"] < 0.16:
                                continue
                            if metrics["stable_width_ratio"] < 0.16 or metrics["long_cell_ratio"] > 0.05:
                                continue
                        score = (
                            (1 - metrics["cell_occupancy"])
                            + (1 - metrics["multi_cell_row_ratio"])
                            + area_ratio
                        )
                        candidates.append({
                            "bbox": bbox,
                            "metrics": metrics,
                            "strategy": strategy,
                            "score": score,
                            "table_data": data,
                            "_row_bboxes": _table_row_bboxes(table, data),
                        })
                except Exception as exc:
                    logging.getLogger(__name__).warning(
                        "Table strategy %s failed on %s page %s: %s",
                        strategy, pdf_path.name, page_number, exc,
                    )

            candidates.extend(_detect_unbordered_column_header_table(page))
            candidates = _segmented_candidates(
                page, page_lines, candidates, ruled_seeds, page_area
            )

            caption_anchors = _caption_anchors(page, page_lines, ruled_seeds)
            table_anchor_count = sum(
                _is_table_caption_start(anchor, caption_anchors, page_lines)
                for anchor in caption_anchors
            )
            broad_text_candidate = any(
                candidate["strategy"] == "text"
                and candidate["bbox"][3] - candidate["bbox"][1] > page_height * 0.40
                for candidate in candidates
            )
            should_ocr = page_info["page_type"] == "SCANNED_WITHOUT_TEXT" or (
                page_info["page_type"] == "IMAGE_BACKED_WITH_TEXT"
                and (
                    not candidates
                    or broad_text_candidate
                    or table_anchor_count > len(candidates)
                )
            )
            layout = None
            if use_ocr and should_ocr:
                try:
                    layout = ocr_page_layout(pdf_path, page_number)
                    for region in detect_ocr_table_regions(layout):
                        width, height = layout["image_size"]
                        scale_x, scale_y = page_width / width, page_height / height
                        x0, y0, x1, y1 = region["bbox"]
                        bbox = (x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y)
                        region_lines = region.get("ocr_lines", [])
                        region_text = " ".join(
                            line["text"] for line in region_lines
                        )
                        ocr_title = extract_ocr_caption(layout, region["bbox"])
                        has_header = bool(re.search(
                            r"\b(particulars|description|amount|balance|as\s+at|"
                            r"year\s+ended|period\s+ended|debit|credit)\b",
                            region_text,
                            re.I,
                        ))
                        numeric_or_nil_rows = sum(
                            (
                                bool(re.search(r"\d", line["text"]))
                                or bool(re.search(r"\b(?:nil|n/?a|none)\b", line["text"], re.I))
                                or bool(re.search(r"\bN\s+N\b", line["text"]))
                            )
                            and not re.search(
                                r"\b(?:as\s+at|year\s+ended|period\s+ended|"
                                r"note|page)\b",
                                line["text"],
                                re.I,
                            )
                            for line in region_lines
                        )
                        if region["rows"] < 4 and not (
                            numeric_or_nil_rows >= 2
                            or (
                                has_header
                                and ocr_title != "Untitled table"
                                and not STRUCTURAL_HEADING.match(ocr_title)
                            )
                        ):
                            continue
                        prose_line_ratio = (
                            sum(line["word_count"] > 10 for line in region_lines)
                            / max(len(region_lines), 1)
                        )
                        if prose_line_ratio > 0.35:
                            continue
                        candidates.append({
                            "bbox": bbox,
                            "metrics": {
                                "rows": region["rows"],
                                "columns": region["columns"],
                                "cell_occupancy": 1.0,
                                "multi_cell_row_ratio": 1.0,
                                "numeric_cell_ratio": 0.25,
                            },
                            "strategy": "ocr",
                            "score": 0.5,
                            "table_data": [],
                            "ocr_title": ocr_title,
                            "ocr_lines": region.get("ocr_lines", []),
                        })
                except Exception as exc:
                    logging.getLogger(__name__).warning(
                        "OCR failed on %s page %s: %s", pdf_path.name, page_number, exc
                    )

            ocr_page_lines = _ocr_lines_in_page_coordinates(
                layout, page_width, page_height
            )
            all_page_lines = page_lines + ocr_page_lines
            caption_anchors = _caption_anchors(page, all_page_lines, ruled_seeds)
            candidates = [
                candidate for candidate in candidates
                if not _looks_like_footer_candidate(candidate, all_page_lines, page_height)
                and not _looks_like_header_candidate(candidate, all_page_lines, page_height)
            ]
            candidates = _split_candidates_at_section_anchors(
                page, all_page_lines, candidates, page_area
            )
            broad_candidates = [
                candidate for candidate in candidates
                if candidate["strategy"] in ("text", "lines")
                and candidate["bbox"][3] - candidate["bbox"][1] > page_height * 0.40
            ]
            for broad in broad_candidates:
                bx0, by0, bx1, by1 = broad["bbox"]
                broad_metrics = broad.get("metrics", {})
                anchors_inside_broad = [
                    a for a in caption_anchors
                    if by0 - 15.0 <= a["top"] <= by1 + 5.0
                ]
                broad_is_authoritative = (
                    broad_metrics.get("rows", 0) >= 8
                    and broad_metrics.get("columns", 0) >= 3
                    and broad_metrics.get("numeric_cell_ratio", 0) >= 0.12
                    and len(anchors_inside_broad) <= 1
                )
                localized = [
                    candidate for candidate in candidates
                    if candidate is not broad
                    and candidate["bbox"][3] - candidate["bbox"][1] < (by1 - by0) * 0.75
                    and (
                        (
                            bx0 - 5.0 <= (candidate["bbox"][0] + candidate["bbox"][2]) / 2 <= bx1 + 5.0
                            and by0 - 5.0 <= (candidate["bbox"][1] + candidate["bbox"][3]) / 2 <= by1 + 5.0
                        )
                        or _overlap(candidate["bbox"], broad["bbox"]) > 0.25
                    )
                ]
                if broad_is_authoritative:
                    for item in localized:
                        if item["strategy"] == "ocr" and item in candidates:
                            candidates.remove(item)

                localized_native = [
                    c for c in localized
                    if c["strategy"] in ("lines", "text", "header-grid-fallback")
                ]
                distinct = []
                for candidate in sorted(localized_native, key=lambda item: item["bbox"][1]):
                    if all(_overlap(candidate["bbox"], kept["bbox"]) < 0.45 for kept in distinct):
                        distinct.append(candidate)
                if len(distinct) >= 2 and len(caption_anchors) >= 2:
                    if broad in candidates:
                        candidates.remove(broad)

            candidates = _merge_primary_statement_ocr_fragments(
                all_page_lines, candidates, page_width, page_height
            )
            candidates = _deduplicate(candidates, page_lines=all_page_lines)
            candidates.sort(key=lambda candidate: (
                candidate["bbox"][1], candidate["bbox"][0]
            ))

            note_headings = _note_heading_lines(all_page_lines)
            page_carried_note = None
            if (
                active_note
                and active_note["page"] == page_number - 1
                and in_notes_section
                and candidates
                and not any(
                    item["top"] <= candidates[0]["bbox"][1] + 8.0
                    for item in note_headings
                )
            ):
                previous_title_matches_note = bool(
                    previous_bottom_table
                    and previous_bottom_table["page"] == page_number - 1
                    and previous_bottom_table["title"].lower().startswith(
                        active_note["title"].lower()
                    )
                )
                note_follows_previous_table = bool(
                    previous_bottom_table
                    and previous_bottom_table["page"] == page_number - 1
                    and active_note.get("top", 0.0)
                    >= previous_bottom_table["bottom"] - 5.0
                )
                if (
                    candidates[0]["bbox"][1] <= page_height * 0.35
                    or previous_title_matches_note
                    or note_follows_previous_table
                ):
                    page_carried_note = active_note

            for candidate in candidates:
                table_top = candidate["bbox"][1]
                nearby_note = next(
                    (
                        item for item in reversed(note_headings)
                        if 0.0 <= table_top - item["top"] <= 25.0
                    ),
                    None,
                )
                if nearby_note:
                    x0, _, x1, y1 = candidate["bbox"]
                    candidate["bbox"] = (
                        x0,
                        max(0.0, nearby_note["top"] - 3.0),
                        x1,
                        y1,
                    )
                    table_top = candidate["bbox"][1]
                local_note = next(
                    (
                        item for item in reversed(note_headings)
                        if item["top"] <= table_top + 8.0
                    ),
                    None,
                )
                title = extract_table_title(
                    page,
                    candidate["bbox"],
                    additional_lines=ocr_page_lines,
                    min_y=local_note["top"] if local_note else None,
                )
                ocr_title = candidate.get("ocr_title")
                if (
                    candidate["strategy"] == "ocr"
                    and ocr_title
                    and ocr_title != "Untitled table"
                    and not STRUCTURAL_HEADING.match(ocr_title)
                    and not NUMBERED_SECTION_HEADING.match(ocr_title)
                ):
                    title = ocr_title
                parent_note = local_note or page_carried_note
                if parent_note:
                    min_anchor_top = local_note["top"] if local_note else 0.0
                    note_captions = [
                        anchor for anchor in caption_anchors
                        if not anchor["structural"]
                        and min_anchor_top <= anchor["top"] <= table_top + 8.0
                        and table_top - anchor["top"] <= 120.0
                        and (
                            _is_table_caption_start(
                                anchor, caption_anchors, all_page_lines
                            )
                            or bool(_ALPHA_SUBSECTION.match(anchor["text"]))
                            or bool(_NUMBERED_SUBSECTION.match(anchor["text"]))
                        )
                    ]
                    note_caption = max(
                        note_captions, key=lambda anchor: anchor["top"], default=None
                    )
                    if note_caption and (
                        title == "Untitled table"
                        or title == parent_note["title"]
                        or STRUCTURAL_HEADING.match(title)
                    ):
                        title = note_caption["text"]

                if title == "Untitled table" and candidate.get("ocr_title"):
                    ocr_title = candidate["ocr_title"]
                    if ocr_title and ocr_title != "Untitled table":
                        title = ocr_title

                if title == "Untitled table":
                    title = _header_fallback(candidate.get("table_data"))
                if title != "Untitled table":
                    title = normalize_title_case(title)
                if candidate.get("_primary_statement_title"):
                    title = normalize_title_case(candidate["_primary_statement_title"])
                elif candidate.get("_section_caption"):
                    title = normalize_title_case(candidate["_section_caption"])

                cols = candidate["metrics"]["columns"]

                has_current_page_heading = any(
                    (
                        _is_table_caption_start(anchor, caption_anchors, all_page_lines)
                        or bool(_ALPHA_SUBSECTION.match(anchor["text"]))
                        or bool(_NUMBERED_SUBSECTION.match(anchor["text"]))
                    )
                    and not (
                        RUNNING_NAV_BANNER.search(anchor["text"])
                        or GENERIC_NOTES_BANNER.search(anchor["text"])
                        or GENERIC_HEADER.search(anchor["text"])
                        or re.search(r"\b(?:overview|reports|financial\s+statements|standalone)\b", anchor["text"], re.I)
                    )
                    and 0.0 <= anchor["top"] <= table_top + 10.0
                    for anchor in caption_anchors
                )

                if (
                    (
                        title == "Untitled table"
                        or bool(STRUCTURAL_HEADING.match(title))
                        or bool(_BARE_NOTE_HEADING.match(title))
                    )
                    and not has_current_page_heading
                    and previous_bottom_table
                    and previous_bottom_table["page"] == page_number - 1
                    and previous_bottom_table["bottom"] >= previous_bottom_table["page_height"] * 0.70
                    and table_top <= page_height * 0.25
                    and (
                        abs(cols - previous_bottom_table["columns"]) <= 2
                        or not in_notes_section
                        or candidate.get("strategy") != previous_bottom_table.get("strategy")
                    )
                    and (
                        (
                            in_notes_section
                            and (
                                local_note is None
                                or re.sub(r"\s+", " ", local_note["title"]).strip().lower()
                                in re.sub(
                                    r"\s+", " ", previous_bottom_table["title"]
                                ).strip().lower()
                            )
                        )
                        or (
                            not in_notes_section
                            and bool(PRIMARY_STATEMENT_HEADING.match(previous_bottom_table["title"]))
                        )
                    )
                    and previous_bottom_table["title"] != "Untitled table"
                ):
                    title = previous_bottom_table["title"]

                if title == "Untitled table" and parent_note:
                    title = parent_note["title"]
                elif parent_note and title != "Untitled table":
                    normalized_title = re.sub(r"\s+", " ", title).strip().lower()
                    normalized_parent = re.sub(
                        r"\s+", " ", parent_note["title"]
                    ).strip().lower()
                    if (
                        normalized_title != normalized_parent
                        and not normalized_title.startswith(normalized_parent)
                        and not STRUCTURAL_HEADING.match(title)
                        and not (
                            PRIMARY_STATEMENT_HEADING.match(title)
                            and not in_notes_section
                        )
                    ):
                        title = f"{parent_note['title']} – {title}"

                candidate["_resolved_title"] = title
            candidates = _deduplicate_resolved_candidates(
                candidates, page_height, note_headings
            )
            for candidate in candidates:
                result = {
                    "Table Title": candidate["_resolved_title"],
                    "Page Number": page_number,
                }
                if include_diagnostics:
                    result.update({
                        "Bounding Box": [
                            round(float(value), 2) for value in candidate["bbox"]
                        ],
                        "Strategy": candidate["strategy"],
                        "Metrics": dict(candidate["metrics"]),
                    })
                results.append(result)

            if candidates:
                last_candidate = max(candidates, key=lambda item: item["bbox"][3])
                previous_bottom_table = {
                    "page": page_number,
                    "bottom": last_candidate["bbox"][3],
                    "page_height": page_height,
                    "columns": last_candidate["metrics"]["columns"],
                    "title": last_candidate.get("_resolved_title", "Untitled table"),
                }
            else:
                previous_bottom_table = None

            if note_headings:
                active_note = {
                    "page": page_number,
                    "title": note_headings[-1]["title"],
                    "top": note_headings[-1]["top"],
                }
            elif active_note and active_note["page"] == page_number - 1 and in_notes_section:
                active_note = {**active_note, "page": page_number}
            else:
                active_note = None
    return results
