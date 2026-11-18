from src.table_detector import _metrics, _overlap

def test_metrics_rejects_non_table():
    assert _metrics([["only one"], ["row"]]) is None

def test_metrics_accepts_financial_table():
    result = _metrics([["Particulars", "Amount"], ["Cash", "100"], ["Debt", "50"]])
    assert result and result["columns"] == 2

def test_overlap():
    assert _overlap((0, 0, 10, 10), (0, 0, 10, 10)) == 1


def test_header_fallback_identifies_bank_statement():
    from src.table_detector import _header_fallback
    data = [["Txn Date", "Value Date", "Cheque No.", "Description", "Branch Code", "Debit", "Credit", "Balance"]]
    assert _header_fallback(data) == "Bank Transaction Statement"


def test_header_fallback_does_not_invent_generic_titles():
    from src.table_detector import _header_fallback
    assert _header_fallback([["Particulars", "Note", "Amount"]]) == "Untitled table"


def test_letterhead_grid_is_not_treated_as_table():
    from src.table_detector import _looks_like_letterhead_or_signature
    data = [
        ["Ph. No. +91 98640 48892", "Email: office@example.com"],
        ["JAGADISH NATH", "CHARTERED ACCOUNTANTS"],
    ]
    assert _looks_like_letterhead_or_signature(data)


def test_signature_block_is_not_treated_as_table():
    from src.table_detector import _looks_like_letterhead_or_signature
    data = [
        ["For and on behalf of the Board", "Place : Mumbai"],
        ["Partner", "Membership No. 12345"],
    ]
    assert _looks_like_letterhead_or_signature(data)


def test_regular_financial_table_is_not_letterhead():
    from src.table_detector import _looks_like_letterhead_or_signature
    data = [["Particulars", "Amount"], ["Cash", "100"], ["Debt", "50"]]
    assert not _looks_like_letterhead_or_signature(data)


def test_two_column_narrative_alignment_is_not_a_table():
    from src.table_detector import _looks_like_letterhead_or_signature

    data = [
        ["The company invests in short term deposits", ""],
        ["Considering the short term nature of these deposits", ""],
        ["There is no significant interest rate risk", ""],
        ["These amounts are exposed to changes in rates", ""],
        ["The company reviews its investment policy annually", ""],
        ["No material impact is expected from the change", ""],
    ]
    assert _looks_like_letterhead_or_signature(data)


def test_dues_subsection_is_a_table_caption_anchor():
    from src.table_detector import _is_table_caption_start

    anchor = {
        "text": "Dues to Micro and Small Enterprises",
        "structural": False,
        "top": 140,
    }
    assert _is_table_caption_start(anchor, [anchor], [])


def test_ocr_candidate_uses_the_nearest_local_section_caption():
    from src.table_detector import _nearest_local_caption

    caption = {"text": "B. Movements in Present Value of Obligation", "top": 150, "bottom": 162, "structural": False}
    candidate = {"bbox": (40, 145, 550, 420)}

    assert _nearest_local_caption(candidate, [caption]) == caption["text"]


def test_ocr_candidate_prefers_a_specific_financial_term_from_its_rows():
    from src.table_detector import _specific_ocr_domain_caption

    candidate = {
        "ocr_lines": [
            {"text": "Weighted average number of equity shares 10,000"},
            {"text": "Basic and diluted earning per share (4.85)"},
        ],
    }

    assert _specific_ocr_domain_caption(
        candidate, "Equity Shareholders"
    ) == "earning per share"


def test_repeated_ocr_column_headers_are_not_preferred_over_subsection_captions():
    from src.table_detector import _repeats_adjacent_caption_phrase

    assert _repeats_adjacent_caption_phrase("Plan Assets Total Plan Assets Total")
    assert not _repeats_adjacent_caption_phrase(
        "Employees' Benefit Plans Where There Is Significant Influence"
    )


