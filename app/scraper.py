"""
Web scraper for restaurant listings.
"""
from bs4 import BeautifulSoup
import re
import time
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


REQUEST_TIMEOUT_SECONDS = 15
REQUEST_THROTTLE_SECONDS = 2  # pause between requests to avoid hammering site
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.8,en-US;q=0.5",
    "Referer": "https://www.thefork.co.uk/",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}

SESSION = requests.Session()
RETRY = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET",),
    raise_on_status=False,
)
SESSION.mount("https://", HTTPAdapter(max_retries=RETRY))
SESSION.headers.update(HEADERS)

DEFAULT_SEARCH_URL = (
    "https://www.thefork.co.uk/search?cityId=665790&date=2026-02-28&hour=780&p=1&partySize=8&promotionOnly=true&timezone=Europe%2FLondon"
)


def _pluck_number(text: str | None):
    if not text:
        return None
    m = re.search(r"-?\d+[\.,]?\d*", text)
    if not m:
        return None
    raw = m.group(0).replace(",", "")
    try:
        # Return int when possible, else float
        if "." in raw:
            return float(raw)
        return int(raw)
    except Exception:
        return None


def _build_page_url(base_url: str, page: int) -> str:
    parsed = urlsplit(base_url)
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query_dict = dict(query_pairs)
    query_dict["p"] = str(page)
    new_query = urlencode(query_dict, doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))

def _extract_restaurants(soup: BeautifulSoup):
    container = soup.find("div", {"data-testid": "result-list-restaurants"})

    if not container:
        return []

    restaurants = []
    for anchor in container.find_all("a", href=True):
        name_el = anchor.find("h2")
        address_el = anchor.find("span", {"data-testid": "address"})
        cuisine_el = anchor.find("span", {"data-testid": "cuisine"})
        rating_el = anchor.find("span", {"data-testid": "rating"})
        reviews_el = anchor.find("span", {"data-testid": "reviews"})
        price_el = anchor.find(string=lambda t: t and "Average price" in t)
        offer_el = anchor.find("div", {"data-testid": "offer-tag"})

        rating_text = rating_el.get_text(strip=True) if rating_el else None
        reviews_text = reviews_el.get_text(strip=True) if reviews_el else None
        price_text = price_el.strip() if price_el else None
        offer_text = offer_el.get_text(strip=True) if offer_el else None

        data = {
            "name": name_el.get_text(strip=True) if name_el else None,
            "address": address_el.get_text(strip=True) if address_el else None,
            "cuisine": cuisine_el.get_text(strip=True) if cuisine_el else None,
            # store numerics
            "average_price": _pluck_number(price_text),
            "rating": (rating_text),
            "reviews": _pluck_number(reviews_text),
            # store absolute discount percent if present
            "offer": abs(_pluck_number(offer_text)) if _pluck_number(offer_text) is not None else None,
            "url": anchor["href"],
        }
        # results.append(data)
        restaurants.append(data)
    return restaurants


def scrape_restaurants(base_url: str | None = None, pages: int = 3):
    """Scrape TheFork listings by iterating the `p` page parameter."""

    url = base_url or DEFAULT_SEARCH_URL
    restaurants = []
    total_pages = max(1, pages)
    for page in range(1, total_pages + 1):
        page_url = _build_page_url(url, page)
        response = SESSION.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        restaurants.extend(_extract_restaurants(soup))
        # brief delay between requests so we behave like a normal user
        if page < total_pages:
            time.sleep(REQUEST_THROTTLE_SECONDS)
    return restaurants


# import pandas as pd

# df = pd.DataFrame(scrape_restaurants(num_pages=7))
