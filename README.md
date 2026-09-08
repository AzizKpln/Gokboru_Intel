# Gökbörü Intelligence

Phone and username investigation workspace with a desktop installer, interactive
console and local Web UI. The internal Python package and launcher retain the
`moriarty` name for compatibility.

## Quick start (Ubuntu desktop)

Open a terminal in the extracted project directory:

```bash
bash ./install.sh
```

After installation:

```bash
bash ./moriarty-local
bash ./moriarty-local web-workspace
```

The Web UI is available at http://127.0.0.1:8765/. Web phone scans use hidden
browser windows by default. Sources requiring interactive authentication report
that action is needed. Closing the browser tab does not stop the server; use
Ctrl+C in its terminal. In VirtualBox, configure the shared folder as permanent.

## Data and credentials

Reports, cached investigations and browser sessions can contain personal data
and are stored locally. Selected providers receive the query needed to perform
their lookup. Microsoft credentials and API keys are stored in a local JSON
configuration protected by filesystem permissions; this is not encrypted storage.
Do not publish that configuration, reports, browser profiles or session files.
This distribution excludes those runtime files. Use only for authorized queries.

## Screenshots

Add Web UI and console screenshots here after removing targets, credentials and
personal findings from the images.

## Username investigations

Run exact public-profile checks for a nickname without opening a browser:

```bash
bash ./moriarty-local username-audit "AzizKpln" --sources all --timeout 30
```

Save the complete entity/relationship graph as JSON:

```bash
bash ./moriarty-local username-audit "AzizKpln" --sources all --output reports/username-AzizKpln.json
```

GitHub works anonymously at lower rate limits. Set `GITHUB_TOKEN` or pass
`--github-token` when authenticated API capacity is needed.

Current exact-profile sources: GitHub, GitLab, Codeberg, Bitbucket, Docker Hub,
npm, DEV Community, Reddit, Hacker News, Keybase, Bluesky, Telegram, Gravatar,
Roblox, Lichess and Chess.com. A result
means that the same username exists on that service; it is not, by itself, proof
that all profiles belong to the same person.

The extended browserless catalog also covers Facebook, Instagram, X/Twitter,
TikTok, Pinterest, Tumblr, Twitch and the profile services represented in the
WhatsMyName reference set. Generic HTTP 200 pages are reported as
`indeterminate`, not as a confirmed profile; retired services are labelled
`retired` without making a network request.

V5 is a separate, modular rewrite. The V4 application in the repository root is
left unchanged.

## Setup and usage

```bash
bash install.sh
hash -r
moriarty phone "+1 650-253-0000"
moriarty investigate "+1 650-253-0000"
moriarty web-mentions "+1 650-253-0000"
moriarty reputation "+44 20 8138 0007"
moriarty business-listings "+1 650-967-9176"
moriarty documents "+1 650-253-0000"
pytest
```

`install.sh` opens the native Gökbörü Setup application. The GUI collects the
Microsoft/Hotmail credentials shared by Truecaller and Sync.me, Telegram API
credentials, and optional intelligence API keys. It creates an isolated environment under
`~/.local/share/moriarty-v5/venv` and a user-local launcher. Keeping the virtual
environment outside the project also works on VirtualBox shared folders, which
do not support the symlink Python normally creates inside a Linux venv. The
launcher always imports this checkout's `src` directory, so edits take effect
on the next command and an older global Moriarty installation cannot supply the
code. Reputation results are not cached; providers query their sources on every
run. `./moriarty-local` can be used to explicitly run this checkout.

Credentials are stored in
`~/.local/share/moriarty-v5/gokboru/configuration.json` with user-only mode 600
and should be kept private. If Microsoft email or
password is omitted, Truecaller and Sync.me return `configuration_required`
without opening Chromium.

Numbers without a `+` country code require an ISO 3166-1 alpha-2 region:

```bash
moriarty phone "0532 123 45 67" --region TR
```

The command emits structured JSON containing the normalized E.164 number,
possible/valid flags, region code and description, country calling code,
carrier, and time zones. Invalid syntax returns an error without a traceback.

## Architecture

- `domain`: immutable result and evidence models, plus provider contracts
- `providers`: integrations that acquire or enrich data
- `services`: use cases that coordinate providers
- `cli.py`: replaceable presentation layer

Future web-mention, reputation, public-listing, and public-profile providers can
implement the generic provider contract and return source-attributed evidence.

## Public business listings