def test_nested_ocr_candidate_survives_when_its_caption_is_distinct():
    from src.table_detector import _deduplicate

    class Page:
        height = 800

    ocr_candidate = {
        "bbox": (100, 100, 300, 150),
        "strategy": "ocr",
        "score": 0.1,
        "metrics": {"rows": 3, "columns": 3},
        "table_data": [],
        "ocr_title": "Expenditure in foreign currency",
    }
    broad_candidate = {
        "bbox": (0, 0, 500, 700),
        "strategy": "text",
        "score": 0.2,
        "metrics": {"rows": 40, "columns": 8},
        "table_data": [],
    }
    lines = [
        {"text": "Expenditure in foreign currency", "top": 100, "bottom": 112, "bold_ratio": 0.8},
        {"text": "Particulars As at", "top": 116, "bottom": 128},
        {"text": "Royalty 100", "top": 132, "bottom": 144},
    ]

    result = _deduplicate(
        [ocr_candidate, broad_candidate], page_lines=lines, page=Page()
    )
    assert len(result) == 2


def test_primary_statement_merges_aligned_ocr_fragments():
    from src.table_detector import _merge_primary_statement_ocr_fragments

    page_lines = [
        {"text": "BALANCE SHEET AS AT 31 MARCH 2025", "top": 30, "bottom": 45},
    ]
    candidates = [
        {
            "bbox": (40, 80, 500, 220),
            "strategy": "ocr",
            "score": 0.5,
            "metrics": {"rows": 5, "columns": 4},
            "table_data": [],
        },
        {
            "bbox": (44, 260, 502, 430),
            "strategy": "text",
            "score": 0.6,
            "metrics": {"rows": 6, "columns": 5},
            "table_data": [],
        },
    ]

    merged = _merge_primary_statement_ocr_fragments(page_lines, candidates, 595, 842)

    assert len(merged) == 1
    assert tuple(round(value, 1) for value in merged[0]["bbox"]) == (35.7, 22.0, 559.3, 430.0)
    assert merged[0]["_primary_statement_title"] == "BALANCE SHEET"
    assert merged[0]["metrics"]["rows"] == 11


def test_deduplicate_joins_touching_vertical_fragments():
    from src.table_detector import _deduplicate

    def candidate(bbox, rows):
        return {
            "bbox": bbox,
            "strategy": "text",
            "score": 0.5,
            "metrics": {"rows": rows, "columns": 6},
            "table_data": [],
        }

    result = _deduplicate([
        candidate((40, 100, 550, 220), 6),
        candidate((41, 220, 551, 360), 7),
    ])

    assert len(result) == 1
    assert result[0]["bbox"] == (40, 100, 551, 360)
    assert result[0]["metrics"]["rows"] == 13


def test_deduplicate_keeps_touching_tables_separated_by_a_note_heading():
    from src.table_detector import _deduplicate

    def candidate(bbox):
        return {
            "bbox": bbox,
            "strategy": "text",
            "score": 0.5,
            "metrics": {"rows": 5, "columns": 4},
            "table_data": [],
        }

    result = _deduplicate(
        [
            candidate((40, 100, 550, 220)),
            candidate((41, 220, 551, 360)),
        ],
        page_lines=[{"text": "Note 11", "top": 220, "bottom": 232}],
    )

    assert len(result) == 2


def test_deduplicate_merges_overlapping_fragments_with_a_heading_in_the_overlap():
    from src.table_detector import _deduplicate

    def candidate(bbox):
        return {
            "bbox": bbox,
            "strategy": "text",
            "score": 0.5,
            "metrics": {"rows": 5, "columns": 4},
            "table_data": [],
        }

    result = _deduplicate(
        [
            candidate((40, 100, 550, 220)),
            candidate((41, 218, 551, 360)),
        ],
        page_lines=[{"text": "Balance Sheet", "top": 218, "bottom": 232}],
    )

    assert len(result) == 1
    assert result[0]["bbox"] == (40, 100, 551, 360)


