
import pymupdf
from pathlib import Path


def inspect_document(pdf_path):

    doc = pymupdf.open(pdf_path)

    print(f"\nDOCUMENT: {pdf_path.name}")
    print("=" * 75)

    for page_number, page in enumerate(doc, start=1):

        page_area = page.rect.width * page.rect.height

        images = page.get_images(full=True)
        drawings = page.get_drawings()
        words = page.get_text("words")

        largest_image_ratio = 0

        for img in images:

            xref = img[0]
            rectangles = page.get_image_rects(xref)

            for rect in rectangles:

                image_area = rect.width * rect.height
                ratio = image_area / page_area

                largest_image_ratio = max(
                    largest_image_ratio,
                    ratio
                )

        if largest_image_ratio >= 0.80:
            page_type = "IMAGE_BACKED"
        elif len(words) > 0:
            page_type = "NATIVE_TEXT"
        else:
            page_type = "POSSIBLE_SCANNED"

        print(
            f"Page {page_number:3} | "
            f"Type: {page_type:14} | "
            f"Words: {len(words):4} | "
            f"Images: {len(images):2} | "
            f"Drawings: {len(drawings):3} | "
            f"Largest image coverage: "
            f"{largest_image_ratio:.1%}"
        )

    doc.close()


def main():

    input_dir = Path("data/input")

    for pdf_path in sorted(input_dir.glob("*.pdf")):
        inspect_document(pdf_path)


if __name__ == "__main__":
    main()
