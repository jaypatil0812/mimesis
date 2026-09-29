"""Optional OpenAI-compatible structured extraction adapter."""

from __future__ import annotations

import json
from typing import Any

import httpx

from memesis.domain.schemas import ExtractionMethod
from memesis.extraction.contracts import ExtractionResult


class OpenAICompatibleStructuredExtractor:
    """A replaceable JSON-only model client used for unresolved span packs."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_name: str,
        prompt_version: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.prompt_version = prompt_version
        self.timeout_seconds = timeout_seconds

    async def extract(self, text: str, *, context: dict[str, Any]) -> ExtractionResult:
        payload = {
            "model": self.model_name,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": self._instructions()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"span_pack": json.loads(text), "context": context},
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions", headers=headers, json=payload
            )
            response.raise_for_status()
        body = response.json()
        raw = body["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
        usage = body.get("usage", {})
        parsed.update(
            {
                "extraction_method": ExtractionMethod.EXTRACTED.value,
                "extraction_model": self.model_name,
                "prompt_version": self.prompt_version,
                "input_tokens": int(usage.get("prompt_tokens", 0)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
            }
        )
        return ExtractionResult.from_dict(parsed)

    @staticmethod
    def _instructions() -> str:
        return """You extract only explicit evidence from supplied spans.
Return one JSON object with arrays: entities, beliefs, relationships, ambiguous_spans.
Use only these node types: Person, Company, Market, Product, Event.
Do not return Content; it is deterministic. A belief must be a contestable proposition,
not a topic. Copy belief proposition text exactly from one supplied span. Every entity,
belief, and relationship must use original global start/end offsets from the span pack.
Relationships use edge_type, from_key, to_key, start, end, confidence, qualifiers.
Valid edges are BELIEVES, PUBLISHED, EXPRESSES, INFLUENCES, FOUNDED, WORKS_AT,
INVESTED_IN, ACTS_ON, BUILDS, SERVES, ADJACENT_TO, DEPENDS_ON, PRECEDES, AMPLIFIES,
PARTICIPATED_IN. Never infer identity from similar names. Put unresolved spans in
ambiguous_spans. Return no prose and do not invent facts or identifiers."""
