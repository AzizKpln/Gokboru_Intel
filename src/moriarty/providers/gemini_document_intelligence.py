from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from moriarty.providers.search_backend import SearchBackendError, _api_error_message


class GeminiDocumentIntelligence:
    """Extracts source-grounded organization and contact fields from a verified snippet."""

    def __init__(self, api_key: str | None = None, model: str | None = None, response_loader=None) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._model = model or os.environ.get("GEMINI_INTELLIGENCE_MODEL") or os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self._response_loader = response_loader or _load_response

    def analyze(self, context: str, expected_e164: str, title: str, timeout: float) -> dict:
        if not self._api_key:
            raise SearchBackendError("GEMINI_API_KEY is not set; document intelligence cannot run.")
        endpoint = "https://generativelanguage.googleapis.com/v1beta/models/" + quote(self._model, safe="") + ":generateContent"
        prompt = (
            "Extract structured public contact information only from the supplied document excerpt. "
            "Do not use outside knowledge and do not infer ownership. Every organization, department, address, email, phone, and website value must appear verbatim in the excerpt. "
            f"The already verified queried number is {expected_e164}. Document title: {title}. "
            "Use empty strings or empty arrays for unknown values. Confidence must be between 0 and 1.\n\nEXCERPT:\n" + context
        )
        schema = {
            "type": "OBJECT",
            "properties": {
                "document_category": {"type": "STRING"}, "language": {"type": "STRING"},
                "organization": {"type": "STRING"}, "department": {"type": "STRING"},
                "queried_phone_role": {"type": "STRING"}, "address": {"type": "STRING"},
                "emails": {"type": "ARRAY", "items": {"type": "STRING"}},
                "additional_phones": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {"raw": {"type": "STRING"}, "role": {"type": "STRING"}}, "required": ["raw", "role"]}},
                "websites": {"type": "ARRAY", "items": {"type": "STRING"}},
                "confidence": {"type": "NUMBER"},
            },
            "required": ["document_category", "language", "organization", "department", "queried_phone_role", "address", "emails", "additional_phones", "websites", "confidence"],
        }
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": schema}}
        request = Request(endpoint, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key}, method="POST")
        try:
            response = json.loads(self._response_loader(request, timeout))
            text = "".join(str(part.get("text") or "") for candidate in response.get("candidates", ()) for part in candidate.get("content", {}).get("parts", ()))
            return json.loads(text)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SearchBackendError(f"Gemini document intelligence returned HTTP {exc.code}: {_api_error_message(detail)}") from exc
        except URLError as exc:
            raise SearchBackendError(f"Gemini document intelligence network error: {exc.reason}") from exc
        except TimeoutError as exc:
            raise SearchBackendError(f"Gemini document intelligence timed out after {timeout:g}s.") from exc
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError) as exc:
            raise SearchBackendError("Gemini document intelligence returned invalid structured JSON.") from exc


def _load_response(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        return response.read()
