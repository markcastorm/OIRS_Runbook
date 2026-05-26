"""
Scraper for OIRS - OECD Financing SMEs and Entrepreneurs reports.

Uses Playwright (Chromium) + playwright-stealth instead of Selenium.
Playwright uses the Chrome DevTools Protocol directly — no WebDriver layer —
which has a significantly better Cloudflare bypass rate than Selenium-based
approaches.

Flow:
  1. Navigate to OECD publications landing page
  2. Find the target report (latest or by configured date)
  3. Derive the PDF URL — tries iLibrary direct URL first (no Cloudflare),
     then requests with session cookies, then human-like browser click
  4. Download the PDF via requests

Returns download metadata: {pdf_path, date_str, report_title}
"""

import os
import re
import time
import random
import logging
from datetime import datetime

import requests
import urllib3
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _human_delay(lo=0.8, hi=2.2):
    time.sleep(random.uniform(lo, hi))


def _dismiss_cookie_consent(page):
    """Dismiss GDPR / cookie-consent popup if present."""
    labels = ['Accept all', 'Accept All', 'Accept cookies', 'I agree', 'Agree', 'OK']
    try:
        for label in labels:
            btns = page.query_selector_all(f"button:has-text('{label}')")
            for btn in btns:
                if btn.is_visible():
                    btn.click()
                    logger.info(f"Cookie consent dismissed via '{label}' button")
                    _human_delay(1.0, 2.0)
                    return
    except Exception:
        pass


def _is_detail_page_loaded(html):
    """Return True when actual OECD publication content is visible (not Cloudflare)."""
    lower = html.lower()
    indicators = ['read online', 'download pdf', 'oecd-ilibrary', 'doi:', 'isbn:',
                  'financing smes', 'content/dam']
    return any(kw in lower for kw in indicators)


def _click_turnstile_checkbox(page):
    """
    Attempt to click the Cloudflare Turnstile checkbox.
    Playwright can access cross-origin frames via page.frames, which Selenium cannot.
    Returns True if a click was attempted.
    """
    # Method 1: iterate Playwright frame list — finds Cloudflare cross-origin frame
    try:
        for frame in page.frames:
            if 'challenges.cloudflare.com' in (frame.url or ''):
                logger.info(f"Found Cloudflare frame: {frame.url[:80]}")
                body = frame.query_selector('body')
                if body:
                    body.click()
                    logger.info("Clicked inside Cloudflare Turnstile frame")
                    _human_delay(1.0, 2.0)
                    return True
    except Exception as exc:
        logger.debug(f"Frame iteration click failed: {exc}")

    # Method 2: frame_locator (Playwright's high-level iframe API)
    try:
        fl = page.frame_locator('iframe[src*="challenges.cloudflare.com"]')
        fl.locator('body').click(timeout=5000)
        logger.info("Clicked Turnstile body via frame_locator")
        _human_delay(1.0, 2.0)
        return True
    except Exception as exc:
        logger.debug(f"frame_locator click failed: {exc}")

    # Method 3: any visible iframe
    try:
        iframes = page.query_selector_all('iframe')
        logger.info(f"Found {len(iframes)} iframes on page")
        for iframe in iframes:
            if iframe.is_visible():
                src = iframe.get_attribute('src') or '(no src)'
                logger.info(f"Clicking visible iframe: {src[:80]}")
                iframe.click()
                _human_delay(1.0, 2.0)
                return True
    except Exception as exc:
        logger.debug(f"Visible iframe click failed: {exc}")

    # Method 4: click at the typical Turnstile widget position
    try:
        page.mouse.click(430, 362)
        logger.info("Clicked at estimated Turnstile position (430, 362)")
        _human_delay(1.0, 2.0)
        return True
    except Exception as exc:
        logger.debug(f"Mouse position click failed: {exc}")

    return False


