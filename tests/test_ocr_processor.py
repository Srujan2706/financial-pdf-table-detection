from src.ocr_processor import detect_ocr_table_regions, extract_ocr_caption

def test_ocr_finds_aligned_table_and_caption():
    def line(text, y, xs):
        words = [{"text": t, "x": x, "y": y, "w": 20, "h": 10} for t, x in zip(text.split(), xs)]
        return {"text": text, "x": min(xs), "y": y, "right": max(xs) + 20,
                "bottom": y + 10, "word_count": len(words), "words": words}
    layout = {"lines": [
        line("BALANCE SHEET AS AT 2025", 10, [10, 40, 80, 100, 130]),
        line("Particulars Note Amount", 50, [10, 300, 500]),
        line("Cash 1 1000", 80, [10, 300, 500]),
        line("Debt 2 500", 110, [10, 300, 500]),
        line("Equity 3 1500", 140, [10, 300, 500]),
    ]}
    regions = detect_ocr_table_regions(layout)
    assert len(regions) == 1
    assert regions[0]["rows"] == 5
    assert "BALANCE SHEET" in extract_ocr_caption(layout, regions[0]["bbox"])


def test_ocr_retains_sparse_table_with_two_numeric_rows():
    def line(text, y, xs):
        words = [{"text": t, "x": x, "y": y, "w": 20, "h": 10} for t, x in zip(text.split(), xs)]
        return {"text": text, "x": min(xs), "y": y, "right": max(xs) + 20,
                "bottom": y + 10, "word_count": len(words), "words": words}

    layout = {"lines": [
        line("Particulars Note Amount", 10, [10, 300, 500]),
        line("Cash 1 1000", 30, [10, 300, 500]),
        line("Debt 2 500", 50, [10, 300, 500]),
        line("Equity Total Amount", 70, [10, 300, 500]),
    ]}
    regions = detect_ocr_table_regions(layout)
    assert len(regions) == 1


def test_ocr_retains_non_numeric_financial_schedule_with_headers():
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
        "image_size": (600, 500),
        "lines": [
            line("Particulars As at 2025 As at 2024", 10, [10, 300, 500, 530]),
            line("Royalty N N", 30, [10, 300, 500]),
            line("Know how I I", 50, [10, 300, 500]),
            line("Interest L L", 70, [10, 300, 500]),
        ],
    }

    regions = detect_ocr_table_regions(layout)

    assert len(regions) == 1
    assert regions[0]["rows"] == 4


def test_ocr_rejects_paragraph_like_runs():
    def line(text, y, xs):
        words = [{"text": t, "x": x, "y": y, "w": 20, "h": 10} for t, x in zip(text.split(), xs)]
        return {"text": text, "x": min(xs), "y": y, "right": max(xs) + 20,
                "bottom": y + 10, "word_count": len(words), "words": words}

    long_text = "The company has audited the accompanying financial statements and the notes thereto"
    layout = {"lines": [
        line(long_text, 10, list(range(10, 10 + 20 * len(long_text.split()), 20))),
        line(long_text, 30, list(range(10, 10 + 20 * len(long_text.split()), 20))),
        line(long_text, 50, list(range(10, 10 + 20 * len(long_text.split()), 20))),
        line(long_text, 70, list(range(10, 10 + 20 * len(long_text.split()), 20))),
    ]}
    assert detect_ocr_table_regions(layout) == []


def test_ocr_rejects_aligned_prose_with_numeric_references():
    def line(text, y, xs):
        words = [{"text": t, "x": x, "y": y, "w": 20, "h": 10} for t, x in zip(text.split(), xs)]
        return {"text": text, "x": min(xs), "y": y, "right": max(xs) + 20,
                "bottom": y + 10, "word_count": len(words), "words": words}

    narrative = [
        "NOTE 40 Defined Benefit Plans",
        "Refer note 2.4 for accounting policy on Employee Benefits",
        "Retirement Benefit Plans of the Company include Gratuity and Pension",
        "Gratuity is funded through investments with an insurance service provider",
        "Pension for most employees is managed through a trust investments",
    ]
    layout = {"lines": [
        line(text, i * 20, list(range(10, 10 + 20 * len(text.split()), 20)))
        for i, text in enumerate(narrative)
    ]}
    assert detect_ocr_table_regions(layout) == []


