from __future__ import annotations

import html
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable


TextLoader = Callable[[urllib.request.Request, float], tuple[int, str, str]]


@dataclass(frozen=True, slots=True)
class WebProfileSpec:
    name: str
    category: str
    url_template: str
    retired: bool = False


WEB_PROFILE_SPECS = (
    WebProfileSpec("facebook", "social_profile", "https://www.facebook.com/{username}"),
    WebProfileSpec("instagram", "social_profile", "https://www.instagram.com/{username}/"),
    WebProfileSpec("twitter", "social_profile", "https://x.com/{username}"),
    WebProfileSpec("tiktok", "social_profile", "https://www.tiktok.com/@{username}"),
    WebProfileSpec("pinterest", "social_profile", "https://www.pinterest.com/{username}/"),
    WebProfileSpec("tumblr", "social_profile", "https://{username}.tumblr.com/"),
    WebProfileSpec("twitch", "social_profile", "https://www.twitch.tv/{username}"),
    WebProfileSpec("dailymotion", "video_profile", "https://www.dailymotion.com/{username}"),
    WebProfileSpec("bitchute", "video_profile", "https://www.bitchute.com/channel/{username}/"),
    WebProfileSpec("scribd", "document_profile", "https://www.scribd.com/{username}"),
    WebProfileSpec("slideshare", "document_profile", "https://www.slideshare.net/{username}"),
    WebProfileSpec("archiveorg", "document_profile", "https://archive.org/details/@{username}"),
    WebProfileSpec("kaggle", "data_profile", "https://www.kaggle.com/{username}"),
    WebProfileSpec("replit", "developer_profile", "https://replit.com/@{username}"),
    WebProfileSpec("arduino", "developer_profile", "https://create.arduino.cc/projecthub/{username}"),
    WebProfileSpec("githubcommunity", "developer_profile", "https://github.com/orgs/community/discussions?discussions_q=author%3A{username}"),
    WebProfileSpec("weblate", "developer_profile", "https://hosted.weblate.org/user/{username}/"),
    WebProfileSpec("virustotal", "security_profile", "https://www.virustotal.com/gui/user/{username}"),
    WebProfileSpec("applediscussions", "community_profile", "https://discussions.apple.com/profile/{username}"),
    WebProfileSpec("skeb", "creative_profile", "https://skeb.jp/@{username}"),
    WebProfileSpec("picsart", "creative_profile", "https://picsart.com/u/{username}"),
    WebProfileSpec("inkbunny", "creative_profile", "https://inkbunny.net/{username}"),
    WebProfileSpec("gurushots", "creative_profile", "https://gurushots.com/{username}/photos"),
    WebProfileSpec("castingcallclub", "creative_profile", "https://castingcall.club/{username}"),
    WebProfileSpec("iconfinder", "creative_profile", "https://www.iconfinder.com/{username}"),
    WebProfileSpec("trakt", "entertainment_profile", "https://www.trakt.tv/users/{username}"),
    WebProfileSpec("minds", "social_profile", "https://www.minds.com/{username}/"),
    WebProfileSpec("tamtam", "social_profile", "https://tamtam.chat/{username}"),
    WebProfileSpec("hubski", "community_profile", "https://hubski.com/user/{username}"),
    WebProfileSpec("bodybuilding", "community_profile", "https://bodyspace.bodybuilding.com/{username}"),
    WebProfileSpec("clozemaster", "education_profile", "https://www.clozemaster.com/players/{username}"),
    WebProfileSpec("hexrpg", "gaming_profile", "https://www.hexrpg.com/userinfo/{username}"),
    WebProfileSpec("ninjak iwi".replace(" ", ""), "gaming_profile", "https://ninjakiwi.com/profile/{username}"),
    WebProfileSpec("mercadolivre", "marketplace_profile", "https://www.mercadolivre.com.br/perfil/{username}"),
    WebProfileSpec("shpock", "marketplace_profile", "https://www.shpock.com/shop/{username}/items"),
    WebProfileSpec("bazarcz", "marketplace_profile", "https://www.bazar.cz/{username}/"),
    WebProfileSpec("tagged", "social_profile", "https://www.tagged.com/profile.html?uid={username}"),
    WebProfileSpec("salon24", "blog_profile", "https://www.salon24.pl/u/{username}/"),
    WebProfileSpec("prvpl", "community_profile", "https://www.prv.pl/osoba/{username}"),
    WebProfileSpec("sv idbook".replace(" ", ""), "community_profile", "https://www.svidbook.ru/user/{username}"),
    WebProfileSpec("forumguns", "community_profile", "https://forum.guns.ru/forummisc/blog/{username}"),
    WebProfileSpec("magix", "music_profile", "https://www.magix.info/us/users/profile/{username}/"),
    WebProfileSpec("lolchess", "gaming_profile", "https://lolchess.gg/profile/na/{username}"),
    WebProfileSpec("authorstream", "document_profile", "http://www.authorstream.com/{username}/", True),
    WebProfileSpec("nitter", "retired_service", "https://nitter.net/{username}", True),
    WebProfileSpec("viddler", "retired_service", "https://www.viddler.com/channel/{username}/", True),
    WebProfileSpec("microsofttechnet", "retired_service", "https://social.technet.microsoft.com/profile/{username}/", True),
    WebProfileSpec("wanelo", "retired_service", "https://wanelo.co/{username}", True),
    WebProfileSpec("taringa", "retired_service", "https://www.taringa.net/{username}", True),
    WebProfileSpec("eyeem", "retired_service", "https://www.eyeem.com/u/{username}", True),
    WebProfileSpec("periscope", "retired_service", "https://www.periscope.tv/{username}/", True),
    WebProfileSpec("icq", "retired_service", "https://icq.im/{username}/en", True),
    WebProfileSpec("f3", "retired_service", "https://f3.cool/{username}", True),
    WebProfileSpec("anonup", "retired_service", "https://anonup.com/@{username}", True),
    WebProfileSpec("ulubpl", "retired_service", "http://ulub.pl/profil/{username}", True),
    WebProfileSpec("tldrlegal", "retired_service", "https://tldrlegal.com/users/{username}/", True),
)


