import os

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, 'downloads')
OUTPUT_DIR   = os.path.join(BASE_DIR, 'output')

# ── Source ────────────────────────────────────────────────────────────────────
BASE_URL = 'https://www.oecd.org/en/publications/financing-smes-and-entrepreneurs_23065265.html'

# ── Browser ───────────────────────────────────────────────────────────────────
HEADLESS_MODE  = True
WAIT_TIMEOUT   = 60

# ── Job identity ──────────────────────────────────────────────────────────────
JOB_NAME = 'OIRS'

# ── Report date targeting ─────────────────────────────────────────────────────
# None  = dynamically pick the latest (first/most recent) publication
# String = match a specific date, e.g. "31 March 2026"
TARGET_DATE = None

# ── Target row label ─────────────────────────────────────────────────────────
TARGET_ROW_LABEL = 'Interest rate spread'

# ── Countries (absolute order, matches output columns) ───────────────────────
COUNTRIES = [
    {
        'name': 'Australia',
        'iso': 'AUS',
        'code': 'OIRS.IRS.AUS.A',
        'mnemonic': 'OIRS.IRS.AUS',
        'description': 'Interest rate spread: Australia',
        'table_search': 'Scoreboard for Australia',
    },
    {
        'name': 'Canada',
        'iso': 'CAN',
        'code': 'OIRS.IRS.CAN.A',
        'mnemonic': 'OIRS.IRS.CAN',
        'description': 'Interest rate spread: Canada',
        'table_search': 'Scoreboard for Canada',
    },
    {
        'name': 'France',
        'iso': 'FRA',
        'code': 'OIRS.IRS.FRA.A',
        'mnemonic': 'OIRS.IRS.FRA',
        'description': 'Interest rate spread: France',
        'table_search': 'Scoreboard for France',
    },
    {
        'name': 'Italy',
        'iso': 'ITA',
        'code': 'OIRS.IRS.ITA.A',
        'mnemonic': 'OIRS.IRS.ITA',
        'description': 'Interest rate spread: Italy',
        'table_search': 'Scoreboard for Italy',
    },
    {
        'name': 'Spain',
        'iso': 'ESP',
        'code': 'OIRS.IRS.ESP.A',
        'mnemonic': 'OIRS.IRS.ESP',
        'description': 'Interest rate spread: Spain',
        'table_search': 'Scoreboard for Spain',
    },
    {
        'name': 'United Kingdom',
        'iso': 'GBR',
        'code': 'OIRS.IRS.GBR.A',
        'mnemonic': 'OIRS.IRS.GBR',
        'description': 'Interest rate spread: United Kingdom',
        'table_search': 'Scoreboard for the United Kingdom',
    },
    {
        'name': 'United States',
        'iso': 'USA',
        'code': 'OIRS.IRS.USA.A',
        'mnemonic': 'OIRS.IRS.USA',
        'description': 'Interest rate spread: United States',
        'table_search': 'Scoreboard for the United States',
    },
]

# ── Output column headers (absolute) ─────────────────────────────────────────
# DATA file has 2 header rows:
#   Row 0: blank + codes
#   Row 1: blank + descriptions
HEADER_ROW_CODES  = [''] + [c['code'] for c in COUNTRIES]
HEADER_ROW_LABELS = [''] + [c['description'] for c in COUNTRIES]

# ── META file columns (absolute) ─────────────────────────────────────────────
META_COLUMNS = [
    'CODE', 'CODE_MNEMONIC', 'DESCRIPTION', 'FREQUENCY', 'MULTIPLIER',
    'AGGREGATION_TYPE', 'UNIT_TYPE', 'DATA_TYPE', 'DATA_UNIT',
    'SEASONALLY_ADJUSTED', 'ANNUALIZED', 'PROVIDER_MEASURE_URL',
    'PROVIDER', 'SOURCE', 'SOURCE_DESCRIPTION', 'COUNTRY', 'DATASET',
]

META_STATIC = {
    'FREQUENCY': 'A',
    'MULTIPLIER': 0,
    'AGGREGATION_TYPE': 'UNDEFINED',
    'UNIT_TYPE': 'LEVEL',
    'DATA_TYPE': 'PERCENT',
    'DATA_UNIT': 'PERCENT',
    'SEASONALLY_ADJUSTED': 'NSA',
    'ANNUALIZED': False,
    'PROVIDER_MEASURE_URL': 'https://www.oecd-ilibrary.org/industry-and-services/financing-smes-and-entrepreneurs_23065265',
    'PROVIDER': 'AfricaAI',
    'SOURCE': 'OECD',
    'SOURCE_DESCRIPTION': 'Organisation for Economic Co-operation and Development',
    'DATASET': 'OIRS',
}

# ── NA handling ───────────────────────────────────────────────────────────────
NA_OUTPUT_VALUE = ''

# ── Table search helpers ─────────────────────────────────────────────────────
# The scoreboard title alone is NOT enough — it appears on TOC/index pages too.
# We require MULTIPLE table-specific labels that only appear on the actual data
# table page (row labels with units, dense year columns, etc.)
#
# A page is confirmed as the real scoreboard table only when:
#   1. The scoreboard title is present ("Scoreboard for <Country>")
#   2. AND at least TABLE_CONFIRM_MIN of these keywords are found on the same page
#   3. AND the page has dense year numbers (5+ years like 2007 2008 2009...)
TABLE_CONFIRM_KEYWORDS = [
    'outstanding business loans, smes',
    'non-performing loans',
    'interest rate, smes',
    'interest rate, large firms',
    'percentage points',
    'venture and growth capital',
]
TABLE_CONFIRM_MIN = 3  # require at least 3 of the above to match
TABLE_MIN_YEAR_COUNT = 5  # require at least 5 year numbers on the page
