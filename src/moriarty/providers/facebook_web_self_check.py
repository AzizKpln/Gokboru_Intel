from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable

from moriarty.services.phone_analyzer import PhoneAnalyzer


class FacebookWebSelfCheckError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FacebookProfileCandidate:
    display_name: str
    photo_url: str | None
    photo_path: str | None = None


@dataclass(frozen=True, slots=True)
class FacebookWebSelfCheckResult:
    source: str
    number: str
    status: str
    profiles: tuple[FacebookProfileCandidate, ...]
    page_url: str
    recovery_action_triggered: bool
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FacebookWebSelfCheckClient:
    """Observe a user-controlled Facebook recovery self-check.

    Moriarty never types the phone number, submits the lookup form, selects an
    account, or selects a recovery delivery method.
    """

    def __init__(self, analyzer: PhoneAnalyzer, *, timeout_seconds: float = 180.0) -> None:
        self.analyzer = analyzer
        self.timeout_seconds = timeout_seconds

    def check_own_number(
        self,
        number: str,
        region: str | None = None,
        *,
        confirm_save: Callable[[], bool] | None = None,
    ) -> FacebookWebSelfCheckResult:
        analysis = self.analyzer.analyze(number, region)
        if not analysis.is_valid:
            raise FacebookWebSelfCheckError("A valid phone number is required.")
        if os.name != "nt" and not (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY")):
            raise FacebookWebSelfCheckError("A visible browser requires DISPLAY or WAYLAND_DISPLAY.")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise FacebookWebSelfCheckError("Playwright is not installed. Run: bash install.sh") from exc

        with sync_playwright() as playwright:
            
            
            
            
            
            browser = playwright.chromium.launch(
                headless=False,
                args=(((["--ozone-platform=x11"] if os.name != "nt" else []) + ["--window-size=260,180", "--window-position=20,20"])),
            )
            context = browser.new_context(
                viewport={"width": 1365, "height": 900},
                screen={"width": 1365, "height": 900},
                locale="en-US",
            )
            try:
                page = context.new_page()
                page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30_000)
                self._open_forgot_password(page)
                page.locator('//*[@id="_r_2_"]').fill(analysis.e164)
                page.get_by_text("Continue", exact=True).click()
                deadline = time.monotonic() + self.timeout_seconds
                while time.monotonic() < deadline:
                    try:
                        body = page.locator("body").inner_text(timeout=2_000).lower()
                    except Exception:
                        break
                    if self._is_account_selection(page.url, body):
                        approved = "y" if confirm_save is not None else False
                        if not approved:
                            return FacebookWebSelfCheckResult(
                                "facebook_web_manual_self_check", analysis.e164, "consent_declined", (),
                                page.url, False, "The account-selection page was observed, but local extraction was not approved.",
                            )
                        
                        
                        
                        
                        raw = page.locator("body").evaluate(self._candidate_script())
                        if not isinstance(raw, list) or not raw:
                            raw = page.locator("body").evaluate(self._single_candidate_script())
                        profiles = self._normalize_candidates(raw)
                        profiles = self._save_rendered_profile_photos(
                            page, profiles, analysis.e164
                        )
                        return FacebookWebSelfCheckResult(
                            "facebook_web_manual_self_check", analysis.e164,
                            "found" if profiles else "page_changed", profiles, page.url, False,
                            (
                                "Visible account candidates were saved after explicit terminal confirmation. "
                                "No account or recovery delivery method was selected."
                                if profiles else
                                "Facebook showed an account-selection page, but its visible profile cards could not be parsed."
                            ),
                        )
                    if self._is_no_result(body):
                        return FacebookWebSelfCheckResult(
                            "facebook_web_manual_self_check", analysis.e164, "not_found", (), page.url, False,
                            "Facebook displayed no matching account after the user manually submitted their own number.",
                        )
                    page.wait_for_timeout(500)
                return FacebookWebSelfCheckResult(
                    "facebook_web_manual_self_check", analysis.e164, "manual_check_incomplete", (), page.url, False,
                    "No conclusive Facebook self-check result was observed before timeout.",
                )
            finally:
                context.close()
                browser.close()

    @staticmethod
    def _is_account_selection(url: str, body: str) -> bool:
        body = body.lower()
        phrases = (
            "choose your account", "select your account", "hesabını seç", "hesabini seç",
            "these facebook profiles match", "bu facebook profilleri",
            "choose a way to log in", "giriş yapmanın bir yolunu seç", "giris yapmanin bir yolunu sec",
        )
        result_page = "/login/identify" in url or "/recover/initiate" in url
        return result_page and any(phrase in body for phrase in phrases)

    @staticmethod
    def _open_forgot_password(page: Any) -> None:
        if "/login/identify" in page.url:
            return
        label = re.compile(
            r"forgot (?:your )?password|şifreni mi unuttun|şifremi unuttum|parolanı mı unuttun",
            re.I,
        )
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            candidates = (
                page.locator("a[href*='/login/identify']"),
                page.locator("a[href*='/recover/initiate']"),
                page.get_by_role("link", name=label),
                page.get_by_role("button", name=label),
                page.get_by_text(label, exact=False),
            )
            for locator in candidates:
                try:
                    if locator.count() and locator.first.is_visible():
                        locator.first.click(timeout=5_000)
                        page.wait_for_url(
                            re.compile(r"facebook\.com/(?:login/identify|recover/)", re.I),
                            wait_until="domcontentloaded",
                            timeout=20_000,
                        )
                        return
                except Exception:
                    continue
            page.wait_for_timeout(500)

        
        
        
        page.goto(
            "https://www.facebook.com/login/identify/",
            wait_until="domcontentloaded",
            timeout=30_000,
        )

    @staticmethod
    def _is_no_result(body: str) -> bool:
        body = body.lower()
        phrases = (
            "no search results", "your search did not return any results", "account not found",
            "no account found", "check your mobile number or email address and try again",
            "arama sonucu yok", "hesap bulunamadı", "hesap bulunamadi",
        )
        return any(phrase in body for phrase in phrases)

    @staticmethod
    def _candidate_script() -> str:
        return r"""
        () => {
          const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
          const ignored = new Set([
            'choose your account', 'select your account', 'hesabını seç', 'hesabini seç',
            'choose a way to log in', 'giriş yapmanın bir yolunu seç',
            'log in', 'login', 'giriş yap', 'forgot password', 'şifreni mi unuttun',
            'create new account', 'yeni hesap oluştur', 'back', 'geri',
            'english (uk)', 'türkçe', 'more languages...', 'facebook',
            'get code via sms', 'continue with password', 'use your password to continue',
            'no longer have access to these?', 'continue', 'not you?'
          ]);
          const visible = element => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none' &&
              rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < innerHeight;
          };
          const headings = [...document.querySelectorAll('h1, h2, [role="heading"]')];
          const heading = headings.find(element => {
            const text = normalize(element.innerText).toLowerCase();
            return text.includes('choose your account') || text.includes('select your account') ||
              text.includes('hesabını seç') || text.includes('hesabini seç') ||
              text.includes('choose a way to log in') ||
              text.includes('giriş yapmanın bir yolunu seç');
          });
          const headingBottom = heading ? heading.getBoundingClientRect().bottom : 100;
          const imageUrl = element => {
            const image = element.matches && element.matches('img') ? element : element.querySelector('img');
            if (image) {
              const src = image.currentSrc || image.src;
              if (src) return src;
            }
            const svgImage = element.querySelector('svg image');
            if (svgImage) {
              const href = svgImage.getAttribute('href') || svgImage.getAttribute('xlink:href');
              if (href) return href;
            }
            for (const node of [element, ...element.querySelectorAll('*')]) {
              const background = getComputedStyle(node).backgroundImage || '';
              const match = background.match(/^url\(["']?(.*?)["']?\)$/);
              if (match && match[1]) return match[1];
            }
            return null;
          };
          const cards = new Map();
          // Collect every semantic avatar. Facebook often exposes one such
          // node per account card; using querySelector here used to retain
          // only the first account.
          for (const avatar of document.querySelectorAll(
            '[role="img"][aria-label^="Profile picture,"]'
          )) {
            if (!visible(avatar)) continue;
            const name = normalize(
              (avatar.getAttribute('aria-label') || '')
                .replace(/^Profile picture,\s*/i, '')
            );
            if (!name) continue;
            const svgImage = avatar.querySelector('image');
            const photo = svgImage ? (
              svgImage.getAttribute('href') ||
              svgImage.getAttribute('xlink:href') ||
              svgImage.getAttributeNS('http://www.w3.org/1999/xlink', 'href') ||
              null
            ) : imageUrl(avatar);
            (svgImage || avatar).setAttribute('data-moriarty-profile-avatar', name);
            cards.set(name.toLowerCase(), {
              area: avatar.getBoundingClientRect().width * avatar.getBoundingClientRect().height,
              display_name: name,
              photo_url: photo
            });
          }
          // Single-account recovery pages split the avatar and text across
          // several nested divs. Start at each visible avatar and walk upward
          // until its account label becomes available.
          for (const image of document.querySelectorAll('img')) {
            if (!visible(image)) continue;
            const imageRect = image.getBoundingClientRect();
            if (imageRect.width < 24 || imageRect.height < 24 ||
                imageRect.width > 180 || imageRect.height > 180) continue;
            if (imageRect.top < headingBottom || imageRect.top > headingBottom + 350) continue;
            let container = image.parentElement;
            for (let depth = 0; container && depth < 12; depth += 1, container = container.parentElement) {
              const rect = container.getBoundingClientRect();
              if (rect.height > 180 || rect.top < headingBottom) continue;
              const lines = (container.innerText || '').split(/\n+/).map(normalize).filter(Boolean);
              const name = lines.find(line =>
                line.length <= 100 &&
                !ignored.has(line.toLowerCase()) &&
                !/^get code via /i.test(line) &&
                !/^continue with /i.test(line)
              );
              if (!name) continue;
              const key = name.toLowerCase();
              if (!cards.has(key)) {
                cards.set(key, {
                  area: rect.width * rect.height,
                  display_name: name,
                  photo_url: image.currentSrc || image.src || null
                });
              }
              break;
            }
          }

          // Keep the earlier card-based path for Facebook's multi-account
          // layout, where each candidate is a conventional clickable row.
          for (const element of document.querySelectorAll('a, [role="button"], div')) {
            if (!visible(element)) continue;
            const rect = element.getBoundingClientRect();
            if (rect.top < headingBottom || rect.top > headingBottom + 500) continue;
            if (rect.width < 240 || rect.height < 45 || rect.height > 150) continue;
            // Recovery-method rows also contain radio-button SVGs. Requiring an
            // actual image/background keeps only account cards with avatars.
            if (!element.querySelector('img, svg image, [role="img"], [style*="background-image"]')) continue;
            const lines = (element.innerText || '').split(/\n+/).map(normalize).filter(Boolean);
            const name = lines.find(line => line.length <= 100 && !ignored.has(line.toLowerCase()));
            if (!name) continue;
            const area = rect.width * rect.height;
            const previous = cards.get(name.toLowerCase());
            if (!previous || (!previous.photo_url && area < previous.area)) {
              cards.set(name.toLowerCase(), {
                area,
                display_name: name,
                photo_url: imageUrl(element)
              });
            }
          }
          return [...cards.values()].map(({display_name, photo_url}) => ({display_name, photo_url}));
        }
        """

    @staticmethod
    def _single_candidate_script() -> str:
        return r"""
        () => {
          const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
          const semanticAvatar = document.querySelector(
            '[role="img"][aria-label^="Profile picture,"]'
          );
          if (semanticAvatar) {
            const displayName = normalize(
              (semanticAvatar.getAttribute('aria-label') || '')
                .replace(/^Profile picture,\s*/i, '')
            );
            const svgImage = semanticAvatar.querySelector('image');
            const photoUrl = svgImage ? (
              svgImage.getAttribute('href') ||
              svgImage.getAttribute('xlink:href') ||
              svgImage.getAttributeNS('http://www.w3.org/1999/xlink', 'href') ||
              null
            ) : null;
            (svgImage || semanticAvatar)
              .setAttribute('data-moriarty-single-avatar', '1');
            if (displayName) return [{display_name: displayName, photo_url: photoUrl}];
          }
          const ignored = new Set([
            'choose a way to log in', 'facebook', 'get code via sms',
            'get code via email', 'continue with password',
            'use your password to continue', 'no longer have access to these?',
            'continue', 'not you?', 'english (uk)', 'türkçe',
            'more languages...'
          ]);
          const lines = (document.body.innerText || '')
            .split(/\n+/).map(normalize).filter(Boolean);
          const headingIndex = lines.findIndex(line =>
            line.toLowerCase().includes('choose a way to log in') ||
            line.toLowerCase().includes('giriş yapmanın bir yolunu seç')
          );
          if (headingIndex < 0) return [];
          let displayName = null;
          for (const line of lines.slice(headingIndex + 1)) {
            const lower = line.toLowerCase();
            if (ignored.has(lower) || /^get code via /i.test(line) ||
                /^continue with /i.test(line)) continue;
            if (line.length <= 100) {
              displayName = line;
              break;
            }
          }
          if (!displayName) return [];

          const heading = [...document.querySelectorAll('h1, h2, [role="heading"]')]
            .find(element => normalize(element.innerText).toLowerCase()
              .includes('choose a way to log in'));
          const headingBottom = heading ? heading.getBoundingClientRect().bottom : 100;
          let best = null;
          for (const element of document.querySelectorAll('img, svg, div, span')) {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            if (style.display === 'none' || style.visibility === 'hidden') continue;
            if (rect.width < 30 || rect.height < 30 || rect.width > 120 || rect.height > 120) continue;
            if (Math.abs(rect.width - rect.height) > 20) continue;
            if (rect.top < headingBottom || rect.top > headingBottom + 180) continue;
            const background = style.backgroundImage || '';
            const hasVisual = element.tagName === 'IMG' || element.tagName === 'SVG' ||
              (background && background !== 'none');
            if (!hasVisual) continue;
            let score = 0;
            if (element.tagName === 'IMG') score += 10;
            if (background !== 'none') score += 8;
            if (element.tagName === 'SVG') score += 4;
            if (parseFloat(style.borderRadius || '0') >= rect.width / 3) score += 3;
            score += Math.min(rect.width, rect.height) / 100;
            if (!best || score > best.score) best = {element, score, background};
          }
          let photoUrl = null;
          if (best) {
            best.element.setAttribute('data-moriarty-single-avatar', '1');
            if (best.element.tagName === 'IMG') {
              photoUrl = best.element.currentSrc || best.element.src || null;
            } else {
              const match = (best.background || '').match(/^url\(["']?(.*?)["']?\)$/);
              if (match) photoUrl = match[1];
            }
          }
          return [{display_name: displayName, photo_url: photoUrl}];
        }
        """

    @staticmethod
    def _normalize_candidates(raw: Any) -> tuple[FacebookProfileCandidate, ...]:
        if not isinstance(raw, list):
            return ()
        results: list[FacebookProfileCandidate] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = " ".join(str(item.get("display_name") or "").split()).strip()
            if not name or len(name) > 100 or name.casefold() in seen:
                continue
            photo = str(item.get("photo_url") or "").strip() or None
            if photo is not None and not photo.startswith(("https://", "http://")):
                photo = None
            seen.add(name.casefold())
            results.append(FacebookProfileCandidate(name, photo))
        return tuple(results)

    @staticmethod
    def _save_rendered_profile_photos(
        page: Any,
        profiles: tuple[FacebookProfileCandidate, ...],
        number: str,
    ) -> tuple[FacebookProfileCandidate, ...]:
        output_dir = (
            Path.home()
            / ".local/share/moriarty-v5/facebook/photos"
            / number.lstrip("+")
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[FacebookProfileCandidate] = []
        for index, profile in enumerate(profiles, start=1):
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", profile.display_name).strip("_") or "profile"
            path = output_dir / f"{index:02d}_{safe_name}.png"
            saved = False
            errors: list[str] = []

            
            
            if profile.photo_url:
                try:
                    rendered = page.locator("img")
                    for candidate_index in range(rendered.count()):
                        candidate = rendered.nth(candidate_index)
                        current = candidate.evaluate("el => el.currentSrc || el.src || ''")
                        if current == profile.photo_url and candidate.is_visible():
                            candidate.screenshot(path=str(path), type="png")
                            saved = path.is_file() and path.stat().st_size > 0
                            if saved:
                                break
                    if not saved:
                        visible_avatars = page.locator('img[src*="profile/pic.php"]')
                        avatar_index = index - 1
                        if visible_avatars.count() > avatar_index and visible_avatars.nth(avatar_index).is_visible():
                            visible_avatars.nth(avatar_index).screenshot(path=str(path), type="png")
                            saved = path.is_file() and path.stat().st_size > 0
                except Exception as exc:
                    errors.append(f"rendered image: {exc}")

            
            
            if not saved and profile.photo_url:
                try:
                    response = page.context.request.get(profile.photo_url, timeout=20_000)
                    content_type = response.headers.get("content-type", "").lower()
                    if response.ok and content_type.startswith("image/"):
                        suffix = ".png" if "png" in content_type else ".webp" if "webp" in content_type else ".jpg"
                        path = output_dir / f"{index:02d}_{safe_name}{suffix}"
                        path.write_bytes(response.body())
                        saved = path.is_file() and path.stat().st_size > 0
                except Exception as exc:
                    errors.append(f"image response: {exc}")

            
            
            if not saved and profile.photo_url:
                photo_page = None
                try:
                    photo_page = page.context.new_page()
                    photo_page.goto(profile.photo_url, wait_until="load", timeout=20_000)
                    image = photo_page.locator("img").first
                    image.wait_for(state="visible", timeout=10_000)
                    image.screenshot(path=str(path), type="png")
                    saved = path.is_file() and path.stat().st_size > 0
                except Exception as exc:
                    errors.append(f"photo URL: {exc}")
                finally:
                    if photo_page is not None:
                        photo_page.close()

            
            
            if not saved:
                try:
                    marked_avatar = page.locator('[data-moriarty-single-avatar="1"]')
                    if len(profiles) == 1 and marked_avatar.count() and marked_avatar.first.is_visible():
                        marked_avatar.first.screenshot(path=str(path), type="png")
                        saved = path.is_file() and path.stat().st_size > 0
                except Exception as exc:
                    errors.append(f"marked avatar: {exc}")

            
            
            
            if not saved:
                try:
                    name = page.get_by_text(profile.display_name, exact=True).first
                    name.wait_for(state="visible", timeout=5_000)
                    box = name.bounding_box()
                    if box:
                        viewport_width = int(page.evaluate("window.innerWidth"))
                        x = max(0.0, box["x"] - 100.0)
                        y = max(0.0, box["y"] - 30.0)
                        width = min(95.0, viewport_width - x)
                        page.screenshot(
                            path=str(path), type="png",
                            clip={"x": x, "y": y, "width": width, "height": 90.0},
                        )
                        saved = path.is_file() and path.stat().st_size > 0
                except Exception as exc:
                    errors.append(f"name crop: {exc}")

            if saved:
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
                downloaded.append(replace(profile, photo_path=str(path)))
            else:
                if errors:
                    print(
                        f"Facebook photo capture failed for {profile.display_name}: " + " | ".join(errors),
                        file=sys.stderr,
                    )
                downloaded.append(profile)
        return tuple(downloaded)
