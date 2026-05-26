"""
main.py — Entry point for the OIRS data pipeline.

Usage:
    python main.py
"""

import logging
import sys

import orchestrator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)

if __name__ == '__main__':
    try:
        orchestrator.main()
    except Exception as exc:
        logging.error(f"Pipeline failed: {exc}", exc_info=True)
        sys.exit(1)