def test_deduplicate_prefers_segmented_sections_over_their_broad_source():
    from src.table_detector import _deduplicate

    source_data = [["Particulars", "Amount"], ["Cash", "100"]]

    def candidate(bbox, segmented=False, caption=None):
        item = {
            "bbox": bbox,
            "strategy": "text",
            "score": 0.5,
            "metrics": {"rows": 8, "columns": 2},
            "table_data": source_data,
        }
        if segmented:
            item["segmented"] = True
            item["_section_caption"] = caption
        return item

    result = _deduplicate([
        candidate((40, 100, 550, 400)),
        candidate((40, 100, 550, 240), True, "Current assets"),
        candidate((40, 240, 550, 400), True, "Current liabilities"),
    ])

    assert len(result) == 2
    assert all(item.get("_section_caption") for item in result)


def test_deduplicate_prefers_more_complete_nested_candidate_with_similar_rows():
    from src.table_detector import _deduplicate

    def candidate(bbox, rows, score, segmented=False):
        return {
            "bbox": bbox,
            "strategy": "text",
            "score": score,
            "metrics": {"rows": rows, "columns": 5},
            "table_data": [["Particulars", "Amount"]],
            "segmented": segmented,
        }

    partial = candidate((44.5, 62.1, 547.8, 522.7), 49, 1.47, True)
    complete = candidate((44.5, 62.1, 547.8, 720.9), 51, 1.71)

    result = _deduplicate([partial, complete])

    assert result == [complete]


def test_resolved_deduplication_collapses_nested_continuations_but_keeps_separate_captions():
    from src.table_detector import _deduplicate_resolved_candidates

    def candidate(bbox, rows, title, strategy="text", segmented=False):
        return {
            "bbox": bbox,
            "strategy": strategy,
            "metrics": {"rows": rows, "columns": 5},
            "_resolved_title": title,
            "segmented": segmented,
        }

    partial = candidate((44, 62, 548, 523), 49, "Appendix I", segmented=True)
    complete = candidate((44, 62, 548, 721), 51, "Appendix I")
    separate = candidate((44, 523, 548, 721), 18, "Appendix II")

    result = _deduplicate_resolved_candidates(
        [partial, complete, separate], 842, []
    )

    assert result == [complete, separate]


def test_resolved_deduplication_prefers_native_candidate_over_same_captioned_ocr():
    from src.table_detector import _deduplicate_resolved_candidates

    native = {
        "bbox": (43, 168, 548, 444),
        "strategy": "text",
        "metrics": {"rows": 27, "columns": 8},
        "_resolved_title": "Note 38 : Financial Instruments",
    }
    ocr = {
        "bbox": (45, 201, 547, 314),
        "strategy": "ocr",
        "metrics": {"rows": 11, "columns": 6},
        "_resolved_title": "Note 38 : Financial Instruments",
    }

    assert _deduplicate_resolved_candidates([native, ocr], 842, []) == [native]


def test_resolved_deduplication_drops_broad_candidate_crossing_into_another_note():
    from src.table_detector import _deduplicate_resolved_candidates

    broad = {
        "bbox": (44, 60, 553, 721),
        "strategy": "text",
        "metrics": {"rows": 61, "columns": 15},
        "_resolved_title": "Note 3 : Property, Plant And Equipment",
    }
    next_note_table = {
        "bbox": (44, 207, 547, 254),
        "strategy": "ocr",
        "metrics": {"rows": 4, "columns": 7},
        "_resolved_title": "Note 4 : Intangible Assets",
    }

    result = _deduplicate_resolved_candidates(
        [broad, next_note_table],
        721,
        [{"text": "NOTE 4", "top": 140}],
    )

    assert result == [next_note_table]


def test_failed_section_reanalysis_does_not_clone_a_broad_candidate():
    from src.table_detector import _split_candidates_at_section_anchors

    class EmptyCrop:
        def find_tables(self, table_settings):
            return []

    class Page:
        width = 600
        height = 842

        def crop(self, bbox):
            return EmptyCrop()

    candidate = {
        "bbox": (40, 80, 550, 500),
        "strategy": "text",
        "score": 0.5,
        "metrics": {"rows": 20, "columns": 5},
        "table_data": [["Particulars", "Amount"]],
    }
    lines = [
        {"text": "Note 2", "top": 300, "bottom": 312},
        {"text": "Note 1", "top": 100, "bottom": 112},
    ]

    assert _split_candidates_at_section_anchors(
        Page(), lines, [candidate], 600 * 842
    ) == [candidate]


