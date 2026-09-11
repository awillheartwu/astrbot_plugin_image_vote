from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ImageProcessingUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ProcessedImage:
    main_path: Path
    thumbnail_path: Path
    original_size: int
    main_size: int
    thumbnail_size: int


class PillowImageProcessor:
    def __init__(
        self,
        image_format: str = "webp",
        max_width: int = 1920,
        max_height: int = 1920,
        quality: int = 82,
        thumbnail_width: int = 480,
        thumbnail_quality: int = 72,
        strip_metadata: bool = True,
    ):
        self.image_format = image_format.lower()
        self.max_width = max_width
        self.max_height = max_height
        self.quality = quality
        self.thumbnail_width = thumbnail_width
        self.thumbnail_quality = thumbnail_quality
        self.strip_metadata = strip_metadata

    def process(self, source_path: Path, main_path: Path, thumbnail_path: Path) -> ProcessedImage:
        try:
            from PIL import Image, ImageOps
        except ImportError as exc:
            raise ImageProcessingUnavailable("Pillow is required for report image processing") from exc

        source_size = source_path.stat().st_size
        main_path.parent.mkdir(parents=True, exist_ok=True)
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(str(source_path)) as source:
            image = ImageOps.exif_transpose(source).copy()
        image.thumbnail((self.max_width, self.max_height), Image.Resampling.LANCZOS)
        self._save(image, main_path, self.quality)
        thumbnail = image.copy()
        if thumbnail.width > self.thumbnail_width:
            target_height = max(1, int(thumbnail.height * self.thumbnail_width / float(thumbnail.width)))
            thumbnail = thumbnail.resize((self.thumbnail_width, target_height), Image.Resampling.LANCZOS)
        self._save(thumbnail, thumbnail_path, self.thumbnail_quality)
        return ProcessedImage(
            main_path=main_path,
            thumbnail_path=thumbnail_path,
            original_size=source_size,
            main_size=main_path.stat().st_size,
            thumbnail_size=thumbnail_path.stat().st_size,
        )

    def _save(self, image, path: Path, quality: int) -> None:
        format_name = "JPEG" if self.image_format in {"jpg", "jpeg"} else self.image_format.upper()
        save_image = image
        if format_name == "JPEG" and image.mode not in {"RGB", "L"}:
            save_image = image.convert("RGB")
        kwargs = {}
        if format_name in {"JPEG", "WEBP"}:
            kwargs["quality"] = quality
        if format_name == "WEBP":
            kwargs["method"] = 4
        if format_name == "PNG":
            kwargs["optimize"] = True
        if self.strip_metadata:
            kwargs["exif"] = b""
        save_image.save(str(path), format=format_name, **kwargs)
