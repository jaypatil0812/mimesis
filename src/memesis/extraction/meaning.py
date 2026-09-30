"""Conservative meaning and attribution features; these are not truth judgments."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from memesis.domain.schemas import Evidence

MEMORY_VERSION = "connected-memory-v2"


def meaning(text: str) -> dict[str, object]:
    return {
        "negated": bool(re.search(r"\b(not|never|cannot|can't|won't|unlikely|without)\b", text, re.I)),
        "conditions": re.findall(
            r"\b(?:if|unless|when|only for|provided that|for certain|in some|in (?:the|this|that|a|the same) (?:pilot|trial|study|workload))\b[^.;!?]*", text, re.I
        ),
        "time_expressions": re.findall(
            r"\b(?:20\d{2}|(?:next|last) (?:year|month|quarter|week)|within \d+ (?:days|months|years)|today|currently)\b",
            text, re.I,
        ),
        "qualified": bool(re.search(r"\b(some|many|only|may|might|could|sometimes)\b", text, re.I)),
    }


def attribution(text: str) -> str:
    if re.search(r"\b(disagree|reject|criticiz\w*|criticis\w*|dispute)\b", text, re.I):
        return "criticism"
    if re.search(r'["“”«»]|\b(according to|said|says|quoted|claims? that)\b', text, re.I):
        return "reported_or_quoted"
    if re.search(r"\b(I|we|my|our)\b", text, re.I):
        return "first_person"
    return "unattributed"


def canonical_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("source origin must be an absolute HTTP(S) URL")
    query = sorted((k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")
                   and k.lower() not in {"fbclid", "gclid"})
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), ""))


def source_family(evidence: Evidence) -> dict[str, str]:
    """Known derivation is explicit; similar wording alone never proves syndication."""
    for field in ("original_source_url", "syndicated_from", "repost_of"):
        value = evidence.metadata.get(field)
        if isinstance(value, str):
            try:
                origin = canonical_url(value)
                return {"id": "origin:" + hashlib.sha256(origin.encode()).hexdigest(),
                        "basis": field, "origin": origin}
            except ValueError:
                continue
    # Copies of the same normalized text form one evidence family, irrespective
    # of URL. This is observable duplication, not proof of author independence.
    text = evidence.normalized_text or evidence.raw_text
    digest = hashlib.sha256(" ".join(text.split()).encode()).hexdigest()
    return {"id": "text:" + digest, "basis": "exact_normalized_content",
            "origin": str(evidence.source_url)}
