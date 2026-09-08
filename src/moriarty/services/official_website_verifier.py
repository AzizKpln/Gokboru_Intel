from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from moriarty.domain.models import Evidence, ProviderOutput, Source
from moriarty.services.phone_analyzer import PhoneAnalyzer

_PHONE_PATTERN = re.compile(r"(?<!\w)\+?\d[\d\s()./-]{5,}\d(?!\w)")
_CONTACT_HINTS = ("contact", "about", "location", "iletisim", "iletişim", "kontakt")


@dataclass(frozen=True, slots=True)
class WebsiteVerification:
    business_name: str
    queried_number: str
    website: str
    verification_status: str
    matched_page: str | None
    matched_text: str | None
    checked_pages: tuple[str, ...]
    error: str | None = None


class OfficialWebsiteVerifier:
    name = "business_verification:official_website"

    def __init__(self, analyzer: PhoneAnalyzer, timeout_seconds: float = 10.0, loader=None, max_websites: int = 10, max_pages_per_site: int = 3) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Website timeout must be greater than zero.")
        if max_websites <= 0 or max_pages_per_site <= 0:
            raise ValueError("Website and page limits must be greater than zero.")
        self._analyzer, self._timeout = analyzer, timeout_seconds
        self._loader = loader or _load
        self._max_websites, self._max_pages = max_websites, max_pages_per_site

    def verify(self, raw_number: str, listings: tuple[dict, ...], default_region: str | None = None) -> ProviderOutput:
        phone = self._analyzer.analyze(raw_number, default_region)
        candidates = _unique_candidates(listings)[: self._max_websites]
        deadline = monotonic() + self._timeout
        verifications = tuple(self._verify_site(name, website, phone.e164, phone.region_code, deadline) for name, website in candidates)
        evidence = tuple(
            Evidence(
                kind="official_website_phone_match",
                value=item.business_name,
                source=Source(provider=self.name, url=item.matched_page),
                confidence=.98,
                attributes={"phone":item.queried_number,"website":item.website,"matched_text":item.matched_text},
            )
            for item in verifications if item.verification_status == "verified"
        )
        return ProviderOutput(
            data={"number":phone.e164,"count":len(verifications),"verified_count":len(evidence),"verifications":tuple(asdict(item) for item in verifications)},
            evidence=evidence,
        )

    def _verify_site(self, name: str, website: str, e164: str, region: str | None, deadline: float) -> WebsiteVerification:
        checked: list[str] = []
        try:
            root = _safe_url(website)
            queue = [root]
            seen: set[str] = set()
            while queue and len(checked) < self._max_pages:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise RuntimeError("Official website verification timed out.")
                url = queue.pop(0)
                if url in seen:
                    continue
                seen.add(url)
                loaded_url, html = self._loader(url, remaining)
                loaded_url = _same_origin_url(root, loaded_url)
                checked.append(loaded_url)
                page = _PageParser(); page.feed(html)
                match = _phone_match(page.text + " " + " ".join(page.tel_values), e164, region, self._analyzer)
                if match:
                    return WebsiteVerification(name,e164,root,"verified",loaded_url,match,tuple(checked))
                for link, label in page.links:
                    candidate = urljoin(loaded_url, link)
                    if any(hint in (candidate + " " + label).lower() for hint in _CONTACT_HINTS):
                        try:
                            candidate = _same_origin_url(root, candidate)
                        except ValueError:
                            continue
                        if candidate not in seen and candidate not in queue:
                            queue.append(candidate)
            return WebsiteVerification(name,e164,root,"not_found",None,None,tuple(checked))
        except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
            return WebsiteVerification(name,e164,website,"unreachable",None,None,tuple(checked),str(exc))


def _unique_candidates(listings: tuple[dict, ...]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in listings:
        website = str(item.get("website") or "").strip()
        if not website:
            continue
        try:
            key = _origin(_safe_url(website))
        except ValueError:
            continue
        if key not in seen:
            seen.add(key); found.append((str(item.get("name") or "Unnamed business"), website))
    return found


def _phone_match(text: str, expected: str, region: str | None, analyzer: PhoneAnalyzer) -> str | None:
    for match in _PHONE_PATTERN.finditer(text):
        candidate = match.group(0).strip()
        try:
            if analyzer.analyze(candidate, region).e164 == expected:
                return candidate
        except Exception:
            continue
    return None


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def _safe_url(url: str) -> str:
    value = url.strip()
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Unsafe website URL.")
    _validate_public_host(parts.hostname)
    return value


def _same_origin_url(root: str, candidate: str) -> str:
    value = _safe_url(candidate)
    if _origin(value) != _origin(root):
        raise ValueError("Website redirected outside its original domain.")
    return value


def _validate_public_host(host: str) -> None:
    if host.lower() == "localhost" or host.lower().endswith(".local"):
        raise ValueError("Local website addresses are not allowed.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise ValueError("Website hostname could not be resolved.") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Website resolves to a non-public address.")


def _load(url: str, timeout: float) -> tuple[str, str]:
    opener = build_opener(_SafeRedirect(_origin(url)))
    request = Request(url, headers={"User-Agent":"Moriarty-V5/0.1 (+official website verification)","Accept":"text/html,application/xhtml+xml","Accept-Language":"en-US,en;q=0.8"})
    with opener.open(request, timeout=timeout) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise RuntimeError(f"Unsupported website content type: {content_type}")
        return response.geturl(), response.read(2_000_000).decode(response.headers.get_content_charset() or "utf-8", errors="replace")


class _SafeRedirect(HTTPRedirectHandler):
    def __init__(self, allowed_origin: str) -> None:
        super().__init__()
        self._allowed_origin = allowed_origin
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin(_safe_url(newurl)) != self._allowed_origin:
            raise RuntimeError("Website redirected outside its original domain.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored = 0; self._href: str | None = None; self._label: list[str] = []
        self.text = ""; self.tel_values: list[str] = []; self.links: list[tuple[str,str]] = []
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {"script","style","noscript"}: self._ignored += 1
        if tag == "a":
            self._href = values.get("href"); self._label = []
            if self._href and self._href.lower().startswith("tel:"): self.tel_values.append(self._href[4:])
    def handle_data(self, data):
        if not self._ignored:
            self.text += " " + data
            if self._href is not None: self._label.append(data)
    def handle_endtag(self, tag):
        if tag in {"script","style","noscript"} and self._ignored: self._ignored -= 1
        if tag == "a" and self._href is not None:
            self.links.append((self._href," ".join(self._label))); self._href = None; self._label = []
