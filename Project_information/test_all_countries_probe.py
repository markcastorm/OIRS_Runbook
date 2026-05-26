"""
Probe: Test fitz extraction for ALL 7 countries across ALL 4 PDFs.
Finds pages, extracts tables, locates Interest rate spread row.
Reports results in a summary table.
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


def _count_years_on_page(text_flat):
    return len(set(re.findall(r'\b(20[0-3]\d)\b', text_flat)))


def find_country_page(pdf_path, country_cfg):
    """
    Find the scoreboard table page. Handles multi-page tables by combining
    text from page N and page N+1 when checking confirmation keywords.
    Returns 0-indexed page number (the first page of the table) or None.
    """
    search_term = country_cfg['table_search'].lower()
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    candidates = []

    for pg in range(total_pages):
        text_flat = ' '.join(doc[pg].get_text().lower().split())
        if search_term not in text_flat:
            continue

        # Combine current page + next page text for keyword/year checking
        # (tables often span 2 pages — title on page N, data continues on N+1)
        combined_text = text_flat
        if pg + 1 < total_pages:
            next_text = ' '.join(doc[pg + 1].get_text().lower().split())
            combined_text = text_flat + ' ' + next_text

        confirm_count = sum(1 for kw in config.TABLE_CONFIRM_KEYWORDS if kw in combined_text)
        year_count = _count_years_on_page(text_flat)  # Years only from first page

        if confirm_count >= config.TABLE_CONFIRM_MIN and year_count >= config.TABLE_MIN_YEAR_COUNT:
            candidates.append((pg, confirm_count, year_count))

    doc.close()
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return candidates[0][0]


def _normalize_label(cell_text):
    return ' '.join(str(cell_text).replace('\n', ' ').split()).strip()


def extract_years_from_page(doc, page_num):
    """
    Extract year headers from page text. For multi-page tables, combines
    text from the current page and the next page to catch all year headers.
    Returns sorted list of consecutive years.
    """
    page_text = doc[page_num].get_text()
    # Also include next page text for multi-page tables
    if page_num + 1 < len(doc):
        page_text += '\n' + doc[page_num + 1].get_text()

    all_years = [int(y) for y in re.findall(r'\b(20[0-3]\d)\b', page_text)]
    if not all_years:
        return []
    unique_years = sorted(set(all_years))

    # Find longest consecutive run of years
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

    return best_run if len(best_run) >= 5 else sorted(y for y in set(all_years) if 2005 <= y <= 2039)


def probe_country(pdf_path, edition, country_cfg):
    """Probe a single country in a single PDF. Returns result dict."""
    result = {
        'country': country_cfg['name'],
        'edition': edition,
        'page': None,
        'table_rows': None,
        'table_cols': None,
        'years_found': 0,
        'year_range': '',
        'target_found': False,
        'values_count': 0,
        'sample_values': '',
        'notes': '',
    }

    # Find page
    page_num = find_country_page(pdf_path, country_cfg)
    if page_num is None:
        result['notes'] = 'PAGE NOT FOUND'
        return result
    result['page'] = page_num + 1

    # Extract years
    doc = fitz.open(pdf_path)
    years = extract_years_from_page(doc, page_num)
    result['years_found'] = len(years)
    if years:
        result['year_range'] = f"{years[0]}-{years[-1]}"

    # Extract tables
    page = doc[page_num]
    tabs = page.find_tables()
    target_label = config.TARGET_ROW_LABEL.lower()

    target_df = None
    target_row_idx = None

    for t in tabs.tables:
        df = t.to_pandas()
        if len(df) == 0:
            continue
        for r in range(len(df)):
            label = _normalize_label(df.iloc[r, 0]).lower()
            if target_label in label:
                target_df = df
                target_row_idx = r
                break
        if target_df is not None:
            break

    # Check next page if not found
    if target_df is None and page_num + 1 < len(doc):
        next_page = doc[page_num + 1]
        next_tabs = next_page.find_tables()
        for t in next_tabs.tables:
            df = t.to_pandas()
            if len(df) == 0:
                continue
            for r in range(len(df)):
                label = _normalize_label(df.iloc[r, 0]).lower()
                if target_label in label:
                    target_df = df
                    target_row_idx = r
                    result['notes'] = f'Found on NEXT page ({page_num + 2})'
                    break
            if target_df is not None:
                break

    doc.close()

    if target_df is None:
        result['notes'] = result['notes'] or 'TARGET ROW NOT FOUND'
        # Save what we have for inspection
        return result

    result['target_found'] = True
    result['table_rows'] = target_df.shape[0]
    result['table_cols'] = target_df.shape[1]

    # Extract values
    data_start_col = 2
    data_col_count = target_df.shape[1] - data_start_col
    values = []
    for c in range(data_start_col, target_df.shape[1]):
        raw = str(target_df.iloc[target_row_idx, c]).strip().replace('\n', ' ')
        if raw in ('', '-', '--', 'None', '..', '…', 'nil', 'n/a'):
            continue
        try:
            v = float(raw.replace(',', '').replace(' ', ''))
            values.append(v)
        except ValueError:
            pass

    result['values_count'] = len(values)
    # Show first 3 and last 2 values
    if values:
        if len(values) <= 5:
            result['sample_values'] = ', '.join(f'{v:.2f}' for v in values)
        else:
            first3 = ', '.join(f'{v:.2f}' for v in values[:3])
            last2 = ', '.join(f'{v:.2f}' for v in values[-2:])
            result['sample_values'] = f'{first3}, ..., {last2}'

    # Check year/column alignment
    if len(years) != data_col_count:
        result['notes'] = f'YEAR MISMATCH: {len(years)} years vs {data_col_count} data cols'

    return result


if __name__ == '__main__':
    os.makedirs(DEBUG_DIR, exist_ok=True)

    all_results = []
    for edition, pdf_path in sorted(SAMPLE_PDFS.items()):
        if not os.path.exists(pdf_path):
            logger.warning(f"{edition}: PDF not found at {pdf_path}")
            continue

        logger.info(f"\n{'='*70}")
        logger.info(f"  {edition} PDF")
        logger.info(f"{'='*70}")

        for country_cfg in config.COUNTRIES:
            r = probe_country(pdf_path, edition, country_cfg)
            all_results.append(r)

            status = 'OK' if r['target_found'] else 'MISSING'
            page_str = str(r['page']) if r['page'] else '??'
            logger.info(
                f"  {r['country']:<20} pg={page_str:<4} "
                f"years={r['years_found']:<3} "
                f"vals={r['values_count']:<3} "
                f"[{status}] {r['notes']}"
            )

    # Final summary table
    logger.info(f"\n{'='*70}")
    logger.info(f"  FULL SUMMARY")
    logger.info(f"{'='*70}")
    logger.info(f"{'Country':<20} {'2020':>10} {'2022':>10} {'2024':>10} {'2026':>10}")
    logger.info(f"{'-'*20} {'-'*10} {'-'*10} {'-'*10} {'-'*10}")

    for country_cfg in config.COUNTRIES:
        name = country_cfg['name']
        row = f"{name:<20}"
        for edition in ['2020', '2022', '2024', '2026']:
            matches = [r for r in all_results if r['country'] == name and r['edition'] == edition]
            if matches:
                r = matches[0]
                if r['target_found']:
                    row += f" pg{r['page']}/{r['values_count']}v"
                    row = f"{row:>{len(row)}}"  # pad
                else:
                    row += f"  {'MISS':>6}"
            else:
                row += f"  {'N/A':>6}"
        logger.info(row)

    # Count results
    found = sum(1 for r in all_results if r['target_found'])
    total = len(all_results)
    missing = total - found
    logger.info(f"\nTotal: {found}/{total} found, {missing} missing")

    # List all missing
    if missing > 0:
        logger.info(f"\nMissing details:")
        for r in all_results:
            if not r['target_found']:
                logger.info(f"  {r['edition']} {r['country']}: {r['notes']}")
