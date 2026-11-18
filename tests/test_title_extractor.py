from src.title_extractor import extract_table_title


class FakePage:
    def extract_text_lines(self, **kwargs):
        return [
            {"top": 20, "text": "Example Company Private Limited"},
            {"top": 48, "text": "BALANCE SHEET AS AT 31 MARCH 2025"},
            {"top": 90, "text": "Particulars Note Amount"},
        ]


def test_caption_is_selected_instead_of_company_header():
    title = extract_table_title(FakePage(), (10, 70, 590, 760))
    assert title == "BALANCE SHEET AS AT 31 MARCH 2025"


def test_missing_caption_returns_explicit_fallback():
    class NoCaptionPage:
        def extract_text_lines(self, **kwargs):
            return [{"top": 20, "text": "Example Company Private Limited"}]

    assert extract_table_title(NoCaptionPage(), (10, 70, 590, 760)) == "Untitled table"


def test_narrative_sentence_is_not_used_as_caption():
    class NarrativePage:
        def extract_text_lines(self, **kwargs):
            return [{"top": 30, "text": "Goodwill is initially recognised based on the accounting policy for business combinations"}]

    assert extract_table_title(NarrativePage(), (10, 60, 590, 760)) == "Untitled table"


def test_generic_notes_banner_is_not_used_as_caption():
    class NotesBannerPage:
        height = 842

        def extract_text(self):
            return "NOTES to the financial statements"

        def extract_text_lines(self, **kwargs):
            return [
                {"top": 30, "text": "NOTES to the financial statements"},
                {"top": 90, "text": "Particulars Note Amount"},
            ]

    assert extract_table_title(NotesBannerPage(), (10, 70, 590, 760)) == "Untitled table"


def test_capital_account_heading_is_recognized():
    class CapitalPage:
        def extract_text_lines(self, **kwargs):
            return [{"top": 90, "text": "CAPITAL ACCOUNT FOR THE PERIOD ENDED 31.03.2023"}]

    assert extract_table_title(CapitalPage(), (10, 70, 590, 760)) == "CAPITAL ACCOUNT FOR THE PERIOD ENDED 31.03.2023"


def test_note_number_heading_is_recognized():
    class NotePage:
        def extract_text_lines(self, **kwargs):
            return [
                {"top": 30, "text": "NOTES to the financial statements"},
                {"top": 78, "text": "NOTE 3 : PROPERTY, PLANT AND EQUIPMENT"},
                {"top": 120, "text": "Gross Block"},
            ]

    assert extract_table_title(NotePage(), (10, 110, 590, 760)) == "NOTE 3 : PROPERTY, PLANT AND EQUIPMENT"


def test_additional_information_heading_is_recognized():
    class DisclosurePage:
        def extract_text_lines(self, **kwargs):
            return [{"top": 35, "text": "13 Additional Information and Disclosures"}]

    assert extract_table_title(DisclosurePage(), (10, 80, 590, 760)) == "13 Additional Information and Disclosures"


def test_primary_cash_flow_heading_beats_lettered_subsection():
    class CashFlowPage:
        def extract_text_lines(self, **kwargs):
            return [
                {"top": 30, "text": "CASH FLOW STATEMENT"},
                {"top": 110, "text": "(C) CASH FLOW FROM FINANCING ACTIVITIES"},
            ]

    assert extract_table_title(CashFlowPage(), (10, 100, 590, 760)) == "CASH FLOW STATEMENT"


def test_revenue_from_operations_heading_is_recognized():
    class RevenuePage:
        def extract_text_lines(self, **kwargs):
            return [
                {"top": 20, "text": "Notes 10"},
                {"top": 35, "text": "Revenue From Operation"},
            ]

    assert extract_table_title(RevenuePage(), (10, 65, 590, 760)) == "Revenue From Operation"


def test_distant_note_heading_is_not_inherited_by_a_later_table():
    class DistantHeadingPage:
        height = 842

        def extract_text(self):
            return "NOTES to the financial statements"

        def extract_text_lines(self, **kwargs):
            return [
                {"top": 30, "text": "NOTE 3 : PROPERTY, PLANT AND EQUIPMENT"},
                {"top": 400, "text": "Particulars Amount"},
            ]

    assert extract_table_title(DistantHeadingPage(), (10, 400, 590, 760)) == "Untitled table"


