import fitz
import re
import os
import json
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables from the .env file.
# This allows the API key to be stored outside the code for better security.
load_dotenv()

# Create the OpenAI-compatible client.
# The base_url points to the external AI provider used by the project.
# The API key is read from the environment variable instead of being hardcoded.
client = OpenAI(
    base_url="https://alapi.deep.sa/v1",
    api_key=os.getenv("OPENAI_API_KEY")
)


def extract_pdf_blocks_with_pymupdf(pdf_path: str):
    """
    Benefit:
        Extracts text from a PDF while keeping information about where each text block
        appears on the page.

    What it does:
        Opens the PDF file using PyMuPDF, loops through every page, reads the page as
        structured text blocks, extracts only real text blocks, collects their position
        coordinates and text content, then returns all extracted blocks grouped by page.

    Why it is useful:
        Regular text extraction may return Arabic PDF content in the wrong order,
        especially when the page contains columns, tables, or text boxes. Keeping
        block coordinates allows the system to reorder the content later based on
        the page layout.
    """

    # Open the PDF document from the given file path.
    doc = fitz.open(pdf_path)

    # This list will store the extracted blocks for all pages.
    pages = []

    # Loop through all PDF pages.
    # start=1 is used because users and documents usually count pages from 1,
    # while programming libraries often count from 0.
    for page_index, page in enumerate(doc, start=1):

        # Extract the page content as a dictionary.
        # This format includes blocks, lines, spans, text, and coordinates.
        data = page.get_text("dict")

        # This list will store all readable text blocks from the current page.
        blocks = []

        # Loop through each block detected by PyMuPDF.
        for block in data.get("blocks", []):

            # PyMuPDF blocks can contain text or non-text elements such as images.
            # type 0 means this block is a text block.
            if block.get("type") != 0:
                continue

            # This list will collect text lines inside the current block.
            block_text = []

            # Get the bounding box coordinates of the block.
            # bbox format is usually [x0, y0, x1, y1].
            # These coordinates help reorder text according to its visual position.
            bbox = block.get("bbox", [0, 0, 0, 0])

            # Loop through the text lines inside the block.
            for line in block.get("lines", []):

                # This variable collects all spans in one line.
                line_text = ""

                # A span is a small part of text with the same font/style.
                # A single visual line may contain multiple spans.
                for span in line.get("spans", []):

                    # Extract the span text and remove extra spaces around it.
                    text = span.get("text", "").strip()

                    # Add the span text to the line only if it is not empty.
                    if text:
                        line_text += text + " "

                # If the full line contains useful text, add it to the block text.
                if line_text.strip():
                    block_text.append(line_text.strip())

            # Join all lines from the same block into one text value.
            final_text = "\n".join(block_text).strip()

            # Add the block only if it contains actual text.
            if final_text:
                blocks.append({
                    "x0": bbox[0],
                    "y0": bbox[1],
                    "x1": bbox[2],
                    "y1": bbox[3],
                    "text": final_text
                })

        # Store the page number and its extracted text blocks.
        pages.append({
            "page_number": page_index,
            "blocks": blocks
        })

    # Return all pages with their extracted text blocks.
    return pages


def order_blocks_arabic_layout(blocks):
    """
    Benefit:
        Reorders extracted PDF text blocks so Arabic content becomes easier to read.

    What it does:
        Sorts blocks by their vertical position, groups nearby blocks into the same
        visual row, then sorts each row from right to left because Arabic reading
        order is right-to-left.

    Why it is useful:
        PDF extraction does not always return text in the same order that appears
        visually on the page. This function improves the reading order before the
        text is cleaned, chunked, or sent to the AI model.
    """

    # If there are no blocks, return an empty list immediately.
    if not blocks:
        return []

    # Sort all blocks from top to bottom based on their y0 coordinate.
    # y0 represents the upper vertical position of the block on the page.
    blocks = sorted(blocks, key=lambda b: b["y0"])

    # This list will store rows of blocks.
    # Each row contains blocks that appear on approximately the same horizontal line.
    rows = []

    # Group blocks into rows based on close vertical positions.
    for block in blocks:
        placed = False

        # Try to place the current block into an existing row.
        for row in rows:

            # If the block's vertical position is close to the first block in the row,
            # it is considered part of the same visual row.
            if abs(row[0]["y0"] - block["y0"]) < 25:
                row.append(block)
                placed = True
                break

        # If the block does not match any existing row, create a new row for it.
        if not placed:
            rows.append([block])

    # This list will store blocks after applying Arabic reading order.
    ordered = []

    # Sort each row from right to left.
    for row in rows:

        # In Arabic layouts, the rightmost block should usually be read first.
        # A larger x0 value means the block starts further to the right.
        row_sorted = sorted(row, key=lambda b: b["x0"], reverse=True)

        # Add the sorted row blocks to the final ordered list.
        ordered.extend(row_sorted)

    # Return blocks in the improved Arabic reading order.
    return ordered


