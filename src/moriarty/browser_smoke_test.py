from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any, Sequence


BROWSER_SOURCES = (
    "truecaller",
    "syncme",
    "facebook",
    "whatsapp",
    "cybernews",
    "databreach",
    "duckduckgo",
    "btk",
)


def _command(source: str, number: str, region: str, timeout: float, microsoft_mail: str | None) -> list[str]:
    base = [sys.executable, "-m", "moriarty"]
    common = [number, "--region", region, "--timeout", str(timeout), "--i-own-this-number"]
    commands = {
        "truecaller": base + ["truecaller-browser", *common, "--visible-browser"],
        "syncme": base + ["syncme-browser", *common, "--visible-browser"],
        "facebook": base + ["facebook-self-check", *common],
        "whatsapp": base + ["whatsapp-self-check", *common],
        "cybernews": base + ["cybernews-leak-check", *common],
        "databreach": base + ["databreach-leak-check", *common],
        "duckduckgo": base + ["duckduckgo-phone-search", *common, "--limit", "5"],
        "btk": base + ["btk-portability", *common],
    }
    command = commands[source]
    if microsoft_mail and source in {"truecaller", "syncme"}:
        command.extend(["--microsoft-mail", microsoft_mail])
    return command


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except (ProcessLookupError, OSError):
        process.kill()


def _json_payload(text: str) -> dict[str, Any] | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _result_status(returncode: int, payload: dict[str, Any] | None) -> str:
    if returncode != 0:
        return "failed"
    if not payload:
        return "completed"
    status = str(payload.get("status", "completed")).lower()
    if status in {"login_required", "authentication_failed", "manual_action_required", "subscription_required", "search_limit_exceeded"}:
        return "needs_attention"
    if status in {"failed", "error", "access_restricted"} or payload.get("error"):
        return "failed"
    return "completed"


def run_browser_smoke_test(
    number: str,
    region: str,
    sources: Sequence[str],
    timeout: float,
    output: str | None = None,
    microsoft_mail: str | None = None,
    microsoft_password: str | None = None,
) -> dict[str, Any]:
    selected = tuple(dict.fromkeys(item.strip().lower() for item in sources if item.strip()))
    unknown = tuple(item for item in selected if item not in BROWSER_SOURCES)
    if unknown:
        raise ValueError(f"Unknown browser source(s): {', '.join(unknown)}")
    if not selected:
        raise ValueError("Select at least one browser source.")

    results: list[dict[str, Any]] = []
    hard_timeout = max(15.0, timeout + 12.0)
    for index, source in enumerate(selected, 1):
        command = _command(source, number, region, timeout, microsoft_mail)
        print(f"\n[{index}/{len(selected)}] {source.upper()} — visible browser test", flush=True)
        started = monotonic()
        child_environment = os.environ.copy()
        if microsoft_password and source in {"truecaller", "syncme"}:
            child_environment["GOKBORU_BROWSER_TEST_PASSWORD"] = microsoft_password
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=(os.name == "posix"),
            env=child_environment,
        )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=hard_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop_process(process)
            stdout, stderr = process.communicate()
        duration = round(monotonic() - started, 2)
        payload = _json_payload(stdout) or _json_payload(stderr)
        status = "timeout" if timed_out else _result_status(process.returncode or 0, payload)
        note = "Provider exceeded its hard deadline; browser process was closed."
        if not timed_out:
            note = str((payload or {}).get("note") or (payload or {}).get("error") or "Test finished.")
        item = {
            "source": source,
            "status": status,
            "duration_seconds": duration,
            "return_code": process.returncode,
            "note": note,
            "result": payload,
            "stderr": stderr.strip()[-2000:] or None,
        }
        results.append(item)
        marker = "+" if status == "completed" else "!" if status == "needs_attention" else "-"
        print(f"[{marker}] {source}: {status} ({duration:.1f}s) — {note}", flush=True)

    report = {
        "schema_version": "1.0",
        "test": "visible_browser_smoke_test",
        "number": number,
        "region": region,
        "microsoft_login_tested": bool(microsoft_mail and microsoft_password),
        "generated_at": datetime.now().astimezone().isoformat(),
        "summary": {
            "requested": len(results),
            "completed": sum(item["status"] == "completed" for item in results),
            "needs_attention": sum(item["status"] == "needs_attention" for item in results),
            "failed": sum(item["status"] == "failed" for item in results),
            "timed_out": sum(item["status"] == "timeout" for item in results),
        },
        "results": results,
    }
    destination = Path(output).expanduser() if output else Path("reports") / f"browser-smoke-{datetime.now():%Y%m%d-%H%M%S}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report["report_path"] = str(destination.resolve())

    print("\nVISIBLE BROWSER TEST SUMMARY", flush=True)
    for item in results:
        print(f"  {item['source']:<12} {item['status']:<16} {item['duration_seconds']:>6.1f}s", flush=True)
    print(f"\nReport: {report['report_path']}", flush=True)
    return report