def test_ocr_rejects_signature_blocks():
    def line(text, y, xs):
        words = [{"text": t, "x": x, "y": y, "w": 20, "h": 10} for t, x in zip(text.split(), xs)]
        return {"text": text, "x": min(xs), "y": y, "right": max(xs) + 20,
                "bottom": y + 10, "word_count": len(words), "words": words}

    layout = {"lines": [
        line("Place Kolkata Date 2025", 10, [10, 100, 200, 300]),
        line("For and on behalf of the Board", 30, [10, 100, 200, 300, 400, 500]),
        line("Chartered Accountants Partner", 50, [10, 100, 200]),
        line("Membership No 12345", 70, [10, 100, 200]),
    ]}
    assert detect_ocr_table_regions(layout) == []


def test_ocr_drops_unstructured_prose_and_short_footer_grids():
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
            line("Particulars Note Amount", 100, [10, 300, 500]),
            line("Cash 1 1000", 130, [10, 300, 500]),
            line("Debt 2 500", 160, [10, 300, 500]),
            line("Equity 3 1500", 190, [10, 300, 500]),
            line(
                "The reported figures are subject to confirmation and reconciliation from the respective parties at the end of the current financial year",
                230,
                list(range(10, 10 + 20 * 20, 20)),
            ),
            line("Director A 12345", 850, [10, 300, 500]),
            line("Director B 67890", 880, [10, 300, 500]),
            line("Accountant C 54321", 910, [10, 300, 500]),
            line("Partner D 98765", 940, [10, 300, 500]),
        ],
    }

    regions = detect_ocr_table_regions(layout)

    assert len(regions) == 1
    assert regions[0]["bbox"][1] == 100


def test_ocr_splits_financial_schedules_without_splitting_narrative_heading():
    def line(text, y, xs):
        words = [
            {"text": token, "x": x, "y": y, "w": 20, "h": 10}
            for token, x in zip(text.split(), xs)
        ]
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
        "image_size": (600, 500),
        "lines": [
            line("Particulars Note Amount", 10, [10, 300, 500]),
            line("Cash 1 100", 30, [10, 300, 500]),
            line("Debt 2 50", 50, [10, 300, 500]),
            line("Equity 3 150", 70, [10, 300, 500]),
            line("Payments to the auditor", 110, [10, 300, 500]),
            line("Particulars As at 2025 Amount", 130, [10, 300, 500]),
            line("Audit fees 100 100", 150, [10, 300, 500]),
            line("Consulting fees 50 50", 170, [10, 300, 500]),
            line("Travel fees 40 40", 190, [10, 300, 500]),
            line("Investment Strategy", 220, [10, 100]),
            line(
                "The company's investment strategy is implemented within the framework",
                240,
                list(range(10, 10 + 20 * 10, 20)),
            ),
            line(
                "The plans expose the company to actuarial and market risks",
                260,
                list(range(10, 10 + 20 * 10, 20)),
            ),
            line(
                "The company has established controls and governance requirements",
                280,
                list(range(10, 10 + 20 * 10, 20)),
            ),
            line(
                "These measures are reviewed periodically by management",
                300,
                list(range(10, 10 + 20 * 8, 20)),
            ),
        ],
    }

    regions = detect_ocr_table_regions(layout)

    assert len(regions) == 2
    assert "Payments to the auditor" in extract_ocr_caption(layout, regions[1]["bbox"])


def test_ocr_keeps_sparse_schedule_when_its_header_precedes_the_caption():
    def line(text, y, xs):
        words = [
            {"text": token, "x": x, "y": y, "w": 20, "h": 10}
            for token, x in zip(text.split(), xs)
        ]
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
        "image_size": (600, 500),
        "lines": [
            line("Particulars Note Amount", 10, [10, 300, 500]),
            line("Cash 1 100", 30, [10, 300, 500]),
            line("Debt 2 50", 50, [10, 300, 500]),
            line("Equity 3 150", 70, [10, 300, 500]),
            line("As at 2025 As at 2024", 110, [300, 500, 300, 500]),
            line("Payments to the auditor", 120, [10, 100, 200, 300]),
            line("Audit fees 100 50", 140, [10, 300, 500]),
            line("Note 3", 180, [10, 100]),
        ],
    }

    regions = detect_ocr_table_regions(layout)

    assert len(regions) == 2
    assert "Payments to the auditor" in extract_ocr_caption(layout, regions[1]["bbox"])