OpenStreetMap/Overpass and Wikidata are queried globally. Turkish numbers also
query Firma Fihristi and Telefon.org.tr, while UK numbers query GotMyNumber
and German numbers query Das Örtliche plus Das Telefonbuch concurrently; none of these sources
requires an API key:

```bash
moriarty business-listings "+1 650-967-9176" --timeout 20
moriarty investigate "+1 650-967-9176" --business --timeout 20
```

Results include the public business name, category, address, coordinates,
website, tagged phone value, and direct OpenStreetMap source URL. A listing is
a public association with the number, not proof of current ownership. Source
errors are isolated, so a temporary Wikidata or Overpass outage does not discard
the other source's result.

Firma Fihristi receives only Turkish numbers and is searched using the national
display format expected by its public search form. Moriarty accepts only rows
whose displayed phone normalizes back to the exact queried E.164 number.

Telefon.org.tr publishes a small, customer-service-focused directory inside its
public page. Moriarty downloads that dataset once per run and performs the phone
comparison locally, so the queried number is never sent to Telefon.org.tr.

GotMyNumber contributes a business listing only when its public result names a
business and explicitly labels it as verified. Registered-but-unverified or
personal-number results never expose a name and are not treated as listings.

Das Örtliche reverse lookup is used only for German numbers. Moriarty accepts a
result only when the detail page identifies itself as a schema.org Organization
and contains a telephone value that normalizes exactly to the query. Personal
directory entries are therefore not promoted into business listings.

Das Telefonbuch provides a second German reverse lookup. Its result pages may
visually shorten telephone values, so Moriarty reads the page's full `phoneTo`
field, normalizes it, and requires an exact match. Only entries marked with the
directory's business hit type are returned.

When a listing supplies a website, Moriarty also checks its home page and up to
two same-site contact/about pages. An exact normalized phone match produces an
`official_website_phone_match` evidence item with confidence `0.98`. The checker
does not submit forms, follow off-site links, or access local/private network
addresses. A missing number is reported as `not_found`; network and site errors
are isolated as `unreachable` per website.

## Investigation pipeline

```bash
moriarty investigate "number"
moriarty investigate "number" --region TR --timeout 10
```

The pipeline runs registered providers concurrently and isolates provider errors
and timeouts. Its top-level status is `success`, `partial`, or `failed`; every
provider also reports its own status, duration, data, evidence, and safe error
message. At this stage Phone Analyzer is the first registered provider.

## Public web mentions

Web discovery uses Gemini's managed Google Search grounding. It does not launch
a browser or scrape Google HTML.

```bash
export GEMINI_API_KEY="your-new-key"
export GEMINI_MODEL="gemini-3.6-flash"  # optional; this is the default
moriarty web-mentions "+44 02038246771" --engine gemini --limit 10 --timeout 60
moriarty investigate "+44 02038246771" --web --web-engine gemini --timeout 60
```

Never commit the API key or pass it as a command-line argument. The provider
searches quoted E.164, digits-only, international, national, and common
country-code-plus-national representations (such as `+44 02038246771`). It
removes duplicate URLs and labels results as `social_profile`, `business_listing`,
`forum`, `document`, or `other`. Categories and confidence values are heuristic;
a mention means only that a public search result contains the queried number,
not that the page or account belongs to the number's owner.

## Phone reputation

The reputation lookup queries UnknownPhone, Phoneya, and WhoCalled.Today
globally. Phoneya reads
explicit FTC/FCC complaint counts when present. It also queries Phone Spam
Filter for US, UK, France, Australia, and New Zealand numbers. UK numbers query
WhoCalled UK and Should I Answer UK concurrently as well. NANP numbers also
query 800Notes and WhoCallsMe. CleverDialer ratings are queried for UK and NANP
numbers:

```bash
moriarty reputation "+44 20 8138 0007"
moriarty investigate "+44 20 8138 0007" --reputation
```

Each source returns its own `found`, `not_found`, or `not_applicable` result and
source URL. Available fields include rating/security level, report and lookup
counts, categories, carrier, line type, and area. A source failure is isolated,
so the other result is still returned. Non-UK numbers are skipped without
contacting the UK-only sites. UnknownPhone returns up to ten public comments and
its detected-call count when available. Community reports are evidence, not
proof of caller identity or malicious intent.

## Truecaller user-consent verification

Moriarty uses Truecaller's official Android mobile-web consent flow. It does not
scrape reverse-lookups or automate account credentials. Register a Web app and
HTTPS callback in the Truecaller developer console, then keep the app key out of
source control:

