from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from dataclasses import asdict, replace
from time import monotonic
from collections.abc import Sequence

from moriarty.domain.models import InvestigationQuery, InvestigationStatus, ProviderResult, ProviderStatus
from moriarty.providers.phone_investigation_provider import PhoneInvestigationProvider
from moriarty.providers.phonenumbers_provider import (
    PhoneNumberParseError,
    PhoneNumbersProvider,
)
from moriarty.services.phone_analyzer import PhoneAnalyzer
from moriarty.services.phone_audit import DEFAULT_PHONE_AUDIT_SOURCES, PhoneAuditCore
from moriarty.services.username_audit import DEFAULT_USERNAME_SOURCES, UsernameAuditCore, compact_username_audit, render_username_audit_text
from moriarty.providers.github_username import GitHubUsernameClient
from moriarty.providers.gitlab_username import GitLabUsernameClient
from moriarty.providers.public_username_profiles import PublicUsernameProfilesClient
from moriarty.providers.social_username_profiles import SocialUsernameProfilesClient
from moriarty.providers.web_username_probe import WEB_PROFILE_SPECS, WebUsernameProbe
from moriarty.providers.username_exposure import UsernameExposureClient
from moriarty.providers.whatsmyname_username import WhatsMyNameClient
from moriarty.providers.username_tool_adapters import UsernameToolClient
from moriarty.providers.fediverse_username import FediverseUsernameClient
from moriarty.providers.historical_username import HistoricalUsernameClient
from moriarty.webapp import serve_workspace
from moriarty.services.pastebin_leak_audit import PastebinLeakAuditService
from moriarty.services.investigation import InvestigationPipeline
from moriarty.providers.search_backend import GeminiGroundedSearchBackend, SearchBackendError, list_gemini_models
from moriarty.providers.cybernews_leak_check import CybernewsLeakCheckClient, CybernewsLeakCheckError
from moriarty.providers.databreach_leak_check import DataBreachLeakCheckClient, DataBreachLeakCheckError
from moriarty.providers.whatsapp_self_check import WhatsAppSelfCheckClient, WhatsAppSelfCheckError
from moriarty.providers.hudsonrock_self_check import HudsonRockSelfCheckClient, HudsonRockSelfCheckError
from moriarty.providers.github_phone_search import GitHubPhoneSearchClient, GitHubPhoneSearchError
from moriarty.providers.reddit_phone_search import RedditPhoneSearchClient, RedditPhoneSearchError
from moriarty.providers.brave_phone_search import BravePhoneSearchClient, BravePhoneSearchError
from moriarty.providers.duckduckgo_phone_search import DuckDuckGoPhoneSearchClient, DuckDuckGoPhoneSearchError
from moriarty.providers.opensanctions_phone_search import OpenSanctionsPhoneSearchClient, OpenSanctionsPhoneSearchError
from moriarty.providers.ftc_dnc_complaints import FTCDNCClient, FTCDNCError
from moriarty.providers.btk_number_portability import BTKNumberPortabilityClient, BTKNumberPortabilityError
from moriarty.providers.reputation_provider import (
    ShouldIAnswerUkProvider,
    PhoneSpamFilterProvider,
    EightHundredNotesProvider,
    WhoCallsMeProvider,
    PhoneyaProvider,
    CleverDialerProvider,
    WhoCalledTodayProvider,
    KimAriyorProvider,
    UnknownPhoneProvider,
    WhoCalledUkProvider,
)
from moriarty.providers.should_i_answer_uk import ShouldIAnswerUkClient
from moriarty.providers.phone_spam_filter import PhoneSpamFilterClient
from moriarty.providers.eight_hundred_notes import EightHundredNotesClient
from moriarty.providers.who_calls_me import WhoCallsMeClient
from moriarty.providers.phoneya import PhoneyaClient
from moriarty.providers.clever_dialer import CleverDialerClient
from moriarty.providers.who_called_today import WhoCalledTodayClient
from moriarty.providers.kim_ariyor import KimAriyorClient
from moriarty.providers.unknownphone import UnknownPhoneClient
from moriarty.providers.whocalled_uk import WhoCalledUkClient
from moriarty.providers.web_mentions_provider import WebMentionsProvider
from moriarty.services.web_mentions import WebMentionsService
from moriarty.services.reputation_summary import summarize_reputation
from moriarty.providers.osm_business import OsmBusinessClient
from moriarty.providers.business_listing_provider import OsmBusinessProvider
from moriarty.providers.wikidata_business import WikidataBusinessClient
from moriarty.providers.business_listing_provider import WikidataBusinessProvider
from moriarty.providers.firma_fihristi_business import FirmaFihristiBusinessClient
from moriarty.providers.business_listing_provider import FirmaFihristiBusinessProvider
from moriarty.providers.got_my_number_business import GotMyNumberBusinessClient
from moriarty.providers.business_listing_provider import GotMyNumberBusinessProvider
from moriarty.providers.telefon_org_business import TelefonOrgBusinessClient
from moriarty.providers.business_listing_provider import TelefonOrgBusinessProvider
from moriarty.providers.das_oertliche_business import DasOertlicheBusinessClient
from moriarty.providers.business_listing_provider import DasOertlicheBusinessProvider
from moriarty.providers.das_telefonbuch_business import DasTelefonbuchBusinessClient
from moriarty.providers.business_listing_provider import DasTelefonbuchBusinessProvider
from moriarty.services.document_discovery import DocumentDiscoveryService
from moriarty.providers.document_discovery_provider import DocumentDiscoveryProvider
from moriarty.providers.gemini_document_ocr import GeminiDocumentOcr
from moriarty.providers.gemini_document_intelligence import GeminiDocumentIntelligence
from moriarty.providers.gemini_web_intelligence import GeminiWebIntelligence
from moriarty.services.official_website_verifier import OfficialWebsiteVerifier
from moriarty.services.structured_contacts import extract_structured_contacts
from moriarty.services.web_page_verifier import load_public_html
from moriarty.services.domain_intelligence import DomainIntelligenceService
from moriarty.services.email_validation import EmailValidationService
from moriarty.providers.companies_house import CompaniesHouseClient
from moriarty.services.disposable_number import DisposableNumberService
from moriarty.providers.disposable_provider import DisposableNumberProvider
from moriarty.services.contact_payload import decode_qr_contacts,read_image
from moriarty.services.truecaller_consent import TruecallerConsentError, create_consent_request
from moriarty.providers.truecaller_browser import TruecallerBrowserClient, TruecallerBrowserError
from moriarty.providers.syncme_browser import SyncMeBrowserClient, SyncMeBrowserError
from moriarty.configuration import microsoft_credentials
from moriarty.providers.telegram_presence import (
    TelegramPresenceClient,
    TelegramPresenceError,
    telegram_credentials,
)
from moriarty.providers.facebook_web_self_check import (
    FacebookWebSelfCheckClient,
    FacebookWebSelfCheckError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moriarty")
    subparsers = parser.add_subparsers(dest="command", required=True)
    workspace = subparsers.add_parser("web-workspace", help="Start the local Gökbörü Intelligence workspace")
    workspace.add_argument("--host", default="127.0.0.1")
    workspace.add_argument("--port", type=int, default=8765)
    workspace.add_argument("--data-dir")
    workspace.add_argument("--no-browser", action="store_true")
    browser_test = subparsers.add_parser(
        "browser-smoke-test",
        help="Test every active browser provider visibly, one at a time, with hard timeouts",
    )
    browser_test.add_argument("number")
    browser_test.add_argument("--region", default="TR")
    browser_test.add_argument("--sources", default="all", help="Comma-separated names or all")
    browser_test.add_argument("--timeout", type=float, default=120.0, help="Per-provider timeout")
    browser_test.add_argument("--output")
    browser_test.add_argument("--microsoft-mail", help="Also test Truecaller/Sync.me Microsoft OAuth; password is prompted securely once")
    browser_test.add_argument("--list-sources", action="store_true")
    browser_test.add_argument("--i-own-this-number", action="store_true", required=True)
    phone = subparsers.add_parser("phone", help="Analyze a phone number")
    phone.add_argument("number")
    phone.add_argument("--region", help="Default two-letter region, e.g. TR")
    username_audit = subparsers.add_parser("username-audit", help="Find exact public profiles for a username")
    username_audit.add_argument("username")
    username_audit.add_argument("--sources", default="all", help="Comma-separated sources or all")
    username_audit.add_argument("--list-sources", action="store_true")
    username_audit.add_argument("--timeout", type=float, default=20.0)
    username_audit.add_argument("--github-token", help="Defaults to GITHUB_TOKEN")
    username_audit.add_argument("--breach-path", action="append", default=[], help="Local authorized dataset file/directory; may be repeated")
    username_audit.add_argument("--breachdirectory-key", help="Defaults to BREACHDIRECTORY_API_KEY or RAPIDAPI_KEY")
    username_audit.add_argument("--exposure-limit", type=int, default=20)
    username_audit.add_argument("--wmn-catalog", help="WhatsMyName catalog path; defaults to the local cache")
    username_audit.add_argument("--wmn-categories", default="", help="Comma-separated WhatsMyName categories")
    username_audit.add_argument("--wmn-limit", type=int, default=500)
    username_audit.add_argument("--wmn-refresh", action="store_true")
    username_audit.add_argument("--include-nsfw", action="store_true")
    username_audit.add_argument("--output", help="Save the displayed compact JSON (or full JSON with --full-json) to this file")
    username_audit.add_argument("--full-json", action="store_true", help="Include graph IDs, relationships and raw provider payloads")
    username_audit.add_argument("--format", choices=("json", "readable"), default="json", help="Terminal output format")
    username_audit.add_argument("--language", choices=("tr", "en"), default="en", help="Language for readable output")
    audit = subparsers.add_parser("phone-audit", help="Run the provider-neutral phone audit core")
    audit.add_argument("number")
    audit.add_argument("--region", help="Default two-letter region, e.g. TR")
    audit.add_argument("--sources", default="local", help="Comma-separated phone-audit source names")
    audit.add_argument("--list-sources", action="store_true")
    audit.add_argument("--output", help="Also save the complete audit JSON to this file")
    audit.add_argument("--limit", type=int, default=20)
    audit.add_argument("--timeout", type=float, default=30.0)
    audit.add_argument("--no-browser-fallback", action="store_true")
    audit.add_argument("--headless", action="store_true")
    audit.add_argument("--truecaller-profile-dir")
    audit.add_argument("--syncme-profile-dir")
    audit.add_argument("--telegram-account")
    audit.add_argument("--telegram-api-id", type=int)
    audit.add_argument("--telegram-api-hash")
    audit.add_argument("--telegram-session-path")
    audit.add_argument("--ftc-days", type=int, default=7)
    audit.add_argument("--gemini-model")
    audit.add_argument("--web-verify", action="store_true")
    audit.add_argument("--web-intelligence", action="store_true")
    audit.add_argument("--document-ocr", action="store_true")
    audit.add_argument("--document-intelligence", action="store_true")
    audit.add_argument("--i-own-this-number", action="store_true", required=True)
    investigate = subparsers.add_parser(
        "investigate", help="Run the investigation pipeline"
    )
    investigate.add_argument("number")
    investigate.add_argument("--region", help="Default two-letter region, e.g. TR")
    investigate.add_argument(
        "--timeout", type=float, default=120.0, help="Per-run provider timeout"
    )
    investigate.add_argument(
        "--web", action="store_true", help="Include public web mention discovery"
    )
    investigate.add_argument("--web-verify", action="store_true", help="Verify the phone in visible HTML")
    investigate.add_argument("--web-intelligence", action="store_true", help="Analyze verified web-page excerpts")
    investigate.add_argument("--disposable", action="store_true", help="Check public temporary-SMS directory signals")
    investigate.add_argument(
        "--reputation", action="store_true", help="Include regional reputation sources"
    )
    investigate.add_argument(
        "--business", action="store_true", help="Include public business listings"
    )
    investigate.add_argument("--documents", action="store_true", help="Find verified phone mentions in public documents")
    investigate.add_argument("--document-ocr", action="store_true", help="Use paid Gemini OCR for scanned public PDFs")
    investigate.add_argument("--document-intelligence", action="store_true", help="Extract structured fields from verified document matches")
    investigate.add_argument("--gemini-model", help="Gemini model used by document search and OCR")
    investigate.add_argument(
        "--web-engine",
        choices=("gemini",),
        default="gemini",
    )
    web = subparsers.add_parser(
        "web-mentions", help="Find public pages mentioning a phone number"
    )
    web.add_argument("number")
    web.add_argument("--region", help="Default two-letter region, e.g. TR")
    web.add_argument("--limit", type=int, default=10)
    web.add_argument("--timeout", type=float, default=120.0)
    web.add_argument("--engine", choices=("gemini",), default="gemini")
    web.add_argument("--verify", action="store_true", help="Verify the phone in visible HTML")
    web.add_argument("--intelligence", action="store_true", help="Analyze verified page excerpts with Gemini")
    web.add_argument("--intelligence-limit", type=int, default=3)
    web.add_argument("--model", help="Gemini model used by search and intelligence")
    reputation = subparsers.add_parser(
        "reputation", help="Check regional phone reputation sources"
    )
    reputation.add_argument("number")
    reputation.add_argument("--region", help="Default two-letter region, e.g. GB")
    reputation.add_argument("--timeout", type=float, default=8.0)
    business = subparsers.add_parser(
        "business-listings", help="Find public business listings for a phone number"
    )
    business.add_argument("number")
    business.add_argument("--region", help="Default two-letter region")
    business.add_argument("--timeout", type=float, default=15.0)
    documents = subparsers.add_parser("documents", help="Find phone mentions inside public PDF, DOCX, and XLSX files")
    documents.add_argument("number")
    documents.add_argument("--region", help="Default two-letter region")
    documents.add_argument("--limit", type=int, default=10)
    documents.add_argument("--timeout", type=float, default=60.0)
    documents.add_argument("--ocr", action="store_true", help="Use paid Gemini OCR for scanned PDFs")
    documents.add_argument("--ocr-limit", type=int, default=3, help="Maximum scanned PDFs sent to Gemini")
    documents.add_argument("--model", help="Gemini model used by search and OCR")
    documents.add_argument("--intelligence", action="store_true", help="Extract structured fields from verified matches")
    documents.add_argument("--intelligence-limit", type=int, default=3, help="Maximum verified snippets analyzed by Gemini")
    models = subparsers.add_parser("gemini-models", help="List Gemini models available to the API key")
    models.add_argument("--timeout", type=float, default=20.0)
    contacts=subparsers.add_parser("structured-contacts",help="Extract JSON-LD, tel, mailto, and structured public contacts")
    contacts.add_argument("url");contacts.add_argument("--region");contacts.add_argument("--timeout",type=float,default=15.0)
    domain=subparsers.add_parser("domain",help="Inspect public RDAP, DNS, MX, and TLS metadata")
    domain.add_argument("value");domain.add_argument("--timeout",type=float,default=10.0)
    email=subparsers.add_parser("email",help="Validate a public email without sending mail")
    email.add_argument("value");email.add_argument("--timeout",type=float,default=10.0)
    company=subparsers.add_parser("company-registry",help="Search the UK Companies House public registry")
    company.add_argument("name");company.add_argument("--limit",type=int,default=10);company.add_argument("--timeout",type=float,default=15.0)
    disposable=subparsers.add_parser("disposable",help="Check public temporary-SMS directory signals")
    disposable.add_argument("number");disposable.add_argument("--region");disposable.add_argument("--limit",type=int,default=10);disposable.add_argument("--timeout",type=float,default=12.0)
    qr=subparsers.add_parser("qr-contact",help="Decode public QR/vCard contact payloads locally")
    qr.add_argument("image");qr.add_argument("--region");qr.add_argument("--timeout",type=float,default=15.0)
    truecaller=subparsers.add_parser("truecaller-consent",help="Create an official user-consent Truecaller verification request")
    truecaller.add_argument("number");truecaller.add_argument("--region")
    truecaller.add_argument("--app-key",help="Truecaller app key; defaults to TRUECALLER_APP_KEY")
    truecaller.add_argument("--app-name",default="Moriarty V5")
    truecaller.add_argument("--privacy-url");truecaller.add_argument("--terms-url")
    truecaller.add_argument("--ttl",type=int,default=120000,help="Consent-screen lifetime in milliseconds")
    tc_browser=subparsers.add_parser("truecaller-browser",help="Look up your own number in a persistent Truecaller browser session")
    tc_browser.add_argument("number");tc_browser.add_argument("--region")
    tc_browser.add_argument("--timeout",type=float,default=90.0)
    tc_browser.add_argument("--profile-dir")
    tc_browser.set_defaults(headless=True)
    tc_browser.add_argument("--headless",dest="headless",action="store_true",help="Run without a visible browser window (default)")
    tc_browser.add_argument("--visible-browser",dest="headless",action="store_false",help="Show the browser window for login troubleshooting")
    tc_browser.add_argument("--google-email","--google-mail",dest="google_email",help="Google login email")
    tc_browser.add_argument("--auth-provider",choices=("microsoft","google"),default="microsoft")
    tc_browser.add_argument("--microsoft-mail",dest="microsoft_email",help="Microsoft/Hotmail login email")
    tc_browser.add_argument("--password",help="Login password (visible in shell history/process list); omit for a hidden prompt")
    tc_browser.add_argument("--i-own-this-number",action="store_true",required=True,help="Confirm that the queried number is yours")
    tc_login=subparsers.add_parser("truecaller-login",help="Open and persist an interactive Truecaller Google login session")
    tc_login.add_argument("--timeout",type=float,default=300.0)
    tc_login.add_argument("--profile-dir")
    syncme=subparsers.add_parser("syncme-browser",help="Look up your own number with a persistent Sync.me browser session")
    syncme.add_argument("number");syncme.add_argument("--region")
    syncme.add_argument("--timeout",type=float,default=90.0)
    syncme.add_argument("--profile-dir")
    syncme.set_defaults(headless=True)
    syncme.add_argument("--headless",dest="headless",action="store_true",help="Run without a visible browser window (default)")
    syncme.add_argument("--visible-browser",dest="headless",action="store_false",help="Show the browser for login troubleshooting")
    syncme.add_argument("--auth-provider",choices=("microsoft",),default="microsoft")
    syncme.add_argument("--microsoft-mail",dest="microsoft_email",help="Microsoft/Outlook login email")
    syncme.add_argument("--password",help="Login password; omit for a hidden prompt")
    syncme.add_argument("--i-own-this-number",action="store_true",required=True,help="Confirm that the queried number is yours")
    telegram=subparsers.add_parser(
        "telegram-phone", aliases=["telegram-presence"],
        help="Check your own Telegram number by temporarily importing and deleting it as a contact",
    )
    telegram.add_argument("number");telegram.add_argument("--region")
    telegram.add_argument("--telegram-account",required=True,help="Telegram login number; must match the queried number")
    telegram.add_argument("--api-id",type=int,help="Defaults to TELEGRAM_API_ID")
    telegram.add_argument("--api-hash",help="Defaults to TELEGRAM_API_HASH")
    telegram.add_argument("--session-path")
    telegram.add_argument("--i-own-this-number",action="store_true",required=True)
    facebook_web=subparsers.add_parser(
        "facebook-self-check",
        help="Observe a manual Facebook recovery lookup for your own number without selecting a recovery method",
    )
    facebook_web.add_argument("number");facebook_web.add_argument("--region")
    facebook_web.add_argument("--timeout",type=float,default=180.0)
    facebook_web.add_argument("--i-own-this-number",action="store_true",required=True)
    pastebin_audit=subparsers.add_parser(
        "pastebin-leak-audit",
        help="Check public search indexes for Pastebin links containing your own phone number",
    )
    pastebin_audit.add_argument("number")
    pastebin_audit.add_argument("--region")
    pastebin_audit.add_argument("--limit",type=int,default=10)
    pastebin_audit.add_argument("--timeout",type=float,default=60.0)
    pastebin_audit.add_argument("--model")
    pastebin_audit.add_argument("--i-own-this-number",action="store_true",required=True)
    cybernews=subparsers.add_parser(
        "cybernews-leak-check",
        help="Check your own phone number with Cybernews Personal Data Leak Checker",
    )
    cybernews.add_argument("number")
    cybernews.add_argument("--region")
    cybernews.add_argument("--timeout",type=float,default=60.0)
    cybernews.add_argument(
        "--headless",action="store_true",
        help="Run Chromium without opening a visible browser window",
    )
    cybernews.add_argument("--i-own-this-number",action="store_true",required=True)
    databreach=subparsers.add_parser(
        "databreach-leak-check",
        help="Check your own phone number with DataBreach.com and list exposed field categories",
    )
    databreach.add_argument("number")
    databreach.add_argument("--region")
    databreach.add_argument("--timeout",type=float,default=60.0)
    databreach.add_argument(
        "--headless",action="store_true",
        help="Run Chromium without opening a visible browser window",
    )
    databreach.add_argument("--i-own-this-number",action="store_true",required=True)
    whatsapp=subparsers.add_parser(
        "whatsapp-self-check",
        help="Check your own number with WhatsApp's official click-to-chat page without sending a message",
    )
    whatsapp.add_argument("number")
    whatsapp.add_argument("--region")
    whatsapp.add_argument("--timeout",type=float,default=45.0)
    whatsapp.add_argument("--i-own-this-number",action="store_true",required=True)
    hudsonrock=subparsers.add_parser(
        "hudsonrock-self-check",
        help="Check your own number for summarized Hudson Rock infostealer exposure",
    )
    hudsonrock.add_argument("number")
    hudsonrock.add_argument("--region")
    hudsonrock.add_argument("--timeout",type=float,default=30.0)
    hudsonrock.add_argument("--api-key",help="Defaults to HUDSONROCK_API_KEY")
    hudsonrock.add_argument("--i-own-this-number",action="store_true",required=True)
    github_phone=subparsers.add_parser(
        "github-phone-search",
        help="Search public GitHub repository file metadata for your own phone number",
    )
    github_phone.add_argument("number")
    github_phone.add_argument("--region")
    github_phone.add_argument("--limit",type=int,default=20)
    github_phone.add_argument("--timeout",type=float,default=30.0)
    github_phone.add_argument("--github-token",help="Defaults to GITHUB_TOKEN")
    github_phone.add_argument("--i-own-this-number",action="store_true",required=True)
    reddit_phone=subparsers.add_parser(
        "reddit-phone-search",
        help="Search public Reddit post metadata for your own phone number",
    )
    reddit_phone.add_argument("number")
    reddit_phone.add_argument("--region")
    reddit_phone.add_argument("--limit",type=int,default=20)
    reddit_phone.add_argument("--timeout",type=float,default=30.0)
    reddit_phone.add_argument("--client-id",help="Defaults to REDDIT_CLIENT_ID")
    reddit_phone.add_argument("--client-secret",help="Defaults to REDDIT_CLIENT_SECRET")
    reddit_phone.add_argument("--user-agent",help="Defaults to REDDIT_USER_AGENT")
    reddit_phone.add_argument("--i-own-this-number",action="store_true",required=True)
    brave=subparsers.add_parser("brave-phone-search",help="Search Brave's public web index for your own phone number")
    brave.add_argument("number");brave.add_argument("--region");brave.add_argument("--limit",type=int,default=20);brave.add_argument("--timeout",type=float,default=30.0)
    brave.add_argument("--api-key",help="Defaults to BRAVE_SEARCH_API_KEY");brave.add_argument("--i-own-this-number",action="store_true",required=True)
    duckduckgo=subparsers.add_parser("duckduckgo-phone-search",help="Search DuckDuckGo's public index for your own phone number")
    duckduckgo.add_argument("number");duckduckgo.add_argument("--region");duckduckgo.add_argument("--limit",type=int,default=20);duckduckgo.add_argument("--timeout",type=float,default=30.0)
    duckduckgo.add_argument("--no-browser-fallback",action="store_true");duckduckgo.add_argument("--headless",action="store_true")
    duckduckgo.add_argument("--i-own-this-number",action="store_true",required=True)
    opensanctions=subparsers.add_parser("opensanctions-phone-search",help="Search exact phone fields in OpenSanctions public-interest datasets")
    opensanctions.add_argument("number");opensanctions.add_argument("--region");opensanctions.add_argument("--dataset",default="default");opensanctions.add_argument("--limit",type=int,default=20);opensanctions.add_argument("--timeout",type=float,default=30.0)
    opensanctions.add_argument("--api-key",help="Defaults to OPENSANCTIONS_API_KEY");opensanctions.add_argument("--i-own-this-number",action="store_true",required=True)
    ftc=subparsers.add_parser("ftc-complaints",help="Search recent official FTC unwanted-call complaint files for a US number")
    ftc.add_argument("number");ftc.add_argument("--region");ftc.add_argument("--days",type=int,default=7);ftc.add_argument("--timeout",type=float,default=30.0)
    ftc.add_argument("--i-own-this-number",action="store_true",required=True)
    btk=subparsers.add_parser("btk-portability",help="Check a Turkish number with the official BTK/e-Devlet portability service")
    btk.add_argument("number");btk.add_argument("--region",default="TR");btk.add_argument("--timeout",type=float,default=90.0)
    btk.add_argument("--headless",action="store_true");btk.add_argument("--i-own-this-number",action="store_true",required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "browser-smoke-test":
        from moriarty.browser_smoke_test import BROWSER_SOURCES, run_browser_smoke_test
        if args.list_sources:
            print(json.dumps({"sources": BROWSER_SOURCES}, indent=2)); return 0
        selected = BROWSER_SOURCES if args.sources.strip().lower() == "all" else tuple(args.sources.split(","))
        try:
            stored_mail, stored_password = microsoft_credentials()
            browser_mail = args.microsoft_mail or stored_mail
            browser_password = stored_password
            if args.microsoft_mail and args.microsoft_mail != stored_mail:
                browser_password = getpass.getpass("Microsoft password (hidden, not saved): ")
            run_browser_smoke_test(
                args.number, args.region, selected, args.timeout, args.output,
                browser_mail, browser_password,
            )
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr); return 2
        return 0
    if args.command == "username-audit":
        core = UsernameAuditCore()
        if args.list_sources:
            print(json.dumps({"sources": [asdict(source) for source in DEFAULT_USERNAME_SOURCES]}, indent=2, ensure_ascii=False)); return 0
        selected = tuple(item.strip().lower() for item in args.sources.split(",") if item.strip())
        if selected == ("all",):
            selected = tuple(source.name for source in DEFAULT_USERNAME_SOURCES)
        public_profiles = PublicUsernameProfilesClient(timeout_seconds=args.timeout)
        social_profiles = SocialUsernameProfilesClient(timeout_seconds=args.timeout)
        web_probe = WebUsernameProbe(timeout_seconds=args.timeout)
        exposure = UsernameExposureClient(timeout_seconds=args.timeout, breachdirectory_key=args.breachdirectory_key)
        wmn = WhatsMyNameClient(timeout_seconds=args.timeout, catalog_path=args.wmn_catalog)
        username_tools = UsernameToolClient(timeout_seconds=args.timeout)
        fediverse = FediverseUsernameClient(timeout_seconds=args.timeout)
        historical = HistoricalUsernameClient(timeout_seconds=args.timeout)
        runners = {
            "github": lambda: GitHubUsernameClient(token=args.github_token, timeout_seconds=args.timeout).lookup(args.username),
            "gitlab": lambda: GitLabUsernameClient(timeout_seconds=args.timeout).lookup(args.username),
            "codeberg": lambda: public_profiles.codeberg(args.username),
            "dockerhub": lambda: public_profiles.dockerhub(args.username),
            "reddit": lambda: public_profiles.reddit(args.username),
            "hackernews": lambda: public_profiles.hackernews(args.username),
            "keybase": lambda: public_profiles.keybase(args.username),
            "bitbucket": lambda: public_profiles.bitbucket(args.username),
            "npm": lambda: public_profiles.npm(args.username),
            "devto": lambda: public_profiles.devto(args.username),
            "lichess": lambda: public_profiles.lichess(args.username),
            "chesscom": lambda: public_profiles.chesscom(args.username),
            "bluesky": lambda: social_profiles.bluesky(args.username),
            "telegram": lambda: social_profiles.telegram(args.username),
            "gravatar": lambda: social_profiles.gravatar(args.username),
            "roblox": lambda: social_profiles.roblox(args.username),
        }
        runners.update({spec.name: (lambda spec=spec: web_probe.lookup(spec, args.username)) for spec in WEB_PROFILE_SPECS})
        runners.update({
            "ahmia": lambda: exposure.ahmia(args.username, args.exposure_limit),
            "localbreach": lambda: exposure.local_files(args.username, args.breach_path, args.exposure_limit),
            "whatsmyname": lambda: wmn.search(args.username, categories=tuple(value.strip() for value in args.wmn_categories.split(",") if value.strip()), limit=args.wmn_limit, include_nsfw=args.include_nsfw, refresh=args.wmn_refresh),
            "sherlock": lambda: username_tools.sherlock(args.username),
            "maigret": lambda: username_tools.maigret(args.username),
            "socialscan": lambda: username_tools.socialscan(args.username),
            "blackbird": lambda: username_tools.blackbird(args.username),
            "gitfive": lambda: username_tools.gitfive(args.username),
            "fediverse": lambda: fediverse.search(args.username),
            "wayback": lambda: historical.wayback(args.username),
            "commoncrawl": lambda: historical.commoncrawl(args.username),
            "breachdirectory": lambda: exposure.breachdirectory(args.username),
        })
        try:
            result = core.run(args.username, selected, runners)
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr); return 2
        rendered_result = result if args.full_json else compact_username_audit(result)
        rendered = json.dumps(rendered_result, indent=2, ensure_ascii=False)
        if args.output:
            output_path = Path(args.output).expanduser(); output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered + "\n", encoding="utf-8")
        print(render_username_audit_text(compact_username_audit(result), args.language) if args.format == "readable" and not args.full_json else rendered); return 0
    if args.command=="web-workspace":
        try:
            serve_workspace(args.host,args.port,args.data_dir,not args.no_browser)
        except OSError as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        return 0
    analyzer = PhoneAnalyzer(PhoneNumbersProvider())
    if args.command=="phone-audit":
        core=PhoneAuditCore(DEFAULT_PHONE_AUDIT_SOURCES)
        if args.list_sources:
            print(json.dumps({"sources":[asdict(source) for source in core.catalog]},indent=2,ensure_ascii=False));return 0
        selected=tuple(item.strip().lower() for item in args.sources.split(",") if item.strip())
        if selected == ("all",):
            selected=tuple(source.name for source in core.catalog)
        def telegram_runner():
            if not args.telegram_account:
                return {"status":"configuration_required","note":"Set --telegram-account for the own-number Telegram source."}
            api_id,api_hash=telegram_credentials(args.telegram_api_id,args.telegram_api_hash)
            return TelegramPresenceClient(analyzer,api_id=api_id,api_hash=api_hash,session_path=args.telegram_session_path).lookup_own_number(args.number,args.telegram_account,args.region)
        def confirm_facebook_audit_save() -> bool:
            if not sys.stdin.isatty():
                return False
            
            return sys.stdin.readline().strip().lower() in {"y","yes"}
        def reputation_runner():
            result=InvestigationPipeline(_reputation_providers(analyzer,args.timeout),args.timeout).investigate(InvestigationQuery(args.number,args.region))
            payload=result.to_dict();payload["reputation_summary"]=summarize_reputation(result.providers);return payload
        def business_runner():
            result=InvestigationPipeline(_business_providers(analyzer,args.timeout),args.timeout).investigate(InvestigationQuery(args.number,args.region))
            return _with_website_verification(result,analyzer,args.timeout).to_dict()
        def documents_runner():
            provider=_document_provider(analyzer,args.limit,args.timeout,args.document_ocr,3,args.gemini_model,args.document_intelligence,3)
            return InvestigationPipeline((provider,),args.timeout).investigate(InvestigationQuery(args.number,args.region)).to_dict()
        microsoft_email,microsoft_password=microsoft_credentials()
        runners={
            "local":lambda: {"status":"completed",**analyzer.analyze(args.number,args.region).to_dict()},
            "truecaller":lambda: TruecallerBrowserClient(analyzer,timeout_seconds=args.timeout,profile_dir=args.truecaller_profile_dir,headless=args.headless).lookup_own_number(args.number,args.region,auth_provider="microsoft",auth_email=microsoft_email,auth_password=microsoft_password),
            "syncme":lambda: SyncMeBrowserClient(analyzer,timeout_seconds=args.timeout,profile_dir=args.syncme_profile_dir,headless=args.headless).lookup_own_number(args.number,args.region,microsoft_email=microsoft_email,microsoft_password=microsoft_password),
            "telegram":telegram_runner,
            "facebook":lambda: FacebookWebSelfCheckClient(analyzer,timeout_seconds=args.timeout).check_own_number(args.number,args.region,confirm_save="y"),
            "whatsapp":lambda: WhatsAppSelfCheckClient(analyzer,timeout_seconds=args.timeout).check_own_number(args.number,args.region),
            "cybernews":lambda: CybernewsLeakCheckClient(analyzer,timeout_seconds=args.timeout,headless=args.headless).check_own_number(args.number,args.region),
            "databreach":lambda: DataBreachLeakCheckClient(analyzer,timeout_seconds=args.timeout,headless=args.headless).check_own_number(args.number,args.region),
            "hudsonrock":lambda: HudsonRockSelfCheckClient(analyzer,timeout_seconds=args.timeout).check_own_number(args.number,args.region),
            "github":lambda: GitHubPhoneSearchClient(analyzer,max_results=args.limit,timeout_seconds=args.timeout).search_own_number(args.number,args.region),
            "reddit":lambda: RedditPhoneSearchClient(analyzer,max_results=args.limit,timeout_seconds=args.timeout).search_own_number(args.number,args.region),
            "brave":lambda: BravePhoneSearchClient(analyzer,max_results=args.limit,timeout_seconds=args.timeout).search(args.number,args.region),
            "duckduckgo":lambda: DuckDuckGoPhoneSearchClient(analyzer,max_results=args.limit,timeout_seconds=args.timeout,browser_fallback=not args.no_browser_fallback,headless=args.headless).search(args.number,args.region),
            "web-mentions":lambda: _web_mentions_service(analyzer,args.limit,args.timeout,"gemini",args.web_verify,args.web_intelligence,3,args.gemini_model).discover(args.number,args.region),
            "pastebin":lambda: PastebinLeakAuditService(analyzer,GeminiGroundedSearchBackend(model=args.gemini_model,timeout_seconds=args.timeout),max_results=args.limit).audit(args.number,args.region),
            "documents":documents_runner,
            "reputation":reputation_runner,
            "business":business_runner,
            "disposable":lambda: DisposableNumberService(analyzer,max_results=args.limit,timeout_seconds=min(args.timeout,15.0)).check(args.number,args.region),
            "opensanctions":lambda: OpenSanctionsPhoneSearchClient(analyzer,max_results=args.limit,timeout_seconds=args.timeout).search(args.number,args.region),
            "ftc":lambda: FTCDNCClient(analyzer,coverage_days=args.ftc_days,timeout_seconds=args.timeout).search(args.number,args.region),
            "btk":lambda: BTKNumberPortabilityClient(analyzer,timeout_seconds=args.timeout,headless=args.headless).check(args.number,args.region),
        }
        try:
            normalized=analyzer.analyze(args.number,args.region)
            if not normalized.is_valid: raise ValueError("A valid phone number is required.")
            result=core.run(number=normalized.e164,region=args.region,selected_sources=selected,runners=runners)
        except (ValueError,PhoneNumberParseError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        rendered=json.dumps(result.to_dict(),indent=2,ensure_ascii=False)
        if args.output:
            output_path=Path(args.output).expanduser()
            output_path.parent.mkdir(parents=True,exist_ok=True)
            output_path.write_text(rendered+"\n",encoding="utf-8")
        print(rendered);return 0
    if args.command=="brave-phone-search":
        try:
            result=BravePhoneSearchClient(analyzer,api_key=args.api_key,max_results=args.limit,timeout_seconds=args.timeout).search(args.number,args.region)
        except (BravePhoneSearchError,PhoneNumberParseError,ValueError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="duckduckgo-phone-search":
        try:
            result=DuckDuckGoPhoneSearchClient(analyzer,max_results=args.limit,timeout_seconds=args.timeout,browser_fallback=not args.no_browser_fallback,headless=args.headless).search(args.number,args.region)
        except (DuckDuckGoPhoneSearchError,PhoneNumberParseError,ValueError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="opensanctions-phone-search":
        try:
            result=OpenSanctionsPhoneSearchClient(analyzer,api_key=args.api_key,dataset=args.dataset,max_results=args.limit,timeout_seconds=args.timeout).search(args.number,args.region)
        except (OpenSanctionsPhoneSearchError,PhoneNumberParseError,ValueError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="ftc-complaints":
        try:
            result=FTCDNCClient(analyzer,coverage_days=args.days,timeout_seconds=args.timeout).search(args.number,args.region)
        except (FTCDNCError,PhoneNumberParseError,ValueError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="btk-portability":
        try:
            result=BTKNumberPortabilityClient(analyzer,timeout_seconds=args.timeout,headless=args.headless).check(args.number,args.region)
        except (BTKNumberPortabilityError,PhoneNumberParseError,ValueError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="reddit-phone-search":
        try:
            result=RedditPhoneSearchClient(
                analyzer,client_id=args.client_id,client_secret=args.client_secret,
                user_agent=args.user_agent,max_results=args.limit,
                timeout_seconds=args.timeout,
            ).search_own_number(args.number,args.region)
        except (RedditPhoneSearchError,PhoneNumberParseError,ValueError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="github-phone-search":
        try:
            result=GitHubPhoneSearchClient(
                analyzer,token=args.github_token,max_results=args.limit,
                timeout_seconds=args.timeout,
            ).search_own_number(args.number,args.region)
        except (GitHubPhoneSearchError,PhoneNumberParseError,ValueError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="hudsonrock-self-check":
        try:
            result=HudsonRockSelfCheckClient(
                analyzer,api_key=args.api_key,timeout_seconds=args.timeout
            ).check_own_number(args.number,args.region)
        except (HudsonRockSelfCheckError,PhoneNumberParseError,ValueError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="whatsapp-self-check":
        try:
            result=WhatsAppSelfCheckClient(
                analyzer,timeout_seconds=args.timeout
            ).check_own_number(args.number,args.region)
        except (WhatsAppSelfCheckError,PhoneNumberParseError,ValueError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="databreach-leak-check":
        try:
            result=DataBreachLeakCheckClient(
                analyzer,timeout_seconds=args.timeout,headless=args.headless
            ).check_own_number(args.number,args.region)
        except (DataBreachLeakCheckError,PhoneNumberParseError,ValueError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="cybernews-leak-check":
        try:
            result=CybernewsLeakCheckClient(
                analyzer,timeout_seconds=args.timeout,headless=args.headless
            ).check_own_number(args.number,args.region)
        except (CybernewsLeakCheckError,PhoneNumberParseError,ValueError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="pastebin-leak-audit":
        try:
            backend=GeminiGroundedSearchBackend(
                model=args.model,timeout_seconds=args.timeout
            )
            result=PastebinLeakAuditService(
                analyzer,backend,max_results=args.limit
            ).audit(args.number,args.region)
        except (ValueError,PhoneNumberParseError,SearchBackendError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="facebook-self-check":
        def confirm_facebook_save() -> bool:
            return sys.stdin.readline().strip().lower() in {"y","yes"}
        try:
            result=FacebookWebSelfCheckClient(
                analyzer,timeout_seconds=args.timeout
            ).check_own_number(args.number,args.region,confirm_save="y")
        except (FacebookWebSelfCheckError,PhoneNumberParseError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command in {"telegram-phone","telegram-presence"}:
        try:
            api_id,api_hash=telegram_credentials(args.api_id,args.api_hash)
            result=TelegramPresenceClient(
                analyzer,api_id=api_id,api_hash=api_hash,session_path=args.session_path
            ).lookup_own_number(args.number,args.telegram_account,args.region)
        except (TelegramPresenceError,PhoneNumberParseError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="syncme-browser":
        try:
            stored_mail,stored_password=microsoft_credentials()
            syncme_email=args.microsoft_email or stored_mail
            syncme_password=args.password or os.environ.pop("GOKBORU_BROWSER_TEST_PASSWORD", None) or stored_password
            if args.microsoft_email and not syncme_password:
                syncme_password=getpass.getpass("Microsoft password (hidden): ")
            result=SyncMeBrowserClient(
                analyzer,timeout_seconds=args.timeout,profile_dir=args.profile_dir,headless=args.headless
            ).lookup_own_number(
                args.number,args.region,
                microsoft_email=syncme_email,microsoft_password=syncme_password,
            )
        except (SyncMeBrowserError,PhoneNumberParseError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="truecaller-login":
        try:
            result=TruecallerBrowserClient(
                analyzer,timeout_seconds=args.timeout,profile_dir=args.profile_dir,headless=False
            ).login()
        except TruecallerBrowserError as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        print(json.dumps(result,indent=2,ensure_ascii=False));return 0
    if args.command=="truecaller-browser":
        try:
            stored_mail,stored_password=microsoft_credentials()
            auth_email=(args.microsoft_email or stored_mail) if args.auth_provider=="microsoft" else args.google_email
            auth_password=args.password or os.environ.pop("GOKBORU_BROWSER_TEST_PASSWORD", None) or (stored_password if args.auth_provider=="microsoft" else None)
            if auth_email and not auth_password:
                auth_password=getpass.getpass(f"{args.auth_provider.title()} password (hidden): ")
            truecaller_client=TruecallerBrowserClient(
                analyzer,timeout_seconds=args.timeout,profile_dir=args.profile_dir,headless=args.headless
            )
            result=truecaller_client.lookup_own_number(
                args.number,args.region,auth_provider=args.auth_provider,
                auth_email=auth_email,auth_password=auth_password
            )
            payload=result.to_dict()
            if result.status=="search_limit_exceeded" and sys.stdin.isatty():
                print(
                    "Search limit exceeded. Would you like to sign out and try another account? [y/N]: ",
                    end="", file=sys.stderr, flush=True,
                )
                answer=sys.stdin.readline().strip().lower()
                if answer in {"y","yes"}:
                    payload["account_signed_out"]=truecaller_client.sign_out()
                    payload["next_action"]="Run the command again with another account."
                else:
                    payload["account_signed_out"]=False
        except (TruecallerBrowserError,PhoneNumberParseError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        except KeyboardInterrupt:
            print(json.dumps({"status":"cancelled","browser_closed":True},ensure_ascii=False),file=sys.stderr)
            return 130
        print(json.dumps(payload,indent=2,ensure_ascii=False));return 0
    if args.command=="truecaller-consent":
        try:
            result=create_consent_request(
                analyzer,args.number,args.app_key or os.getenv("TRUECALLER_APP_KEY", ""),args.app_name,
                region=args.region,privacy_url=args.privacy_url,terms_url=args.terms_url,ttl_ms=args.ttl,
            )
        except (TruecallerConsentError,PhoneNumberParseError) as exc:
            print(json.dumps({"error":str(exc)},ensure_ascii=False),file=sys.stderr);return 2
        payload=result.to_dict()
        payload["next_step"]="Open deep_link on an Android phone with Truecaller installed. The approved profile is sent to the HTTPS callback registered for this app key."
        print(json.dumps(payload,indent=2,ensure_ascii=False));return 0
    if args.command=="structured-contacts":
        try:
            final_url,payload,content_type=load_public_html(args.url,args.timeout)
            charset="utf-8"
            if "charset=" in content_type.lower():charset=content_type.lower().split("charset=",1)[1].split(";",1)[0].strip()
            result=extract_structured_contacts(payload.decode(charset,errors="replace"),final_url,analyzer,args.region)
        except Exception as exc:print(json.dumps({"error":str(exc) or type(exc).__name__}),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="qr-contact":
        try:result=decode_qr_contacts(read_image(args.image,args.timeout),analyzer,args.region)
        except Exception as exc:print(json.dumps({"error":str(exc) or type(exc).__name__}),file=sys.stderr);return 2
        print(json.dumps(result,indent=2,ensure_ascii=False));return 0
    if args.command=="domain":
        try:result=DomainIntelligenceService(args.timeout).analyze(args.value)
        except Exception as exc:print(json.dumps({"error":str(exc) or type(exc).__name__}),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="email":
        try:result=EmailValidationService(DomainIntelligenceService(args.timeout)).validate(args.value)
        except Exception as exc:print(json.dumps({"error":str(exc) or type(exc).__name__}),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="company-registry":
        try:result=CompaniesHouseClient(timeout_seconds=args.timeout).search(args.name,args.limit)
        except Exception as exc:print(json.dumps({"error":str(exc) or type(exc).__name__}),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command=="disposable":
        try:
            result=DisposableNumberService(analyzer,max_results=args.limit,timeout_seconds=args.timeout).check(args.number,args.region)
        except Exception as exc:print(json.dumps({"error":str(exc) or type(exc).__name__}),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False));return 0
    if args.command == "gemini-models":
        try:
            available = list_gemini_models(timeout_seconds=args.timeout)
        except (ValueError, SearchBackendError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 2
        print(json.dumps({"count": len(available), "models": available}, indent=2, ensure_ascii=False))
        return 0
    if args.command == "documents":
        try:
            provider=_document_provider(analyzer,args.limit,args.timeout,args.ocr,args.ocr_limit,args.model,args.intelligence,args.intelligence_limit)
            result=InvestigationPipeline((provider,),args.timeout).investigate(InvestigationQuery(args.number,args.region))
        except ValueError as exc:
            print(json.dumps({"error":str(exc)}),file=sys.stderr);return 2
        print(json.dumps(result.to_dict(),indent=2,ensure_ascii=False))
        return 0 if result.status is not InvestigationStatus.FAILED else 2
    if args.command == "business-listings":
        try:
            pipeline = InvestigationPipeline(
                _business_providers(analyzer, args.timeout), args.timeout
            )
        except (ValueError, PhoneNumberParseError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        except Exception as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        result = pipeline.investigate(InvestigationQuery(args.number, args.region))
        result = _with_website_verification(result, analyzer, args.timeout)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0 if result.status is not InvestigationStatus.FAILED else 2

    if args.command == "reputation":
        try:
            pipeline = InvestigationPipeline(
                _reputation_providers(analyzer, args.timeout), args.timeout
            )
        except (ValueError, PhoneNumberParseError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        result = pipeline.investigate(InvestigationQuery(args.number, args.region))
        payload = result.to_dict()
        payload["reputation_summary"] = summarize_reputation(result.providers)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if result.status is not InvestigationStatus.FAILED else 2

    if args.command == "web-mentions":
        try:
            service = _web_mentions_service(
                analyzer,
                args.limit,
                args.timeout,
                args.engine,
                args.verify,
                args.intelligence,
                args.intelligence_limit,
                args.model,
            )
            result = service.discover(args.number, args.region)
        except (ValueError, PhoneNumberParseError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        except Exception as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 1
        payload = result.to_dict()
        payload["count"] = len(result.mentions)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if args.command == "investigate":
        try:
            providers = [PhoneInvestigationProvider(analyzer)]
            if args.reputation:
                providers.extend(_reputation_providers(analyzer, args.timeout))
            if args.business:
                providers.extend(_business_providers(analyzer, args.timeout))
            if args.documents:
                providers.append(_document_provider(analyzer,10,args.timeout,args.document_ocr,3,args.gemini_model,args.document_intelligence,3))
            if args.web:
                providers.append(
                    WebMentionsProvider(
                        _web_mentions_service(
                            analyzer,
                            10,
                            args.timeout,
                            args.web_engine,
                            args.web_verify,
                            args.web_intelligence,
                            3,
                            args.gemini_model,
                        )
                    )
                )
            if args.disposable:
                providers.append(DisposableNumberProvider(DisposableNumberService(analyzer,max_results=10,timeout_seconds=min(args.timeout,15.0))))
            pipeline = InvestigationPipeline(
                tuple(providers), args.timeout
            )
        except ValueError as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 2
        result = pipeline.investigate(InvestigationQuery(args.number, args.region))
        if args.business:
            result = _with_website_verification(result, analyzer, args.timeout)
        payload = result.to_dict()
        if args.reputation:
            payload["reputation_summary"] = summarize_reputation(result.providers)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if result.status is not InvestigationStatus.FAILED else 2

    try:
        result = analyzer.analyze(args.number, args.region)
    except PhoneNumberParseError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2

    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _web_mentions_service(
    analyzer: PhoneAnalyzer,
    limit: int,
    timeout: float,
    engine: str,
    verify: bool = False,
    intelligence_enabled: bool = False,
    intelligence_limit: int = 3,
    model: str | None = None,
) -> WebMentionsService:
    if engine != "gemini":
        raise ValueError(f"Unsupported web engine: {engine}")
    return WebMentionsService(
        analyzer,
        GeminiGroundedSearchBackend(model=model,timeout_seconds=min(timeout*.65,120.0)),
        max_results=limit,
        verify=verify,
        timeout_seconds=timeout,
        intelligence=GeminiWebIntelligence(model=model) if intelligence_enabled else None,
        intelligence_limit=intelligence_limit,
    )


def _reputation_providers(
    analyzer: PhoneAnalyzer, timeout: float
) -> tuple[WhoCalledUkProvider, ShouldIAnswerUkProvider, UnknownPhoneProvider, PhoneSpamFilterProvider, EightHundredNotesProvider, WhoCallsMeProvider, PhoneyaProvider, CleverDialerProvider, WhoCalledTodayProvider, KimAriyorProvider]:
    return (
        WhoCalledUkProvider(WhoCalledUkClient(analyzer, timeout)),
        ShouldIAnswerUkProvider(ShouldIAnswerUkClient(analyzer, timeout)),
        UnknownPhoneProvider(UnknownPhoneClient(analyzer, timeout)),
        PhoneSpamFilterProvider(PhoneSpamFilterClient(analyzer, timeout)),
        EightHundredNotesProvider(EightHundredNotesClient(analyzer, timeout)),
        WhoCallsMeProvider(WhoCallsMeClient(analyzer, timeout)),
        PhoneyaProvider(PhoneyaClient(analyzer, timeout)),
        CleverDialerProvider(CleverDialerClient(analyzer, timeout)),
        WhoCalledTodayProvider(WhoCalledTodayClient(analyzer, timeout)),
        KimAriyorProvider(KimAriyorClient(analyzer, timeout)),
    )


def _business_providers(
    analyzer: PhoneAnalyzer, timeout: float
) -> tuple[OsmBusinessProvider, WikidataBusinessProvider, FirmaFihristiBusinessProvider, GotMyNumberBusinessProvider, TelefonOrgBusinessProvider, DasOertlicheBusinessProvider, DasTelefonbuchBusinessProvider]:
    return (
        OsmBusinessProvider(OsmBusinessClient(analyzer, timeout)),
        WikidataBusinessProvider(WikidataBusinessClient(analyzer, timeout)),
        FirmaFihristiBusinessProvider(FirmaFihristiBusinessClient(analyzer, timeout)),
        GotMyNumberBusinessProvider(GotMyNumberBusinessClient(analyzer, timeout)),
        TelefonOrgBusinessProvider(TelefonOrgBusinessClient(analyzer, timeout)),
        DasOertlicheBusinessProvider(DasOertlicheBusinessClient(analyzer, timeout)),
        DasTelefonbuchBusinessProvider(DasTelefonbuchBusinessClient(analyzer, timeout)),
    )


def _document_provider(analyzer:PhoneAnalyzer,limit:int,timeout:float,ocr_enabled:bool=False,ocr_limit:int=3,model:str|None=None,intelligence_enabled:bool=False,intelligence_limit:int=3)->DocumentDiscoveryProvider:
    
    
    
    
    backend=GeminiGroundedSearchBackend(model=model,timeout_seconds=min(timeout*.55,75.0))
    ocr=GeminiDocumentOcr(model=model) if ocr_enabled else None
    intelligence=GeminiDocumentIntelligence(model=model) if intelligence_enabled else None
    return DocumentDiscoveryProvider(DocumentDiscoveryService(analyzer,backend,timeout_seconds=timeout,max_results=limit,ocr=ocr,ocr_limit=ocr_limit,intelligence=intelligence,intelligence_limit=intelligence_limit))


def _with_website_verification(result, analyzer: PhoneAnalyzer, timeout: float):
    listings = tuple(
        listing
        for provider in result.providers
        if provider.status is ProviderStatus.SUCCESS and provider.provider.startswith("business_listings:") and provider.data
        for listing in provider.data.get("listings", ())
    )
    started = monotonic()
    verifier = OfficialWebsiteVerifier(analyzer, timeout_seconds=timeout)
    try:
        output = verifier.verify(result.query.phone_number, listings, result.query.default_region)
        if not listings:
            output = replace(output, data={**output.data, "status":"not_applicable", "reason":"No business listing with a website was available to verify."})
        verification = ProviderResult(verifier.name,ProviderStatus.SUCCESS,max(0,round((monotonic()-started)*1000)),output.data,output.evidence)
    except Exception as exc:
        verification = ProviderResult(verifier.name,ProviderStatus.ERROR,max(0,round((monotonic()-started)*1000)),error=str(exc) or type(exc).__name__)
    providers = result.providers + (verification,)
    successes = sum(item.status is ProviderStatus.SUCCESS for item in providers)
    status = InvestigationStatus.SUCCESS if successes == len(providers) else InvestigationStatus.PARTIAL if successes else InvestigationStatus.FAILED
    return replace(result, status=status, providers=providers)
