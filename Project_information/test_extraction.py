"""
Test script for OIRS table extraction.

Uses fitz (PyMuPDF) for fast page finding, then camelot for table extraction.
Tests against sample PDFs in Project_information/samplepdf/.

Usage:
    python test_extraction.py                          # test 2026 PDF (default)
    python test_extraction.py 2024                     # test 2024 PDF
    python test_extraction.py 2022                     # test 2022 PDF
    python test_extraction.py all                      # test all PDFs
    python test_extraction.py <path_to_pdf>            # test a specific PDF
"""

import os
import re
import sys
import logging
import threading

import fitz       # PyMuPDF - fast page search
import camelot    # table extraction
import pandas as pd

# Add parent dir to path for config import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

# ── Sample PDF paths ─────────────────────────────────────────────────────────
SAMPLE_DIR = os.path.join(config.BASE_DIR, 'Project_information', 'samplepdf')
SAMPLE_PDFS = {
    '2026': os.path.join(SAMPLE_DIR, '075d8058-en.pdf'),
    '2024': os.path.join(SAMPLE_DIR, 'fa521246-en.pdf'),
    '2022': os.path.join(SAMPLE_DIR, 'e9073a0f-en.pdf'),
}

# ── Debug output ─────────────────────────────────────────────────────────────
DEBUG_DIR = os.path.join(config.BASE_DIR, 'debug')


# ── Fast page search using fitz ──────────────────────────────────────────────

def _scan_range_fitz(pdf_path, page_sequence, name, keyword, found_event, result_holder):
    """Worker: scan pages in given order for a keyword."""
    try:
        doc = fitz.open(pdf_path)
        for pg in page_sequence:
            if found_event.is_set():
                doc.close()
                return
            if pg < 0 or pg >= len(doc):
                continue
            text = doc[pg].get_text().lower()
            text_flat = ' '.join(text.split())
            if keyword.lower() in text_flat:
                result_holder[0] = pg
                found_event.set()
                doc.close()
                return
        doc.close()
    except Exception as e:
        logger.debug(f"[{name}] Error: {e}")


def find_page_fitz(pdf_path, keyword):
    """
    Find the page containing the given keyword using 3 parallel workers.
    Returns page number (0-indexed) or None.
    """
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    bottom_up = list(range(total_pages - 1, -1, -1))
    top_down = list(range(total_pages))
    mid = total_pages // 2
    middle_out = []
    for offset in range(total_pages):
        if mid + offset < total_pages:
            middle_out.append(mid + offset)
        if mid - offset >= 0 and mid - offset != mid + offset:
            middle_out.append(mid - offset)

    found_event = threading.Event()
    result_holder = [None]

    workers = [
        ('bottom-up', bottom_up),
        ('middle-out', middle_out),
        ('top-down', top_down),
    ]

    threads = []
    for name, seq in workers:
        t = threading.Thread(
            target=_scan_range_fitz,
            args=(pdf_path, seq, name, keyword, found_event, result_holder),
            daemon=True,
        )
        threads.append(t)
        t.start()

    while any(t.is_alive() for t in threads):
        if found_event.wait(timeout=0.2):
            break

    return result_holder[0]


def _count_years_on_page(text_flat):
    """Count how many distinct year numbers (2007-2030) appear on a page."""
    year_pattern = re.compile(r'\b(20[0-3]\d)\b')
    years = set(year_pattern.findall(text_flat))
    return len(years)


def find_country_page(pdf_path, country_config):
    """
    Find the page for a country's scoreboard table.

    The scoreboard title alone is NOT enough — it appears on TOC/index pages too.
    We require the title PLUS multiple table-specific row labels (from config)
    AND dense year numbers to confirm it's the actual data table page.

    Returns page number (0-indexed) or None.
    """
    search_term = country_config['table_search'].lower()
    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    candidates = []
    for pg in range(total_pages):
        text = doc[pg].get_text().lower()
        text_flat = ' '.join(text.split())

        if search_term not in text_flat:
            continue

        # Count how many confirm keywords match on this page
        confirm_count = sum(1 for kw in config.TABLE_CONFIRM_KEYWORDS if kw in text_flat)

        # Count year numbers on this page
        year_count = _count_years_on_page(text_flat)

        # The real table page has many confirm keywords AND dense year columns
        if (confirm_count >= config.TABLE_CONFIRM_MIN
                and year_count >= config.TABLE_MIN_YEAR_COUNT):
            candidates.append((pg, confirm_count, year_count))
            logger.debug(
                f"  Page {pg+1}: title=YES, confirms={confirm_count}, years={year_count} -> CANDIDATE"
            )
        else:
            logger.debug(
                f"  Page {pg+1}: title=YES, confirms={confirm_count}, years={year_count} -> skipped"
            )

    doc.close()

    if not candidates:
        logger.warning(
            f"No page matched all criteria for '{country_config['table_search']}'. "
            f"Searched {total_pages} pages."
        )
        return None

    # Pick the candidate with the highest confirm count, then highest year count
    candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
    best_page = candidates[0][0]
    return best_page