```bash
export TRUECALLER_APP_KEY="your-app-key"
bash ./moriarty-local truecaller-consent "number" \
  --privacy-url "https://your-domain.example/privacy" \
  --terms-url "https://your-domain.example/terms"
```

Open the returned `deep_link` on the Android phone that owns the number. Moriarty
accepts a resulting profile only when the callback request id and normalized
E.164 number match the pending consent request.

### Browser fallback for your own number

When the official developer console is unavailable, a visible persistent browser
session can be tried for a number you own:

```bash
bash install.sh
bash ./moriarty-local truecaller-browser "number" \
  --i-own-this-number --timeout 90
```

If the stored profile is not authenticated, this command now opens **Sign in →
Google** itself and waits for the user to finish Google's visible login before
continuing the same number lookup.

The email and password fields can be completed automatically without exposing
the password in shell history:

```bash
bash ./moriarty-local truecaller-browser "number" \
  --i-own-this-number --google-email "account@example.com" --timeout 300
```

The password is requested using a hidden terminal prompt. It is not accepted as
a command-line argument by default, saved to disk, or included in JSON output.
For unattended test accounts, `--google-mail EMAIL --password PASSWORD` is also
accepted, but exposes the password to shell history and the operating-system
process list. Complete 2FA or additional Google challenges manually in the
visible browser.

Microsoft is the default browser-login provider. The credentials saved by the
Setup application are loaded automatically:

```bash
bash ./moriarty-local truecaller-browser "number" \
  --i-own-this-number --auth-provider microsoft --timeout 300
```

The first run may require signing in inside the visible Chromium window. The
profile is stored outside the shared project under
`~/.local/share/moriarty-v5/truecaller-browser`. Moriarty does not export cookies
or bypass CAPTCHA/human-verification screens.

To prepare the persistent login separately, run:

```bash
bash ./moriarty-local truecaller-login --timeout 300
```

Moriarty opens Truecaller and selects Google. Enter the Google credentials only
inside Google's visible page. After the command reports `authenticated`, run
`truecaller-browser` again.

### Sync.me browser lookup

Sync.me uses its own persistent browser profile. The initial command reports
public line/address details and returns `login_required` when the caller name is
locked behind Sync.me sign-in:

```bash
bash ./moriarty-local syncme-browser "number" \
  --i-own-this-number \
  --visible-browser \
  --timeout 300
```

The Microsoft credentials saved by the Setup application are loaded
automatically. After the first successful login the dedicated Sync.me profile
preserves the session, and later lookups can run headlessly.

The profile is stored at `~/.local/share/moriarty-v5/syncme-browser`.

### Telegram self-presence

Create an application at `https://my.telegram.org`, then export its numeric
`api_id` and `api_hash`. The queried number must be the same as the Telegram
account used to authenticate:

```bash
export TELEGRAM_API_ID="12345678"
export TELEGRAM_API_HASH="your_api_hash"

bash ./moriarty-local telegram-phone "number" \
  --telegram-account "number" \
  --i-own-this-number
```

On first use Telegram asks for the login code and, when enabled, the account's
two-step-verification password. The reusable session is stored outside the
shared project at `~/.local/share/moriarty-v5/telegram/moriarty.session`.
Moriarty temporarily imports the number as a Telegram contact, reads the returned
account fields, and immediately deletes the temporary contact. The target must
exactly match `--telegram-account`; this command is intentionally limited to a
self-audit. `telegram-presence` remains available as a backwards-compatible alias.

Successful and inconclusive self-audit results are cached for 15 minutes in a
user-only local file. Repeated requests during that period do not contact
Telegram and return `cached: true` with `cache_age_seconds`.

### Facebook manual self-check

Moriarty can open Facebook in a visible browser for a user-controlled recovery
self-check of the user's own number:

```bash
bash ./moriarty-local facebook-self-check "number" \
  --i-own-this-number --timeout 180
```

Moriarty opens Facebook and clicks Forgot password. The user manually enters and
submits their own number. Moriarty never types or submits the number, selects an account, or selects a recovery
delivery method. If Facebook shows account candidates, Moriarty asks for explicit
terminal confirmation before saving the visible names and HTTP(S) photo URLs.
Rendered profile avatars are also captured directly from the visible page as PNG
files under `~/.local/share/moriarty-v5/facebook/photos/<number>/`; this does not
depend on Facebook CDN downloads succeeding.

