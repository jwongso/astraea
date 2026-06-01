"""AustLII scraper for NSW NCAT Consumer and Commercial Division decisions.

Index pages are behind Cloudflare and require Playwright (BrowserSession).
Individual case pages are served as plain HTML and fetched via httpx.

Source: https://www.austlii.edu.au/cgi-bin/viewtoc/au/cases/nsw/NSWCATCD/YEAR/

Usage:
    python -m ingest.run_nsw_tenancy --years 2025 2026 --collection nsw_tenancy_ncat
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

AUSTLII_BASE = "https://www.austlii.edu.au"
TOC_URL = AUSTLII_BASE + "/cgi-bin/viewtoc/au/cases/nsw/NSWCATCD/{year}/"

_NS = uuid.UUID("b3c4d5e6-f7a8-9012-bcde-f01234567890")
CHUNK_WORDS = 150
DELAY_S = 1.0       # polite delay between httpx fetches

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.5",
}

_MONTHS = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def _parse_date(raw: str) -> str:
    """'6 January 2026' -> '2026-01-06'"""
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", raw.strip())
    if not m:
        return raw.strip()
    day, month_name, year = m.group(1), m.group(2).lower(), m.group(3)
    mon = _MONTHS.get(month_name, "01")
    return f"{year}-{mon}-{int(day):02d}"


def _chunk_text(text: str, case_id: str, title: str, date: str, url: str, citation: str) -> list[dict]:
    words = text.split()
    chunks = []
    for i in range(0, len(words), CHUNK_WORDS):
        chunk_words = words[i: i + CHUNK_WORDS]
        if len(chunk_words) < 20:
            continue
        chunks.append({
            "case_id": case_id,
            "chunk_id": f"{case_id}#{i // CHUNK_WORDS}",
            "chunk_index": i // CHUNK_WORDS,
            "court": "NSWCATCD",
            "court_name": "NCAT Consumer and Commercial Division",
            "title": title,
            "date": date,
            "url": url,
            "citation": citation,
            "text": " ".join(chunk_words),
            "source_type": "case",
            "document_type": "decision",
            "jurisdiction": "NSW",
            "legal_area": "civil",
        })
    return chunks


def _case_id(url: str) -> str:
    m = re.search(r"NSWCATCD/(\d+)/(\d+)\.html", url)
    return f"NSWCATCD/{m.group(1)}/{m.group(2)}" if m else url


async def _fetch_index_urls(browser, year: int) -> list[str]:
    """Use Playwright to get case URLs from the Cloudflare-protected index."""
    url = TOC_URL.format(year=year)
    log.info("Fetching index %s (via Playwright)", url)
    html = await browser.fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.select(f'a[href*="NSWCATCD/{year}"]'):
        href = a.get("href", "")
        if "viewdoc" in href and href.endswith(".html"):
            full = AUSTLII_BASE + href if href.startswith("/") else href
            if full not in links:
                links.append(full)
    log.info("Found %d cases for %d", len(links), year)
    return links


def _fetch_case_httpx(client: httpx.Client, url: str) -> list[dict] | None:
    """Fetch and parse a case page via plain httpx (no JS needed for case pages)."""
    try:
        r = client.get(url, timeout=20)
        r.raise_for_status()
    except Exception as exc:
        log.warning("HTTP error fetching %s: %s", url, exc)
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    content = soup.find("div", id="page-content") or soup.find("div", id="page-main")
    if not content:
        log.warning("No content div at %s", url)
        return None

    raw_text = content.get_text(separator=" ", strip=True)
    if len(raw_text) < 300:
        log.warning("Very short content at %s (%d chars) - skipping", url, len(raw_text))
        return None

    # Title: first line before "Last Updated"
    title = re.split(r"Last Updated", raw_text)[0].strip()
    title = re.sub(r"\s+", " ", title)[:200]

    # Citation
    citation_m = re.search(r"\[(\d{4})\]\s+NSWCATCD\s+(\d+)", raw_text)
    citation = citation_m.group(0) if citation_m else ""

    # Decision date
    date_m = re.search(r"Decision Date\s*:\s*([^\n;|]+)", raw_text)
    date = _parse_date(date_m.group(1)) if date_m else ""

    # Body text: start from JUDGMENT / REASONS / DECISION heading if present
    body_m = re.search(
        r"(JUDGMENT|REASONS?\s+FOR\s+(DECISION|JUDGMENT)|DECISION\s*:\s*\n)",
        raw_text, re.IGNORECASE
    )
    text = raw_text[body_m.start():] if body_m else raw_text

    case_id = _case_id(url)
    chunks = _chunk_text(text, case_id, title, date, url, citation)
    return chunks if chunks else None


class NSWCATScraper:
    """Scraper for NSWCATCD decisions from AustLII.

    Uses Playwright (via BrowserSession) to fetch Cloudflare-protected index pages,
    then plain httpx for individual case pages.
    """

    def __init__(self, years: list[int] | None = None):
        self.years = years or [2025, 2026]

    async def scrape(self, browser) -> list[dict]:
        """Fetch all cases and return a flat list of chunk payload dicts."""
        # Step 1: collect all case URLs via Playwright (handles Cloudflare on index)
        all_urls: list[str] = []
        for year in self.years:
            urls = await _fetch_index_urls(browser, year)
            all_urls.extend(urls)
            await asyncio.sleep(2)

        log.info("Total cases to fetch: %d", len(all_urls))

        # Step 2: fetch case pages via httpx (no Cloudflare on individual pages)
        all_chunks: list[dict] = []
        with httpx.Client(headers=_HEADERS, follow_redirects=True) as client:
            for i, url in enumerate(all_urls):
                log.info("[%d/%d] %s", i + 1, len(all_urls), url)
                chunks = _fetch_case_httpx(client, url)
                if chunks:
                    all_chunks.extend(chunks)
                    log.info("  -> %d chunks", len(chunks))
                time.sleep(DELAY_S)

        log.info("Scrape complete: %d chunks from %d URLs", len(all_chunks), len(all_urls))
        return all_chunks