# ── Camelot table extraction ────────────────────────────────────────────────

def extract_table_from_page(pdf_path, page_num, country_name=''):
    """
    Extract tables from a page (and optionally next page) using camelot.
    Returns a single merged DataFrame or None.
    """
    page_str = str(page_num + 1)  # camelot is 1-indexed

    try:
        tables = camelot.read_pdf(
            pdf_path,
            pages=page_str,
            flavor='stream',
            edge_tol=50,
        )
    except Exception as e:
        logger.error(f"Camelot failed on page {page_str}: {e}")
        return None

    if not tables:
        logger.warning(f"No tables found on page {page_str}")
        return None

    logger.info(f"Camelot found {len(tables)} table(s) on page {page_str} for {country_name}")

    # Pick the table with the most rows (most likely the scoreboard)
    best_df = max([t.df for t in tables], key=lambda df: len(df))

    # Check if table spans to next page
    doc = fitz.open(pdf_path)
    if page_num + 1 < len(doc):
        next_text = doc[page_num + 1].get_text().lower()
        next_flat = ' '.join(next_text.split())

        # The continuation page should have data rows but NOT the scoreboard title again
        country_search = None
        for c in config.COUNTRIES:
            if c['name'] == country_name:
                country_search = c['table_search'].lower()
                break

        # Check if the next page has continuation indicators
        has_continuation = (
            ('venture' in next_flat or 'leasing' in next_flat or
             'bankruptcies' in next_flat or 'payment delay' in next_flat or
             'factoring' in next_flat)
            and (country_search is None or country_search not in next_flat)
        )

        if has_continuation:
            logger.info(f"Table for {country_name} may span to page {page_num + 2}, extracting...")
            try:
                next_tables = camelot.read_pdf(
                    pdf_path,
                    pages=str(page_num + 2),
                    flavor='stream',
                    edge_tol=50,
                )
                if next_tables:
                    next_df = max([t.df for t in next_tables], key=lambda df: len(df))
                    # Only merge if the continuation table has data-looking rows
                    # (not a completely new scoreboard for another country)
                    first_label = str(next_df.iloc[0, 0]).strip().lower() if len(next_df) > 0 else ''
                    if 'scoreboard' not in first_label:
                        best_df = pd.concat([best_df, next_df], ignore_index=True)
                        logger.info(f"Merged continuation page: now {len(best_df)} rows")
            except Exception as e:
                logger.debug(f"Continuation extraction failed: {e}")

    doc.close()
    return best_df


# ── Table parsing ────────────────────────────────────────────────────────────

def parse_year_headers(df):
    """
    Find the row containing year columns (2007, 2008, ...) and return:
      - data_start_row: first row of actual data
      - year_columns: dict of {df_col_index: year_int}
    """
    year_pattern = re.compile(r'^(19|20)\d{2}$')

    for row_idx in range(min(10, len(df))):
        row_vals = [str(v).strip() for v in df.iloc[row_idx]]
        years_found = {}
        for col_idx, val in enumerate(row_vals):
            if year_pattern.match(val):
                years_found[col_idx] = int(val)

        if len(years_found) >= 3:  # at least 3 year columns to confirm
            logger.info(f"Year header row: {row_idx}, years: {sorted(years_found.values())}")
            return row_idx + 1, years_found

    return 0, {}


def find_interest_rate_spread(df, data_start_row, year_columns):
    """
    Find the 'Interest rate spread' row in the table and extract values.
    Returns: dict of {year: value} or empty dict if not found.
    """
    target = config.TARGET_ROW_LABEL.lower()

    for row_idx in range(data_start_row, len(df)):
        label = str(df.iloc[row_idx, 0]).strip().lower()
        # Clean up label
        label_clean = re.sub(r'\s+', ' ', label).strip()

        if target in label_clean:
            logger.info(f"Found '{config.TARGET_ROW_LABEL}' at row {row_idx}")
            values = {}
            for col_idx, year in year_columns.items():
                if col_idx < len(df.columns):
                    raw = str(df.iloc[row_idx, col_idx]).strip()
                    # Parse numeric value
                    raw = raw.replace(',', '').replace(' ', '')
                    if raw in ('', '-', '--', 'nan', '..', '…', 'nil', 'n/a'):
                        values[year] = None
                    else:
                        try:
                            values[year] = float(raw)
                        except ValueError:
                            values[year] = None
            return values

    logger.warning(f"'{config.TARGET_ROW_LABEL}' NOT found in table")
    return {}


# ── Main test function ───────────────────────────────────────────────────────

