from __future__ import annotations

import base64
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from moriarty.providers.search_backend import SearchBackendError, _api_error_message


class GeminiDocumentOcr:
    """Reads image-only public PDFs and returns a small, structured phone match."""

    def __init__(self, api_key: str | None = None, model: str | None = None, response_loader=None) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._model = model or os.environ.get("GEMINI_OCR_MODEL") or os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self._response_loader = response_loader or _load_response

    @property
    def name(self) -> str:
        return f"gemini_document_ocr:{self._model}"

    def analyze(self, payload: bytes, expected_e164: str, timeout: float) -> dict:
        if not self._api_key:
            raise SearchBackendError("GEMINI_API_KEY is not set; document OCR cannot run.")
        endpoint = "https://generativelanguage.googleapis.com/v1beta/models/" + quote(self._model, safe="") + ":generateContent"
        prompt = (
            "OCR this public PDF. Determine whether it visibly contains the exact telephone number "
            f"{expected_e164}, allowing only formatting differences such as spaces, parentheses, a national trunk prefix, or hyphens. "
            "Never infer ownership and never substitute a similar number. Return JSON only. "
            "matched_text and context must be copied from visible document text. Use empty strings when unknown."
        )
        schema = {
            "type": "OBJECT",
            "properties": {
                "matched": {"type": "BOOLEAN"}, "matched_text": {"type": "STRING"},
                "context": {"type": "STRING"}, "page": {"type": "INTEGER"},
                "organization": {"type": "STRING"}, "department": {"type": "STRING"},
                "address": {"type": "STRING"}, "email": {"type": "STRING"},
            },
            "required": ["matched", "matched_text", "context", "page", "organization", "department", "address", "email"],
        }
        body = {
            "contents": [{"role": "user", "parts": [
                {"text": prompt},
                {"inlineData": {"mimeType": "application/pdf", "data": base64.b64encode(payload).decode("ascii")}},
            ]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": schema},
        }
        request = Request(endpoint, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key}, method="POST")
        try:
            response = json.loads(self._response_loader(request, timeout))
            text = "".join(str(part.get("text") or "") for candidate in response.get("candidates", ()) for part in candidate.get("content", {}).get("parts", ()))
            return json.loads(text)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SearchBackendError(f"Gemini OCR returned HTTP {exc.code}: {_api_error_message(detail)}") from exc
        except URLError as exc:
            raise SearchBackendError(f"Gemini OCR network error: {exc.reason}") from exc
        except TimeoutError as exc:
            raise SearchBackendError(f"Gemini OCR request timed out after {timeout:g}s.") from exc
        except (json.JSONDecodeError, UnicodeDecodeError, KeyError) as exc:
            raise SearchBackendError("Gemini OCR returned invalid structured JSON.") from exc


def _load_response(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        return response.read()
