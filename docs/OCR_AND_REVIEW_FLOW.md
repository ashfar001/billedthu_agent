# OCR and Review Flow

The agent uses this receipt text strategy:

1. Extract selectable PDF text with PyMuPDF/pdfplumber/pypdf.
2. If the PDF is image-only, run free local Tesseract OCR when installed.
3. If local OCR cannot read it, optionally run Google Vision if enabled.
4. If OCR still fails, upload the original PDF with `NEEDS_REVIEW`.

This avoids paid OCR for normal digital bills and still avoids losing image-only
receipts.

## Free Windows OCR Setup

Install Tesseract OCR on the Windows machine:

```text
https://github.com/UB-Mannheim/tesseract/wiki
```

Default install path is usually:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

If Tesseract is on `PATH`, the agent will find it automatically. Otherwise set
`tesseract_cmd` in the support-locked settings/config to the full path.

## Recommended Production Policy

- Agent should always upload the source PDF file.
- Backend should store the PDF at least until the receipt is confirmed or marked
  reviewed.
- If `upload_status` is `NEEDS_REVIEW`, the admin/backend can inspect the PDF
  and correct receipt fields.
- Delete or archive PDFs only after successful processing according to your data
  retention policy.

For cost control, keep Google Vision disabled by default and use it only for
stores where local OCR is not accurate enough.