def test_pdf(pdf_path, pdf_label=''):
    """Test extraction on a single PDF. Returns results dict."""
    if not os.path.exists(pdf_path):
        logger.error(f"PDF not found: {pdf_path}")
        return None

    logger.info(f"\n{'='*70}")
    logger.info(f"TESTING: {pdf_label or pdf_path}")
    logger.info(f"{'='*70}")

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()
    logger.info(f"PDF has {total_pages} pages")

    os.makedirs(DEBUG_DIR, exist_ok=True)

    all_results = {}

    for country in config.COUNTRIES:
        name = country['name']
        logger.info(f"\n--- {name} ---")

        # Step 1: Find page
        page_num = find_country_page(pdf_path, country)
        if page_num is None:
            logger.warning(f"Could not find table for {name}")
            all_results[name] = {'page': None, 'values': {}}
            continue

        logger.info(f"Found {name} table on page {page_num + 1} (0-idx: {page_num})")

        # Step 2: Extract table
        df = extract_table_from_page(pdf_path, page_num, name)
        if df is None:
            logger.warning(f"No table extracted for {name}")
            all_results[name] = {'page': page_num + 1, 'values': {}}
            continue

        # Save debug CSV
        debug_path = os.path.join(
            DEBUG_DIR,
            f'{pdf_label}_{name.replace(" ", "_")}_page{page_num + 1}_raw.csv'
        )
        df.to_csv(debug_path, index=False)
        logger.info(f"Raw table: {df.shape[0]} rows x {df.shape[1]} cols -> {debug_path}")

        # Step 3: Parse years
        data_start, year_cols = parse_year_headers(df)
        if not year_cols:
            logger.warning(f"No year columns found for {name}")
            all_results[name] = {'page': page_num + 1, 'values': {}}
            continue

        # Step 4: Find interest rate spread
        values = find_interest_rate_spread(df, data_start, year_cols)
        all_results[name] = {
            'page': page_num + 1,
            'years': sorted(year_cols.values()),
            'values': values,
        }

        if values:
            # Print values in a nice format
            sorted_years = sorted(values.keys())
            val_strs = [f"{y}: {values[y]}" for y in sorted_years if values[y] is not None]
            logger.info(f"Interest rate spread: {', '.join(val_strs)}")
        else:
            logger.info(f"Interest rate spread: NOT FOUND (will be blank in output)")

    # ── Summary ──
    logger.info(f"\n{'='*70}")
    logger.info(f"SUMMARY for {pdf_label}")
    logger.info(f"{'='*70}")

    for name, result in all_results.items():
        page = result.get('page', '?')
        vals = result.get('values', {})
        count = sum(1 for v in vals.values() if v is not None)
        status = f"page {page}, {count} values" if vals else f"page {page}, NO data"
        logger.info(f"  {name:25s} -> {status}")

    return all_results


def compare_with_reference(results, pdf_label):
    """Compare extracted values against the reference CSV data."""
    csv_path = os.path.join(
        config.BASE_DIR, 'Project_information',
        'OIRS_DATA_20231010[1].xlsx - DATA.csv'
    )
    if not os.path.exists(csv_path):
        logger.warning("Reference CSV not found, skipping comparison")
        return

    ref = pd.read_csv(csv_path)
    logger.info(f"\n--- Comparison with reference data ---")

    # ref columns: blank, AUS, CAN, FRA, ITA, ESP, GBR, USA
    country_col_map = {
        'Australia': ref.columns[1],
        'Canada': ref.columns[2],
        'France': ref.columns[3],
        'Italy': ref.columns[4],
        'Spain': ref.columns[5],
        'United Kingdom': ref.columns[6],
        'United States': ref.columns[7],
    }

    total_checks = 0
    matches = 0
    mismatches = []

    for country_name, result in results.items():
        values = result.get('values', {})
        if not values or country_name not in country_col_map:
            continue

        col_name = country_col_map[country_name]

        for year, extracted_val in values.items():
            if extracted_val is None:
                continue

            # Find this year in reference
            ref_row = ref[ref.iloc[:, 0] == year]
            if ref_row.empty:
                continue

            ref_val = ref_row[col_name].values[0]
            total_checks += 1

            if pd.isna(ref_val):
                # Reference is blank, we have a value - this is new data
                continue

            ref_val = float(ref_val)
            if abs(extracted_val - ref_val) < 0.011:
                matches += 1
            else:
                mismatches.append(
                    f"  {country_name} {year}: extracted={extracted_val}, reference={ref_val}"
                )

    if total_checks > 0:
        logger.info(f"Checked {total_checks} values: {matches} match, "
                     f"{len(mismatches)} mismatch")
        for m in mismatches:
            logger.warning(f"MISMATCH: {m}")
    else:
        logger.info("No comparable values found")


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else '2026'

    if target == 'all':
        for label, path in sorted(SAMPLE_PDFS.items()):
            results = test_pdf(path, label)
            if results:
                compare_with_reference(results, label)
    elif target in SAMPLE_PDFS:
        results = test_pdf(SAMPLE_PDFS[target], target)
        if results:
            compare_with_reference(results, target)
    elif os.path.exists(target):
        results = test_pdf(target, os.path.basename(target))
        if results:
            compare_with_reference(results, os.path.basename(target))
    else:
        logger.error(f"Unknown target: {target}")
        logger.info(f"Available: {', '.join(SAMPLE_PDFS.keys())}, all, or a file path")
        sys.exit(1)