def test_section_split_can_use_positioned_rows_from_a_broad_table():
    from src.table_detector import _split_candidates_at_section_anchors

    class EmptyCrop:
        def find_tables(self, table_settings):
            return []

    class Page:
        width = 600
        height = 842

        def crop(self, bbox):
            return EmptyCrop()

    first = [
        ["Particulars", "Amount"],
        ["Cash", "100"],
        ["Debt", "50"],
        ["Total", "150"],
    ]
    second = [
        ["Particulars", "Amount"],
        ["Shares", "75"],
        ["Loans", "25"],
        ["Total", "100"],
    ]
    rows = first + second
    candidate = {
        "bbox": (40, 80, 550, 500),
        "strategy": "text",
        "score": 0.5,
        "metrics": {"rows": 8, "columns": 2},
        "table_data": rows,
        "_row_bboxes": [
            (50, 120 + index * 10, 300, 128 + index * 10)
            for index in range(4)
        ] + [
            (50, 320 + index * 10, 300, 328 + index * 10)
            for index in range(4)
        ],
    }
    lines = [
        {"text": "Note 2", "top": 300, "bottom": 312},
        {"text": "Note 1", "top": 100, "bottom": 112},
    ]

    result = _split_candidates_at_section_anchors(
        Page(), lines, [candidate], 600 * 842
    )
    assert len(result) == 2
    assert [item["_section_caption"] for item in result] == ["Note 1", "Note 2"]
    assert [item["metrics"]["rows"] for item in result] == [4, 4]


def test_section_split_can_recover_positioned_rows_after_single_note_boundary():
    from src.table_detector import _split_candidates_at_section_anchors

    class EmptyCrop:
        def find_tables(self, table_settings):
            return []

    class Page:
        width = 600
        height = 842

        def crop(self, bbox):
            return EmptyCrop()

    rows = [
        ["Particulars", "Amount"],
        ["Cash", "100"],
        ["Debt", "50"],
        ["Total", "150"],
        ["Particulars", "Amount"],
        ["Shares", "75"],
        ["Loans", "25"],
        ["Total", "100"],
    ]
    candidate = {
        "bbox": (40, 80, 550, 500),
        "strategy": "text",
        "score": 0.5,
        "metrics": {"rows": 8, "columns": 2},
        "table_data": rows,
        "_row_bboxes": [
            (50, 120 + index * 10, 300, 128 + index * 10)
            for index in range(4)
        ] + [
            (50, 320 + index * 10, 300, 328 + index * 10)
            for index in range(4)
        ],
    }

    result = _split_candidates_at_section_anchors(
        Page(), [{"text": "Note 2", "top": 300, "bottom": 312}],
        [candidate], 600 * 842,
    )

    assert len(result) == 1
    assert result[0]["table_data"] == rows[4:]
    assert result[0]["_section_caption"] == "Note 2"


def test_failed_single_note_crop_keeps_original_candidate():
    from src.table_detector import _split_candidates_at_section_anchors

    class EmptyCrop:
        def find_tables(self, table_settings):
            return []

    class Page:
        width = 600
        height = 842

        def crop(self, bbox):
            return EmptyCrop()

    candidate = {
        "bbox": (40, 80, 550, 500),
        "strategy": "text",
        "score": 0.5,
        "metrics": {"rows": 20, "columns": 5},
        "table_data": [["Particulars", "Amount"]],
    }

    assert _split_candidates_at_section_anchors(
        Page(), [{"text": "Note 2", "top": 300, "bottom": 312}],
        [candidate], 600 * 842,
    ) == [candidate]


def test_deduplicate_joins_continuing_ocr_region_without_new_header():
    from src.table_detector import _deduplicate

    def candidate(bbox, line):
        return {
            "bbox": bbox,
            "strategy": "ocr",
            "score": 0.5,
            "metrics": {"rows": 4, "columns": 3},
            "table_data": [],
            "ocr_title": "Disclosure Schedule",
            "ocr_lines": [{"text": line}],
        }

    first = candidate((40, 100, 500, 220), "Particulars As at 2025 Amount")
    continuation = candidate((42, 226, 498, 300), "Interest due for the period")
    separate = candidate((42, 226, 498, 300), "Particulars As at 2025 Amount")

    assert len(_deduplicate([first, continuation])) == 1
    first = candidate((40, 100, 500, 220), "Particulars As at 2025 Amount")
    assert len(_deduplicate([first, separate])) == 2


