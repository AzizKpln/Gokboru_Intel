from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from moriarty.domain.models import InvestigationQuery
from moriarty.providers.brave_phone_search import BravePhoneSearchClient
from moriarty.providers.btk_number_portability import BTKNumberPortabilityClient
from moriarty.providers.cybernews_leak_check import CybernewsLeakCheckClient
from moriarty.providers.databreach_leak_check import DataBreachLeakCheckClient
from moriarty.providers.duckduckgo_phone_search import DuckDuckGoPhoneSearchClient
from moriarty.providers.ftc_dnc_complaints import FTCDNCClient
from moriarty.providers.github_phone_search import GitHubPhoneSearchClient
from moriarty.providers.hudsonrock_self_check import HudsonRockSelfCheckClient
from moriarty.providers.opensanctions_phone_search import OpenSanctionsPhoneSearchClient
from moriarty.providers.phonenumbers_provider import PhoneNumbersProvider
from moriarty.providers.reddit_phone_search import RedditPhoneSearchClient
from moriarty.providers.syncme_browser import SyncMeBrowserClient
from moriarty.providers.telegram_presence import TelegramPresenceClient, telegram_credentials
from moriarty.providers.truecaller_browser import TruecallerBrowserClient
from moriarty.providers.whatsapp_self_check import WhatsAppSelfCheckClient
from moriarty.providers.facebook_web_self_check import FacebookWebSelfCheckClient
from moriarty.providers.search_backend import GeminiGroundedSearchBackend
from moriarty.services.disposable_number import DisposableNumberService
from moriarty.services.investigation import InvestigationPipeline
from moriarty.services.pastebin_leak_audit import PastebinLeakAuditService
from moriarty.services.phone_analyzer import PhoneAnalyzer
from moriarty.services.phone_audit import DEFAULT_PHONE_AUDIT_SOURCES, PhoneAuditCore
from moriarty.services.reputation_summary import summarize_reputation
from moriarty.configuration import microsoft_credentials
from moriarty.web_runner_guard import run_unattended
from contextlib import redirect_stdout



