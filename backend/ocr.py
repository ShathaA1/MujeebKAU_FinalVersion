import os
import time
import requests
import re
from datetime import date


# Read the OCR API key from environment variables instead of hardcoding it.
# This keeps the API key secure and prevents exposing it inside the source code.
ALOCR_API_KEY = os.getenv("ALOCR_API_KEY")


def extract_text_from_file(file_path: str) -> str:
    """
    Benefit:
        Converts an uploaded PDF or image file into searchable plain text using alOCR.

    What it does:
        Sends the file to the alOCR API, receives a processing token, checks the OCR job
        status repeatedly until it is completed, then combines all extracted page texts
        into one string. Each page is separated using PAGE_BREAK so the system can still
        recognize where one page ends and the next page begins.

    Why it is useful:
        This function is useful when the uploaded file is scanned, image-based, or does
        not contain selectable text. It allows the rest of the system to work with the
        extracted text instead of the original file format.
    """

    # Make sure the OCR API key exists before sending any request.
    # Without this key, the external OCR service cannot be accessed.
    if not ALOCR_API_KEY:
        raise ValueError("ALOCR_API_KEY is not set.")

    print("OCR 1- upload started")

    # Open the file in binary mode because files must be uploaded as raw bytes.
    # The file is then sent to the OCR upload endpoint with the authorization token.
    with open(file_path, "rb") as f:
        response = requests.post(
            "https://alapi.deep.sa/v1/ocr/upload",
            headers={"Authorization": f"Bearer {ALOCR_API_KEY}"},
            files={"file": f},
            timeout=60
        )

    # If the upload request fails, stop the process and show the API error response.
    if response.status_code != 200:
        raise Exception(f"Upload failed: {response.text}")

    # Convert the API response from JSON text into a Python dictionary.
    data = response.json()
    print("OCR 2- upload response:", data)

    # The token is used later to ask the API about the OCR job status.
    token = data["token"]
    print("OCR 3- token:", token)

    # Poll the OCR job until it is completed, failed, or timed out.
    # The loop tries up to 60 times, with a 2-second wait between attempts.
    for _ in range(60):
        result = requests.get(
            f"https://alapi.deep.sa/v1/ocr/jobs/{token}",
            headers={"Authorization": f"Bearer {ALOCR_API_KEY}"},
            timeout=60
        )

        # Read the OCR job response and check its current status.
        job = result.json()
        status = job.get("status")
        print("OCR 4- status:", status)

        # When the OCR job is done, collect the text from all returned pages.
        if status == "done":
            pages = job.get("pages", [])

            # Join page texts into one string while keeping page boundaries visible.
            return "\n\nPAGE_BREAK\n\n".join(
                page.get("text", "") for page in pages
            )

        # If the OCR service reports failure, stop immediately and show details.
        if status in ["failed", "error"]:
            raise Exception(f"OCR failed: {job}")

        # Wait before checking the job again to avoid sending requests too quickly.
        time.sleep(2)

    # If the loop finishes without a final result, the OCR job took too long.
    raise TimeoutError("OCR timed out")


def extract_pages_via_ocr(file_path: str) -> list:
    """
    Benefit:
        Extracts OCR text page by page when the system needs to preserve page structure.

    What it does:
        Uploads the file to alOCR, waits for the asynchronous OCR job to finish,
        then returns a list of page texts. Each list item represents one page from
        the original document.

    Why it is useful:
        This function is useful as a fallback when normal PDF text extraction gives
        weak, empty, or unreliable results. Returning text page by page helps later
        processing steps keep the relationship between extracted content and page numbers.
    """

    # Check that the OCR API key is available before calling the external service.
    if not ALOCR_API_KEY:
        raise ValueError("ALOCR_API_KEY is not set.")

    print(f"[OCR-FALLBACK] Uploading to alOCR: {file_path}")

    # Upload the file to alOCR in binary format.
    with open(file_path, "rb") as f:
        response = requests.post(
            "https://alapi.deep.sa/v1/ocr/upload",
            headers={"Authorization": f"Bearer {ALOCR_API_KEY}"},
            files={"file": f},
            timeout=60
        )

    # Stop the fallback process if the file upload fails.
    if response.status_code != 200:
        raise Exception(
            f"[OCR-FALLBACK] Upload failed ({response.status_code}): {response.text}"
        )

    # Read the upload response and extract the OCR job token.
    data = response.json()
    token = data.get("token")

    # The token is required to track the OCR job.
    # If it is missing, the API response is invalid or unexpected.
    if not token:
        raise Exception(f"[OCR-FALLBACK] No token in upload response: {data}")

    print(f"[OCR-FALLBACK] Token received: {token}")

    # Check the OCR job status repeatedly until the result is ready.
    for attempt in range(60):
        result = requests.get(
            f"https://alapi.deep.sa/v1/ocr/jobs/{token}",
            headers={"Authorization": f"Bearer {ALOCR_API_KEY}"},
            timeout=60
        )

        # Convert the job response into a dictionary and read its status.
        job = result.json()
        status = job.get("status")
        print(f"[OCR-FALLBACK] Poll {attempt + 1}: status={status}")

        # When the job is complete, extract text from each page separately.
        if status == "done":
            pages = job.get("pages", [])

            # Store each page's text as one item in the returned list.
            texts = [page.get("text", "") for page in pages]

            print(f"[OCR-FALLBACK] Done. Pages returned by OCR: {len(texts)}")
            return texts

        # Stop if the OCR job fails.
        if status in ["failed", "error"]:
            raise Exception(f"[OCR-FALLBACK] OCR job failed: {job}")

        # Wait before sending the next status request.
        time.sleep(2)

    # Stop if OCR takes longer than the allowed polling time.
    raise TimeoutError("[OCR-FALLBACK] OCR job timed out after 120 seconds")


