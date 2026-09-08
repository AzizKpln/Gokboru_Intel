from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from moriarty.providers.search_backend import SearchBackendError, _api_error_message


class GeminiWebIntelligence:
    def __init__(self, api_key: str | None = None, model: str | None = None, response_loader=None) -> None:
        self._api_key=api_key or os.environ.get("GEMINI_API_KEY")
        self._model=model or os.environ.get("GEMINI_WEB_INTELLIGENCE_MODEL") or os.environ.get("GEMINI_MODEL","gemini-3.5-flash-lite")
        self._response_loader=response_loader or _load_response

    def analyze(self,context:str,expected_e164:str,title:str,timeout:float)->dict:
        if not self._api_key:raise SearchBackendError("GEMINI_API_KEY is not set; web intelligence cannot run.")
        endpoint="https://generativelanguage.googleapis.com/v1beta/models/"+quote(self._model,safe="")+":generateContent"
        prompt=("Extract structured public information only from this visible web-page excerpt. Do not use outside knowledge or infer ownership. "
                "Every organization, department, address, email, additional phone, and website must appear verbatim in the excerpt. "
                f"The queried telephone {expected_e164} is already verified. Page title: {title}. Use empty values when unknown.\n\nEXCERPT:\n{context}")
        schema={"type":"OBJECT","properties":{
            "page_type":{"type":"STRING"},"language":{"type":"STRING"},"organization":{"type":"STRING"},"department":{"type":"STRING"},
            "queried_phone_role":{"type":"STRING"},"business_category":{"type":"STRING"},"address":{"type":"STRING"},
            "emails":{"type":"ARRAY","items":{"type":"STRING"}},
            "additional_phones":{"type":"ARRAY","items":{"type":"OBJECT","properties":{"raw":{"type":"STRING"},"role":{"type":"STRING"}},"required":["raw","role"]}},
            "websites":{"type":"ARRAY","items":{"type":"STRING"}},"confidence":{"type":"NUMBER"}},
            "required":["page_type","language","organization","department","queried_phone_role","business_category","address","emails","additional_phones","websites","confidence"]}
        body={"contents":[{"role":"user","parts":[{"text":prompt}]}],"generationConfig":{"temperature":0,"responseMimeType":"application/json","responseSchema":schema}}
        request=Request(endpoint,data=json.dumps(body).encode(),headers={"Content-Type":"application/json","x-goog-api-key":self._api_key},method="POST")
        try:
            response=json.loads(self._response_loader(request,timeout))
            text="".join(str(part.get("text") or "") for candidate in response.get("candidates",()) for part in candidate.get("content",{}).get("parts",()))
            return json.loads(text)
        except HTTPError as exc:
            detail=exc.read().decode("utf-8",errors="replace");raise SearchBackendError(f"Gemini web intelligence returned HTTP {exc.code}: {_api_error_message(detail)}") from exc
        except URLError as exc:raise SearchBackendError(f"Gemini web intelligence network error: {exc.reason}") from exc
        except TimeoutError as exc:raise SearchBackendError(f"Gemini web intelligence timed out after {timeout:g}s.") from exc
        except (json.JSONDecodeError,UnicodeDecodeError,KeyError) as exc:raise SearchBackendError("Gemini web intelligence returned invalid structured JSON.") from exc


def _load_response(request:Request,timeout:float)->bytes:
    with urlopen(request,timeout=timeout) as response:return response.read()
