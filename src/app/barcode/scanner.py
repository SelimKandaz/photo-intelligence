from __future__ import annotations

from typing import Sequence

from app.entity_parser.serials import barcode_serials_from_values
from app.ocr.image_io import Image, ImageEnhance, ImageOps

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:
    cv2 = None
    np = None

try:
    import zxingcpp  # type: ignore
except Exception:
    zxingcpp = None

try:
    from pyzbar.pyzbar import decode as pyzbar_decode  # type: ignore
except Exception:
    pyzbar_decode = None


class BarcodeScanner:
    def detect_label_crops(self, img) -> list:
        if cv2 is None or np is None:
            return []
        try:
            rgb = np.array(img.convert("RGB"))
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            mask = cv2.inRange(gray, 0, 95)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 8))
            dilated = cv2.dilate(mask, kernel, iterations=2)
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            boxes = []
            width, height = img.size
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                area = w * h
                if not (3000 <= area <= width * height * 0.40):
                    continue
                if w < 110 or h < 35:
                    continue
                if w > width * 0.90 or h > height * 0.40:
                    continue
                pad_x = max(8, int(w * 0.08))
                pad_y = max(6, int(h * 0.10))
                x1 = max(0, x - pad_x)
                y1 = max(0, y - pad_y)
                x2 = min(width, x + w + pad_x)
                y2 = min(height, y + h + pad_y)
                boxes.append((x1, y1, x2, y2))

            boxes = sorted(boxes, key=lambda b: (b[1], b[0]))
            merged = []
            for box in boxes:
                x1, y1, x2, y2 = box
                duplicate = False
                for mx1, my1, mx2, my2 in merged:
                    ix1, iy1 = max(x1, mx1), max(y1, my1)
                    ix2, iy2 = min(x2, mx2), min(y2, my2)
                    if ix2 > ix1 and iy2 > iy1:
                        inter = (ix2 - ix1) * (iy2 - iy1)
                        area = (x2 - x1) * (y2 - y1)
                        if inter / max(1, area) > 0.55:
                            duplicate = True
                            break
                if not duplicate:
                    merged.append(box)
            return [img.crop(box) for box in merged[:30]]
        except Exception:
            return []

    def read_barcode_values_from_pil(self, item) -> list[str]:
        values: list[str] = []

        def add(value: str | None) -> None:
            text = str(value or "").strip()
            if text and text not in values:
                values.append(text)

        if item is None:
            return values

        if pyzbar_decode is not None:
            try:
                for result in pyzbar_decode(item):
                    try:
                        add(result.data.decode("utf-8", errors="ignore"))
                    except Exception:
                        add(str(result.data))
            except Exception:
                pass

        if zxingcpp is not None:
            try:
                for result in zxingcpp.read_barcodes(item):
                    add(getattr(result, "text", ""))
            except Exception:
                pass

        if cv2 is not None and np is not None and hasattr(cv2, "barcode_BarcodeDetector"):
            try:
                arr = np.array(item.convert("RGB"))
                detector = cv2.barcode_BarcodeDetector()
                out = detector.detectAndDecode(arr)
                decoded = []
                if isinstance(out, tuple):
                    for obj in out:
                        if isinstance(obj, str):
                            decoded.append(obj)
                        elif isinstance(obj, (list, tuple)):
                            decoded.extend([x for x in obj if isinstance(x, str)])
                for text in decoded:
                    add(text)
            except Exception:
                pass

        return values

    def barcode_image_variants(self, img) -> list:
        variants = []

        def add(im) -> None:
            if im is None:
                return
            try:
                max_dim = max(im.size)
                if max_dim > 2600:
                    scale = 2600 / max_dim
                    im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.Resampling.LANCZOS)
                variants.append(im)
            except Exception:
                pass

        add(img)
        try:
            gray = ImageOps.grayscale(img)
            add(gray)
            add(ImageEnhance.Contrast(gray).enhance(2.2))
        except Exception:
            pass

        try:
            for scale in (2, 3):
                if max(img.size) < 1600:
                    up = img.resize((img.width * scale, img.height * scale), Image.Resampling.LANCZOS)
                    add(up)
                    try:
                        add(ImageEnhance.Contrast(ImageOps.grayscale(up)).enhance(2.5))
                    except Exception:
                        pass
        except Exception:
            pass
        return variants[:12]

    def serial_barcode_subcrops(self, label_img) -> list:
        crops = []
        try:
            w, h = label_img.size
            boxes = [
                (0, int(h * 0.45), int(w * 0.68), h),
                (0, int(h * 0.35), int(w * 0.75), h),
                (0, 0, int(w * 0.60), int(h * 0.62)),
                (int(w * 0.28), 0, int(w * 0.72), int(h * 0.70)),
                (0, 0, w, h),
            ]
            for box in boxes:
                x1, y1, x2, y2 = box
                if x2 - x1 >= 40 and y2 - y1 >= 20:
                    crops.append(label_img.crop((x1, y1, x2, y2)))
        except Exception:
            pass
        return crops

    def decode_barcodes_deep(self, img, progress_callback=None) -> list[str]:
        values: list[str] = []

        def add_many(items: Sequence[str]) -> None:
            for value in items:
                text = str(value or "").strip()
                if text and text not in values:
                    values.append(text)

        def decode_one(im, note: str = "") -> None:
            if progress_callback and note:
                try:
                    progress_callback(note)
                except Exception:
                    pass
            for variant in self.barcode_image_variants(im):
                add_many(self.read_barcode_values_from_pil(variant))

        decode_one(img, "Barcode scan: full image")
        try:
            if not barcode_serials_from_values(values):
                decode_one(img.rotate(180, expand=True), "Barcode scan: rotated full image")
        except Exception:
            pass

        for idx, crop in enumerate(self.detect_label_crops(img), start=1):
            decode_one(crop, f"Barcode scan: label crop {idx}")
            for sub_idx, subcrop in enumerate(self.serial_barcode_subcrops(crop), start=1):
                decode_one(subcrop, f"Barcode scan: label {idx} zone {sub_idx}")
            try:
                decode_one(crop.rotate(180, expand=True), f"Barcode scan: rotated label crop {idx}")
            except Exception:
                pass
        return values

    def decode_barcodes_optional(self, img) -> list[str]:
        values: list[str] = []

        def add_many(items: Sequence[str]) -> None:
            for value in items:
                text = str(value or "").strip()
                if text and text not in values:
                    values.append(text)

        add_many(self.read_barcode_values_from_pil(img))
        if barcode_serials_from_values(values):
            return values
        try:
            add_many(self.read_barcode_values_from_pil(img.rotate(180, expand=True)))
        except Exception:
            pass
        return values