def _handle_cloudflare(page, max_wait=90):
    """
    Poll the current page for Cloudflare challenge, click Turnstile if present.
    Returns True once the actual page content is visible.
    """
    logger.info("Waiting for page to load (Cloudflare check)...")
    start = time.time()
    clicked = False

    while time.time() - start < max_wait:
        try:
            src = page.content()
        except Exception:
            _human_delay(1.0, 2.0)
            continue

        if _is_detail_page_loaded(src):
            logger.info(f"Page loaded ({time.time() - start:.1f}s)")
            return True

        lower = src.lower()
        if 'verify you are human' in lower or 'just a moment' in lower:
            if not clicked:
                logger.info("Turnstile challenge detected — waiting for widget to render...")
                _human_delay(2.0, 3.0)
                clicked = _click_turnstile_checkbox(page)
                if clicked:
                    logger.info("Turnstile clicked — waiting for verification...")
                    _human_delay(3.0, 5.0)
                else:
                    logger.warning("Could not find Turnstile widget")
            else:
                if time.time() - start > 20:
                    logger.info("Retrying Turnstile click...")
                    clicked = False
            _human_delay(2.0, 3.0)
            continue

        _human_delay(1.0, 2.0)

    try:
        if _is_detail_page_loaded(page.content()):
            logger.info("Page loaded after extended wait")
            return True
    except Exception:
        pass

    logger.warning(f"Cloudflare did not resolve within {max_wait}s")
    return False


# ── Browser setup ─────────────────────────────────────────────────────────────

def _build_playwright(download_dir):
    """
    Launch a Playwright Chromium browser with stealth patches.

    Playwright uses the Chrome DevTools Protocol directly (no WebDriver layer),
    which eliminates the primary navigator.webdriver signal Cloudflare checks.
    playwright-stealth applies the same patches as puppeteer-extra-plugin-stealth
    (chrome.runtime injection, WebGL fingerprint, canvas noise, etc.).
    """
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    abs_dl = os.path.abspath(download_dir)
    os.makedirs(abs_dl, exist_ok=True)

    pw = sync_playwright().start()

    # IMPORTANT: Playwright v1.58+ uses a separate 'chrome-headless-shell' binary
    # when headless=True.  That binary is trivially detected by Cloudflare because
    # it lacks GPU, has a different TLS fingerprint, and exposes headless-specific
    # signals.  Instead we ALWAYS launch the full Chrome binary (headless=False)
    # and, when headless mode is wanted, pass '--headless=new' as an argument.
    # Chrome's "new headless" mode uses the full rendering pipeline — same WebGL,
    # same TLS, same everything — making it indistinguishable from headed Chrome.
    launch_args = [
        '--disable-blink-features=AutomationControlled',
    ]
    if config.HEADLESS_MODE:
        launch_args.append('--headless=new')
        # In Docker / Linux without GPU, also suppress GPU-related noise
        launch_args.extend(['--no-sandbox', '--disable-dev-shm-usage'])

    browser = pw.chromium.launch(
        headless=False,           # Always use the full Chrome binary
        args=launch_args,
    )

    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent=(
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ),
        locale='en-US',
        timezone_id='America/New_York',
        accept_downloads=True,
    )
    context.set_default_timeout(config.WAIT_TIMEOUT * 1000)

    page = context.new_page()
    Stealth().apply_stealth_sync(page)

    logger.info(f"Playwright Chromium ready — download dir: {abs_dl}")
    return pw, browser, context, page


# ── PDF URL helpers ───────────────────────────────────────────────────────────

def _download_pdf_via_requests(url, dest_path, cookies=None):
    """Download a PDF via requests. Returns True on success."""
    try:
        resp = requests.get(
            url,
            headers=_HEADERS,
            cookies=cookies or {},
            stream=True,
            timeout=120,
            verify=False,
        )
        resp.raise_for_status()
        content_type = resp.headers.get('Content-Type', '')
        if 'html' in content_type and 'pdf' not in content_type:
            logger.warning(f"Response is HTML, not PDF: {content_type}")
            return False

        with open(dest_path, 'wb') as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)

        size = os.path.getsize(dest_path)
        if size < 50_000:
            logger.warning(f"Downloaded file suspiciously small: {size} bytes")
            return False

        logger.info(f"Downloaded {size:,} bytes -> {dest_path}")
        return True
    except Exception as exc:
        logger.warning(f"requests download failed: {exc}")
        return False


def _parse_publication_date(date_text):
    date_text = date_text.strip()
    for fmt in ['%d %B %Y', '%B %d, %Y', '%d %b %Y']:
        try:
            return datetime.strptime(date_text, fmt)
        except ValueError:
            continue
    return None


