from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from moriarty.domain.models import SearchResult


class SearchBackendError(RuntimeError):
    """Raised when the configured public search backend is unavailable."""


class SearchBackend(Protocol):
    @property
    def name(self) -> str: ...

    def search(self, query: str, limit: int) -> tuple[SearchResult, ...]: ...


ResponseLoader = Callable[[Request, float], bytes]


def list_gemini_models(api_key: str | None = None, timeout_seconds: float = 20.0, response_loader: ResponseLoader | None = None) -> tuple[dict, ...]:
    """Lists models available to the configured API key without generating tokens."""
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SearchBackendError("GEMINI_API_KEY is not set.")
    request = Request(
        "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
        headers={"x-goog-api-key": key},
    )
    loader = response_loader or _load_response
    try:
        response = json.loads(loader(request, timeout_seconds))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SearchBackendError(f"Gemini API returned HTTP {exc.code}: {_api_error_message(detail)}") from exc
    except URLError as exc:
        raise SearchBackendError(f"Gemini API network error: {exc.reason}") from exc
    except TimeoutError as exc:
        raise SearchBackendError(f"Gemini model listing timed out after {timeout_seconds:g}s.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SearchBackendError("Gemini model listing returned invalid JSON.") from exc
    models = []
    for item in response.get("models", ()):
        methods = tuple(item.get("supportedGenerationMethods") or ())
        if "generateContent" not in methods:
            continue
        models.append({
            "name": str(item.get("name") or "").removeprefix("models/"),
            "display_name": str(item.get("displayName") or ""),
            "methods": methods,
        })
    return tuple(models)


class GeminiGroundedSearchBackend:
    """Uses Gemini's managed Google Search grounding and citation metadata."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 30.0,
        response_loader: ResponseLoader | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Gemini timeout must be greater than zero.")
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._model = model or os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self._timeout_seconds = timeout_seconds
        self._response_loader = response_loader or _load_response

    @property
    def name(self) -> str:
        return f"gemini_google_search:{self._model}"

    def search(self, query: str, limit: int) -> tuple[SearchResult, ...]:
        if not self._api_key:
            raise SearchBackendError(
                "GEMINI_API_KEY is not set. Export a new Gemini API key before running."
            )
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{quote(self._model, safe='')}:generateContent"
        )
        prompt = (
            "Search the public web for pages matching this query: "
            f"{query}. Return only findings supported by web citations. "
            f"Find at most {max(1, limit)} distinct source pages. Do not infer ownership. "
            "Return a JSON object with a results array. Each result must contain title and the actual public destination URL, never a Google or Vertex AI redirect URL."
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0},
        }
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._api_key,
            },
            method="POST",
        )
        try:
            raw_response = self._response_loader(request, self._timeout_seconds)
            response = json.loads(raw_response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SearchBackendError(
                f"Gemini API returned HTTP {exc.code}: {_api_error_message(detail)}"
            ) from exc
        except URLError as exc:
            raise SearchBackendError(f"Gemini API network error: {exc.reason}") from exc
        except TimeoutError as exc:
            raise SearchBackendError(
                f"Gemini API request timed out after {self._timeout_seconds:g}s."
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SearchBackendError("Gemini API returned invalid JSON.") from exc

        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for result in _response_text_results(response):
            if result.url not in seen_urls:
                seen_urls.add(result.url);results.append(result)
                if len(results)>=limit:return tuple(results)
        for candidate in response.get("candidates", []):
            metadata = candidate.get("groundingMetadata", {})
            for chunk in metadata.get("groundingChunks", []):
                web = chunk.get("web") or {}
                url = str(web.get("uri") or "").strip()
                title = str(web.get("title") or url).strip()
                if url.startswith(("http://", "https://")) and url not in seen_urls:
                    seen_urls.add(url)
                    results.append(SearchResult(title=title, url=url))
                    if len(results) >= limit:
                        return tuple(results)
        return tuple(results)


def _response_text_results(response: dict) -> tuple[SearchResult, ...]:
    found=[]
    for candidate in response.get("candidates", ()):
        text="".join(str(part.get("text") or "") for part in candidate.get("content", {}).get("parts", ())).strip()
        if text.startswith("```"):
            text=text.split("\n",1)[-1].rsplit("```",1)[0].strip()
        try:payload=json.loads(text)
        except json.JSONDecodeError:continue
        items=payload.get("results", ()) if isinstance(payload,dict) else payload if isinstance(payload,list) else ()
        for item in items:
            if not isinstance(item,dict):continue
            url=str(item.get("url") or "").strip();title=str(item.get("title") or url).strip()
            if url.startswith(("http://","https://")) and "vertexaisearch.cloud.google.com/grounding-api-redirect/" not in url:
                found.append(SearchResult(title,url))
    return tuple(found)


def _load_response(request: Request, timeout: float) -> bytes:
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _api_error_message(raw_body: str) -> str:
    try:
        body = json.loads(raw_body)
        return str(body.get("error", {}).get("message") or "request failed")
    except json.JSONDecodeError:
        return "request failed"
