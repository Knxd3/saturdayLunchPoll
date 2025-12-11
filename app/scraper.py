"""
Web scraper for restaurant listings.
"""
from bs4 import BeautifulSoup
from pathlib import Path
import os
import re
import time
from typing import Iterable, Optional

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


def scrape_restaurants(urls: Optional[Iterable[str]] = None):
    restaurants = []
    if urls:
        url_list = list(urls)
        for idx, url in enumerate(url_list):
            response = SESSION.get(url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            restaurants.extend(_extract_restaurants(soup))
            # brief delay between requests so we behave like a normal user
            if idx < len(url_list) - 1:
                time.sleep(REQUEST_THROTTLE_SECONDS)
        return restaurants

    # response = requests.get(url, timeout=10)
    # response.raise_for_status()
    # soup = BeautifulSoup(response.text, "html.parser")

    # container = soup.find("div", {"data-testid": "result-list-restaurants"})
    base = Path(__file__).resolve().parent.parent / "soups"
    count_pages = len(os.listdir(base))
    for page in [i for i in range(1, count_pages + 1)]:
        file_path = base / f"souppage{page}.txt"
        with open(file_path, "r", encoding="utf-8") as f:
            response = f.read()

        soup = BeautifulSoup(response, "html.parser")
        restaurants.extend(_extract_restaurants(soup))
    return restaurants


# import pandas as pd

# df = pd.DataFrame(scrape_restaurants(num_pages=7))
