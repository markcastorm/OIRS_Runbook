"""
file_generator.py — Write OIRS output files: DATA xlsx, META xlsx, ZIP.

Public API
----------
generate_files(df, date_str) -> dict
    Writes OIRS_DATA_<stamp>.xlsx, OIRS_META_<stamp>.xlsx, OIRS_<stamp>.zip
    to config.OUTPUT_DIR and copies all three to config.OUTPUT_DIR/latest/.
    Returns {'data_path': ..., 'meta_path': ..., 'zip_path': ...}.
"""

import os
import shutil
import zipfile

import openpyxl
import pandas as pd

import config


def generate_files(df, date_str):
    """
    df       : DataFrame from extractor.extract()
                 index=year int, columns=country names, values=float/NaN
    date_str : 'YYYYMMDD' string from scraper.download()
    """
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    data_path = _write_data(df, date_str)
    meta_path = _write_meta(date_str)
    zip_path  = _write_zip(date_str, [data_path, meta_path])

    latest_dir = os.path.join(config.OUTPUT_DIR, 'latest')
    os.makedirs(latest_dir, exist_ok=True)
    for src in [data_path, meta_path, zip_path]:
        shutil.copy2(src, os.path.join(latest_dir, os.path.basename(src)))

    return {'data_path': data_path, 'meta_path': meta_path, 'zip_path': zip_path}


# ── DATA file ─────────────────────────────────────────────────────────────────

def _write_data(df, stamp):
    """
    Two header rows (codes / descriptions) followed by one row per year.
    Missing values are written as config.NA_OUTPUT_VALUE (empty string).
    """
    path = os.path.join(config.OUTPUT_DIR, f'OIRS_DATA_{stamp}.xlsx')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Data'

    ws.append([''] + [c['code']        for c in config.COUNTRIES])
    ws.append([''] + [c['description'] for c in config.COUNTRIES])

    country_names = [c['name'] for c in config.COUNTRIES]
    for year in sorted(df.index):
        row = [year]
        for name in country_names:
            v = df.loc[year, name]
            row.append(config.NA_OUTPUT_VALUE if pd.isna(v) else float(v))
        ws.append(row)

    wb.save(path)
    return path


# ── META file ─────────────────────────────────────────────────────────────────

def _write_meta(stamp):
    path = os.path.join(config.OUTPUT_DIR, f'OIRS_META_{stamp}.xlsx')
    rows = []
    for c in config.COUNTRIES:
        row = dict(config.META_STATIC)
        row['CODE']          = c['code']
        row['CODE_MNEMONIC'] = c['mnemonic']
        row['DESCRIPTION']   = c['description']
        row['COUNTRY']       = c['iso']
        rows.append(row)

    pd.DataFrame(rows, columns=config.META_COLUMNS).to_excel(
        path, index=False, engine='openpyxl'
    )
    return path


# ── ZIP ───────────────────────────────────────────────────────────────────────

def _write_zip(stamp, files):
    path = os.path.join(config.OUTPUT_DIR, f'OIRS_{stamp}.zip')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, os.path.basename(f))
    return path