The command also emits a `reputation_summary` with a normalized 0–100 risk
score, verdict, source counts, individual signals, and a conflict flag. Counts
from different sites are not added together because their definitions and
underlying report sets may overlap.

Turkish numbers also query Kim Arıyor for its community rating, risk percentage,
lookup count, and public comments. Tellows is not enabled because its public
number pages reject automated HTTP clients and its API requires partner access.

## Public documents

Document discovery searches specifically for public PDF, DOCX, and XLSX files,
downloads candidates, extracts their text locally, and returns only exact
normalized phone matches:

```bash
export GEMINI_API_KEY="your-new-key"
moriarty documents "+49 30 2970" --limit 10 --timeout 60
moriarty investigate "+49 30 2970" --documents --timeout 60
```

For image-only scanned PDFs, explicitly enable paid Gemini OCR. Local text extraction still runs first, and at most three scanned PDFs are uploaded by default:

```bash
bash ./moriarty-local documents "+49 30 2970" --ocr --ocr-limit 3 --timeout 120
bash ./moriarty-local investigate "+49 30 2970" --documents --document-ocr --timeout 120
```

If the selected Gemini model returns HTTP 503 high demand, list the models available to the current API key and explicitly select another one. Moriarty does not automatically retry paid requests:

```bash
bash ./moriarty-local gemini-models
bash ./moriarty-local documents "+49 30 2970" --model "MODEL_FROM_THE_LIST" --ocr --timeout 180
```

To enrich verified matches with source-grounded organization, department, address, email, additional phone, website, language, and document-category fields:

```bash
bash ./moriarty-local documents "+49 30 2970" --intelligence --intelligence-limit 3 --timeout 180
bash ./moriarty-local investigate "+49 30 2970" --documents --document-intelligence --timeout 180
```

Document intelligence sends only the verified text excerpt, not the full document. Extracted contact values are retained only when visible in that excerpt, and additional phone numbers are normalized before output. Intelligence errors do not remove the underlying verified document match.

## Verified web mentions

Web search results can be downloaded and verified against visible HTML before being accepted. Optional Gemini intelligence analyzes only the verified excerpt:

```bash
bash ./moriarty-local web-mentions "+44 20 3824 6771" --verify --limit 10 --timeout 180
bash ./moriarty-local web-mentions "+44 20 3824 6771" --verify --intelligence --intelligence-limit 3 --timeout 180
bash ./moriarty-local investigate "+44 20 3824 6771" --web --web-verify --web-intelligence --timeout 180
```

Private-network URLs and unsafe redirects are rejected. Script/style content is ignored, pages are limited to 2 MB, and document URLs are left to the `documents` module. Intelligence failures preserve the locally verified web mention.

## Additional investigation features

The offline phone profile now includes number type, national/international/RFC3966 formats, destination code, subscriber number, and fixed/mobile/VoIP/toll-free/premium/shared-cost/personal flags:

```bash
bash ./moriarty-local phone "+44 20 3824 6771"
```

Extract public JSON-LD, `tel:`, `mailto:`, organization, address, and opening-hours data from a page; or decode a local/public QR vCard without Gemini:

```bash
bash ./moriarty-local structured-contacts "https://example.com/contact" --region GB
bash ./moriarty-local qr-contact "/path/to/contact-qr.png" --region GB
```

Inspect public RDAP, DNS, MX, and TLS data, and validate an email without SMTP or sending a message:

```bash
bash ./moriarty-local domain "example.com" --timeout 10
bash ./moriarty-local email "support@example.com" --timeout 10
```

UK company-registry search uses the official Companies House API and requires its own key:

```bash
export COMPANIES_HOUSE_API_KEY="your-key"
bash ./moriarty-local company-registry "Example Ltd" --limit 10
```

Check whether a number is publicly listed by temporary-SMS directory pages. This is a public-source indicator, not proof of current ownership:

```bash
bash ./moriarty-local disposable "+44 20 3824 6771" --limit 10 --timeout 12
bash ./moriarty-local investigate "+44 20 3824 6771" --disposable --timeout 15
```

Disposable checking does not call Gemini. It fetches a bounded set of public SMS-directory index pages in parallel and reports `checked_sources` and per-source `failures`. A missing match means only `not_observed_on_checked_directory_pages`, never proof that a number is not disposable.

The `reputation` summary now also emits deterministic `campaign_clusters`, explicit-date `timeline` entries, and `related_number_mentions` labelled `co_mentioned_only`. No shared ownership is inferred.