def test_deduplicate_preserves_ocr_sections_with_distinct_captions():
    from src.table_detector import _deduplicate

    def candidate(bbox, caption):
        return {
            "bbox": bbox,
            "strategy": "ocr",
            "score": 0.5,
            "metrics": {"rows": 4, "columns": 3},
            "table_data": [],
            "ocr_title": "Disclosure Schedule",
            "_section_caption": caption,
            "ocr_lines": [{"text": "Amount and particulars"}],
        }

    result = _deduplicate([
        candidate((40, 100, 500, 220), "Investments"),
        candidate((42, 220, 498, 300), "Loans"),
    ])

    assert len(result) == 2


def test_footer_signoff_grid_is_not_a_table():
    from src.table_detector import _looks_like_footer_candidate

    candidate = {"bbox": (300, 700, 500, 780)}
    footer_lines = [
        {"text": "In terms of our attached report of even date", "top": 690},
        {"text": "Chartered Accountants Partner", "top": 740},
    ]
    financial_lines = [
        {"text": "Particulars Note Amount", "top": 700},
        {"text": "Cash 1 1000", "top": 740},
    ]

    assert _looks_like_footer_candidate(candidate, footer_lines, 842)
    assert not _looks_like_footer_candidate(candidate, financial_lines, 842)


def test_table_caption_anchor_requires_local_tabular_evidence():
    from src.table_detector import _is_table_caption_start

    caption = {"text": "Investment Strategy", "top": 100, "bottom": 112, "structural": False}
    narrative_lines = [
        {"text": "The company's investment strategy is implemented within the framework.", "top": 120},
        {"text": "The plans expose the company to a number of actuarial risks.", "top": 145},
    ]
    assert not _is_table_caption_start(caption, [caption], narrative_lines)

    table_lines = [
        {"text": "As at 31 March 2025", "top": 120},
        {"text": "Particulars Amount", "top": 135},
        {"text": "Investment in shares 1,250", "top": 150},
    ]
    assert _is_table_caption_start(caption, [caption], table_lines)


def test_primary_statement_merge_stops_at_numbered_note():
    from src.table_detector import _merge_primary_statement_ocr_fragments

    page_lines = [
        {"text": "BALANCE SHEET", "top": 30, "bottom": 45},
        {"text": "Note 3 Property Plant and Equipment", "top": 300, "bottom": 315},
    ]
    candidates = [
        {
            "bbox": (40, 80, 500, 220),
            "strategy": "ocr",
            "score": 0.5,
            "metrics": {"rows": 5, "columns": 4},
            "table_data": [],
        },
        {
            "bbox": (44, 330, 502, 430),
            "strategy": "ocr",
            "score": 0.6,
            "metrics": {"rows": 6, "columns": 5},
            "table_data": [],
        },
    ]

    assert _merge_primary_statement_ocr_fragments(page_lines, candidates, 595, 842) == candidates


def test_primary_statement_merge_joins_aligned_native_fragments():
    from src.table_detector import _merge_primary_statement_ocr_fragments

    page_lines = [
        {
            "text": "STATEMENT OF PROFIT AND LOSS",
            "top": 30,
            "bottom": 45,
        },
    ]
    candidates = [
        {
            "bbox": (40, 80, 500, 220),
            "strategy": "text",
            "score": 0.5,
            "metrics": {"rows": 5, "columns": 4},
            "table_data": [],
        },
        {
            "bbox": (44, 250, 502, 430),
            "strategy": "text",
            "score": 0.6,
            "metrics": {"rows": 6, "columns": 5},
            "table_data": [],
        },
    ]

    merged = _merge_primary_statement_ocr_fragments(
        page_lines, candidates, 595, 842, allow_native=True
    )

    assert len(merged) == 1
    assert merged[0]["strategy"] == "text"
    assert merged[0]["metrics"]["rows"] == 11
    assert merged[0]["_primary_statement_title"] == "STATEMENT OF PROFIT AND LOSS"


