"""Image preparation helpers for Pinterest-safe 2:3 assets."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImagePrepareResult:
    output_path: Path
    risk_notes: tuple[str, ...] = ()


def prepare_image(source: str | Path, output_dir: str | Path) -> ImagePrepareResult:
    """Copy the source into the run temp dir.

    The first implementation keeps image mutation conservative. A future pass can
    replace this with Sharp/Pillow resize logic without changing worker contracts.
    """

    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"source image not found: {source_path}")
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / source_path.name
    if source_path.resolve() != output_path.resolve():
        shutil.copyfile(source_path, output_path)
    return ImagePrepareResult(output_path=output_path)
