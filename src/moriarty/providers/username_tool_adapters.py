from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, Mapping


class UsernameToolClient:
    """Adapters for optional open-source username tools.

    The tools run as child processes and their differing JSON formats are
    normalized into Moriarty's provider contract. A missing tool never aborts
    the rest of an audit.
    """

    def __init__(self, *, timeout_seconds: float = 120.0) -> None:
        self.timeout_seconds = max(5.0, float(timeout_seconds))

    def sherlock(self, username: str) -> dict[str, Any]:
        return self._run("sherlock", username, self._sherlock_command)

    def maigret(self, username: str) -> dict[str, Any]:
        return self._run("maigret", username, self._maigret_command)

    def socialscan(self, username: str) -> dict[str, Any]:
        return self._run("socialscan", username, self._socialscan_command)

    def blackbird(self, username: str) -> dict[str, Any]:
        return self._run("blackbird", username, self._blackbird_command)

    def gitfive(self, username: str) -> dict[str, Any]:
        return self._run("gitfive", username, self._gitfive_command)

    def _run(self, tool: str, username: str, builder: Any) -> dict[str, Any]:
        executable = self._find_executable(tool)
        if not executable:
            return {
                "source": tool,
                "status": "configuration_required",
                "profile": None,
                "profiles": [],
                "note": f"Optional local tool is not installed. Run: python -m pip install {self._package_name(tool)}",
            }
        with tempfile.TemporaryDirectory(prefix=f"moriarty-{tool}-") as directory:
            workdir = Path(directory)
            command = builder(executable, username, workdir)
            try:
                completed = subprocess.run(
                    command,
                    cwd=workdir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    check=False,
                    env={**os.environ, "NO_COLOR": "1"},
                )
            except subprocess.TimeoutExpired:
                return {"source": tool, "status": "provider_error", "profile": None, "profiles": [], "note": f"Timed out after {self.timeout_seconds:g} seconds."}
            except OSError as exc:
                return {"source": tool, "status": "provider_error", "profile": None, "profiles": [], "note": str(exc)}
            payloads = self._load_payloads(workdir, completed.stdout)
            if tool in {"sherlock", "blackbird", "gitfive"}:
                payloads.extend(self._load_sherlock_text(workdir, completed.stdout))
            profiles, checks = self._normalize(tool, username, payloads)
            conclusive = sum(check.get("status") in {"found", "not_found"} for check in checks)
            status = "found" if profiles else "not_found" if checks and conclusive == len(checks) else "partial" if checks else "provider_error"
            note = None
            if status == "provider_error":
                stderr = [line.strip() for line in completed.stderr.splitlines() if line.strip()]
                meaningful = [line for line in stderr if any(word in line.casefold() for word in ("error", "traceback", "exception", "usage:"))]
                note = (meaningful[-1] if meaningful else stderr[-1])[:500] if stderr else f"{tool} returned no readable output (exit {completed.returncode})."
            return {
                "source": tool,
                "status": status,
                "profile": None,
                "profiles": profiles,
                "checks": checks,
                "checked_count": len(checks),
                "found_count": len(profiles),
                "exit_code": completed.returncode,
                **({"note": note} if note else {}),
            }

    @staticmethod
    def _package_name(tool: str) -> str:
        packages = {"sherlock": "sherlock-project", "blackbird": "blackbird-osint", "gitfive": "git+https://github.com/mxrch/GitFive.git"}
        return packages.get(tool, tool)

    @staticmethod
    def _find_executable(name: str) -> str | None:
        configured = os.getenv(f"MORIARTY_{name.upper()}_COMMAND", "").strip()
        if configured and Path(configured).is_file():
            return configured
        
        
        adjacent = Path(sys.executable).parent / name
        candidates = (adjacent, adjacent.with_suffix(".exe"))
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return shutil.which(name)

    @staticmethod
    def _sherlock_command(executable: str, username: str, workdir: Path) -> list[str]:
        
        
        return [executable, username, "--folderoutput", str(workdir), "--print-found", "--no-color"]

    @staticmethod
    def _maigret_command(executable: str, username: str, workdir: Path) -> list[str]:
        return [executable, username, "--json", "simple", "--folderoutput", str(workdir)]

    @staticmethod
    def _socialscan_command(executable: str, username: str, workdir: Path) -> list[str]:
        return [executable, username, "--show-urls", "--json", str(workdir / "socialscan.json")]

    @staticmethod
    def _blackbird_command(executable: str, username: str, workdir: Path) -> list[str]:
        return [executable, "-u", username, "--json"]

    @staticmethod
    def _gitfive_command(executable: str, username: str, workdir: Path) -> list[str]:
        return [executable, "user", username]

    @staticmethod
    def _load_sherlock_text(workdir: Path, stdout: str) -> list[Any]:
        
        
        lines = ["\n".join(line for line in stdout.splitlines() if "[+]" in line)]
        for path in workdir.rglob("*.txt"):
            try:
                lines.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for text in lines:
            for url in re.findall(r"https?://[^\s\]\[<>'\"]+", text):
                url = url.rstrip(".,;:)")
                if url in seen:
                    continue
                seen.add(url)
                records.append({"url_user": url, "status": "found"})
        return records

    @staticmethod
    def _load_payloads(workdir: Path, stdout: str) -> list[Any]:
        payloads: list[Any] = []
        for path in workdir.rglob("*.json"):
            try:
                payloads.append(json.loads(path.read_text(encoding="utf-8", errors="replace")))
            except (OSError, json.JSONDecodeError):
                pass
        text = stdout.strip()
        if text:
            try:
                payloads.append(json.loads(text))
            except json.JSONDecodeError:
                for line in text.splitlines():
                    try:
                        payloads.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return payloads

    def _normalize(self, tool: str, username: str, payloads: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        records: list[tuple[str, Mapping[str, Any]]] = []
        for payload in payloads:
            self._collect_records(payload, "", records)
        profiles: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []
        seen: set[str] = set()
        for fallback_name, record in records:
            site = str(record.get("site") or record.get("platform") or record.get("name") or fallback_name or tool)
            url = str(record.get("url_user") or record.get("profile_url") or record.get("web_url") or record.get("url") or "")
            status = self._record_status(record)
            if not url and status == "found":
                url = self._social_profile_url(site, username)
            if site.startswith("{") or len(site) > 80:
                site = self._site_name_from_url(url) or tool
            if status == "found" and url and not self._url_mentions_username(url, username):
                status = "false_positive"
            if not url and status is None:
                continue
            check = {"site": site, "status": status or "unverified"}
            if url:
                check["url"] = url
            checks.append(check)
            if status != "found" or not url or url in seen:
                continue
            seen.add(url)
            profile = {"username": username, "name": site, "web_url": url, "tool": tool}
            for source_key, target_key in (("bio", "bio"), ("description", "bio"), ("avatar_url", "avatar_url"), ("photo", "avatar_url"), ("category", "category")):
                value = record.get(source_key)
                if value and target_key not in profile:
                    profile[target_key] = value
            profiles.append(profile)
        return profiles, checks

    @staticmethod
    def _url_mentions_username(url: str, username: str) -> bool:
        decoded = urllib.parse.unquote(url).casefold()
        wanted = username.casefold()
        return bool(re.search(rf"(?<![a-z0-9._-]){re.escape(wanted)}(?![a-z0-9._-])", decoded))

    @staticmethod
    def _site_name_from_url(url: str) -> str:
        match = re.match(r"https?://(?:www\.)?([^/]+)", url, re.I)
        return match.group(1).split(".")[0].replace("-", " ").title() if match else ""

    @staticmethod
    def _social_profile_url(site: str, username: str) -> str:
        templates = {
            "github": "https://github.com/{username}", "gitlab": "https://gitlab.com/{username}",
            "instagram": "https://www.instagram.com/{username}/", "twitter": "https://x.com/{username}",
            "reddit": "https://www.reddit.com/user/{username}/", "tumblr": "https://{username}.tumblr.com/",
            "lastfm": "https://www.last.fm/user/{username}", "snapchat": "https://www.snapchat.com/add/{username}",
            "yahoo": "https://profile.yahoo.com/{username}",
        }
        template = templates.get(site.casefold().replace(" ", ""), "")
        return template.format(username=username) if template else ""

    @classmethod
    def _collect_records(cls, value: Any, name: str, output: list[tuple[str, Mapping[str, Any]]]) -> None:
        if isinstance(value, list):
            for item in value:
                cls._collect_records(item, name, output)
        elif isinstance(value, Mapping):
            keys = {str(key).lower() for key in value}
            if keys & {"url_user", "profile_url", "web_url", "available", "exists", "claimed", "status"}:
                output.append((name, value))
            else:
                for key, item in value.items():
                    cls._collect_records(item, str(key), output)

    @classmethod
    def _record_status(cls, record: Mapping[str, Any]) -> str | None:
        if isinstance(record.get("available"), bool):
            return "not_found" if record["available"] else "found"
        for key in ("exists", "claimed"):
            if isinstance(record.get(key), bool):
                return "found" if record[key] else "not_found"
        raw: Any = record.get("status")
        if isinstance(raw, Mapping):
            raw = raw.get("status") or raw.get("name") or raw.get("value")
        text = str(raw or "").strip().casefold().replace("_", " ")
        if any(token in text for token in ("claimed", "found", "exists", "taken", "registered")):
            return "found"
        if any(token in text for token in ("available", "not found", "unclaimed", "does not exist")):
            return "not_found"
        return None
