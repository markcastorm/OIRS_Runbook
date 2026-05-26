# OIRS Runbook

Automated pipeline that downloads the OECD "Financing SMEs and Entrepreneurs" annual report
and extracts the **Interest Rate Spread** for 7 countries into standard AfricaAI output files.

---

## Quick Start

```bash
python main.py
```

Outputs written to `output/`:
- `OIRS_DATA_YYYYMMDD.xlsx` — data file (two header rows + year rows)
- `OIRS_META_YYYYMMDD.xlsx` — metadata file (one row per country)
- `OIRS_YYYYMMDD.zip` — ZIP of both files
- `output/latest/` — copy of the latest run

---

## Countries

Australia, Canada, France, Italy, Spain, United Kingdom, United States

(USA always blank — US scoreboard tables don't include "Interest rate spread".)

---

## Configuration (`config.py`)

| Setting | Default | Description |
|---------|---------|-------------|
| `HEADLESS_MODE` | `True` | `True` for Docker/Linux, `False` for local debugging |
| `TARGET_DATE` | `None` | `None` = latest report; `"31 March 2026"` = specific edition |
| `WAIT_TIMEOUT` | `60` | Browser wait timeout in seconds |

---

## Dependencies

```bash
pip install playwright playwright-stealth pymupdf pandas openpyxl requests beautifulsoup4
python -m playwright install chromium
```

---

## How It Works

1. **Scraper** (`scraper.py`) — Uses Playwright Chromium + playwright-stealth to navigate the
   OECD publications page, locate the target report, and download the PDF. Playwright uses the
   Chrome DevTools Protocol directly (no WebDriver), which bypasses Cloudflare bot detection.

2. **Extractor** (`extractor.py`) — Opens the PDF with fitz (PyMuPDF). For each country, finds
   the "Scoreboard for \<Country\>" page using multi-criteria confirmation (title + keywords + year
   density), then uses `find_tables()` to extract the "Interest rate spread" row values.

3. **File Generator** (`file_generator.py`) — Writes the DATA and META xlsx files and ZIP archive.

---

## Project Information

See `Project_information/Claude.md` for complete technical documentation:
- Cloudflare bypass approach and history
- Page finding algorithm details
- Year extraction and column mapping
- Edge cases and lessons learned
- All test results (28/28 PASS)

Sample PDFs for testing: `Project_information/samplepdf/` (2020, 2022, 2024, 2026 editions)

Test files: `Project_information/test_*.py`

---

## Source

OECD "Financing SMEs and Entrepreneurs" series  
`https://www.oecd.org/en/publications/financing-smes-and-entrepreneurs_23065265.html`
