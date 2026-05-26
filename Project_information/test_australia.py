"""
Focused test: Perfect Australia table extraction across all sample PDFs.

Uses fitz (PyMuPDF) find_tables() for table extraction — superior to camelot
because it uses PDF border information for cell detection, preserves multi-line
labels in single cells (no row-splitting), and separates values correctly.

Tests page finding, table extraction, year parsing, and Interest rate spread
value extraction. Runs on all available sample PDFs (2020, 2022, 2024, 2026).

Usage:
    python test_australia.py
"""

import os
import re
import sys
import logging

import fitz
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

SAMPLE_DIR = os.path.join(config.BASE_DIR, 'Project_information', 'samplepdf')
SAMPLE_PDFS = {
    '2026': os.path.join(SAMPLE_DIR, '075d8058-en.pdf'),
    '2024': os.path.join(SAMPLE_DIR, 'fa521246-en.pdf'),
    '2022': os.path.join(SAMPLE_DIR, 'e9073a0f-en.pdf'),
    '2020': os.path.join(SAMPLE_DIR, '061fe03d-en.pdf'),
}
DEBUG_DIR = os.path.join(config.BASE_DIR, 'debug')

# Australia config
COUNTRY = config.COUNTRIES[0]  # Australia

# ── Reference values per edition ─────────────────────────────────────────────
# OECD revises historical data between editions, so values can differ.
# The 2026 edition is our primary reference; older editions have their own.
REFERENCE = {
    '2026': {
        2007: 0.71, 2008: 1.70, 2009: 1.66, 2010: 1.38, 2011: 1.28,
        2012: 1.62, 2013: 1.77, 2014: 1.67, 2015: 1.73, 2016: 1.86,
        2017: 1.85, 2018: 1.61, 2019: 1.70, 2020: 1.77, 2021: 1.60,
        2022: 0.98, 2023: 0.72, 2024: 0.76,
    },
    '2024': {
        2007: 0.71, 2008: 1.70, 2009: 1.66, 2010: 1.38, 2011: 1.28,
        2012: 1.62, 2013: 1.77, 2014: 1.67, 2015: 1.73, 2016: 1.86,
        2017: 1.85, 2018: 1.61, 2019: 1.70, 2020: 1.77, 2021: 1.60,
        2022: 0.99,
    },
    '2022': {
        2007: 0.71, 2008: 1.70, 2009: 1.66, 2010: 1.38, 2011: 1.28,
        2012: 1.62, 2013: 1.77, 2014: 1.67, 2015: 1.73, 2016: 1.86,
        2017: 1.85, 2018: 1.61, 2019: 1.70, 2020: 1.77,
    },
    '2020': {
        # 2020 edition uses a different interest rate methodology/source
        # Values differ significantly from 2022+ editions
        2007: 0.96, 2008: 1.83, 2009: 1.71, 2010: 1.62, 2011: 1.57,
        2012: 1.78, 2013: 2.14, 2014: 2.03, 2015: 1.99, 2016: 2.09,
        2017: 2.00, 2018: 1.73,
    },
}


# ── Page finder ──────────────────────────────────────────────────────────────

def _count_years_on_page(text_flat):
    """Count distinct year numbers (2000-2039) on a page."""
    return len(set(re.findall(r'\b(20[0-3]\d)\b', text_flat)))


def find_country_page(pdf_path, country_cfg):
    """
    Find the scoreboard table page using title + table-specific label keywords
    + dense year numbers. Returns 0-indexed page number or None.
    """
    search_term = country_cfg['table_search'].lower()
    doc = fitz.open(pdf_path)

    candidates = []
    for pg in range(len(doc)):
        text_flat = ' '.join(doc[pg].get_text().lower().split())
        if search_term not in text_flat:
            continue

        confirm_count = sum(1 for kw in config.TABLE_CONFIRM_KEYWORDS if kw in text_flat)
        year_count = _count_years_on_page(text_flat)

        if confirm_count >= config.TABLE_CONFIRM_MIN and year_count >= config.TABLE_MIN_YEAR_COUNT:
            candidates.append((pg, confirm_count, year_count))

    doc.close()

    if not candidates:
        return None

    # Best = highest confirm count, then highest year count
    candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return candidates[0][0]


# ── Year extraction from page text ──────────────────────────────────────────

