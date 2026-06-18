from __future__ import annotations

import json
import warnings
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from finix_restore.models import ImageProfile

Image.MAX_IMAGE_PIXELS = None


class ImageProfiler:
    def profile(self, image_path: Path) -> ImageProfile:
        image_path = Path(image_path)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(image_path) as img:
                width, height = img.size
        pixels = width * height
        aspect = max(width, height) / max(1, min(width, height))
        if aspect >= 10 or height >= 30_000:
            doc_type = "long_strip"
        elif pixels >= 15_000_000 and 1.25 <= aspect <= 1.55:
            doc_type = "table_page"
        else:
            doc_type = "normal_page"
        if pixels >= 50_000_000:
            risk_level = "extreme"
        elif pixels >= 20_000_000:
            risk_level = "high"
        elif pixels >= 8_000_000:
            risk_level = "medium"
        else:
            risk_level = "low"
        return ImageProfile(
            file_name=image_path.name,
            path=image_path,
            width=width,
            height=height,
            pixels=pixels,
            aspect=aspect,
            doc_type=doc_type,
            risk_level=risk_level,
        )

    def profile_and_write(self, image_path: Path, profiles_dir: Path) -> ImageProfile:
        profile = self.profile(image_path)
        profiles_dir.mkdir(parents=True, exist_ok=True)
        payload = asdict(profile)
        payload["path"] = str(profile.path)
        out_path = profiles_dir / f"{Path(profile.file_name).stem}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return profile
