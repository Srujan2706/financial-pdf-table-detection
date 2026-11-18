
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
