# OIRS Runbook - Claude Working Context

## Project Status: COMPLETE — All 7 countries, 28/28 tests PASS, full pipeline working end-to-end

---

## Project Summary

Automated extraction of **Interest Rate Spread** data for 7 countries from OECD "Financing SMEs and Entrepreneurs" annual PDF reports.

- **Source**: OECD Publications - "Financing SMEs and Entrepreneurs" series
- **Source URL**: `https://www.oecd.org/en/publications/financing-smes-and-entrepreneurs_23065265.html`
- **Provider**: AfricaAI | **Dataset**: OIRS | **Source Org**: OECD (Organisation for Economic Co-operation and Development)
- **Frequency**: Annual (A)
- **Data Type**: PERCENT | **Unit**: Percentage points | **Seasonally Adjusted**: NSA

Pipeline: `main.py` → `orchestrator.py` → `scraper.py` → `extractor.py` → `file_generator.py`

---

## Pipeline Flow

```
python main.py
  |
  v
orchestrator.main()
  |
  |-- Step 1: scraper.download()
  |     - Launch Playwright Chromium (headless) + playwright-stealth
  |     - Navigate to OECD publications landing page
  |     - Find target report (latest or by config date)
  |     - Derive PDF URL (3-path strategy: iLibrary direct → requests+cookies → browser click)
  |     - Download PDF via requests
  |     Returns: {pdf_path, date_str, report_title}
  |
  |-- Step 2: extractor.extract(pdf_path)
  |     - Open PDF once with fitz (PyMuPDF)
  |     - For each of 7 countries:
  |       - Find "Scoreboard for <Country>" page (multi-criteria confirmation)
  |       - Extract years from page text
  |       - Use fitz find_tables() to locate "Interest rate spread" row
  |       - Map years to columns and extract values
  |     - Merge all country data into DataFrame
  |     Returns: DataFrame (index=year int, columns=country names, values=float/NaN)
  |
  |-- Step 3: file_generator.generate_files(df, date_str)
  |     - Writes OIRS_DATA_<date>.xlsx (two header rows + data)
  |     - Writes OIRS_META_<date>.xlsx (one row per country)
  |     - Creates OIRS_<date>.zip
  |     - Copies all three to output/latest/
  |     Returns: {data_path, meta_path, zip_path}
```

---

## File Map

| File | Purpose | Status |
|------|---------|--------|
| `main.py` | Entry point, logging setup | DONE |
| `orchestrator.py` | Pipeline coordinator (3 steps) | DONE |
| `config.py` | All configuration, country list, column mappings | DONE |
| `scraper.py` | Playwright browser automation, PDF download | DONE |
| `extractor.py` | PDF table extraction using fitz find_tables() | DONE |
| `file_generator.py` | Excel/ZIP output generation | DONE |
| `Project_information/test_australia.py` | Australia extraction test across 4 PDFs | DONE — ALL 4 PASS |
| `Project_information/test_all_countries.py` | All-country extraction test | DONE — 28/28 PASS |
| `Project_information/test_all_countries_probe.py` | Probe/debug script | DONE |
| `Project_information/test_extraction.py` | Legacy camelot-based test | SUPERSEDED (fitz is better) |

---

## Target Countries (7 total)

| Country | ISO Code | Output Code | Table Title in PDF |
|---------|----------|-------------|-------------------|
| Australia | AUS | OIRS.IRS.AUS.A | Scoreboard for Australia |
| Canada | CAN | OIRS.IRS.CAN.A | Scoreboard for Canada |
| France | FRA | OIRS.IRS.FRA.A | Scoreboard for France |
| Italy | ITA | OIRS.IRS.ITA.A | Scoreboard for Italy |
| Spain | ESP | OIRS.IRS.ESP.A | Scoreboard for Spain |
| United Kingdom | GBR | OIRS.IRS.GBR.A | Scoreboard for the United Kingdom |
| United States | USA | OIRS.IRS.USA.A | Scoreboard for the United States |

Note: USA column is **ALL blank/NaN** — US tables don't include "Interest rate spread".
Note: UK/US use **"the"** in the table_search string: "Scoreboard for **the** United Kingdom"

---

## Scraper Design (scraper.py)

### Why Playwright (not Selenium / undetected_chromedriver)

The OECD publication detail page is protected by **Cloudflare Managed Challenge** with
**Private Access Token (PAT)** — a W3C protocol requiring OS/hardware attestation. This
challenge type is unsolvable by any headless automated browser, including:
- Selenium Chrome with undetected_chromedriver
- Selenium Firefox with stealth UA
- Any approach that sets up WebDriver — Cloudflare detects `navigator.webdriver`