def _pdf_url_from_html(html):
    """Extract PDF URL from HTML. Prefers /content/dam/ pattern (OECD canonical)."""
    soup = BeautifulSoup(html, 'html.parser')
    for a in soup.find_all('a'):
        href = a.get('href', '')
        if '.pdf' in href.lower() and '/content/dam/' in href:
            return href if href.startswith('http') else 'https://www.oecd.org' + href
    for a in soup.find_all('a'):
        href = a.get('href', '')
        if '.pdf' in href.lower():
            return href if href.startswith('http') else 'https://www.oecd.org' + href
    return None


def _ilibrary_pdf_url(detail_url):
    """
    Construct the OECD iLibrary deliver URL directly from the publication detail URL.
    e.g. .../financing-smes-and-entrepreneurs-2026_075d8058-en.html
    →    https://www.oecd-ilibrary.org/deliver/075d8058-en/075d8058-en.pdf?...
    This bypasses the Cloudflare-protected detail page entirely.
    """
    match = re.search(r'_([0-9a-f]{8}-en)\.html', detail_url)
    if not match:
        return None
    pub_id = match.group(1)
    return (
        f"https://www.oecd-ilibrary.org/deliver/{pub_id}/{pub_id}.pdf"
        f"?itemId=%2Fcontent%2Fpublication%2F{pub_id}&mimeType=pdf"
    )


# ── Main scraping logic ───────────────────────────────────────────────────────

def _find_target_publication(page):
    """
    On the publications landing page, find the target report link.
    Returns: (detail_url, date_str, report_title, link_element)
    """
    page.wait_for_selector('a.link-list__title-link',
                           timeout=config.WAIT_TIMEOUT * 1000)
    _human_delay(1.0, 2.0)

    entries = page.query_selector_all('li.cmp-list__item')
    logger.info(f"Found {len(entries)} publication entries")

    if not entries:
        raise RuntimeError("No publication entries found on the page")

    best_date = None
    best_title = None
    best_href = None
    best_link_el = None

    for entry in entries:
        try:
            link = entry.query_selector('a.link-list__title-link')
            if not link:
                continue
            title = link.inner_text().strip()
            href = link.get_attribute('href')

            if 'financing smes' not in title.lower():
                continue

            date_span = entry.query_selector('span.link-list__date')
            date_text = date_span.inner_text().strip() if date_span else ''
            pub_date = _parse_publication_date(date_text) if date_text else None

            if config.TARGET_DATE is not None:
                target_dt = _parse_publication_date(config.TARGET_DATE)
                if pub_date and target_dt and pub_date == target_dt:
                    best_date = pub_date
                    best_title = title
                    best_href = href
                    best_link_el = link
                    break
            else:
                if pub_date and (best_date is None or pub_date > best_date):
                    best_date = pub_date
                    best_title = title
                    best_href = href
                    best_link_el = link
        except Exception as exc:
            logger.debug(f"Error processing entry: {exc}")
            continue

    if best_link_el is None:
        raise RuntimeError(
            f"Could not find target publication (TARGET_DATE={config.TARGET_DATE})"
        )

    date_str = best_date.strftime('%Y%m%d') if best_date else datetime.now().strftime('%Y%m%d')
    logger.info(f"Selected: '{best_title}' (date={date_str}, href={best_href})")

    return best_href, date_str, best_title, best_link_el