def test_ocr_heading_can_supply_a_local_caption():
    class OcrHeadingPage:
        height = 842

        def extract_text_lines(self, **kwargs):
            return [{"top": 30, "text": "NOTE 2 : SHARE CAPITAL"}]

    title = extract_table_title(
        OcrHeadingPage(),
        (10, 350, 590, 760),
        additional_lines=[{
            "text": "NOTE 3 : RESERVES AND SURPLUS",
            "top": 310,
            "bottom": 322,
            "confidence": 80,
        }],
    )
    assert title == "NOTE 3 : RESERVES AND SURPLUS"


def test_local_note_scope_excludes_a_prior_section_caption():
    class NoteBoundaryPage:
        height = 842

        def extract_text_lines(self, **kwargs):
            return [
                {"top": 90, "text": "D. Tax Assets and Liabilities"},
                {"top": 160, "text": "NOTE 10 : OTHER NON-CURRENT ASSETS"},
            ]

    title = extract_table_title(
        NoteBoundaryPage(), (10, 170, 590, 400), min_y=158
    )
    assert title == "NOTE 10 : OTHER NON-CURRENT ASSETS"


def test_low_confidence_ocr_caption_is_preserved_when_directly_above_a_table():
    class OcrPage:
        height = 842

        def extract_text_lines(self, **kwargs):
            return []

    title = extract_table_title(
        OcrPage(),
        (10, 100, 590, 400),
        additional_lines=[
            {"text": "EamingPershares", "top": 90, "bottom": 96, "confidence": 39},
            {
                "text": "Particulars As at 2025 Amount",
                "top": 100,
                "bottom": 112,
                "confidence": 94,
            },
        ],
    )
    assert title == "Earning Per shares"


def test_ocr_repair_splits_fused_financial_caption_words():
    from src.title_extractor import repair_ocr_text

    assert repair_ocr_text("EamingPershares") == "Earning Per shares"


def test_ocr_repair_recognizes_long_loans_domain_words():
    from src.title_extractor import repair_ocr_text

    assert repair_ocr_text("Lonll Term Loans Advances") == "Long Term Loans Advances"


def test_ocr_repair_corrects_multi_confusion_financial_heading_without_rewriting_common_words():
    from src.title_extractor import repair_ocr_text

    assert repair_ocr_text(
        "13 Ac1<j1honal mlorma11on and disclosures"
    ) == "13 Additional Information and disclosures"
    assert repair_ocr_text("Payments to the auditor") == "Payments to the auditor"
    assert repair_ocr_text(
        "B. Movements in Present Value of Obligation and Fair Value of Plan Assets"
    ) == "B. Movements in Present Value of Obligation and Fair Value of Plan Assets"
    assert repair_ocr_text("Management and Measurement") == "Management and Measurement"
    assert repair_ocr_text("Expenditure in foreign currency") == "Expenditure in foreign currency"


def test_primary_heading_inside_top_of_table_candidate_is_associated():
    class TopRegionPage:
        height = 792

        def extract_text(self):
            return ""

        def extract_text_lines(self, **kwargs):
            return [
                {"top": 131, "bottom": 142, "text": "BALANCE SHEET AS ON 31.03.2023"},
                {"top": 143, "bottom": 154, "text": "Liabilities Amount Assets Amount"},
            ]

    assert extract_table_title(
        TopRegionPage(), (53, 56, 552, 521)
    ) == "BALANCE SHEET AS ON 31.03.2023"


def test_subsection_caption_inside_table_region_beats_parent_note():
    class SubsectionPage:
        height = 842

        def extract_text(self):
            return "NOTES to the financial statements"

        def extract_text_lines(self, **kwargs):
            return [
                {"top": 90, "bottom": 104, "text": "NOTE 40 : DEFINED BENEFIT PLANS"},
                {
                    "top": 105,
                    "bottom": 117,
                    "text": "Particulars Amount",
                },
                {
                    "top": 485,
                    "bottom": 499,
                    "text": "C. Statement of Profit and Loss",
                },
            ]

    assert extract_table_title(
        SubsectionPage(), (43, 468, 549, 720), min_y=90
    ) == "C. Statement of Profit and Loss"