def clean_basic_text(text: str):
    """
    Benefit:
        Cleans extracted text while keeping the original meaning and important content.

    What it does:
        Removes hidden direction marks, normalizes repeated spaces and excessive line
        breaks, removes repeated noise lines, and returns a cleaner text version.

    Why it is useful:
        Text extracted from PDFs often contains invisible characters, repeated headers,
        or unnecessary spacing. Cleaning the text improves later processing, AI
        organization, and final chunk quality.
    """

    # If the input text is empty or None, return an empty string.
    if not text:
        return ""

    # Remove hidden right-to-left and left-to-right marks.
    # These marks may affect text matching and display without being visible.
    text = text.replace("\u200f", " ").replace("\u200e", " ")

    # Replace repeated spaces or tabs with a single space.
    text = re.sub(r"[ \t]+", " ", text)

    # Replace three or more consecutive line breaks with only two line breaks.
    # This keeps paragraphs separated without creating excessive empty space.
    text = re.sub(r"\n{3,}", "\n\n", text)


    # This list will store cleaned lines after removing noise.
    lines = []

    # Process the text line by line.
    for line in text.splitlines():

        # Remove extra spaces at the beginning and end of the line.
        line = line.strip()

        # Skip empty lines.
        if not line:
            continue

        # Keep useful lines.
        lines.append(line)

    # Join the remaining lines into the final cleaned text.
    return "\n".join(lines).strip()


