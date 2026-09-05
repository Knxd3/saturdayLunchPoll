"""
Web scraper for restaurant listings.
"""
from bs4 import BeautifulSoup
from pathlib import Path
import os
import re


THEFORK_ORIGIN = "https://www.thefork.co.uk"


def _absolute_thefork_url(url: str | None) -> str | None:
    if not url:
        return url
    s = str(url).strip()
    if not s:
        return url
    if "://" in s:
        return s
    if s.startswith("/"):
        return THEFORK_ORIGIN + s
    return THEFORK_ORIGIN + "/" + s


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

def scrape_restaurants():
    # response = requests.get(url, timeout=10)
    # response.raise_for_status()
    # soup = BeautifulSoup(response.text, "html.parser")

    # container = soup.find("div", {"data-testid": "result-list-restaurants"})
    restaurants = []
    base = Path(__file__).resolve().parent.parent / "soups"
    count_pages = len(os.listdir(base))
    for page in [i for i in range(1, count_pages + 1)]:
        file_path = base / f"souppage{page}.txt"
        with open(file_path, "r", encoding="utf-8") as f:
            response = f.read()

        soup = BeautifulSoup(response, "html.parser")
        container = soup.find("div", {"data-testid": "result-list-restaurants"})

        if not container:
            return []

        # results = []
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
                "url": _absolute_thefork_url(anchor["href"]),
            }
            # results.append(data)
            restaurants.append(data)
    return restaurants


# import pandas as pd

# df = pd.DataFrame(scrape_restaurants(num_pages=7))