def clean_cell_text(value: str) -> str:
    """
    Benefit:
        Cleans noisy OCR table text so it becomes easier and safer to parse.

    What it does:
        Removes Arabic tatweel characters, hidden direction marks, duplicated spaces,
        table border symbols, and extra line characters. It returns a cleaner version
        of the text that can be used for date and title extraction.

    Why it is useful:
        OCR output often contains invisible characters, broken spacing, and table borders.
        Cleaning the text first reduces parsing errors and improves the accuracy of
        extracting academic calendar events.
    """

    # Return an empty string if the input is None or empty.
    if not value:
        return ""

    # Remove Arabic tatweel because it can make text matching harder.
    value = value.replace("ـ", " ")

    # Remove hidden right-to-left and left-to-right marks that may appear in OCR output.
    value = value.replace("\u200f", " ").replace("\u200e", " ")

    # Replace repeated whitespace with a single space.
    # Also remove common table-border characters from the beginning and end.
    value = re.sub(r"\s+", " ", value).strip(" |-\t\n\r")

    # Return the final cleaned cell text.
    return value.strip()


def is_title_candidate(cell: str) -> bool:
    """
    Benefit:
        Helps the parser identify whether a table cell can be used as an event title.

    What it does:
        Checks the content of a cell and rejects values that look like table headers,
        dates, numbers, university labels, or repeated academic calendar words.
        It only accepts cells that contain meaningful Arabic or English text.

    Why it is useful:
        Academic calendar tables contain many columns such as date, day, week, and header
        labels. This function prevents the system from accidentally using those values
        as event titles.
    """

    # Empty cells cannot be valid event titles.
    if not cell:
        return False

    # Common words that usually represent headers, labels, or document metadata,
    # not the actual event title.
    ignored_words = [
        "الأسبوع", "اليوم", "التاريخ", "من", "إلى", "الحدث",
        "عمادة", "جامعة", "القبول", "التسجيل", "مواعيد", "التقويم",
        "العام الجامعي", "تحديث"
    ]

    # Reject the cell if it contains any ignored word.
    if any(word in cell for word in ignored_words):
        return False

    # Reject cells that contain only numbers, date separators, Hijri/Gregorian letters,
    # or whitespace. These are usually date values, not event names.
    if re.fullmatch(r"[\d\-\sمه/]+", cell):
        return False

    # Accept only cells that contain Arabic or English letters.
    # This prevents symbols or empty-looking OCR noise from being treated as titles.
    if not re.search(r"[A-Za-z\u0600-\u06FF]", cell):
        return False

    return True


def extract_title_from_row(row: str) -> str | None:
    """
    Benefit:
        Finds the most likely academic event title from a noisy OCR table row.

    What it does:
        Splits the row into table cells, cleans each cell, removes cells containing
        ISO dates, filters out weak title candidates, then selects the strongest
        remaining text value as the event title.

    Why it is useful:
        OCR table rows may contain dates, days, week numbers, and event descriptions
        all mixed together. This function isolates the most meaningful text so the
        final event record has a correct title.
    """

    # Split the row using the table separator and clean each cell.
    cells = [clean_cell_text(c) for c in row.split("|")]

    # Remove empty cells after cleaning.
    cells = [c for c in cells if c]

    # Store possible title candidates with a score.
    candidates = []

    for cell in cells:

        # Skip any cell that contains a Gregorian ISO date.
        # Date cells should not be used as event titles.
        if re.search(r"\d{4}-\d{2}-\d{2}", cell):
            continue

        # Check if the cell looks like a valid title.
        if is_title_candidate(cell):

            # Count Arabic and English letters.
            # Longer meaningful text usually has a better chance of being the title.
            arabic_letters = len(re.findall(r"[\u0600-\u06FFA-Za-z]", cell))

            # Store the score with the cell text.
            candidates.append((arabic_letters, cell))

    # If no valid title candidate is found, return None.
    if not candidates:
        return None

    # Sort candidates by the number of letters from highest to lowest.
    # The strongest candidate is assumed to be the event title.
    candidates.sort(key=lambda x: x[0], reverse=True)

    return candidates[0][1]


def parse_date_safe(value: str):
    """
    Benefit:
        Prevents invalid or noisy date values from crashing the extraction process.

    What it does:
        Tries to convert a date string written in ISO format, such as YYYY-MM-DD,
        into a Python date object. If the value is invalid, it returns None instead
        of raising an error.

    Why it is useful:
        OCR may misread dates or produce incomplete values. This helper keeps the
        event extraction process running even when one date value is not usable.
    """

    try:
        # Convert the string into a Python date object.
        return date.fromisoformat(value)

    except Exception:
        # Return None when the date cannot be parsed safely.
        return None


def extract_academic_events(text: str) -> list[dict]:
    """
    Benefit:
        Converts raw OCR text from an academic calendar table into structured records.

    What it does:
        Reads the OCR text line by line, keeps only table-like rows, extracts Gregorian
        and Hijri dates, identifies the event title, converts dates into date objects,
        removes duplicate events, and returns the final list of academic events.

    Why it is useful:
        This function transforms unstructured OCR output into clean data that can be
        saved in the database, displayed in the frontend, or used by the chatbot to
        answer questions about academic calendar events.
    """

    # Store the final extracted academic events.
    events = []

    # Store unique event keys to prevent duplicate records.
    seen = set()

    # If there is no OCR text, return an empty list.
    if not text:
        return events

    # Split the full OCR text into individual lines.
    lines = text.splitlines()

    for raw_line in lines:

        # Clean the line before trying to extract information from it.
        line = clean_cell_text(raw_line)

        # Skip empty lines after cleaning.
        if not line:
            continue

        # Focus only on table-like rows.
        # Academic calendar rows are expected to contain "|" between columns.
        if "|" not in line:
            continue

        # Extract Gregorian dates that follow ISO format, such as 2025-09-01.
        gregorian_dates = re.findall(r"(20\d{2}-\d{2}-\d{2})", line)

        # Extract Hijri dates that follow ISO-like format, such as 1447-03-10.
        hijri_dates = re.findall(r"(14\d{2}-\d{2}-\d{2})", line)

        # If the row has no Gregorian date, it is not considered a valid event row.
        if not gregorian_dates:
            continue

        # Extract the most likely event title from the row.
        title = extract_title_from_row(line)

        # If no title is found, skip this row.
        if not title:
            continue

        # Use the first Gregorian date as the start date.
        start_date = parse_date_safe(gregorian_dates[0])

        # Use the second Gregorian date as the end date if it exists.
        # If there is only one date, the event starts and ends on the same day.
        end_date = (
            parse_date_safe(gregorian_dates[1])
            if len(gregorian_dates) > 1
            else start_date
        )

        # Use the first Hijri date as the Hijri start date if available.
        hi_start_date = (
            parse_date_safe(hijri_dates[0])
            if len(hijri_dates) > 0
            else None
        )

        # Use the second Hijri date as the Hijri end date if available.
        # If there is only one Hijri date, use it as both start and end.
        hi_end_date = (
            parse_date_safe(hijri_dates[1])
            if len(hijri_dates) > 1
            else hi_start_date
        )

        # Build a unique key for the event to avoid duplicated rows.
        key = (title, start_date, end_date)

        # Skip the event if the same title and dates were already added.
        if key in seen:
            continue

        # Mark this event as already processed.
        seen.add(key)

        # Add the structured academic event to the final list.
        events.append({
            "title": title,
            "startdate": start_date,
            "enddate": end_date,
            "histartdate": hi_start_date,
            "hienddate": hi_end_date
        })

    # Return all extracted and deduplicated academic events.
    return events