The default Gemini model is `gemini-3.5-flash-lite`, which was verified with Google Search grounding for this project. Override it with `GEMINI_MODEL` or `--model` when needed.

OCR results are accepted only when the copied phone text normalizes back to the queried E.164 number. Output includes `page`, `extraction_method`, and any visible organization, department, address, or email context. Public PDF bytes are sent to Gemini only when OCR is enabled and local extraction finds no usable text.

Each result includes the document type, matched representation, nearby text,
source URL, and confidence. Search citations alone are not accepted as proof.
Files larger than 10 MB, unsupported formats, and URLs resolving to private or
local networks are rejected. Scanned image-only PDFs require OCR, which is not
part of this first document-source version.

## Additional phone sources

All commands below require `--i-own-this-number`.

## Gökbörü Intelligence web workspace

Start the local investigation workspace:

```bash
bash ./moriarty-local web-workspace
```

The interface opens at `http://127.0.0.1:8765/`. Create an investigation and
import one or more `phone-audit` JSON outputs; the latest observation from each
source is merged into the case while every original audit remains in history.
Data is stored locally under
`~/.local/share/moriarty-v5/gokboru/investigations.json`. The first release does
not expose the service externally and does not yet include AI scoring or report
generation.

### Phone audit core

`phone-audit` is the provider-neutral orchestration layer for the future web
workspace, AI interpretation, and HTML/PDF reporting layers. It validates the
number once, isolates provider failures, records timings, and emits versioned
JSON with a stable audit ID and common source/finding states. It does not yet
calculate an AI or risk score.

```bash
bash ./moriarty-local phone-audit "number" \
  --i-own-this-number \
  --sources local,brave,duckduckgo,opensanctions \
  --limit 20 --timeout 60
```

The default is the local source only. The catalog also includes `truecaller`,
`syncme`, `telegram`, `facebook`, `whatsapp`, `cybernews`,
`databreach`, `hudsonrock`, `github`, `reddit`, `brave`, `duckduckgo`,
`opensanctions`, `ftc`, and `btk`. Browser/manual sources run only
when explicitly selected. Missing credentials become `skipped`, access controls
become `blocked`, and provider errors become `failed`; one source cannot stop
the remaining audit.

Phone-driven discovery modules are also available as `web-mentions`,
`pastebin`, `documents`, `reputation`, `business`, and `disposable`. The first
three use Gemini and read `GEMINI_API_KEY`. Document OCR and structured
extraction remain opt-in with `--document-ocr` and
`--document-intelligence`.

Use `--sources all` to run the complete catalog. This can open manual/browser
flows and use paid APIs, so it should only be used after the required sessions,
credentials, and optional paid features have been reviewed.

Search exact formatted variants on Brave's public web index:

```bash
export BRAVE_SEARCH_API_KEY="your-key"
bash ./moriarty-local brave-phone-search "+1 202 555 0199" \
  --i-own-this-number --limit 20
```

DuckDuckGo requires no API key. Moriarty first uses DuckDuckGo's non-JavaScript
search and falls back to a normal visible Chromium window if that endpoint is
blocked. CAPTCHA is never bypassed:

```bash
bash ./moriarty-local duckduckgo-phone-search "number" \
  --i-own-this-number --limit 20 --timeout 60
```

To run the normal browser invisibly on Ubuntu without enabling browser headless
mode, wrap the same command with `xvfb-run -a`.

OpenSanctions can search exact E.164 phone fields across its public-interest
entity datasets. An API key is required and the query may appear in provider
access logs:

```bash
export OPENSANCTIONS_API_KEY="your-key"
bash ./moriarty-local opensanctions-phone-search "number" \
  --i-own-this-number --dataset default --limit 20
```

Moriarty discards search candidates unless the returned entity contains the
exact normalized phone number. A hit is a source record requiring human review,
not proof that the current subscriber is the listed entity.

The FTC command downloads recent official daily Do Not Call complaint files and
filters them locally by the exact reported company phone number. Complaints are
unverified consumer reports and this source covers United States calls only:

```bash
bash ./moriarty-local ftc-complaints "+1 202 555 0199" \
  --i-own-this-number --days 7
```

BTK number-portability inquiry opens the official e-Devlet page. It reports only
the displayed operator/portability result and does not bypass CAPTCHA or login:

```bash
bash ./moriarty-local btk-portability "number" \
  --i-own-this-number --timeout 120
```
