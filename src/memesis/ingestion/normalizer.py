"""Versioned, deterministic normalisation for source records."""

from __future__ import annotations

import hashlib
import html
import re

NORMALIZER_VERSION = "phase2-v1"


def normalize_text(value: str) -> str:
    """Decode markup and stabilise whitespace without attempting semantic extraction."""
    no_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(no_tags)).strip()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
