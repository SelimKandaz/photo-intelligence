# Photo Intelligence / Inventory Evidence Search

Serious first project structure for turning company photos into persistent, searchable inventory evidence. The original v7 Tkinter proof-of-concept remains untouched and is now treated as the reference extractor.

The app now has a native Windows desktop UI. You do not need to open a browser for normal desktop use.

## What Is Included

- Native PySide6 desktop app with Dashboard, Import, Search, Photo Detail, Review Queue, and Export screens.
- FastAPI app remains available for future server deployment.
- SQLite persistence for local development with schema boundaries ready for PostgreSQL work later.
- Versioned extraction runs, raw OCR rows, raw barcode rows, structured entities, context guesses, review items, search history, clicks, feedback, and corrections.
- Modular extraction based on the v7 logic: HEIC/Pillow loading, zxing-cpp/pyzbar/OpenCV barcode scans, Tesseract OCR, strict serial parsing, printed-vs-barcode mismatch audit.
- Local threaded worker for long imports with visible progress.
- CLI scripts for initializing the database, checking schema version, importing a folder, and exporting serial rows.
- Ordered SQLite migrations, duplicate tracking, persistent import job records, FTS search text, and review resolution history.

## Windows Setup

Use Python 3.11 or 3.12 for the OCR stack.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Install the native Tesseract program:

```powershell
winget install --id UB-Mannheim.TesseractOCR -e --source winget
```

Edit `.env` for the home computer first. Later, move to the office machine by changing paths such as `PHOTO_STORAGE_ROOT`, `THUMBNAIL_ROOT`, and `IMPORT_FOLDER`.

Important `.env` values:

```text
APP_MODE=desktop
HOST=127.0.0.1
PORT=8001
STORAGE_MODE=copy
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

`STORAGE_MODE=reference` keeps the original file path as the evidence path. `STORAGE_MODE=copy` copies imported files into `PHOTO_STORAGE_ROOT` under a hash path like `ab/abcdef....jpg` while preserving `original_path`.

## Run Desktop App In Developer Mode

```powershell
.\run_app.bat
```

That activates `.venv` if present and runs `app.desktop.main`. Output is written to `logs/dev_startup.log`.

Manual commands:

```powershell
python scripts\init_db.py
python scripts\schema_version.py
python -m app.desktop.main
```

The browser/API app is still available for server-style development:

```powershell
python -m app.main
```

## Build Portable Windows Folder

```powershell
python scripts\build_windows_portable.py
```

Output:

```text
dist\PhotoIntelligence\
dist\PhotoIntelligence\PhotoIntelligence.exe
dist\PhotoIntelligence\run_app.bat
dist\PhotoIntelligence\.env
dist\PhotoIntelligence\.venv\
dist\PhotoIntelligence\src\
dist\PhotoIntelligence\data\
dist\PhotoIntelligence\storage\photos\
dist\PhotoIntelligence\photos\
dist\PhotoIntelligence\logs\
```

The EXE is only a small launcher. The editable source code remains visible in `dist\PhotoIntelligence\src`.

Clean local build/cache artifacts before creating a GitHub source package:

```powershell
python scripts\clean_project.py --keep-dist
```

Omit `--keep-dist` when you want to remove the portable build output too.

## Search Modes

Desktop and API search support two modes:

- Fast Search: exact structured entities plus SQLite FTS candidates.
- Deep Search: full corpus scan/ranking fallback for cases where Fast Search did not find something you expect to exist.

API example:

```powershell
Invoke-WebRequest "http://127.0.0.1:8001/api/search?q=PO%2011234%20MT2331FT15720&mode=deep"
```

Search responses include diagnostics such as `candidate_count`, `total_photo_count`, `search_mode`, `used_deep_scan`, `warning`, and per-result match sources.

CLI import and export:

```powershell
python scripts\import_folder.py "C:\path\to\photos" --backend audit
python scripts\export_serial_rows.py
```

## Safety Rules

- Original photos are never deleted.
- `.venv`, `.env`, local databases, copied photos, thumbnails, exports, and temporary OCR/debug output are ignored by git.
- Raw OCR and raw barcode results are append-only evidence.
- Extraction runs are versioned by `EXTRACTOR_NAME` and `EXTRACTOR_VERSION`.
- Reprocessing can be forced, but regular imports skip files already processed by the same extractor version.
- Duplicate file hashes are recorded in `duplicate_files` instead of being silently lost.
- Printed serials and barcode serials remain separate. Mismatches enter the review queue.
- User corrections are stored separately and inserted as `user_corrected` entities.
- Search opens, feedback, and corrections are stored so ranking can learn conservatively over time.

## Current Limits

- The first database implementation is SQLite. PostgreSQL can be added behind the repository boundary.
- The worker is a local background thread. Redis/RQ or Celery can replace it without changing the extraction tables.
- PaddleOCR/vector search are intentionally future hooks, not active dependencies in this first pass.

## Moving Home To Office

Copy the entire `dist\PhotoIntelligence` folder to the office computer or shared drive. Edit `.env` in that copied folder:

- Keep `DATABASE_URL=sqlite:///data/photo_inventory.db` for a local portable database.
- Set `PHOTO_STORAGE_ROOT=storage/photos` for copied-photo mode, or use an absolute office/NAS path.
- Set `IMPORT_FOLDER` to the office photo drop folder if desired.
- Confirm `TESSERACT_CMD` points to the office computer's `tesseract.exe`.

Do not copy `.venv`, `data`, `storage`, `photos`, or `logs` into GitHub. They are runtime artifacts, not source.

## Serial Harvest

Serial Harvest is a simplified export workflow for inventory jobs where the user only needs serial numbers and source photo traceability.

Outputs:

- `serials_only.txt` - unique serial numbers only, one per line, ready for copy/paste.
- `serials_with_photos.csv` - deduplicated serial rows with source photo names, sequence grouping, and confidence.
- `review_needed_serials.csv` - uncertain serial candidates that need manual review.
- `serial_conflicts_by_photo.csv` - printed serials and QR/barcode serials shown side-by-side when they do not match.

Serial values are deduplicated by default. If the same serial appears in multiple photos, the simple TXT export keeps only one copy, while the CSV keeps traceability through photo names and duplicate counts.

Smart grouping uses import/photo sequence order instead of trusting file download dates. This helps separate serial batches when downloaded files share the same modified date.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
