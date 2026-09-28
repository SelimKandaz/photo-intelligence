# Photo Intelligence

A Windows desktop app that turns inventory photos into searchable evidence. It reads serial numbers from printed labels and barcodes, stores the results in a local database, and lets you search your whole photo library.

## Features

- OCR and barcode extraction (Tesseract, zxing-cpp, pyzbar, OpenCV), including HEIC photos
- Flags mismatches between printed serials and barcode serials for review
- Fast search, with a deep search fallback
- Review queue and user corrections, kept separate from raw results
- Serial Harvest export: clean serial lists and CSVs that trace back to the source photo
- Original photos are never modified or deleted

## Setup

Requires Python 3.11 or 3.12 and Tesseract.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
winget install --id UB-Mannheim.TesseractOCR -e --source winget
```

Run it:

```powershell
.\run_app.bat
```

Build a portable Windows folder with `python scripts\build_windows_portable.py`.

An optional local semantic search backend (Ollama + Qdrant) lives under `src/app/semantic_backend/`.

## License

Copyright (c) 2026 Selim Kandaz. All rights reserved. Public for portfolio and review purposes. See [LICENSE](LICENSE).