def extract_years_from_page(doc, page_num):
    """
    Extract year headers from page text.

    The OECD scoreboard tables have year headers (2007, 2008, ...) in a row
    above the data. fitz find_tables() doesn't always include these in the
    table DataFrame, so we extract them from the page text.

    Strategy:
      1. Get all text from the page
      2. Find all year numbers (2000-2039)
      3. Filter to reasonable range (keep years between the most frequent decade)
      4. Sort chronologically and deduplicate

    Returns: sorted list of year ints, e.g. [2007, 2008, ..., 2024]
    """
    page_text = doc[page_num].get_text()
    year_re = re.compile(r'\b(20[0-3]\d)\b')
    all_years = [int(y) for y in year_re.findall(page_text)]

    if not all_years:
        return []

    # Count frequency of each year — scoreboard years appear in header AND data
    from collections import Counter
    year_counts = Counter(all_years)

    # The scoreboard header years appear at least 1x each as column headers.
    # Other years (page numbers, footnotes) appear sporadically.
    # The header row years form a dense consecutive sequence.
    unique_years = sorted(set(all_years))

    # Find the longest consecutive run of years
    best_run = []
    current_run = [unique_years[0]]
    for i in range(1, len(unique_years)):
        if unique_years[i] == unique_years[i-1] + 1:
            current_run.append(unique_years[i])
        else:
            if len(current_run) > len(best_run):
                best_run = current_run
            current_run = [unique_years[i]]
    if len(current_run) > len(best_run):
        best_run = current_run

    if len(best_run) >= 5:
        return best_run

    # Fallback: return all unique years in 2005-2039 range
    return sorted(y for y in set(all_years) if 2005 <= y <= 2039)


# ── fitz table extraction ───────────────────────────────────────────────────

def _normalize_label(cell_text):
    """
    Normalize a fitz cell label: replace \\n with space, collapse whitespace.
    fitz packs multi-line cell content with \\n separators.
    E.g. "Interest rate\\nspread" → "Interest rate spread"
    """
    return ' '.join(str(cell_text).replace('\n', ' ').split()).strip()


def extract_table_fitz(pdf_path, page_num, country_name):
    """
    Extract the scoreboard table from one or two pages using fitz find_tables().

    fitz detects table borders in the PDF and returns structured tables.
    The OECD scoreboard page typically yields 4 sub-tables:
      Table 0: Empty header area (year labels, often 0 rows)
      Table 1: Debt section (contains Interest rate spread)
      Table 2: Non-bank finance section
      Table 3: Other indicators section

    We find the table containing "interest rate" in column 0.
    If the full scoreboard spans two pages, we also check the next page.

    Returns: (target_table_df, all_tables_dfs) or (None, [])
    """
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    tabs = page.find_tables()

    all_dfs = []
    target_df = None
    target_label = config.TARGET_ROW_LABEL.lower()  # "interest rate spread"

    for t in tabs.tables:
        df = t.to_pandas()
        if len(df) == 0:
            continue
        all_dfs.append(df)

        # Check if this table contains our target row
        for r in range(len(df)):
            label = _normalize_label(df.iloc[r, 0]).lower()
            if target_label in label:
                target_df = df
                break

    # If not found, also check next page for multi-page tables
    if target_df is None and page_num + 1 < len(doc):
        next_page = doc[page_num + 1]
        next_tabs = next_page.find_tables()
        for t in next_tabs.tables:
            df = t.to_pandas()
            if len(df) == 0:
                continue
            all_dfs.append(df)
            for r in range(len(df)):
                label = _normalize_label(df.iloc[r, 0]).lower()
                if target_label in label:
                    target_df = df
                    break
            if target_df is not None:
                break

    doc.close()

    if target_df is not None:
        logger.info(
            f"fitz: Found target table with {len(target_df)} rows x "
            f"{target_df.shape[1]} cols (total {len(all_dfs)} tables on page)"
        )
    else:
        logger.warning(f"fitz: '{config.TARGET_ROW_LABEL}' not found in any table")

    return target_df, all_dfs


# ── Year-to-column mapping for fitz tables ──────────────────────────────────