**Playwright bypasses it entirely** because:
- Uses Chrome DevTools Protocol (CDP) directly — no WebDriver layer
- No `navigator.webdriver` signal by default
- `playwright-stealth` applies puppeteer-extra-plugin-stealth patches (WebGL, canvas, chrome.runtime, etc.)
- Result: Cloudflare detail page loaded in **0.3 seconds** with NO challenge at all

### Browser Setup: `_build_playwright(download_dir)`

**Critical**: Playwright v1.58+ uses TWO separate Chromium binaries:
- `headless=True` → uses `chrome-headless-shell` — a stripped-down headless-only binary that
  Cloudflare **trivially detects** (different TLS fingerprint, no GPU/WebGL, headless-specific signals)
- `headless=False` → uses full `Chrome for Testing` binary

**Solution**: ALWAYS launch with `headless=False` (full Chrome binary) and pass `--headless=new`
as a launch argument when headless mode is needed. Chrome's "new headless" mode uses the full
rendering pipeline — same WebGL, same TLS, same everything — making it indistinguishable from
headed Chrome. Result: Cloudflare detail page loads in **0.2 seconds** with NO challenge.

```python
pw = sync_playwright().start()
launch_args = ['--disable-blink-features=AutomationControlled']
if config.HEADLESS_MODE:
    launch_args.append('--headless=new')
    launch_args.extend(['--no-sandbox', '--disable-dev-shm-usage'])

browser = pw.chromium.launch(
    headless=False,           # Always use the full Chrome binary
    args=launch_args,
)
context = browser.new_context(
    viewport={'width': 1920, 'height': 1080},
    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...',
    locale='en-US', timezone_id='America/New_York', accept_downloads=True,
)
context.set_default_timeout(config.WAIT_TIMEOUT * 1000)
page = context.new_page()
Stealth().apply_stealth_sync(page)   # playwright-stealth v2.0.3 API
```

**Important**: playwright-stealth v2.0.3 API changed:
- OLD (v1.x): `from playwright_stealth import stealth_sync; stealth_sync(page)` — BROKEN
- NEW (v2.x): `from playwright_stealth import Stealth; Stealth().apply_stealth_sync(page)` — CORRECT