def organize_page_with_llm(raw_text: str, page_number: int, document_type: str):
    """
    Benefit:
        Uses the language model to reorganize messy extracted page text into a clearer
        structured format.

    What it does:
        Builds a detailed Arabic prompt containing the document type, page number,
        extraction problem, formatting rules, and raw text. Then it sends the prompt
        to the AI model and asks for a JSON response containing a section title and
        cleaned page text.

    Why it is useful:
        Some PDF pages contain columns, tables, boxes, or mixed definitions that are
        difficult to fix using rules only. The language model helps restore readable
        order without summarizing, deleting, or adding information.
    """

    # Build the prompt sent to the language model.
    # The prompt explains exactly how the model should reorganize the extracted text.
    prompt = f"""
أنت خبير في فهم وتنظيم المستندات الجامعية العربية بعد استخراج النص من PDF.

نوع المستند: {document_type}
رقم الصفحة: {page_number}

المشكلة:
النص المستخرج قد يكون غير مرتب بسبب وجود أعمدة، جداول، مربعات نص، أو تداخل بين المصطلحات والتعريفات.

المطلوب:
أعد كتابة النص بطريقة صحيحة ومنظمة اعتمادًا على المحتوى الموجود فقط.

قواعد إلزامية:
1. لا تلخص.
2. لا تحذف أي معلومة مهمة.
3. لا تضف أي معلومة غير موجودة.
4. لا تغيّر المعنى.
5. أصلح ترتيب القراءة إذا كان النص متداخلًا.
6. إذا وجدت مصطلحًا وتعريفه، اكتبه بهذا الشكل:
   المصطلح:
   التعريف
7. إذا وجدت قائمة أو جدولًا، اجعله مقروءًا ومنظمًا.
8. إذا وجدت مربعات متعددة، افصل كل مربع بعنوان مناسب.
9. صحح أخطاء OCR الواضحة فقط.
10. إذا كان جزء غير واضح، احتفظ به كما هو.
11. أرجع JSON فقط.

الصيغة المطلوبة:
{{
  "section_title": "عنوان مناسب للصفحة",
  "clean_text": "النص الكامل المنظم بدون حذف"
}}

النص المستخرج:
{raw_text}
"""

    # Send the prompt to the language model.
    # temperature=0 is used to make the result more stable and less creative.
    # response_format asks the model to return a JSON object.
    response = client.chat.completions.create(
        model="google/gemini-3-flash",
        messages=[
            {
                "role": "system",
                "content": "أعد تنظيم النص فقط. لا تلخص ولا تحذف معلومات. أرجع JSON فقط."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0,
        response_format={"type": "json_object"}
    )

    # Extract the model response text.
    content = response.choices[0].message.content

    try:
        # Convert the JSON string returned by the model into a Python dictionary.
        data = json.loads(content)
    except Exception:
        # If JSON parsing fails, fall back to the original raw text.
        # This prevents the whole pipeline from failing because of one bad AI response.
        data = {
            "section_title": f"Page {page_number}",
            "clean_text": raw_text
        }

    # Make sure the required keys exist even if the model returns incomplete JSON.
    data.setdefault("section_title", f"Page {page_number}")
    data.setdefault("clean_text", raw_text)

    # Return the structured page data.
    return data


def extract_structured_chunks_from_pdf(pdf_path: str, document_type: str, use_ai: bool = True):
    """
    Benefit:
        Builds final searchable document chunks from readable and scanned PDF pages.

    What it does:
        Extracts text from the PDF using PyMuPDF, detects pages with weak or missing
        text, applies OCR fallback when needed, optionally sends each page to the
        language model for organization, then returns structured chunks with page
        numbers, chunk order, and cleaned text.

    Why it is useful:
        This function is the main PDF processing pipeline. It supports normal text PDFs,
        scanned PDFs, and mixed PDFs that contain both readable pages and image-based
        pages. The final chunks can be stored in ChromaDB or used later by the RAG
        system to answer user questions.
    """

    # Import tempfile here because it is only needed when unreadable pages are converted
    # into temporary PNG images for OCR.
    import tempfile

    # Import OCR fallback function.
    # This is used when PyMuPDF cannot extract enough text from one or more pages.
    from ocr import extract_pages_via_ocr

    # ── Step 1: PyMuPDF extraction per page ──────────────────────────────────

    # Extract structured text blocks from the PDF.
    pages_data = extract_pdf_blocks_with_pymupdf(pdf_path)

    # Count how many pages were detected.
    total_pages = len(pages_data)
    print(f"[PDF-STRUCT] Total pages detected by PyMuPDF: {total_pages}")

    # page_texts stores the final text for each page.
    # Key: page number starting from 1
    # Value: cleaned text string
    page_texts = {}

    # unreadable_pages stores pages where PyMuPDF extracted too little text.
    # These pages will be processed later using OCR.
    unreadable_pages = []

    # Process each page extracted by PyMuPDF.
    for page in pages_data:

        # Read the page number.
        page_number = page["page_number"]

        # Reorder blocks according to Arabic page layout.
        blocks = order_blocks_arabic_layout(page["blocks"])

        # Merge all ordered block texts into one page-level text.
        raw_text = "\n\n".join(block["text"] for block in blocks)

        # Clean the extracted page text.
        raw_text = clean_basic_text(raw_text)

        # Measure the length of cleaned text.
        # This helps decide whether the page is readable or needs OCR.
        text_len = len(raw_text.strip())
        print(f"[PDF-STRUCT] Page {page_number}: PyMuPDF text length = {text_len}")

        # If the page has enough extracted text, keep the PyMuPDF result.
        if text_len >= 20:
            page_texts[page_number] = raw_text

        # If the extracted text is too short, mark the page for OCR fallback.
        else:
            print(f"[PDF-STRUCT] Page {page_number}: unreadable by PyMuPDF → flagged for OCR")
            unreadable_pages.append(page_number)

    # ── Step 2: OCR fallback ─────────────────────────────────────────────────

    # Run OCR only if some pages were unreadable by PyMuPDF.
    if unreadable_pages:

        # Case 1:
        # If all pages are unreadable, the whole PDF is likely scanned.
        # In this case, send the complete file to OCR once instead of page by page.
        if len(unreadable_pages) == total_pages:
            print(
                f"[PDF-STRUCT] All {total_pages} page(s) unreadable. "
                "Sending entire file to alOCR."
            )

            try:
                # Extract OCR text for all pages.
                ocr_page_texts = extract_pages_via_ocr(pdf_path)

                # Store each OCR page result using its page number.
                for i, text in enumerate(ocr_page_texts):
                    pn = i + 1
                    print(
                        f"[PDF-STRUCT] OCR result page {pn}: "
                        f"length = {len(text.strip())}"
                    )
                    page_texts[pn] = text

            except Exception as e:
                # Stop the pipeline if OCR fails for a fully scanned PDF.
                raise RuntimeError(
                    f"[PDF-STRUCT] OCR fallback failed for full PDF: {e}"
                )

        # Case 2:
        # If only some pages are unreadable, the PDF is mixed.
        # Only unreadable pages are converted to images and sent to OCR.
        else:
            print(
                f"[PDF-STRUCT] {len(unreadable_pages)} page(s) need OCR: "
                f"{unreadable_pages}"
            )

            # Open the PDF again so specific pages can be rendered as images.
            doc = fitz.open(pdf_path)

            # Process only the unreadable pages.
            for page_number in unreadable_pages:

                # PyMuPDF pages are zero-based, so subtract 1 from the page number.
                page = doc[page_number - 1]

                # Render the page as an image.
                # dpi=150 gives reasonable OCR quality without making the image too large.
                pix = page.get_pixmap(dpi=150)

                # Create a temporary PNG file to store the rendered page image.
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                tmp_path = tmp.name
                tmp.close()

                try:
                    # Save the rendered page image to the temporary file.
                    pix.save(tmp_path)

                    print(
                        f"[PDF-STRUCT] Sending page {page_number} as image "
                        f"to alOCR: {tmp_path}"
                    )

                    # Send the temporary page image to OCR.
                    ocr_texts = extract_pages_via_ocr(tmp_path)

                    # Since this is one image, use the first OCR result if available.
                    ocr_text = ocr_texts[0] if ocr_texts else ""

                    print(
                        f"[PDF-STRUCT] OCR result page {page_number}: "
                        f"length = {len(ocr_text.strip())}"
                    )

                    # Store OCR result for this page.
                    page_texts[page_number] = ocr_text

                except Exception as e:
                    # Do not stop the full pipeline if OCR fails for one page.
                    # Instead, store an empty text for that page and continue.
                    print(
                        f"[PDF-STRUCT] WARNING: OCR failed for page "
                        f"{page_number}: {e}"
                    )
                    page_texts[page_number] = ""

                finally:
                    # Delete the temporary image file after OCR to avoid leaving
                    # unnecessary files on the server.
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

    # ── Step 3: Debug — merged text summary ──────────────────────────────────

    # Collect page texts in the original PDF page order.
    all_page_texts = [page_texts.get(p["page_number"], "") for p in pages_data]

    # Merge all non-empty page texts for debugging and inspection.
    merged_full = "\n\nPAGE_BREAK\n\n".join(t for t in all_page_texts if t.strip())

    # Print the total length of the final merged text.
    print(f"[PDF-STRUCT] Final merged text length: {len(merged_full)}")

    # Print the first 500 characters to help check extraction quality.
    print(f"[PDF-STRUCT] First 500 chars of merged text:\n{merged_full[:500]}")

    # ── Step 4: Build chunks in page order ───────────────────────────────────

    # This list will store the final structured chunks.
    chunks = []

    # Build one chunk per readable page.
    for page in pages_data:

        # Read the current page number.
        page_number = page["page_number"]

        # Get the final text for this page, whether it came from PyMuPDF or OCR.
        raw_text = page_texts.get(page_number, "")

        # Apply cleaning again because OCR text may also contain noise or extra spacing.
        raw_text = clean_basic_text(raw_text)

        # Skip pages that are still empty or too short after final cleaning.
        if not raw_text or len(raw_text.strip()) < 20:
            print(f"[PDF-STRUCT] Page {page_number}: skipped (empty after final clean)")
            continue

        # If AI organization is enabled, send the page text to the language model.
        if use_ai:
            try:
                # Ask the model to organize the page while preserving the original content.
                structured = organize_page_with_llm(
                    raw_text=raw_text,
                    page_number=page_number,
                    document_type=document_type
                )

                # Extract the generated section title and cleaned text.
                section_title = structured["section_title"]
                clean_text = structured["clean_text"]

            except Exception as e:
                # If the AI step fails, keep the original cleaned text.
                # This prevents the whole pipeline from failing because of one page.
                print(f"[PDF-STRUCT] LLM failed for page {page_number}: {e}")
                section_title = f"Page {page_number}"
                clean_text = raw_text

        # If AI organization is disabled, use the cleaned text directly.
        else:
            section_title = f"Page {page_number}"
            clean_text = raw_text

        # Build the final chunk text with page number and section title.
        # This gives the RAG system useful metadata inside the searchable text.
        chunk_text = f"""
Page: {page_number}
Section: {section_title}

{clean_text}
""".strip()

        # Add the chunk to the final result.
        chunks.append({
            "page_number": page_number,
            "chunk_order": len(chunks) + 1,
            "chunk_text": chunk_text
        })

    # Print how many chunks were created by the full PDF pipeline.
    print(f"[PDF-STRUCT] Structured chunks returned by pipeline: {len(chunks)}")

    # Return the final structured chunks.
    return chunks