class WebUsernameProbe:
    def __init__(self, *, timeout_seconds: float = 15.0, loader: TextLoader | None = None) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Web profile timeout must be greater than zero.")
        self.timeout_seconds = timeout_seconds
        self.loader = loader or self._load

    def lookup(self, spec: WebProfileSpec, username: str) -> dict[str, object]:
        if spec.retired:
            return {"source": spec.name, "status": "retired", "profile": None, "note": "The service or public profile route is retired/unreliable."}
        encoded = urllib.parse.quote(username, safe="")
        url = spec.url_template.format(username=encoded)
        request = urllib.request.Request(url, headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": "Mozilla/5.0 Moriarty-V5 username-audit/1.0"})
        try:
            status, body, final_url = self.loader(request, self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"source": spec.name, "status": "not_found", "profile": None}
            if exc.code in {401, 403, 429}:
                return {"source": spec.name, "status": "access_blocked", "profile": None, "http_status": exc.code}
            return {"source": spec.name, "status": "provider_error", "profile": None, "http_status": exc.code}
        except (OSError, urllib.error.URLError) as exc:
            return {"source": spec.name, "status": "provider_error", "profile": None, "note": str(exc)}
        if status != 200:
            return {"source": spec.name, "status": "provider_error", "profile": None, "http_status": status}
        lowered = html.unescape(body).casefold()
        not_found_markers = (
            "page not found", "page no longer exists", "profile not found", "user not found",
            "account doesn't exist", "account does not exist", "sorry, this page isn't available",
            "esta página não existe", "página não existe", "página no existe", "seite nicht gefunden",
            "страница не найдена", "ページが見つかりません", "존재하지 않는",
        )
        if any(marker in lowered for marker in not_found_markers):
            return {"source": spec.name, "status": "not_found", "profile": None}
        canonical = self._tag(body, "link", "rel", "canonical", "href") or self._tag(body, "meta", "property", "og:url", "content")
        title = self._tag(body, "meta", "property", "og:title", "content") or self._title(body)
        description = self._tag(body, "meta", "property", "og:description", "content")
        image = self._tag(body, "meta", "property", "og:image", "content")
        evidence_url = canonical or final_url
        exact_url_match = self._url_has_exact_username(evidence_url, username)
        body_has_username = username.casefold() in lowered
        generic_titles = {
            "arduino project hub", "trakt web: profile", "facebook", "instagram", "x", "twitter",
            "tiktok", "pinterest", "twitch", "scribd", "slideshare", "home", "welcome",
        }
        title_is_specific = bool(title and title.strip().casefold() not in generic_titles)
        if not (exact_url_match and body_has_username and title_is_specific):
            return {"source": spec.name, "status": "indeterminate", "profile": None, "page_url": final_url, "note": "The page responded, but exact-profile evidence was insufficient."}
        profile = {"username": username, "name": title, "bio": description, "avatar_url": image, "web_url": evidence_url}
        return {"source": spec.name, "status": "found", "confidence": 0.85, "profile": {key: value for key, value in profile.items() if value}}

    @staticmethod
    def _url_has_exact_username(url: str, username: str) -> bool:
        parsed = urllib.parse.urlparse(html.unescape(url))
        wanted = username.casefold()
        host_labels = [urllib.parse.unquote(part).casefold() for part in parsed.hostname.split(".")] if parsed.hostname else []
        path_parts = [urllib.parse.unquote(part).lstrip("@").casefold() for part in parsed.path.split("/") if part]
        query_values = [urllib.parse.unquote(value).lstrip("@").casefold() for values in urllib.parse.parse_qs(parsed.query).values() for value in values]
        return wanted in host_labels or wanted in path_parts or wanted in query_values

    @staticmethod
    def _tag(body: str, tag: str, key: str, expected: str, value_key: str) -> str | None:
        pattern = rf'<{tag}[^>]+{key}=["\']{re.escape(expected)}["\'][^>]+{value_key}=["\']([^"\']+)'
        match = re.search(pattern, body, re.IGNORECASE)
        if not match:
            reverse = rf'<{tag}[^>]+{value_key}=["\']([^"\']+)["\'][^>]+{key}=["\']{re.escape(expected)}["\']'
            match = re.search(reverse, body, re.IGNORECASE)
        return html.unescape(match.group(1)).strip() if match else None

    @staticmethod
    def _title(body: str) -> str | None:
        match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        return re.sub(r"\s+", " ", html.unescape(match.group(1))).strip() if match else None

    @staticmethod
    def _load(request: urllib.request.Request, timeout: float) -> tuple[int, str, str]:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(2_000_000).decode("utf-8", "replace"), response.geturl()