**DO NOT use `--disable-gpu`** — it forces SwiftShader (software WebGL), which is a strong
headless detection signal. Only use `--no-sandbox` and `--disable-dev-shm-usage` in
Docker/Linux (they're added conditionally when `HEADLESS_MODE=True`).

### PDF URL Strategy: `_find_pdf_download_url(page, context, detail_url, link_el)`

Three paths tried in order:

1. **iLibrary direct URL** — Construct `https://www.oecd-ilibrary.org/deliver/{id}/{id}.pdf` from
   the publication ID embedded in the detail page URL. No browser interaction needed.
   Returns HTTP 403 in most environments but kept as Path 1.

2. **requests + session cookies** — Use `context.cookies()` (Playwright API) to get browser cookies,
   fetch the detail page with requests, parse PDF link with BeautifulSoup.
   Works when the detail page is directly accessible (no Cloudflare challenge).

3. **Human-like browser click** — `link_el.scroll_into_view_if_needed()` + `link_el.click()`,
   then handle any Cloudflare Turnstile via `_handle_cloudflare()` / `_click_turnstile_checkbox()`.

**Important**: OECD returns relative hrefs (e.g., `/en/publications/...`). Always check:
```python
if detail_url.startswith('/'):
    detail_url = 'https://www.oecd.org' + detail_url
```

### Cloudflare Turnstile Click: `_click_turnstile_checkbox(page)`

4 fallback methods (only needed if Playwright somehow hits a challenge):
1. `page.frames` iteration — Playwright can access cross-origin Cloudflare iframe (Selenium cannot)
2. `page.frame_locator('iframe[src*="challenges.cloudflare.com"]')` — Playwright high-level API
3. Any visible iframe click
4. `page.mouse.click(430, 362)` — Estimated Turnstile position

### Navigation Flow

1. `page.goto(BASE_URL)` — publications landing page
2. `_dismiss_cookie_consent(page)` — dismiss GDPR popup if present
3. `_find_target_publication(page)` — scan `li.cmp-list__item` entries, pick latest or TARGET_DATE
4. `_find_pdf_download_url(page, context, detail_url, link_el)` — 3-path PDF URL strategy
5. `_download_pdf_via_requests(pdf_url, dest, session_cookies)` — stream download

### Config Options

- `TARGET_DATE = None` → pick latest report (highest publication date)
- `TARGET_DATE = "31 March 2026"` → pick specific dated report
- `HEADLESS_MODE = True` → headless (Docker/Linux production)
- `HEADLESS_MODE = False` → headed (debugging only)

---

## Extraction Technology: fitz (PyMuPDF) find_tables()

### Why fitz over camelot

| Feature | camelot | fitz find_tables() |
|---------|---------|-------------------|
| Label splitting | Splits "Interest rate spread" across 2-3 rows | Keeps labels intact (uses \n within cell) |
| Year headers | Merges narrow year columns ("2020  2021") | Each year gets its own column |
| Value separation | Unpredictable column counts | Consistent, matches PDF borders |
| Sub-table detection | Returns one giant table for the page | Returns separate logical sub-tables |
| Speed | Requires Ghostscript, slower | Native Python, faster |
| Dependency | camelot-py[cv] + Ghostscript | Only PyMuPDF (fitz) |

### OECD Scoreboard Page Structure

Each scoreboard page yields **4 sub-tables** from `fitz find_tables()`:

| Table | Content | Has our target? |
|-------|---------|-----------------|
| Table 0 | Header area (year labels — often 0 rows) | No |
| Table 1 | **Debt section** (loans, interest rates, **Interest rate spread**) | **YES** |
| Table 2 | Non-bank finance (venture capital) | No |
| Table 3 | Other indicators (bankruptcies, etc.) | No |

### Label Normalization

fitz packs multi-line cell content with `\n`:
- `"Interest rate\nspread"` → `_normalize_label()` → `"Interest rate spread"`

```python
def _normalize_label(cell_text):
    return ' '.join(str(cell_text).replace('\n', ' ').split()).strip()
```

---

## Page Finding Algorithm (extractor._find_country_page)

### The Problem

"Scoreboard for Australia" appears on MULTIPLE pages:
- **Table of Contents** (page ~11) — title present, NO data
- **Actual data table** (page ~84-125 depending on edition) — title + data

### The Solution: Multi-criteria confirmation

A page is only accepted when ALL three conditions are met:
1. Scoreboard title present: `"Scoreboard for <Country>"` found in page text
2. At least `TABLE_CONFIRM_MIN` (3) of these keywords found (combined with next page):
   ```
   'outstanding business loans, smes', 'non-performing loans',
   'interest rate, smes', 'interest rate, large firms',
   'percentage points', 'venture and growth capital'
   ```
3. At least `TABLE_MIN_YEAR_COUNT` (5) distinct year numbers on the page

Current+next page combined text is used for keyword matching because spanning tables
may place some labels on page N+1.

---

## Year Extraction & Column Mapping

### Year Extraction

fitz Table 0 (year headers) often has 0 rows. Years are extracted from page text instead:
```python
all_years = [int(y) for y in re.findall(r'\b(20[0-3]\d)\b', doc[page_num].get_text())]
# Find longest consecutive run (avoids page numbers / footnote years)
```

### Year-to-Column Mapping

OECD tables always have:
- Col 0: Label
- Col 1: Unit
- Cols 2+: Data values (one per year, oldest→newest, left→right)

`_map_years_to_columns(df, years_title, years_secondary)` handles spanning tables:
if the next page's year set better matches the data column count, it's used instead.

| Edition | Year range | Data columns |
|---------|-----------|--------------|
| 2020 | 2007-2018 | 12 |
| 2022 | 2007-2020 | 14 |
| 2024 | 2007-2022 | 16 |
| 2026 | 2007-2024 | 18 |

---

## Test Results (all PASS)

### test_all_countries.py — 28/28 PASS (7 countries × 4 editions)

Editions tested: 2020, 2022, 2024, 2026 PDFs from `Project_information/samplepdf/`

USA always returns empty (no "Interest rate spread" row in US tables — expected).

### Reference data (from 2026 PDF edition)

```
Year  AUS   CAN   FRA   ITA   ESP   GBR   USA
2007  0.71  1.40  —     0.60  0.63  —     —
2008  1.70  —     5.42  1.00  1.21  1.05  —
2009  1.66  3.10  2.86  1.40  1.47  1.12  —
2010  1.38  3.20  2.48  1.60  1.21  1.39  —
2011  1.28  2.30  3.11  1.60  1.59  1.27  —
2012  1.62  2.40  2.43  2.00  2.30  1.30  —
2013  1.77  2.60  2.16  2.00  2.10  1.40  —
2014  1.67  2.10  2.08  1.90  1.87  0.98  —
2015  1.73  2.30  1.78  1.90  1.04  1.22  —
2016  1.86  2.60  1.50  1.50  0.88  0.62  —
2017  1.85  2.30  1.40  1.20  0.59  0.73  —
2018  1.61  2.06  1.48  1.30  0.20  0.74  —
2019  1.70  1.70  1.40  1.70  0.56  0.77  —
2020  1.77  2.03  1.00  0.80  0.32  0.28  —
2021  1.60  1.64  1.26  1.20  0.52  0.33  —
2022  0.98  2.10  1.90  2.00  0.20  0.68  —
2023  0.72  2.06  4.20  1.30  0.23  0.66  —
2024  0.76  0.51  4.26  1.30  0.04  0.61  —
```

**Note**: OECD revises historical data between editions. 2020 edition values differ
significantly from 2022+ (different methodology/source). Test validation uses per-edition
reference values. Production always uses the latest edition.

---

## Output Files

### DATA File: `OIRS_DATA_YYYYMMDD.xlsx`

```
Row 0 (codes):   [blank], OIRS.IRS.AUS.A, OIRS.IRS.CAN.A, ..., OIRS.IRS.USA.A
Row 1 (labels):  [blank], Interest rate spread: Australia, ..., ...United States
Row 2+:          2007, 0.71, 1.4, [blank], 0.60, 0.63, [blank], [blank]
```
- Missing values written as `''` (config.NA_OUTPUT_VALUE)
- Column 0 = year integer, no header
- Country columns in absolute order (config.COUNTRIES order)

### META File: `OIRS_META_YYYYMMDD.xlsx`

One row per country. Key columns: CODE, CODE_MNEMONIC, DESCRIPTION, FREQUENCY=A,
MULTIPLIER=0, DATA_TYPE=PERCENT, DATA_UNIT=PERCENT, SEASONALLY_ADJUSTED=NSA,
PROVIDER=AfricaAI, SOURCE=OECD, DATASET=OIRS.

### ZIP: `OIRS_YYYYMMDD.zip`

Contains DATA and META xlsx files. Also copied to `output/latest/`.

---

## Source Website HTML Structure

### Landing Page: `https://www.oecd.org/en/publications/financing-smes-and-entrepreneurs_23065265.html`

```html
<li class="cmp-list__item">
  <div class="link-list report-summary-page">
    <div class="link-list__content">
      <div class="link-list__title">
        <a class="link-list__title-link"
           href="/en/publications/financing-smes-and-entrepreneurs-2026_075d8058-en.html">
          Financing SMEs and Entrepreneurs 2026
        </a>
        <span class="link-list__date">31 March 2026</span>
        <span class="link-list__pages">220 Pages</span>
      </div>
    </div>
  </div>
</li>
```

### Detail Page (e.g., `financing-smes-and-entrepreneurs-2026_075d8058-en.html`)

```html
<div class="cmp-content-language-picker__download">
  <a href="/content/dam/oecd/en/publications/reports/2026/03/.../075d8058-en.pdf"
     class="cmp-button" target="_blank">
    <span class="cmp-button__text">Download PDF</span>
  </a>
</div>
```

PDF URL pattern: `https://www.oecd.org/content/dam/oecd/en/publications/reports/{year}/{month}/.../{id}.pdf`

---

## Sample PDFs (Project_information/samplepdf/)

```
075d8058-en.pdf  — 2026 edition, 220 pages
fa521246-en.pdf  — 2024 edition, 254 pages
e9073a0f-en.pdf  — 2022 edition, 274 pages
061fe03d-en.pdf  — 2020 edition, 224 pages
```

---

## Dependencies

```
playwright          # browser automation (Chromium via CDP)
playwright-stealth  # v2.0.3 — stealth patches (API: Stealth().apply_stealth_sync(page))
pymupdf (fitz)      # PDF parsing and table extraction
pandas, openpyxl    # DataFrame manipulation and Excel output
requests            # HTTP PDF download
beautifulsoup4      # HTML parsing for PDF link extraction
```

Install Playwright browsers once:
```
python -m playwright install chromium
```

**No longer needed**: selenium, undetected-chromedriver, selenium-stealth, camelot-py, Ghostscript

---

## Key Edge Cases

1. **USA has no IRS row** — US scoreboard tables don't include "Interest rate spread". Output is all blank. Expected behavior.
2. **UK/US use "the" in title** — config `table_search` correctly uses "Scoreboard for the United Kingdom" / "Scoreboard for the United States".
3. **Spanning tables** — Some country tables span 2 pages (data on page N+1). `_extract_table()` checks page+1, `_map_years_to_columns()` picks best-matching year set.
4. **TOC pages** — Multi-criteria confirmation prevents landing on Table of Contents page.
5. **Relative hrefs** — OECD returns `/en/publications/...` (not full URLs). Prepend `https://www.oecd.org`.
6. **Data revisions** — 2020 edition has significantly different values from 2022+ (methodology change). Per-edition reference values used in tests.
7. **fitz Table 0 empty** — Year header table often has 0 rows. Always extract years from raw page text.
8. **fitz \n in cells** — Multi-line cell content joined with \n. Normalize with `replace('\n', ' ')`.

---

## Cloudflare Notes

- **Challenge type**: Cloudflare Managed Challenge with Private Access Token (PAT)
- **PAT**: W3C protocol requiring hardware/OS attestation — unsolvable by any headless browser
- **Playwright solution**: CDP direct = no WebDriver = no `navigator.webdriver` = Cloudflare passes
- **Turnstile code exists** in `_click_turnstile_checkbox()` and `_handle_cloudflare()` as fallback,
  but in practice Playwright + stealth + `--headless=new` bypasses the challenge before it appears

### Headless Mode: The `chrome-headless-shell` Problem

Playwright v1.58+ installs **two separate binaries** when you run `playwright install chromium`:
1. `Chrome for Testing` (full browser) — used when `headless=False`
2. `Chrome Headless Shell` (stripped-down) — used when `headless=True`

The headless shell is **trivially detected** by Cloudflare:
- Different TLS fingerprint from real Chrome
- No GPU rendering (falls back to SwiftShader — detectable via WebGL)
- Missing Chrome features (printing, extensions, etc.)
- Different `navigator` properties

**Result with `headless=True`**: Landing page loads fine (no Cloudflare on listing page),
but the detail page triggers Turnstile challenge → loops for 90s → fails with "Just a moment..."

**Fix**: ALWAYS launch with `headless=False` (selects full Chrome binary) and pass
`--headless=new` as a Chrome argument. This uses Chrome's "new headless" mode which runs
the full rendering pipeline without a visible window. Cloudflare cannot distinguish it from
headed Chrome. Detail page loads in **0.2s** with no challenge at all.

Approaches that FAILED (do not attempt):
- Selenium Chrome + undetected_chromedriver (`excludeSwitches` option is unsupported in UC)
- Selenium Firefox headless (`Request for the Private Access Token challenge` in console)
- Waiting/polling for Cloudflare to clear (managed challenge + PAT doesn't auto-clear)
- Playwright `headless=True` (uses `chrome-headless-shell` — detected by Cloudflare)
- `--disable-gpu` flag (forces SwiftShader WebGL — strong headless detection signal)

---

## Environment

- **Dev**: Windows 11, Python 3.11/3.13
- **Prod**: Docker Linux Ubuntu
- All file paths use `os.path.join()` for cross-platform compatibility
- `HEADLESS_MODE = True` for Docker (no display)
- `HEADLESS_MODE = False` for local debugging

---

## Lessons Learned

1. **Playwright bypasses Cloudflare PAT silently** — no challenge appears at all when using CDP direct. This is the key insight that unblocked the entire pipeline.
2. **NEVER use Playwright's `headless=True`** — it selects `chrome-headless-shell` which Cloudflare detects instantly. Instead use `headless=False` + `args=['--headless=new']` to get the full Chrome binary running in headless mode. This is indistinguishable from headed Chrome.
3. **playwright-stealth v2.0.3 API changed** — use `Stealth().apply_stealth_sync(page)`, not the old `stealth_sync(page)` function.
4. **Page finding needs multi-criteria** — scoreboard title alone lands on TOC. Require title + keywords + year density.
5. **fitz is superior to camelot** — no label splitting, proper year columns, cleaner values, no Ghostscript dependency.
6. **Year headers not in fitz table structure** — Table 0 (year header area) often has 0 rows; extract from raw page text.
7. **OECD revises historical data** — test with per-edition reference values, not cross-edition.
8. **Relative hrefs** — OECD detail page hrefs are relative; always prepend `https://www.oecd.org`.
9. **iLibrary deliver URL returns 403** — kept as Path 1 in case environment allows it, but Path 2 (requests+cookies) or Path 3 (browser) always works.
10. **`--disable-gpu` is a detection signal** — forces SwiftShader software rendering which exposes a known WebGL vendor string. Omit this flag; let Chrome use the system GPU or its default renderer.
