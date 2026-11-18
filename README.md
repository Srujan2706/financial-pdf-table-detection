# Financial PDF Table Detection & Title Extraction

A production-grade Python solution for detecting physical tables in financial PDF documents, extracting their authoritative titles/captions, and exporting structured metadata in CSV and JSON formats.

Designed to generalize across unseen financial documents:
- **Annual Reports & Disclosures** (Balance Sheets, Profit & Loss Statements, Cash Flow Statements, Statements of Changes in Equity, Notes to Accounts)
- **Banking & Commercial Statements** (Bank Transaction Statements, Account Summaries, Commercial Invoices)
- **Document Modalities** (Pure digital PDFs, scanned image-backed PDFs, mixed digital/scanned pages)
- **Layout Variations** (Fully bordered tables, semi-bordered tables, completely borderless whitespace-aligned grids)

---

## Output Specifications

For every processed PDF `<document>.pdf`, the pipeline outputs two files in the target output directory:
- `<document>_tables.csv`
- `<document>_tables.json`

Both files follow the required schema:

| Column / Key | Type | Description |
|:---|:---|:---|
| `Table Title` | string | Authoritative title or caption associated with the table (`Untitled table` if no heading exists) |
| `Page Number` | integer | 1-based page number where the table appears in the PDF |

### Continuation Handling
Multi-page tables spanning across page boundaries are reported on each page they appear. When a continuation table lacks an explicit heading at the top of a subsequent page, the preceding statement title is carried forward based on physical layout geometry, page-boundary adjacency, and section context.

---

## System Architecture

```mermaid
flowchart TD
    A["Input PDF / Directory"] --> B["Page Classifier\n(Digital, Scanned, Mixed)"]
    B --> C["Dual-Strategy Layout Detector\n(pdfplumber: 'lines' & 'text')"]
    C --> D{"Credible Tables\nDetected?"}
    D -- "No / Scanned / Conglomerate" --> E["Selective Tesseract OCR\n(Layout & Aligned Regions)"]
    D -- "Yes" --> F["Candidate Segmentation\n(Section & Caption Boundaries)"]
    E --> F
    F --> G["Candidate Validation & Deduplication\n(IoU Overlap, Containment & Rank)"]
    G --> H["Spatial Caption Extractor\n(Proximity, Overlap & Delimiter Checks)"]
    H --> I["Continuation & Inheritance Engine\n(Multi-Page Linkage)"]
    I --> J["Standardized Exporter\n(CSV & JSON Serialization)"]
```

---

## Key Technical Features

1. **Deterministic Layout Analysis:**
   - Evaluates vector path rules (`lines` strategy) for bordered tables.
   - Infers column boundaries and row gutters using whitespace alignment (`text` strategy) for borderless schedules.
   - Calculates candidate quality metrics: cell occupancy, multi-cell row ratios, column stability, and average word counts.

2. **Contextual Document Segmentation:**
   - Detects numbered notes, schedules, and structural section headers.
   - Prevents unbordered native text from collapsing multiple distinct schedules into a single unsegmented table block.
   - Slices conglomerate page regions into distinct physical tables bounded by their respective headings.

3. **Selective High-Resolution OCR Fallback:**
   - Invoked only for scanned pages or image-backed pages with unsegmented text blocks.
   - Evaluates OCR word bounding boxes and lines to detect aligned columns and tabular grids.
   - Supports non-numeric and NIL indicator rows (`NIL`, `N/A`, `None`, `-`), ensuring non-numeric financial disclosures are accurately retained.

4. **Spatial Title Association & Cleaning:**
   - Prioritizes structural note headings (e.g. `Note 3 : Property, Plant And Equipment`), primary statements, and schedule titles.
   - Distinguishes table titles from running headers, page navigation bars, table column headers, and narrative prose.
   - Applies domain-safe OCR token normalization to resolve character confusions without corrupting valid words.

5. **Precision Deduplication:**
   - Compares candidate bounding boxes using Intersection over Union (IoU), spatial containment, and row structure.
   - Retains physically distinct adjacent tables sharing identical note headings while deduplicating genuine spatial duplicates.

---

## Installation & Setup

### Prerequisites
- **Python 3.10+**
- **Tesseract OCR** (required for scanned document fallback):
  - **Windows:** Download and install the Tesseract OCR installer and add the installation directory to your system `PATH`.
  - **Linux (Ubuntu/Debian):** `sudo apt-get install tesseract-ocr`
  - **macOS:** `brew install tesseract`

### Virtual Environment Setup

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Linux / macOS:
source venv/bin/activate

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Usage

### 1. Process All PDFs in a Directory
```bash
python main.py data/input -o data/output
```

### 2. Process a Single PDF Document
```bash
python main.py data/input/annual_report.pdf -o data/output
```

### 3. Disable OCR Fallback (Digital-Only Mode)
```bash
python main.py data/input --no-ocr
```

### CLI Arguments

| Argument | Flag | Default | Description |
|:---|:---|:---|:---|
| `input` | Positional | *(Required)* | Path to a single PDF file or directory containing PDFs |
| `--output` | `-o` | `data/output` | Destination directory for generated CSV and JSON files |
| `--no-ocr` | Flag | `False` | Disable Tesseract OCR fallback for pure-digital environments |

---

## Validation & Testing

### Run Automated Unit Tests
The test suite validates layout extraction, caption parsing, delimiter balancing, and exporter conformity:

```bash
python -m pytest
```

### Run Output Verification Tool
The repository includes a validation utility (`validate.py`) that audits generated CSV and JSON outputs for schema conformity, record parity, page number bounds, and title integrity:

```bash
python validate.py --output data/output --input data/input --strict
```

See [VALIDATION.md](VALIDATION.md) for detailed validation records and benchmarks.

---

## Project Structure

```text
financial-pdf-table-detection/
├── data/
│   ├── input/                 # Input PDF documents
│   └── output/                # Generated CSV and JSON results
├── src/
│   ├── __init__.py
│   ├── main.py                # CLI execution controller
│   ├── table_detector.py      # Core detection, segmentation, and deduplication
│   ├── title_extractor.py     # Heading extraction and title normalization
│   ├── ocr_processor.py       # Tesseract OCR fallback and layout analysis
│   ├── page_classifier.py     # Modal page classifier (digital vs scanned)
│   ├── native_table_detector.py # Vector path metric analysis
│   ├── result_exporter.py     # CSV and JSON serialization
│   ├── pdf_processor.py       # PDF document inspection utilities
│   ├── detection_audit.py     # Diagnostic visual review generator
│   └── table_debugger.py      # Page-level diagnostics
├── tests/
│   ├── test_title_extractor.py
│   ├── test_detector_helpers.py
│   ├── test_ocr_processor.py
│   ├── test_exporter.py
│   └── test_startup.py
├── validate.py                # Automated validation script
├── VALIDATION.md              # Detailed validation documentation
├── main.py                    # Repository root entrypoint
├── requirements.txt           # Python package requirements
├── LICENSE                    # Apache 2.0 license
└── README.md                  # Project documentation
```

---

## Security & Privacy
- **100% Local Processing:** Document parsing and OCR execution run locally; no document data or metadata is transmitted externally.
- **Privacy Compliance:** `.gitignore` excludes sensitive files, local environment artifacts, and cache directories.

---

## License
Released under the [Apache License, Version 2.0](LICENSE).