def test_person_name_and_amount_row_are_not_plausible_captions():
    from src.title_extractor import _is_plausible_caption

    assert not _is_plausible_caption("O. P. Bhatt")
    assert not _is_plausible_caption("Purchase of Fixed Assets - 0")
    assert not _is_plausible_caption("Sale of Fixed Assets 27")
    assert _is_plausible_caption(
        "d) Details of equity shares held by shareholders holding more than "
        "5% of the aggregate shares in the Company"
    )
    assert _is_plausible_caption("D. Assets")
    assert _is_plausible_caption("E. Assumptions")


def test_wrapped_bold_subsection_caption_uses_its_first_column_continuation():
    def positioned_chars(text, start_x, right_column=None):
        chars = []
        x = start_x
        for index, character in enumerate(text):
            if right_column is not None and index == right_column:
                x += 16
            width = 3.0 if character != " " else 2.0
            chars.append({
                "text": character,
                "x0": x,
                "x1": x + width,
                "size": 8.0,
                "fontname": "Arial-Bold",
            })
            x += width
        return chars

    left = "there is significant influence"
    right = "The Hind Lever Pension Fund"
    line_chars = positioned_chars(left + right, 84.0, len(left))

    class WrappedCaptionPage:
        height = 842

        def extract_text(self):
            return "NOTES to the financial statements"

        def extract_text_lines(self, **kwargs):
            return [
                {
                    "text": "(v) Employees' Benefit Plans where : Hind Lever Gratuity Fund",
                    "top": 546,
                    "bottom": 556,
                    "x0": 64,
                    "x1": 328,
                    "chars": positioned_chars(
                        "(v) Employees' Benefit Plans where : Hind Lever Gratuity Fund",
                        64.0,
                        37,
                    ),
                },
                {
                    "text": left + " " + right,
                    "top": 557,
                    "bottom": 567,
                    "x0": 84,
                    "x1": 345,
                    "chars": line_chars,
                },
            ]

    title = extract_table_title(
        WrappedCaptionPage(), (64, 545, 536, 720), min_y=90
    )
    assert "Employees' Benefit Plans where there is significant influence" in title


def test_column_headers_and_grid_rows_are_rejected_as_captions():
    from src.title_extractor import _is_plausible_caption, _clean

    assert not _is_plausible_caption("Goodwill Brands/ Knowhow And Computer Total")
    assert not _is_plausible_caption("A Gon Total Plan Assets A Pen Total")
    assert not _is_plausible_caption("2|Non-Current Assets")
    assert _clean("Property, Plan And Equipment") == "Property, Plant And Equipment"


def test_description_is_not_corrupted_to_depreciation():
    from src.title_extractor import repair_ocr_text, _clean

    assert repair_ocr_text("Description of relationship") == "Description of relationship"
    repaired = repair_ocr_text("Descriotion of relationshl o")
    assert "Depreciation" not in repaired
    assert "Description" in repaired
    cleaned = _clean("Descriotion of relationshl o", is_ocr=True)
    assert "Depreciation" not in cleaned
    assert "Description" in cleaned


def test_earning_per_shares_normalization_and_plausibility():
    from src.title_extractor import _clean, _is_plausible_caption, normalize_title_case, KNOWN_SCHEDULE_HEADING

    cleaned = _clean("Eamlna Per sharos", is_ocr=True)
    norm = normalize_title_case(cleaned)
    assert norm == "Earning Per Shares"
    assert _is_plausible_caption(norm)
    assert bool(KNOWN_SCHEDULE_HEADING.search(norm))

    cleaned_compound = _clean("EamingPershares", is_ocr=True)
    norm_compound = normalize_title_case(cleaned_compound)
    assert norm_compound == "Earning Per Shares"

