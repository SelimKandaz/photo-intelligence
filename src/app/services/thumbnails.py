from __future__ import annotations

from pathlib import Path


def create_thumbnail(image_path: Path, output_path: Path, max_size: int = 320) -> tuple[int, int] | None:
    try:
        from PIL import Image, ImageOps  # type: ignore
    except Exception:
        return None

    try:
        with Image.open(image_path) as src:
            img = ImageOps.exif_transpose(src)
            img.thumbnail((max_size, max_size))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(output_path, format="JPEG", quality=82)
            return img.size
    except Exception:
        return None