def test_adjacent_fragments_merge_only_when_the_same_subsection_bounds_them():
    from src.table_detector import _merge_captioned_fragments

    def candidate(bbox):
        return {
            "bbox": bbox,
            "strategy": "ocr",
            "metrics": {"rows": 4, "columns": 5},
            "_resolved_title": "Note 40 : Defined Benefits Plans – B. Movements",
        }

    section = [
        {
            "text": "B. Movements in Present Value of Obligation",
            "top": 90,
            "bottom": 102,
        }
    ]
    fragments = [
        candidate((42, 18, 552, 129)),
        candidate((45, 138, 549, 466)),
    ]
    merged = _merge_captioned_fragments(fragments, section, 720)

    assert len(merged) == 1
    assert merged[0]["bbox"] == (42, 18, 552, 466)

    same_title_separate_tables = [
        candidate((42, 18, 552, 129)),
        candidate((45, 138, 549, 466)),
    ]
    assert len(
        _merge_captioned_fragments(same_title_separate_tables, [], 720)
    ) == 2


def test_note_schedule_lettered_fragments_remain_separate():
    from src.table_detector import _merge_captioned_fragments

    candidates = [
        {
            "bbox": (45, 361, 547, 392),
            "strategy": "ocr",
            "metrics": {"rows": 3, "columns": 3},
            "_resolved_title": "Note 6 : Investments",
        },
        {
            "bbox": (43, 582, 547, 720),
            "strategy": "ocr",
            "metrics": {"rows": 8, "columns": 9},
            "_resolved_title": "Note 6 : Investments",
        },
    ]
    sections = [
        {"text": "A. Equity instruments", "top": 340, "bottom": 352},
        {"text": "B. Other instruments", "top": 395, "bottom": 407},
        {"text": "C. Other instruments", "top": 516, "bottom": 528},
    ]

    merged = _merge_captioned_fragments(candidates, sections, 720)

    assert len(merged) == 2


def test_deduplicate_resolved_candidates_merges_lines_and_text_same_table():
    from src.table_detector import _deduplicate_resolved_candidates

    candidates = [
        {
            "bbox": (45, 120, 545, 450),
            "strategy": "lines",
            "metrics": {"rows": 12, "columns": 4},
            "_resolved_title": "Note 34 : Other Expenses",
        },
        {
            "bbox": (42, 115, 548, 455),
            "strategy": "text",
            "metrics": {"rows": 14, "columns": 4},
            "_resolved_title": "Note 34 : Other Expenses",
        },
    ]
    deduped = _deduplicate_resolved_candidates(candidates, 842, [])
    assert len(deduped) == 1
    assert deduped[0]["metrics"]["rows"] == 14


def test_deduplicate_resolved_candidates_preserves_separate_tables_same_title():
    from src.table_detector import _deduplicate_resolved_candidates

    candidates = [
        {
            "bbox": (45, 100, 545, 250),
            "strategy": "lines",
            "metrics": {"rows": 5, "columns": 4},
            "_resolved_title": "Note 6 : Investments",
        },
        {
            "bbox": (45, 400, 545, 600),
            "strategy": "lines",
            "metrics": {"rows": 6, "columns": 4},
            "_resolved_title": "Note 6 : Investments",
        },
    ]
    deduped = _deduplicate_resolved_candidates(candidates, 842, [])
    assert len(deduped) == 2


