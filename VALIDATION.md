# Validation & Verification Report

This document records the automated validation results, regression metrics, and architectural verification of the Financial PDF Table Detection & Title Extraction pipeline.

The report covers automated unit testing, output validation, physical table detection across six evaluated PDF documents, and verification of key processing features.

---

## 1. Automated Test Suite

The automated test suite verifies individual application components, including page classification, line/text grid detection, bounding box metrics, OCR fallback, title extraction, delimiter handling, and export serialization.

### Test Execution

Run the following command from the project root directory:

```bash
python -m pytest
```

### Test Results

- **Total Tests:** 84
- **Passed:** 84
- **Failed:** 0
- **Warnings:** 0
- **Execution Time:** Approximately 1.3 seconds

<badge color="success">84/84 tests passed</badge>

### Component Coverage

- `tests/test_title_extractor.py`: Structural note patterns, lettered subsections, OCR repair safeguards, delimiter balancing, and financial domain matching.
- `tests/test_detector_helpers.py`: Bounding box geometry, IoU overlap calculation, cell occupancy, column stability, and table metric scoring.
- `tests/test_ocr_processor.py`: OCR line grouping, text alignment, and table-like region segmentation.
- `tests/test_exporter.py`: CSV and JSON schema conformity (`Table Title`, `Page Number`).
- `tests/test_startup.py`: CLI argument parsing and application execution entry points.

---

## 2. Automated Output Validation (`validate.py`)

The repository includes a dedicated validation utility (`validate.py`) that checks generated output files for schema compliance, CSV/JSON record parity, page number bounds, and title integrity.

### Validation Command

```bash
python validate.py --output data/output --input data/input --strict
```

### Validation Report Output

The following results represent the recorded validation run across the six evaluated PDF documents:

```text
==============================================================================
FINANCIAL PDF TABLE DETECTION — OUTPUT VALIDATION REPORT
==============================================================================
Document                 | Tables   | Parity   | Integrity   | Status
------------------------------------------------------------------------------
Document1                | 3        | OK       | OK          | PASS
Document2                | 7        | OK       | OK          | PASS
Document3                | 20       | OK       | OK          | PASS
Document4                | 85       | OK       | OK          | PASS
Document5                | 2        | OK       | OK          | PASS
Document6                | 16       | OK       | OK          | PASS
------------------------------------------------------------------------------
Total                    | 133      |          |             | ALL PASS
==============================================================================

Validation successful: all documents passed schema, parity, and integrity checks.
```

### Verification Criteria Enforced

1. **Schema Compliance:** Every CSV and JSON output follows the required schema containing `Table Title` and `Page Number`.

2. **Format Parity:** CSV and JSON files contain matching records, identical counts, and identical row ordering.

3. **Page Bounds:** Every reported `Page Number` is an integer within the valid range of the corresponding PDF document's physical page count.

4. **Title Integrity:** Checks for empty titles, uncleaned delimiter fragments (`|`, `---`), and trailing narrative prose fragments according to the implemented validation rules.

**Note:** Automated output validation confirms structural and data consistency. It does not independently establish the semantic correctness of every detected physical table or extracted title.

---

## 3. Physical Table Detection Summary

The system was evaluated using six PDF documents representing different financial document types, layouts, and document characteristics.

| Document | Type & Features | Detected Tables | Key Headings Verified |
|:---|:---|:---:|:---|
| **Document 1** | Digital Financial Report | 3 | `Balance Sheet`, `Capital Account`, `Profit And Loss Account` |
| **Document 2** | Multi-Page Commercial Invoice | 7 | `Commercial Invoice` (Pages 2–8) |
| **Document 3** | Mixed Digital / Scanned Disclosures | 20 | Note 2 Share Capital, Note 3 Surplus, Note 4 Provisions, Notes 5–12 Schedules, Note 13 Disclosures (`Expenditure In Foreign Currency`, `Payments To The Auditor`, `Related Party Transaction`, `Earning Per Shares`) |
| **Document 4** | Full Annual Financial Report (50 Pages) | 85 | Primary Statements (Balance Sheet, Profit & Loss with Page 6 continuation, Cash Flows, Equity), Notes 3–44 Schedules, Share Based Payments, Defined Benefit Plans |
| **Document 5** | Cash Flow Statement | 2 | `Cash Flow Statement` (Pages 1 & 2) |
| **Document 6** | Bank Transaction Statement | 16 | `Bank Transaction Statement` (Pages 1–16) |
| **Total** | **Six evaluated documents** | **133** | **Regression validation completed** |

### Detection Summary

- Total evaluated documents: 6
- Total reported table detections: 133
- CSV/JSON parity: Passed for all evaluated documents.
- Output schema and integrity checks: Passed for all evaluated documents.

The counts represent reported table detections, including continuation tables appearing on multiple pages.

---

## 4. Key Architectural & Generalization Verifications

This section describes important implementation approaches and regression scenarios evaluated during development.

### A. Non-Numeric & NIL Indicator Schedules

