"""
orchestrator.py — OIRS pipeline coordinator.

Runs three steps in sequence:
  1. scraper.download()       — fetch the latest OECD PDF
  2. extractor.extract()      — pull IRS data for all 7 countries
  3. file_generator.generate_files() — write DATA xlsx, META xlsx, ZIP
"""

import logging

import config  # noqa: F401  (ensures BASE_DIR / OUTPUT_DIR are resolved early)
import scraper
import extractor
import file_generator

logger = logging.getLogger(__name__)


def main():
    logger.info("=== OIRS pipeline started ===")

    # Step 1 — Download PDF
    logger.info("Step 1 — Downloading PDF from OECD")
    result       = scraper.download()
    pdf_path     = result['pdf_path']
    date_str     = result['date_str']
    report_title = result['report_title']
    logger.info(f"Downloaded: {report_title} ({date_str}) → {pdf_path}")

    # Step 2 — Extract
    logger.info("Step 2 — Extracting Interest Rate Spread data")
    df = extractor.extract(pdf_path)
    non_null = int(df.notna().sum().sum())
    logger.info(
        f"Extracted {non_null} values across "
        f"{len(df.columns)} countries, {len(df)} years"
    )

    # Step 3 — Write output files
    logger.info("Step 3 — Writing output files")
    files = file_generator.generate_files(df, date_str)
    logger.info(f"DATA : {files['data_path']}")
    logger.info(f"META : {files['meta_path']}")
    logger.info(f"ZIP  : {files['zip_path']}")

    logger.info("=== OIRS pipeline complete ===")
    return files