def test_looks_like_header_candidate_filters_banner_grid():
    from src.table_detector import _looks_like_header_candidate

    banner_candidate = {
        "bbox": (42.87, 19.31, 552.44, 99.82),
        "strategy": "ocr",
        "metrics": {"rows": 4, "columns": 5},
        "ocr_lines": [
            {"text": "106 Standalone Overview Reports Financial Statements 107"},
            {"text": "NOTES to the financial statements for the year ended 31st March, 2018 (Contd.)"},
            {"text": "(All amounts in crores, unless otherwise stated)"},
        ],
    }
    page_lines = [
        {"top": 19.2, "bottom": 27.7, "text": "106 Standalone Overview Reports Financial Statements 107"},
        {"top": 41.3, "bottom": 61.3, "text": "NOTES to the financial statements"},
        {"top": 78.9, "bottom": 87.7, "text": "(All amounts in crores, unless otherwise stated)"},
    ]
    assert _looks_like_header_candidate(banner_candidate, page_lines, 842.0)


def test_looks_like_header_candidate_preserves_genuine_top_table():
    from src.table_detector import _looks_like_header_candidate

    top_table = {
        "bbox": (45.0, 50.0, 550.0, 130.0),
        "strategy": "lines",
        "metrics": {"rows": 4, "columns": 4},
        "table_data": [
            ["Particulars", "Note", "2018", "2017"],
            ["Revenue", "1", "1,000", "900"],
            ["Expenses", "2", "600", "550"],
            ["Profit", "3", "400", "350"],
        ],
    }
    page_lines = [
        {"top": 50.0, "bottom": 65.0, "text": "Particulars Note 2018 2017"},
        {"top": 70.0, "bottom": 85.0, "text": "Revenue 1 1,000 900"},
    ]
    assert not _looks_like_header_candidate(top_table, page_lines, 842.0)


def test_internal_row_categories_rejected_as_captions():
    from src.title_extractor import _is_plausible_caption

    assert not _is_plausible_caption("Liabilities at fair value")
    assert not _is_plausible_caption("Assets at fair value")
    assert not _is_plausible_caption("Financial assets at amortised cost")
    assert not _is_plausible_caption("Fair value through profit and loss")
    assert not _is_plausible_caption("Investments measured at fair value")
    assert _is_plausible_caption("C. Fair Value Hierarchy")
    assert _is_plausible_caption("B. Movements in Present Value of Obligation and Fair Value of Plan Assets")


def test_deduplicate_prefers_authoritative_native_over_ocr_fragment():
    from src.table_detector import _deduplicate

    ocr_fragment = {
        "bbox": (43.2, 637.9, 546.9, 720.3),
        "strategy": "ocr",
        "score": 0.5,
        "metrics": {"rows": 3, "columns": 4},
        "table_data": [],
        "ocr_title": "Untitled table",
    }
    authoritative_native = {
        "bbox": (44.5, 308.2, 547.4, 667.6),
        "strategy": "text",
        "score": 0.79,
        "metrics": {"rows": 34, "columns": 5},
        "table_data": [["Row", "A", "B", "C", "D"]] * 34,
    }
    result = _deduplicate([ocr_fragment, authoritative_native])
    assert len(result) == 1
    assert result[0]["strategy"] == "text"
    assert result[0]["metrics"]["rows"] == 34


def test_ocr_regions_split_at_date_schedule_headings():
    from src.ocr_processor import detect_ocr_table_regions

    def line(text, y, xs):
        words = [{"text": token, "x": x, "y": y, "w": 20, "h": 10}
                 for token, x in zip(text.split(), xs)]
        return {
            "text": text,
            "x": min(xs),
            "y": y,
            "right": max(xs) + 20,
            "bottom": y + 10,
            "word_count": len(words),
            "words": words,
        }

    layout = {
        "image_size": (600, 1000),
        "lines": [
            line("As at 31st March, 2018", 200, [10, 300, 500]),
            line("Item A 10 20", 230, [10, 300, 500]),
            line("Item B 30 40", 260, [10, 300, 500]),
            line("Item C 50 60", 290, [10, 300, 500]),
            line("As at 31st March, 2017", 350, [10, 300, 500]),
            line("Item A 15 25", 380, [10, 300, 500]),
            line("Item B 35 45", 410, [10, 300, 500]),
            line("Item C 55 65", 440, [10, 300, 500]),
        ],
    }

    regions = detect_ocr_table_regions(layout)
    assert len(regions) == 2
    assert regions[0]["bbox"][1] == 200
    assert regions[1]["bbox"][1] == 350

