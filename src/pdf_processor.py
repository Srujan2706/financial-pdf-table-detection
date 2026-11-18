
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