from moriarty.cli import (
    _business_providers,
    _document_provider,
    _reputation_providers,
    _web_mentions_service,
    _with_website_verification,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moriarty-web-audit")
    parser.add_argument("number")
    parser.add_argument("--region")
    parser.add_argument("--sources", default="local")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-browser-fallback", action="store_true")
    parser.add_argument("--truecaller-profile-dir")
    parser.add_argument("--syncme-profile-dir")
    parser.add_argument("--telegram-account")
    parser.add_argument("--telegram-api-id", type=int)
    parser.add_argument("--telegram-api-hash")
    parser.add_argument("--telegram-session-path")
    parser.add_argument("--ftc-days", type=int, default=7)
    parser.add_argument("--gemini-model")
    parser.add_argument("--web-verify", action="store_true")
    parser.add_argument("--web-intelligence", action="store_true")
    parser.add_argument("--document-ocr", action="store_true")
    parser.add_argument("--document-intelligence", action="store_true")
    parser.add_argument("--i-own-this-number", action="store_true", required=True)
    return parser


def run(args: argparse.Namespace) -> dict:
    analyzer = PhoneAnalyzer(PhoneNumbersProvider())
    normalized = analyzer.analyze(args.number, args.region)
    if not normalized.is_valid:
        raise ValueError("A valid phone number is required.")

    selected = tuple(item.strip().lower() for item in args.sources.split(",") if item.strip())
    microsoft_email, microsoft_password = microsoft_credentials(clear_environment=True)
    if selected == ("all",):
        selected = tuple(source.name for source in DEFAULT_PHONE_AUDIT_SOURCES)

    def telegram_runner():
        if not args.telegram_account:
            return {"status": "configuration_required", "note": "Telegram account is not configured."}
        api_id, api_hash = telegram_credentials(args.telegram_api_id, args.telegram_api_hash)
        return TelegramPresenceClient(
            analyzer, api_id=api_id, api_hash=api_hash, session_path=args.telegram_session_path
        ).lookup_own_number(args.number, args.telegram_account, args.region)

    def reputation_runner():
        result = InvestigationPipeline(
            _reputation_providers(analyzer, args.timeout), args.timeout
        ).investigate(InvestigationQuery(args.number, args.region))
        payload = result.to_dict()
        payload["reputation_summary"] = summarize_reputation(result.providers)
        return payload

    def business_runner():
        result = InvestigationPipeline(
            _business_providers(analyzer, args.timeout), args.timeout
        ).investigate(InvestigationQuery(args.number, args.region))
        return _with_website_verification(result, analyzer, args.timeout).to_dict()

    def documents_runner():
        provider = _document_provider(
            analyzer, args.limit, args.timeout, args.document_ocr, 3,
            args.gemini_model, args.document_intelligence, 3,
        )
        return InvestigationPipeline((provider,), args.timeout).investigate(
            InvestigationQuery(args.number, args.region)
        ).to_dict()

    runners = {
        "local": lambda: {"status": "completed", **analyzer.analyze(args.number, args.region).to_dict()},
        "truecaller": lambda: TruecallerBrowserClient(analyzer, timeout_seconds=args.timeout, profile_dir=args.truecaller_profile_dir, headless=args.headless).lookup_own_number(args.number, args.region, auth_provider="microsoft", auth_email=microsoft_email, auth_password=microsoft_password),
        "syncme": lambda: SyncMeBrowserClient(analyzer, timeout_seconds=args.timeout, profile_dir=args.syncme_profile_dir, headless=args.headless).lookup_own_number(args.number, args.region, microsoft_email=microsoft_email, microsoft_password=microsoft_password),
        "telegram": telegram_runner,
        "facebook": lambda: FacebookWebSelfCheckClient(analyzer, timeout_seconds=args.timeout).check_own_number(args.number, args.region, confirm_save="y"),
        "whatsapp": lambda: WhatsAppSelfCheckClient(analyzer, timeout_seconds=args.timeout).check_own_number(args.number, args.region),
        "cybernews": lambda: CybernewsLeakCheckClient(analyzer, timeout_seconds=args.timeout, headless=args.headless).check_own_number(args.number, args.region),
        "databreach": lambda: DataBreachLeakCheckClient(analyzer, timeout_seconds=args.timeout, headless=args.headless).check_own_number(args.number, args.region),
        "hudsonrock": lambda: HudsonRockSelfCheckClient(analyzer, timeout_seconds=args.timeout).check_own_number(args.number, args.region),
        "github": lambda: GitHubPhoneSearchClient(analyzer, max_results=args.limit, timeout_seconds=args.timeout).search_own_number(args.number, args.region),
        "reddit": lambda: RedditPhoneSearchClient(analyzer, max_results=args.limit, timeout_seconds=args.timeout).search_own_number(args.number, args.region),
        "brave": lambda: BravePhoneSearchClient(analyzer, max_results=args.limit, timeout_seconds=args.timeout).search(args.number, args.region),
        "duckduckgo": lambda: DuckDuckGoPhoneSearchClient(analyzer, max_results=args.limit, timeout_seconds=args.timeout, browser_fallback=not args.no_browser_fallback, headless=args.headless).search(args.number, args.region),
        "web-mentions": lambda: _web_mentions_service(analyzer, args.limit, args.timeout, "gemini", args.web_verify, args.web_intelligence, 3, args.gemini_model).discover(args.number, args.region),
        "pastebin": lambda: PastebinLeakAuditService(analyzer, GeminiGroundedSearchBackend(model=args.gemini_model, timeout_seconds=args.timeout), max_results=args.limit).audit(args.number, args.region),
        "documents": documents_runner,
        "reputation": reputation_runner,
        "business": business_runner,
        "disposable": lambda: DisposableNumberService(analyzer, max_results=args.limit, timeout_seconds=min(args.timeout, 15.0)).check(args.number, args.region),
        "opensanctions": lambda: OpenSanctionsPhoneSearchClient(analyzer, max_results=args.limit, timeout_seconds=args.timeout).search(args.number, args.region),
        "ftc": lambda: FTCDNCClient(analyzer, coverage_days=args.ftc_days, timeout_seconds=args.timeout).search(args.number, args.region),
        "btk": lambda: BTKNumberPortabilityClient(analyzer, timeout_seconds=args.timeout, headless=args.headless).check(args.number, args.region),
    }
    result = PhoneAuditCore(DEFAULT_PHONE_AUDIT_SOURCES).run(
        number=normalized.e164, region=args.region, selected_sources=selected,
        runners={name: (lambda runner=runner: run_unattended(runner, args.timeout + 15, headless=args.headless)) for name, runner in runners.items()}
    )
    return result.to_dict()


def main() -> int:
    try:
        with redirect_stdout(sys.stderr):
            result = run(build_parser().parse_args())
    except Exception as exc:
        print(json.dumps({"error": str(exc) or type(exc).__name__}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
