"""
BillLess Agent – File Validator

Pre-upload validation to catch corrupt / empty / invalid files.

Validates:
  ✅ File exists and size > 0
  ✅ PDF magic bytes (%%PDF header)
  ✅ CSV basic structure (has rows, parseable)
  ✅ File not truncated (checks trailer for PDF)

Fixes: ❌ No Data Validation Before Upload
"""

import csv
import os
import io

from services import logger


class ValidationResult:
    def __init__(self, valid: bool, reason: str = ""):
        self.valid = valid
        self.reason = reason

    def __bool__(self):
        return self.valid


def validate_file(filepath: str) -> ValidationResult:
    """
    Run all validation checks on a file before upload.
    Returns ValidationResult with reason on failure.
    """
    # ── Existence ────────────────────────────────────────────────────────
    if not os.path.exists(filepath):
        return ValidationResult(False, "File does not exist")

    # ── Non-empty ────────────────────────────────────────────────────────
    try:
        size = os.path.getsize(filepath)
    except OSError as e:
        return ValidationResult(False, f"Cannot read file size: {e}")

    if size == 0:
        return ValidationResult(False, "File is empty (0 bytes)")

    # ── Extension-specific checks ────────────────────────────────────────
    ext = os.path.splitext(filepath)[1].lower()

    if ext == ".pdf":
        return _validate_pdf(filepath, size)
    elif ext == ".csv":
        return _validate_csv(filepath, size)
    else:
        return ValidationResult(False, f"Unsupported extension: {ext}")


def _validate_pdf(filepath: str, size: int) -> ValidationResult:
    """Validate PDF file integrity."""
    try:
        with open(filepath, "rb") as f:
            # ── Check PDF header magic bytes ─────────────────────────────
            header = f.read(8)
            if not header.startswith(b"%PDF"):
                return ValidationResult(
                    False, "Not a valid PDF (missing %%PDF header)"
                )

            # ── Check for EOF marker (file not truncated) ────────────────
            # PDF files should end with %%EOF (within last 1KB)
            if size > 1024:
                f.seek(-1024, 2)
                tail = f.read()
            else:
                f.seek(0)
                tail = f.read()

            if b"%%EOF" not in tail:
                # Some generators omit %%EOF — warn but don't reject
                logger.warning(
                    f"⚠️  PDF may be truncated (no %%%%EOF): "
                    f"{os.path.basename(filepath)}"
                )

        return ValidationResult(True)

    except IOError as e:
        return ValidationResult(False, f"Cannot read PDF: {e}")
    except Exception as e:
        return ValidationResult(False, f"PDF validation error: {e}")


def _validate_csv(filepath: str, size: int) -> ValidationResult:
    """Validate CSV file structure."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            # Read first 50 lines max
            sample = f.read(65536)     # 64KB sample

        if not sample.strip():
            return ValidationResult(False, "CSV file is empty")

        # ── Try parsing ──────────────────────────────────────────────────
        reader = csv.reader(io.StringIO(sample))
        row_count = 0
        for row in reader:
            row_count += 1
            if row_count >= 50:
                break

        if row_count < 1:
            return ValidationResult(False, "CSV has no rows")

        # ── Check minimum columns ────────────────────────────────────────
        reader2 = csv.reader(io.StringIO(sample))
        first_row = next(reader2, None)
        if first_row and len(first_row) < 2:
            logger.warning(
                f"⚠️  CSV has only {len(first_row)} column(s): "
                f"{os.path.basename(filepath)}"
            )

        return ValidationResult(True)

    except UnicodeDecodeError:
        return ValidationResult(False, "CSV encoding error (not UTF-8)")
    except csv.Error as e:
        return ValidationResult(False, f"CSV parse error: {e}")
    except IOError as e:
        return ValidationResult(False, f"Cannot read CSV: {e}")
    except Exception as e:
        return ValidationResult(False, f"CSV validation error: {e}")
