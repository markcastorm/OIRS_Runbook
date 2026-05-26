"""
extractor.py — Extract Interest Rate Spread for all 7 countries from an OECD PDF.

Uses fitz (PyMuPDF) find_tables() to locate the "Scoreboard for <Country>" table
page and pull the "Interest rate spread" row values for every available year.

Public API
----------
extract(pdf_path) -> pd.DataFrame
    Index : sorted year integers
    Columns : country names in config.COUNTRIES order
    Values : float (NaN where no data)
"""

import re

import fitz
import pandas as pd

import config

# Tokens treated as missing values in PDF cells
_NULL_TOKENS = {'', '-', '--', 'None', '..', '…', 'nil', 'n/a'}


# ── Public entry point ────────────────────────────────────────────────────────

def extract(pdf_path):
    """
    Open pdf_path once and extract IRS data for every country in config.COUNTRIES.
    Returns a DataFrame (index=year int, columns=country name, values=float/NaN).
    """
    doc = fitz.open(pdf_path)
    all_data = {}
    try:
        for country_cfg in config.COUNTRIES:
            all_data[country_cfg['name']] = _extract_country(doc, country_cfg)
    finally:
        doc.close()
    return _build_dataframe(all_data)


# ── Per-country extraction ────────────────────────────────────────────────────

def _extract_country(doc, country_cfg):
    """Return {year: float_or_None} for one country, or {} if not found."""
    page_num = _find_country_page(doc, country_cfg)
    if page_num is None:
        return {}

    years_title = _extract_years_from_page(doc, page_num)
    target_df, row_idx, found_page = _extract_table(doc, page_num)

    if target_df is None:
        return {}

    # If the table spans to the next page, also read years from the data page.
    # map_years_to_columns will pick whichever set better matches the column count.
    years_data = None
    if found_page != page_num:
        years_data = _extract_years_from_page(doc, found_page)

    year_columns = _map_years_to_columns(target_df, years_title, years_data)
    if not year_columns:
        return {}

    return _extract_values(target_df, row_idx, year_columns)


# ── Page finder ───────────────────────────────────────────────────────────────

def _find_country_page(doc, country_cfg):
    """
    Find the 0-indexed page number that starts the scoreboard table.

    The scoreboard title appears on both the TOC and the actual data page, so a
    page is only accepted when it also satisfies keyword + year-density checks.
    Text from page N and N+1 is combined for keyword matching because tables
    that span two pages may place some confirmation keywords on the second page.

    Returns the best-matching page number, or None.
    """
    search_term = country_cfg['table_search'].lower()
    total_pages = len(doc)
    candidates = []

    for pg in range(total_pages):
        text_flat = ' '.join(doc[pg].get_text().lower().split())
        if search_term not in text_flat:
            continue

        # Combine current + next page for keyword confirmation
        combined = text_flat
        if pg + 1 < total_pages:
            combined += ' ' + ' '.join(doc[pg + 1].get_text().lower().split())

        confirm_count = sum(1 for kw in config.TABLE_CONFIRM_KEYWORDS if kw in combined)
        year_count = len(set(re.findall(r'\b(20[0-3]\d)\b', text_flat)))

        if confirm_count >= config.TABLE_CONFIRM_MIN and year_count >= config.TABLE_MIN_YEAR_COUNT:
            candidates.append((pg, confirm_count, year_count))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return candidates[0][0]


# ── Year extraction ───────────────────────────────────────────────────────────

def _extract_years_from_page(doc, page_num):
    """
    Extract the column year headers from page text.
    Returns the longest consecutive run of year integers found on the page.
    Falls back to all years in [2005, 2039] if no run of 5+ is found.
    """
    all_years = [int(y) for y in re.findall(r'\b(20[0-3]\d)\b', doc[page_num].get_text())]
    if not all_years:
        return []

    unique = sorted(set(all_years))
    best_run, current_run = [], [unique[0]]
    for i in range(1, len(unique)):
        if unique[i] == unique[i - 1] + 1:
            current_run.append(unique[i])
        else:
            if len(current_run) > len(best_run):
                best_run = current_run
            current_run = [unique[i]]
    if len(current_run) > len(best_run):
        best_run = current_run

    return best_run if len(best_run) >= 5 else sorted(
        y for y in set(all_years) if 2005 <= y <= 2039
    )


# ── Table extraction ──────────────────────────────────────────────────────────

def _normalize_label(cell_text):
    return ' '.join(str(cell_text).replace('\n', ' ').split()).strip()


def _extract_table(doc, page_num):
    """
    Search page_num and page_num+1 for a table containing 'Interest rate spread'.
    Searching the next page handles tables that span two PDF pages.

    Returns (df, row_idx, found_page) or (None, None, None).
    """
    target_label = config.TARGET_ROW_LABEL.lower()
    pages_to_check = [page_num]
    if page_num + 1 < len(doc):
        pages_to_check.append(page_num + 1)

    for pg in pages_to_check:
        for t in doc[pg].find_tables().tables:
            df = t.to_pandas()
            if len(df) == 0:
                continue
            for r in range(len(df)):
                if target_label in _normalize_label(df.iloc[r, 0]).lower():
                    return df, r, pg

    return None, None, None


# ── Year → column mapping ─────────────────────────────────────────────────────

def _map_years_to_columns(df, years_primary, years_secondary=None):
    """
    Map year integers to DataFrame column indices.
    Col 0 = Label, Col 1 = Unit, Cols 2+ = Data (one column per year, oldest first).

    years_secondary is used when a table spans pages: if it is closer in length
    to the actual data column count than years_primary, it is used instead.
    Excess years are trimmed from the end (most-recent) so the oldest years
    always align to the leftmost data columns, matching OECD table layout.
    """
    data_start = 2
    data_cols = df.shape[1] - data_start
    if data_cols <= 0 or not years_primary:
        return {}

    years = years_primary
    if years_secondary:
        if abs(len(years_secondary) - data_cols) < abs(len(years_primary) - data_cols):
            years = years_secondary

    year_columns = {}
    if len(years) >= data_cols:
        for i in range(data_cols):
            year_columns[data_start + i] = years[i]
    else:
        for i, yr in enumerate(years):
            year_columns[data_start + i] = yr

    return year_columns


# ── Value extraction ──────────────────────────────────────────────────────────

def _extract_values(df, row_idx, year_columns):
    """Extract numeric values from the target row. Returns {year: float or None}."""
    values = {}
    for col_idx, year in year_columns.items():
        if col_idx >= df.shape[1]:
            values[year] = None
            continue
        raw = str(df.iloc[row_idx, col_idx]).strip().replace('\n', ' ')
        if raw in _NULL_TOKENS:
            values[year] = None
        else:
            try:
                values[year] = float(raw.replace(',', '').replace(' ', ''))
            except ValueError:
                values[year] = None
    return values


# ── DataFrame assembly ────────────────────────────────────────────────────────

def _build_dataframe(all_data):
    """
    Merge per-country dicts into a single DataFrame.
    Index = sorted year integers; columns = country names in config.COUNTRIES order.
    """
    all_years = set()
    for vals in all_data.values():
        all_years.update(vals.keys())

    country_names = [c['name'] for c in config.COUNTRIES]

    if not all_years:
        return pd.DataFrame(columns=country_names)

    years = sorted(all_years)
    df = pd.DataFrame(index=years, columns=country_names, dtype=float)
    df.index.name = 'Year'

    for c in config.COUNTRIES:
        name = c['name']
        vals = all_data.get(name, {})
        for year in years:
            v = vals.get(year)
            df.loc[year, name] = float(v) if v is not None else float('nan')

    return df