def test_ocr_does_not_discard_a_long_shareholder_table_header():
    def line(text, y, xs):
        words = [
            {"text": token, "x": x, "y": y, "w": 20, "h": 10}
            for token, x in zip(text.split(), xs)
        ]
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
        "image_size": (600, 400),
        "lines": [
            line("2.2 The details of shareholders holding more than 5% of Equity Shares",
                 10, [10, 30, 50, 70, 90, 110, 130, 150, 170, 190, 210, 230, 250]),
            line("As at 31 March 2022 As at 31 March 2021",
                 30, [10, 30, 50, 70, 90, 210, 230, 250]),
            line("Name of shareholders No. of Shares % of Holding No. of Shares % of Holding",
                 50, [10, 30, 50, 70, 210, 230, 250, 280, 210, 230, 250, 280, 210, 230, 250]),
            line("held held", 70, [210, 280]),
            line("as 50.00 Pd", 90, [10, 210, 280]),
        ],
    }

    regions = detect_ocr_table_regions(layout)
    assert len(regions) == 1
    assert regions[0]["rows"] >= 2
    assert any("Name of shareholders" in line["text"] for line in regions[0]["ocr_lines"])


def test_ocr_caption_selection_rejects_a_distant_previous_heading():
    layout = {
        "lines": [
            {"text": "Details of related parties", "y": 100, "bottom": 112},
        ],
    }

    assert extract_ocr_caption(layout, (20, 400, 500, 500)) == "Untitled table"


def test_ocr_caption_ignores_table_rows_with_multiple_amounts():
    layout = {
        "lines": [
            {"text": "NOTE 4 : INTANGIBLE ASSETS", "y": 10, "bottom": 22},
            {
                "text": "Acquisitions Through Business Combination 0 311 59 - 370",
                "y": 80,
                "bottom": 92,
            },
        ],
    }

    assert extract_ocr_caption(layout, (20, 100, 500, 200)) == (
        "NOTE 4 : INTANGIBLE ASSETS"
    )


def test_ocr_caption_can_be_inside_the_top_of_its_table_region():
    layout = {
        "lines": [
            {"text": "Payments to the auditor", "y": 100, "bottom": 130},
            {"text": "As at 31 March 2025", "y": 135, "bottom": 147},
        ],
    }

    assert extract_ocr_caption(layout, (20, 110, 500, 200)) == "Payments to the auditor"


def test_ocr_caption_ignores_lettered_rows_inside_a_table():
    layout = {
        "lines": [
            {"text": "Reserves and Surplus", "y": 80, "bottom": 92},
            {"text": "(b) Surplus in Statement of Profit and Loss", "y": 100, "bottom": 112},
        ],
    }

    assert extract_ocr_caption(layout, (20, 115, 500, 300)) == "Reserves and Surplus"


def test_ocr_keeps_single_word_rows_below_a_financial_header():
    def line(text, y, xs):
        words = [
            {"text": token, "x": x, "y": y, "w": 20, "h": 10}
            for token, x in zip(text.split(), xs)
        ]
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
        "image_size": (600, 300),
        "lines": [
            line("Expenditure in foreign currency As at 2025 Amount",
                 10, [10, 30, 50, 70, 90, 300, 330, 500]),
            line("Royalty", 30, [10]),
            line("Know how 100", 50, [10, 300, 500]),
            line("Interest 200", 70, [10, 300, 500]),
            line("Other 300", 90, [10, 300, 500]),
        ],
    }

    regions = detect_ocr_table_regions(layout)
    assert len(regions) == 1
    assert any(line["text"] == "Royalty" for line in regions[0]["ocr_lines"])


def test_ocr_rejects_date_led_narrative_fragments_without_table_headers():
    def line(text, y, xs):
        words = [
            {"text": token, "x": x, "y": y, "w": 20, "h": 10}
            for token, x in zip(text.split(), xs)
        ]
        return {
            "text": text,
            "x": min(xs),
            "y": y,
            "right": max(xs) + 20,
            "bottom": y + 10,
            "word_count": len(words),
            "words": words,
        }

    texts = [
        "At 31st March 2018 the investments in debt",
        "mutual funds amounts to 1,830 crores",
        "These are exposed to price risk",
        "At 31st March 2017 the investments were",
        "also exposed to similar market risks",
    ]
    layout = {
        "image_size": (600, 500),
        "lines": [
            line(text, index * 20, [10, 110, 210, 310, 410][:len(text.split())])
            for index, text in enumerate(texts)
        ],
    }

    assert detect_ocr_table_regions(layout) == []
