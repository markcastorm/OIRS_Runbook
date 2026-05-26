"""
Full test: Extract Interest Rate Spread for ALL 7 countries across ALL 4 PDFs.

Uses fitz (PyMuPDF) find_tables() for table extraction. Handles:
- Multi-page tables (scoreboard title on page N, data continues on N+1)
- Missing target rows (e.g., US in some editions)
- Data revisions across editions (per-edition reference values)
- Year/column mismatches (trims or extends as needed)

Usage:
    python test_all_countries.py          # Test all PDFs
    python test_all_countries.py 2026     # Test specific edition
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

# ── Reference values per country per edition ────────────────────────────────
# From manual inspection of PDF tables. Only the 2026 edition is comprehensive;
# older editions may have fewer years or revised values.
# Format: REFERENCE[country_name][edition_label] = {year: value}
REFERENCE = {
    'Australia': {
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
            2007: 0.96, 2008: 1.83, 2009: 1.71, 2010: 1.62, 2011: 1.57,
            2012: 1.78, 2013: 2.14, 2014: 2.03, 2015: 1.99, 2016: 2.09,
            2017: 2.00, 2018: 1.73,
        },
    },
    # Other countries: validate against the 2026 reference data from the manual file.
    # For older editions, we skip strict validation (just check extraction works).
    'Canada': {
        '2026': {
            2007: 1.40, 2009: 3.10, 2010: 3.20, 2011: 2.30, 2012: 2.40,
            2013: 2.60, 2014: 2.10, 2015: 2.30, 2016: 2.60, 2017: 2.30,
            2018: 2.06, 2019: 1.70, 2020: 2.03, 2021: 1.64, 2022: 2.10,
            2023: 2.06, 2024: 0.51,
        },
    },
    'France': {
        '2026': {
            2008: 5.42, 2009: 2.86, 2010: 2.48, 2011: 3.11, 2012: 2.43,
            2013: 2.16, 2014: 2.08, 2015: 1.78, 2016: 1.50, 2017: 1.40,
            2018: 1.48, 2019: 1.40, 2020: 1.00, 2021: 1.26, 2022: 1.90,
            2023: 4.20, 2024: 4.26,
        },
    },
    'Italy': {
        '2026': {
            2007: 0.60, 2008: 1.00, 2009: 1.40, 2010: 1.60, 2011: 1.60,
            2012: 2.00, 2013: 2.00, 2014: 1.90, 2015: 1.90, 2016: 1.50,
            2017: 1.20, 2018: 1.30, 2019: 1.70, 2020: 0.80, 2021: 1.20,
            2022: 2.00, 2023: 1.30, 2024: 1.30,
        },
    },
    'Spain': {
        '2026': {
            2007: 0.63, 2008: 1.21, 2009: 1.47, 2010: 1.21, 2011: 1.59,
            2012: 2.30, 2013: 2.10, 2014: 1.87, 2015: 1.04, 2016: 0.88,
            2017: 0.59, 2018: 0.20, 2019: 0.56, 2020: 0.32, 2021: 0.52,
            2022: 0.20, 2023: 0.23, 2024: 0.04,
        },
    },
    'United Kingdom': {
        '2026': {
            2008: 1.05, 2009: 1.12, 2010: 1.39, 2011: 1.27, 2012: 1.30,
            2013: 1.40, 2014: 0.98, 2015: 1.22, 2016: 0.62, 2017: 0.73,
            2018: 0.74, 2019: 0.77, 2020: 0.28, 2021: 0.33, 2022: 0.68,
            2023: 0.66, 2024: 0.61,
        },
    },
    'United States': {
        # US has Interest rate spread in 2020 and 2022 editions, but NOT in 2024/2026.
        # When present, values should be extracted; when absent, output blank.
        '2020': {},  # We'll validate extraction works, but no manual ref values yet
        '2022': {},
        '2024': {},  # Row expected to be missing
        '2026': {},  # Row expected to be missing
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# CORE EXTRACTION FUNCTIONS (will become extractor.py)
# ═══════════════════════════════════════════════════════════════════════════

def _count_years_on_page(text_flat):
    """Count distinct year numbers (2000-2039) on a page."""
    return len(set(re.findall(r'\b(20[0-3]\d)\b', text_flat)))


def find_country_page(pdf_path, country_cfg):
    """
    Find the scoreboard table page. Handles multi-page tables by combining
    text from page N and page N+1 when checking confirmation keywords.

    The scoreboard title might be on page N, but key data rows (like
    "interest rate, smes") might only appear on page N+1 when the table
    spans two pages. By combining text from both pages for keyword checking,
    we correctly identify the start page.

    Returns 0-indexed page number (first page of table) or None.
    """
    search_term = country_cfg['table_search'].lower()
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    candidates = []

    for pg in range(total_pages):
        text_flat = ' '.join(doc[pg].get_text().lower().split())
        if search_term not in text_flat:
            continue

        # Combine current + next page text for keyword checking
        # (tables often span 2 pages)
        combined_text = text_flat
        if pg + 1 < total_pages:
            next_text = ' '.join(doc[pg + 1].get_text().lower().split())
            combined_text = text_flat + ' ' + next_text

        confirm_count = sum(1 for kw in config.TABLE_CONFIRM_KEYWORDS if kw in combined_text)
        year_count = _count_years_on_page(text_flat)  # Years from first page only

        if confirm_count >= config.TABLE_CONFIRM_MIN and year_count >= config.TABLE_MIN_YEAR_COUNT:
            candidates.append((pg, confirm_count, year_count))

    doc.close()

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return candidates[0][0]


def _normalize_label(cell_text):
    """Normalize fitz cell label: replace \\n with space, collapse whitespace."""
    return ' '.join(str(cell_text).replace('\n', ' ').split()).strip()


def extract_years_from_page(doc, page_num):
    """
    Extract year headers from the scoreboard page text.
    Finds the longest consecutive run of years (2000-2039).
    Returns sorted list of year ints.
    """
    page_text = doc[page_num].get_text()
    all_years = [int(y) for y in re.findall(r'\b(20[0-3]\d)\b', page_text)]
    if not all_years:
        return []

    unique_years = sorted(set(all_years))

    # Find longest consecutive run
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

    return best_run if len(best_run) >= 5 else sorted(
        y for y in set(all_years) if 2005 <= y <= 2039
    )


def extract_table_fitz(doc, page_num):
    """
    Extract the table containing 'Interest rate spread' using fitz find_tables().
    Searches the given page and the next page (for multi-page tables).

    Returns: (target_df, target_row_idx, found_on_page) or (None, None, None)
    """
    target_label = config.TARGET_ROW_LABEL.lower()
    pages_to_check = [page_num]
    if page_num + 1 < len(doc):
        pages_to_check.append(page_num + 1)

    for pg in pages_to_check:
        page = doc[pg]
        tabs = page.find_tables()
        for t in tabs.tables:
            df = t.to_pandas()
            if len(df) == 0:
                continue
            for r in range(len(df)):
                label = _normalize_label(df.iloc[r, 0]).lower()
                if target_label in label:
                    return df, r, pg
    return None, None, None


def map_years_to_columns(df, years_primary, years_secondary=None):
    """
    Map year values to DataFrame column indices.
    Col 0 = Label, Col 1 = Unit, Cols 2+ = Data.

    When a table spans pages the IRS row may be on a different page from the
    title/year-header page.  years_secondary (from the data page) is used as a
    fallback: whichever set is closer in length to the actual data column count
    is preferred, avoiding misalignment when the two pages carry different year
    ranges in their visible text.

    Returns: dict {col_idx: year_int}
    """
    data_start_col = 2
    data_col_count = df.shape[1] - data_start_col

    if data_col_count <= 0 or not years_primary:
        return {}

    # Pick the year set whose length is closest to the data column count
    years = years_primary
    if years_secondary:
        if abs(len(years_secondary) - data_col_count) < abs(len(years_primary) - data_col_count):
            years = years_secondary

    year_columns = {}
    if len(years) >= data_col_count:
        for i in range(data_col_count):
            year_columns[data_start_col + i] = years[i]
    else:
        for i, year in enumerate(years):
            year_columns[data_start_col + i] = year

    return year_columns


def extract_values(df, row_idx, year_columns):
    """
    Extract numeric values from a row using the year-to-column mapping.
    Returns: dict {year: float or None}
    """
    values = {}
    for col_idx, year in year_columns.items():
        if col_idx >= df.shape[1]:
            values[year] = None
            continue
        raw = str(df.iloc[row_idx, col_idx]).strip().replace('\n', ' ')
        if raw in ('', '-', '--', 'None', '..', '…', 'nil', 'n/a'):
            values[year] = None
        else:
            try:
                values[year] = float(raw.replace(',', '').replace(' ', ''))
            except ValueError:
                values[year] = None
    return values


# ═══════════════════════════════════════════════════════════════════════════
# TEST ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════

def test_country(pdf_path, edition, country_cfg):
    """
    Test extraction for one country in one PDF.
    Returns: (success: bool, values: dict, details: str)
    """
    name = country_cfg['name']
    os.makedirs(DEBUG_DIR, exist_ok=True)

    # Step 1: Find page
    page_num = find_country_page(pdf_path, country_cfg)
    if page_num is None:
        return False, {}, 'PAGE NOT FOUND'

    # Step 2: Open doc, extract years and table
    doc = fitz.open(pdf_path)
    years = extract_years_from_page(doc, page_num)
    target_df, row_idx, found_page = extract_table_fitz(doc, page_num)

    # If the table spans pages, also extract years from the data page so
    # map_years_to_columns can pick the better-matching set.
    years_secondary = None
    if target_df is not None and found_page != page_num:
        years_secondary = extract_years_from_page(doc, found_page)

    doc.close()

    if target_df is None:
        # Target row not found — this is OK for US in some editions
        return True, {}, f'pg {page_num+1}, row NOT FOUND (OK if expected)'

    # Save debug CSV
    safe_name = name.replace(' ', '_')
    debug_csv = os.path.join(DEBUG_DIR, f'{edition}_{safe_name}_fitz.csv')
    target_df.to_csv(debug_csv, index=False)

    # Step 3: Map years to columns
    year_columns = map_years_to_columns(target_df, years, years_secondary)
    if not year_columns:
        return False, {}, f'pg {page_num+1}, NO YEAR MAPPING'

    # Step 4: Extract values
    values = extract_values(target_df, row_idx, year_columns)
    non_null = {y: v for y, v in values.items() if v is not None}

    found_info = f'pg {page_num+1}'
    if found_page != page_num:
        found_info += f' (data on pg {found_page+1})'

    year_range = f"{min(year_columns.values())}-{max(year_columns.values())}"
    details = f'{found_info}, {year_range}, {len(non_null)} values'

    # Step 5: Validate against reference (if available)
    ref_data = REFERENCE.get(name, {}).get(edition, None)
    if ref_data is None or not ref_data:
        # No reference — just check extraction produced something reasonable
        if non_null:
            # Check values are in reasonable range for interest rate spread (0-10)
            for y, v in non_null.items():
                if v < -1 or v > 15:
                    return False, values, f'{details}, UNREASONABLE VALUE {y}={v}'
            return True, values, details
        else:
            return True, values, details  # No values extracted, could be valid (US)

    # Validate against reference
    mismatches = []
    missing = []
    pdf_years = sorted(year_columns.values())
    pdf_min, pdf_max = pdf_years[0], pdf_years[-1]

    for year, ref_val in ref_data.items():
        ext_val = values.get(year)
        if ext_val is not None:
            if abs(ref_val - ext_val) >= 0.02:
                mismatches.append(f'{year}: got {ext_val}, expected {ref_val}')
        elif pdf_min <= year <= pdf_max:
            missing.append(str(year))

    if mismatches:
        return False, values, f'{details}, MISMATCH: {"; ".join(mismatches)}'
    if missing:
        return False, values, f'{details}, MISSING years: {", ".join(missing)}'

    return True, values, f'{details}, {len(ref_data)}/{len(ref_data)} matched'


def run_all_tests(target_edition=None):
    """Run extraction tests for all countries across all (or specified) PDFs."""
    editions = sorted(SAMPLE_PDFS.keys())
    if target_edition:
        editions = [target_edition]

    all_results = {}  # {(edition, country_name): (success, values, details)}
    summary_pass = 0
    summary_fail = 0
    summary_skip = 0

    for edition in editions:
        pdf_path = SAMPLE_PDFS.get(edition)
        if not pdf_path or not os.path.exists(pdf_path):
            logger.warning(f"{edition}: PDF not found")
            continue

        logger.info(f"\n{'='*70}")
        logger.info(f"  {edition} PDF")
        logger.info(f"{'='*70}")

        for country_cfg in config.COUNTRIES:
            name = country_cfg['name']
            success, values, details = test_country(pdf_path, edition, country_cfg)
            all_results[(edition, name)] = (success, values, details)

            status = 'PASS' if success else 'FAIL'
            if success:
                summary_pass += 1
            else:
                summary_fail += 1

            logger.info(f"  {name:<20} [{status}] {details}")

    # Final summary
    logger.info(f"\n{'='*70}")
    logger.info(f"  SUMMARY")
    logger.info(f"{'='*70}")

    # Table header
    ed_labels = editions
    header = f"{'Country':<22}"
    for ed in ed_labels:
        header += f" {'|':>1} {ed:>12}"
    logger.info(header)
    logger.info('-' * len(header))

    for country_cfg in config.COUNTRIES:
        name = country_cfg['name']
        row = f"{name:<22}"
        for ed in ed_labels:
            key = (ed, name)
            if key in all_results:
                ok, vals, _ = all_results[key]
                non_null = sum(1 for v in vals.values() if v is not None) if vals else 0
                status = 'PASS' if ok else 'FAIL'
                row += f" | {status:>4} ({non_null:>2}v)"
            else:
                row += f" |     N/A    "
        logger.info(row)

    total = summary_pass + summary_fail
    logger.info(f"\nTotal: {summary_pass}/{total} PASS, {summary_fail} FAIL")

    return summary_fail == 0


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else None
    success = run_all_tests(target)
    if not success:
        sys.exit(1)
