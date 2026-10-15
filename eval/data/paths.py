"""Filesystem layout. Large data lives under $EXEMPLAR_DATA_DIR (gitignored); small manifests live in eval/data/."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DATA = Path(__file__).resolve().parent  # committed configs and manifests

# Kitware annotation tree inside the sparse clone of gitlab.kitware.com/meva/meva-data-repo
ANNOT_SUBDIR = Path("annotation") / "DIVA-phase-2" / "MEVA" / "kitware"
S3_BUCKET = "mevadata-public-01"
S3_PREFIX = "drops-123-r13/"


def data_dir() -> Path:
    return Path(os.environ.get("EXEMPLAR_DATA_DIR") or REPO_ROOT / "data")


def meva_dir() -> Path:
    return data_dir() / "meva"


def repo_clone() -> Path:
    return meva_dir() / "meva-data-repo"


def annotation_dir() -> Path:
    return repo_clone() / ANNOT_SUBDIR


def videos_dir() -> Path:
    return meva_dir() / "videos"


def clips_dir() -> Path:
    return meva_dir() / "clips"


def roi_previews_dir() -> Path:
    return meva_dir() / "roi_previews"


def external_dir() -> Path:
    return data_dir() / "external"


def windows_dir() -> Path:
    return external_dir() / "windows"
