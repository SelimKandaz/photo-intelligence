# v7 Reference

The existing proof-of-concept was inspected at:

`<local legacy extractor path>`

This new project does not modify that file. The reusable parts were lifted into modules:

- `app/entity_parser/serials.py`: strict serial normalization from v7.
- `app/entity_parser/inventory.py`: printed S/N vs barcode audit, model/part/EAN parsing, PO/SO/entity extraction.
- `app/ocr/image_io.py`: HEIC/Pillow image loading and Tesseract executable discovery.
- `app/ocr/tesseract.py`: OCR text extraction and PDF text/OCR fallback.
- `app/barcode/scanner.py`: zxing-cpp, pyzbar, OpenCV, label crop, and barcode sub-crop scanning.
- `app/extraction/pipeline.py`: local audit pipeline that combines barcode, OCR, and entity parsing.

Important behavior preserved:

- Printed S/N and barcode S/N are stored separately.
- Barcode-only serials are useful evidence, but they do not silently replace printed label values.
- Printed-vs-barcode disagreement creates a review item.
- OCR-only serial-shaped guesses are review candidates, not clean serial rows.
- Raw OCR and raw barcode values are stored permanently with extraction run/version metadata.