**Challenge:**

Financial disclosures, such as foreign currency expenditure and import CIF value schedules, can contain `NIL`, `N/A`, or `-` indicators instead of numeric digits.

**Implementation Approach:**

The table candidate validation logic accounts for non-numeric tabular rows and NIL indicators alongside standard numeric columns. This helps prevent valid non-numeric financial schedules from being rejected solely because they lack numeric values.

**Verification:**

The evaluated Document 3 disclosures include non-numeric schedules such as `Expenditure In Foreign Currency` and `Payments To The Auditor`.

### B. Conglomerate Native Block Segmentation

**Challenge:**

Unbordered native text pages can cause PDF extraction tools to identify a large page region as a single candidate, potentially combining multiple distinct tables.

**Implementation Approach:**

Candidates spanning multiple independent section headings are treated as potentially unsegmented regions. The detector uses caption boundaries and structural information to divide these regions into separate table candidates.

**Verification:**

The evaluated financial disclosure pages include multiple schedules within the same page, requiring separate candidate segmentation.

### C. Multi-Page Statement Continuation

**Challenge:**

Financial statements, such as Statements of Profit and Loss, can span multiple pages without repeating the complete heading on every continuation page.

**Implementation Approach:**

The continuation logic considers:

- The preceding table's bottom boundary.
- The continuation candidate's top boundary.
- Page-to-page adjacency.
- Section and heading context.
- The presence of a current-page heading that should take precedence.

The implementation uses geometric thresholds and section context to determine whether a title can be inherited from a preceding page.

**Verification:**

Document 4 includes a Statement of Profit and Loss continuation on page 6 and a subsequent Statement of Changes in Equity.

### D. Navigation Banner & Running Header Suppression

**Challenge:**

Document navigation banners and repeated running headers, such as `Overview Reports Financial Statements`, can be mistaken for subsection headings or interfere with continuation title inheritance.

**Implementation Approach:**

The title association and continuation logic use document-level heading context to distinguish repeated navigation elements from meaningful table captions and section headings.

**Verification:**

The evaluated annual report includes repeated navigation elements and section headings that require contextual title association.

### E. OCR Token Repair Safeguards

**Challenge:**

Low-resolution scanned pages and OCR character confusion can corrupt common financial words. For example, `Description` may be incorrectly recognized as `Descriotion` and then incorrectly normalized to an unrelated domain term such as `Depreciation`.

**Implementation Approach:**

The OCR normalization logic includes safeguards for standard financial vocabulary, including terms such as:

- `Description`
- `Particulars`
- `Relationship`
- `Details`
- `Auditor`

These safeguards help prevent valid words from being incorrectly replaced by unrelated domain-specific terms.

**Verification:**

OCR repair safeguards are covered by the title extraction test suite and were considered during regression testing.

### F. Physical Table Deduplication

**Challenge:**

Multiple detection strategies can identify overlapping regions of the same physical table. Conversely, adjacent physical tables may share an identical parent heading and must remain separate.

**Implementation Approach:**

Candidate validation compares:

- Bounding box overlap.
- Intersection over Union (IoU).
- Spatial containment.
- Row and column structure.
- Candidate ranking and layout evidence.

This approach helps remove duplicate detections while preserving physically distinct tables.

**Verification:**

The evaluated documents include financial schedules with repeated parent headings and multiple tables within the same section.

---

## 5. Validation Scope and Limitations

The validation results presented in this document are based on six evaluated PDF documents representing different financial document types and layout variations.

The automated test suite verifies individual application components and their expected behavior.

The output validation utility checks structural properties such as:

- CSV and JSON schema compliance.
- Record consistency between output formats.
- Page number validity.
- Title integrity according to implemented validation rules.

These results demonstrate successful automated validation against the evaluated documents and test cases.

However, automated schema validation does not guarantee that every detected candidate corresponds to a genuine physical table or that every extracted title is semantically correct.

The six evaluated documents provide regression coverage but do not establish guaranteed accuracy across every possible unseen financial PDF.

Additional testing on previously unseen documents is recommended to assess generalization across different PDF generators, document layouts, scan qualities, and table structures.

---

## 6. Conclusion

The Financial PDF Table Detection & Title Extraction pipeline has completed the recorded automated test and output validation runs.

### Recorded Validation Summary

| Validation Area | Result |
|:---|:---|
| Automated Unit Tests | 84 passed |
| Test Failures | 0 |
| Evaluated PDF Documents | 6 |
| Total Table Detections | 133 |
| CSV/JSON Record Parity | Passed |
| Output Schema Validation | Passed |
| Page Number Validation | Passed |
| Title Integrity Checks | Passed |

The implementation combines native PDF layout analysis, selective OCR fallback, contextual table segmentation, spatial title association, continuation handling, and structured result export.

The recorded results establish that the application passes its automated tests and implemented output validation checks on the evaluated documents.

Further evaluation on unseen financial documents can provide additional evidence of its generalization capability.