def map_years_to_columns(df, years_from_page):
    """
    Map year values to DataFrame column indices.

    fitz tables for OECD scoreboards have:
      Col 0: Label (e.g., "Outstanding business loans, total")
      Col 1: Unit (e.g., "AUD billion")
      Cols 2+: Data values

    The number of data columns should match the number of years.
    We assign years left-to-right to data columns.

    Returns: dict {col_idx: year_int}
    """
    data_start_col = 2  # Skip label and unit columns
    data_col_count = df.shape[1] - data_start_col

    if data_col_count <= 0:
        logger.error("No data columns in table")
        return {}

    year_columns = {}

    if len(years_from_page) == data_col_count:
        # Perfect match
        for i, year in enumerate(years_from_page):
            year_columns[data_start_col + i] = year
        logger.info(
            f"Year mapping: perfect match ({len(years_from_page)} years = "
            f"{data_col_count} data cols)"
        )
    elif len(years_from_page) > data_col_count:
        # More years than columns — take the last N years (most recent)
        # This handles cases where page text has extra year references
        trimmed = years_from_page[-data_col_count:]
        for i, year in enumerate(trimmed):
            year_columns[data_start_col + i] = year
        logger.warning(
            f"Year mapping: {len(years_from_page)} years > {data_col_count} cols, "
            f"using last {data_col_count} years: {trimmed[0]}-{trimmed[-1]}"
        )
    else:
        # Fewer years than columns — could be multi-section table
        # Try assigning from the left
        for i, year in enumerate(years_from_page):
            year_columns[data_start_col + i] = year
        logger.warning(
            f"Year mapping: {len(years_from_page)} years < {data_col_count} cols, "
            f"assigned {len(years_from_page)} years to first columns"
        )

    if year_columns:
        yrs = sorted(year_columns.values())
        logger.info(f"Final year map: {yrs[0]}-{yrs[-1]} ({len(yrs)} years)")

    return year_columns


# ── Interest rate spread extraction (fitz) ──────────────────────────────────

def find_interest_rate_spread_fitz(df, year_columns):
    """
    Find the 'Interest rate spread' row in a fitz DataFrame and extract values.

    fitz cells may contain \\n for multi-line content. We normalize labels
    by replacing \\n with space before matching.

    Returns: dict {year: float_value} or empty dict.
    """
    target = config.TARGET_ROW_LABEL.lower()

    for row_idx in range(len(df)):
        label = _normalize_label(df.iloc[row_idx, 0]).lower()

        if target in label:
            logger.info(f"Found '{config.TARGET_ROW_LABEL}' at row {row_idx}")
            values = {}
            for col_idx, year in year_columns.items():
                if col_idx < df.shape[1]:
                    raw = str(df.iloc[row_idx, col_idx]).strip()
                    # fitz values are clean — just handle None/empty/special
                    raw = raw.replace('\n', ' ').strip()
                    if raw in ('', '-', '--', 'None', '..', '…', 'nil', 'n/a'):
                        values[year] = None
                    else:
                        try:
                            values[year] = float(raw.replace(',', '').replace(' ', ''))
                        except ValueError:
                            logger.warning(f"  Cannot parse value at col {col_idx} ({year}): '{raw}'")
                            values[year] = None
            return values

    logger.warning(f"'{config.TARGET_ROW_LABEL}' NOT found in table")
    return {}


# ── Main test ────────────────────────────────────────────────────────────────