def _find_pdf_download_url(page, context, detail_url, link_el):
    """
    Return the PDF download URL.

    Strategy (priority order):
    1. iLibrary deliver URL — derived from publication ID in the detail URL.
       No browser interaction required — completely bypasses Cloudflare.
    2. requests with session cookies — works if detail page is directly accessible.
    3. Human-like browser navigation — scroll to the link on the landing page
       and click it (sets proper Referer/navigation context), then handle any
       remaining Cloudflare challenge via Turnstile clicking.
    """
    # ── Path 1: iLibrary direct URL ───────────────────────────────────────────
    ilibrary_url = _ilibrary_pdf_url(detail_url)
    if ilibrary_url:
        logger.info(f"Trying iLibrary deliver URL: {ilibrary_url}")
        try:
            resp = requests.head(
                ilibrary_url, headers=_HEADERS,
                timeout=20, verify=False, allow_redirects=True,
            )
            ct = resp.headers.get('Content-Type', '')
            logger.info(f"iLibrary HEAD: HTTP {resp.status_code}, Content-Type: {ct}")
            if resp.status_code == 200 and 'html' not in ct:
                logger.info("iLibrary deliver URL valid — using directly")
                return ilibrary_url
        except Exception as exc:
            logger.warning(f"iLibrary HEAD check failed: {exc}")

    # ── Path 2: requests with session cookies ─────────────────────────────────
    # Ensure detail_url is absolute (OECD sometimes returns relative hrefs)
    if detail_url.startswith('/'):
        detail_url = 'https://www.oecd.org' + detail_url

    session_cookies = {c['name']: c['value'] for c in context.cookies()}
    try:
        resp = requests.get(
            detail_url,
            headers={**_HEADERS, 'Referer': config.BASE_URL,
                     'Accept': 'text/html,*/*;q=0.8'},
            cookies=session_cookies,
            timeout=30, verify=False, allow_redirects=True,
        )
        logger.info(f"Detail page via requests: HTTP {resp.status_code}")
        if resp.status_code == 200:
            url = _pdf_url_from_html(resp.text)
            if url:
                logger.info(f"Found PDF URL (requests): {url}")
                return url
    except Exception as exc:
        logger.warning(f"Requests fetch of detail page failed: {exc}")

    # ── Path 3: human-like browser navigation ────────────────────────────────
    logger.info("Scrolling to publication link and clicking (human-like)...")
    try:
        link_el.scroll_into_view_if_needed()
        _human_delay(1.0, 2.0)
        link_el.click()
        logger.info("Link clicked — waiting for detail page...")
        _human_delay(3.0, 5.0)
    except Exception as exc:
        logger.warning(f"Link click failed ({exc}), falling back to page.goto")
        page.goto(detail_url, wait_until='domcontentloaded')
        _human_delay(3.0, 5.0)

    _dismiss_cookie_consent(page)
    _handle_cloudflare(page, max_wait=90)

    url = _pdf_url_from_html(page.content())
    if url:
        logger.info(f"Found PDF URL (browser BS4): {url}")
        return url

    try:
        pdf_links = page.evaluate("""
            () => Array.from(document.querySelectorAll('a'))
                .map(a => a.href)
                .filter(h => h && h.toLowerCase().includes('.pdf'))
        """)
        if pdf_links:
            logger.info(f"Found PDF URL (browser JS): {pdf_links[0]}")
            return pdf_links[0]
    except Exception as exc:
        logger.debug(f"JS PDF scan failed: {exc}")

    logger.error(f"Could not find PDF link. Page title: '{page.title()}'")
    raise RuntimeError("Could not find PDF download URL on detail page")


# ── Public entry point ────────────────────────────────────────────────────────

def download():
    """
    Download the target OECD report PDF.

    Returns: dict with keys pdf_path, date_str, report_title.
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_dir = os.path.join(config.DOWNLOAD_DIR, timestamp)
    os.makedirs(run_dir, exist_ok=True)

    pw = None
    browser = None

    try:
        pw, browser, context, page = _build_playwright(run_dir)

        logger.info(f"Browser navigating to {config.BASE_URL}")
        page.goto(config.BASE_URL, wait_until='domcontentloaded')
        _human_delay(3.0, 5.0)
        _dismiss_cookie_consent(page)

        # Step 1: find the target publication (page stays on landing page)
        detail_url, date_str, report_title, link_el = _find_target_publication(page)

        # Step 2: locate the PDF URL
        logger.info(f"Locating PDF URL for: {detail_url}")
        pdf_url = _find_pdf_download_url(page, context, detail_url, link_el)
        logger.info(f"PDF URL: {pdf_url}")

        # Step 3: download the PDF via requests
        filename = pdf_url.split('/')[-1].split('?')[0]
        if not filename.lower().endswith('.pdf'):
            filename = f"{config.JOB_NAME}_{date_str}.pdf"
        dest = os.path.join(run_dir, filename)

        session_cookies = {c['name']: c['value'] for c in context.cookies()}

        if not _download_pdf_via_requests(pdf_url, dest, session_cookies):
            logger.info("Retrying PDF download without cookies...")
            if not _download_pdf_via_requests(pdf_url, dest):
                raise RuntimeError(f"Failed to download PDF from {pdf_url}")

        logger.info(f"Download complete: pdf={dest}, date={date_str}, title={report_title}")

        return {
            'pdf_path': dest,
            'date_str': date_str,
            'report_title': report_title,
        }

    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass
