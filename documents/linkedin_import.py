import hashlib
import json
import os
from datetime import datetime

from documents.resume_parser import extract_text
from documents.structured_resume_parser import parse_resume


IMPORT_DIR = os.path.join("storage", "resumes", "linkedin_imports")
INDEX_PATH = os.path.join(IMPORT_DIR, "imports.json")


def _read_index():
    if not os.path.exists(INDEX_PATH):
        return []
    with open(INDEX_PATH, encoding="utf-8") as index_file:
        records = json.load(index_file)
    if not isinstance(records, list):
        raise ValueError("LinkedIn import index is not a list.")
    return records


def _write_index(records):
    os.makedirs(IMPORT_DIR, exist_ok=True)
    temporary_path = f"{INDEX_PATH}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as index_file:
        json.dump(records, index_file, indent=2)
    os.replace(temporary_path, INDEX_PATH)


def import_linkedin_pdf(content, filename):
    if not content:
        raise ValueError("The uploaded LinkedIn PDF is empty.")
    digest = hashlib.sha256(content).hexdigest()
    records = _read_index()
    existing = next((record for record in records if record["sha256"] == digest), None)
    if existing:
        stored_path = existing["path"]
        if not os.path.isfile(stored_path):
            raise ValueError("A duplicate import was found, but its stored PDF is missing.")
        text = extract_text(stored_path)
        if not text.strip():
            raise ValueError("The duplicate PDF contains no extractable text.")
        return {
            **existing,
            "duplicate": True,
            "text": text,
            "parsed": parse_resume(text),
        }

    os.makedirs(IMPORT_DIR, exist_ok=True)
    stored_path = os.path.join(IMPORT_DIR, f"{digest}.pdf")
    with open(stored_path, "wb") as pdf_file:
        pdf_file.write(content)
    text = extract_text(stored_path)
    if not text.strip():
        raise ValueError(
            "No text could be extracted from this PDF. Use a text-based LinkedIn PDF export."
        )

    record = {
        "sha256": digest,
        "filename": str(filename or "LinkedIn export.pdf"),
        "path": stored_path,
        "imported_at": datetime.now().isoformat(),
    }
    records.append(record)
    _write_index(records)
    return {
        **record,
        "duplicate": False,
        "text": text,
        "parsed": parse_resume(text),
    }