def test_australia(pdf_path, edition_label):
    """Run full extraction test for Australia on one PDF."""
    if not os.path.exists(pdf_path):
        logger.error(f"PDF not found: {pdf_path}")
        return False

    logger.info(f"\n{'='*70}")
    logger.info(f"AUSTRALIA TEST — {edition_label} PDF")
    logger.info(f"{'='*70}")

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()
    logger.info(f"PDF: {total_pages} pages")

    os.makedirs(DEBUG_DIR, exist_ok=True)

    # Step 1: Find page
    page_num = find_country_page(pdf_path, COUNTRY)
    if page_num is None:
        logger.error("FAIL: Could not find Australia scoreboard page")
        return False
    logger.info(f"Page found: {page_num + 1}")

    # Step 2: Extract years from page text
    doc = fitz.open(pdf_path)
    years_from_page = extract_years_from_page(doc, page_num)
    logger.info(f"Years from page text: {years_from_page}")

    # Step 3: Extract table using fitz
    target_df, all_dfs = extract_table_fitz(pdf_path, page_num, COUNTRY['name'])
    doc.close()

    if target_df is None:
        logger.error("FAIL: No table with Interest rate spread found")
        return False

    # Save debug CSV
    debug_path = os.path.join(DEBUG_DIR, f'{edition_label}_Australia_fitz_page{page_num+1}.csv')
    target_df.to_csv(debug_path, index=False)
    logger.info(f"Target table saved: {target_df.shape[0]}r x {target_df.shape[1]}c -> {debug_path}")

    # Also save all tables for inspection
    for i, df in enumerate(all_dfs):
        df.to_csv(
            os.path.join(DEBUG_DIR, f'{edition_label}_Australia_fitz_table{i}.csv'),
            index=False,
        )

    # Step 4: Map years to columns
    year_columns = map_years_to_columns(target_df, years_from_page)
    if not year_columns:
        logger.error("FAIL: No year columns mapped")
        return False

    years = sorted(year_columns.values())

    # Step 5: Extract interest rate spread values
    values = find_interest_rate_spread_fitz(target_df, year_columns)
    if not values:
        logger.error("FAIL: Interest rate spread row not found")
        return False

    non_null = {y: v for y, v in values.items() if v is not None}
    logger.info(f"Extracted {len(non_null)} non-null values out of {len(values)} total")

    # Step 6: Validate against edition-specific reference
    ref_data = REFERENCE.get(edition_label, {})
    if not ref_data:
        logger.warning(f"No reference data for edition {edition_label}, skipping validation")
        # Still report what we extracted
        logger.info(f"\nExtracted values:")
        for y in sorted(values.keys()):
            logger.info(f"  {y}: {values[y]}")
        return True

    logger.info(f"\n--- Validation against {edition_label} reference ---")
    matched = 0
    mismatched = 0
    new_values = 0
    missing_in_range = 0
    out_of_range = 0

    pdf_min_year = min(years)
    pdf_max_year = max(years)

    for year in sorted(set(list(ref_data.keys()) + list(values.keys()))):
        ref = ref_data.get(year)
        ext = values.get(year)

        if ref is not None and ext is not None:
            if abs(ref - ext) < 0.02:  # tolerance for rounding
                matched += 1
            else:
                mismatched += 1
                logger.warning(f"  MISMATCH {year}: extracted={ext}, reference={ref}")
        elif ref is not None and ext is None:
            if pdf_min_year <= year <= pdf_max_year:
                missing_in_range += 1
                logger.warning(f"  MISSING  {year}: reference={ref}, within PDF range")
            else:
                out_of_range += 1
        elif ref is None and ext is not None:
            new_values += 1
            logger.info(f"  NEW      {year}: {ext} (not in reference)")

    comparable = matched + mismatched
    logger.info(f"\nResults: {matched}/{comparable} matched, {mismatched} mismatch, "
                f"{missing_in_range} missing-in-range, {out_of_range} outside-range, "
                f"{new_values} new")

    success = mismatched == 0 and missing_in_range == 0
    status = "PASS" if success else "FAIL"
    logger.info(f"Status: {status}")

    # Print all extracted values
    logger.info(f"\nExtracted values:")
    for y in sorted(values.keys()):
        v = values[y]
        ref = ref_data.get(y, None)
        marker = ''
        if ref is not None and v is not None and abs(ref - v) >= 0.02:
            marker = ' *** MISMATCH'
        elif ref is None:
            marker = ' (new)'
        logger.info(f"  {y}: {v}{marker}")

    return success


if __name__ == '__main__':
    results = {}
    for edition_label, path in sorted(SAMPLE_PDFS.items()):
        if os.path.exists(path):
            results[edition_label] = test_australia(path, edition_label)
        else:
            logger.warning(f"PDF not found: {path}")
            results[edition_label] = None

    logger.info(f"\n{'='*70}")
    logger.info(f"FINAL SUMMARY")
    logger.info(f"{'='*70}")
    all_pass = True
    for edition_label, ok in sorted(results.items()):
        status = "PASS" if ok else ("SKIP" if ok is None else "FAIL")
        if not ok and ok is not None:
            all_pass = False
        logger.info(f"  {edition_label}: {status}")

    if all_pass:
        logger.info(f"\nAll tests PASSED!")
    else:
        logger.info(f"\nSome tests FAILED")
        sys.exit(1)
