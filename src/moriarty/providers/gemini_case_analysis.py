from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from moriarty.providers.search_backend import SearchBackendError, _api_error_message


class GeminiCaseAnalysis:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

    def analyze(self, investigation: dict, timeout: float = 60, language: str = "tr") -> dict:
        if not self.api_key:
            raise SearchBackendError("Gemini API anahtarı yapılandırılmamış.")
        endpoint = "https://generativelanguage.googleapis.com/v1beta/models/" + quote(self.model, safe="") + ":generateContent"
        evidence = {"subject": investigation.get("subject"), "summary": investigation.get("summary"), "sources": investigation.get("sources", [])}
        output_language = "English" if language == "en" else "Turkish"
        prompt = (
            "You are an evidence-focused analyst. Analyze only the supplied authorized phone-audit output. "
            "Separate observed facts from inferences. Never accuse a person of wrongdoing, never infer legal ownership, "
            f"and treat missing or blocked sources as unknown rather than clear. Write every human-readable value in {output_language}. Return concise JSON.\n\nAUDIT:\n"
            + json.dumps(evidence, ensure_ascii=False)
        )
        schema = {"type": "OBJECT", "properties": {
            "risk_level": {"type": "STRING", "enum": ["low", "medium", "high", "unknown"]},
            "confidence": {"type": "NUMBER"}, "executive_summary": {"type": "STRING"},
            "observed_facts": {"type": "ARRAY", "items": {"type": "STRING"}},
            "assessments": {"type": "ARRAY", "items": {"type": "STRING"}},
            "contradictions": {"type": "ARRAY", "items": {"type": "STRING"}},
            "limitations": {"type": "ARRAY", "items": {"type": "STRING"}},
            "recommended_actions": {"type": "ARRAY", "items": {"type": "STRING"}},
        }, "required": ["risk_level", "confidence", "executive_summary", "observed_facts", "assessments", "contradictions", "limitations", "recommended_actions"]}
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json", "responseSchema": schema}}
        request = Request(endpoint, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key}, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read())
            text = "".join(str(part.get("text") or "") for candidate in payload.get("candidates", ()) for part in candidate.get("content", {}).get("parts", ()))
            result = json.loads(text)
            result.update({"model": self.model, "generated_at": datetime.now(timezone.utc).isoformat(), "method": "gemini_evidence_analysis", "language": language})
            return result
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SearchBackendError(f"Gemini HTTP {exc.code}: {_api_error_message(detail)}") from exc
        except URLError as exc:
            raise SearchBackendError(f"Gemini bağlantı hatası: {exc.reason}") from exc
        except (json.JSONDecodeError, KeyError) as exc:
            raise SearchBackendError("Gemini geçerli analiz JSON'u döndürmedi.") from exc
