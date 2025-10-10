"""
Web scraper for restaurant listings.
"""
from bs4 import BeautifulSoup
from pathlib import Path
import os

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

            data = {
                "name": name_el.get_text(strip=True) if name_el else None,
                "address": address_el.get_text(strip=True) if address_el else None,
                "cuisine": cuisine_el.get_text(strip=True) if cuisine_el else None,
                "average_price": price_el.strip() if price_el else None,
                "rating": rating_el.get_text(strip=True) if rating_el else None,
                "reviews": reviews_el.get_text(strip=True) if reviews_el else None,
                "offer": offer_el.get_text(strip=True) if offer_el else None,
                "url": anchor["href"],
            }
            # results.append(data)
            restaurants.append(data)
    return restaurants


# import pandas as pd

# df = pd.DataFrame(scrape_restaurants(num_pages=7))
