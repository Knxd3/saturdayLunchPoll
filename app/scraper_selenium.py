"""Selenium-backed scraper for TheFork listings.

This mirrors ``app.scraper`` but drives a headless Chrome session so we can
fetch live HTML even when Cloudflare/anti-bot rules block plain requests.
"""

from __future__ import annotations

import os
import re
import time
import random
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


REQUEST_THROTTLE_SECONDS = 2
LOAD_TIMEOUT_SECONDS = 20
DEFAULT_SEARCH_URL = (
    "https://www.thefork.co.uk/search?cityId=665790&date=2026-02-28&hour=780&p=1&partySize=5"
    "&promotionOnly=true&timezone=Europe%2FLondon"
)


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


def _extract_restaurants(soup: BeautifulSoup) -> list[dict]:
    container = soup.find("div", {"data-testid": "result-list-restaurants"})
    if not container:
        return []

    restaurants: list[dict] = []
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

        restaurants.append(
            {
                "name": name_el.get_text(strip=True) if name_el else None,
                "address": address_el.get_text(strip=True) if address_el else None,
                "cuisine": cuisine_el.get_text(strip=True) if cuisine_el else None,
                "average_price": _pluck_number(price_text),
                "rating": rating_text,
                "reviews": _pluck_number(reviews_text),
                "offer": abs(_pluck_number(offer_text)) if _pluck_number(offer_text) is not None else None,
                "url": _absolute_thefork_url(anchor["href"]),
            }
        )
    return restaurants


def _chromedriver_path() -> str | None:
    direct = os.environ.get("CHROMEDRIVER")
    if direct:
        return direct
    candidate = Path(__file__).resolve().parent.parent / "driver" / "chromedriver.exe"
    if candidate.exists():
        return str(candidate)
    return None


# def _create_driver() -> webdriver.Chrome:
#     chrome_options = Options()
#     chrome_options.add_argument("--headless=new")
#     chrome_options.add_argument("--disable-gpu")
#     chrome_options.add_argument("--disable-dev-shm-usage")
#     chrome_options.add_argument("--no-sandbox")
#     chrome_options.add_argument("--window-size=1280,720")
#     chrome_options.add_argument("--disable-blink-features=AutomationControlled")
#     chrome_options.add_argument(
#         "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
#     )

#     binary = os.environ.get("CHROME_BIN")
#     if binary:
#         chrome_options.binary_location = binary

#     driver_path = _chromedriver_path()
#     if driver_path:
#         service = Service(driver_path)
#         return webdriver.Chrome(service=service, options=chrome_options)
#     return webdriver.Chrome(options=chrome_options)

print(_chromedriver_path())

#### replace user agent with this to avoid captcha
def _create_driver() -> webdriver.Chrome:
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--window-size=1920,1080")  # more realistic size
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    )                                                        # ^^^ updated version
    chrome_options.add_argument("--dns-prefetch-disable")
    chrome_options.add_argument("--host-resolver-rules=MAP * 0.0.0.0 , EXCLUDE *.thefork.co.uk,*.thefork.com")
    # Hide automation flags
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    binary = os.environ.get("CHROME_BIN")
    if binary:
        chrome_options.binary_location = binary

    driver_path = _chromedriver_path()
    if driver_path:
        service = Service(driver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
    else:
        driver = webdriver.Chrome(options=chrome_options)

    # Patch navigator.webdriver to undefined
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })

    return driver


@contextmanager
def browser(driver: webdriver.Chrome | None = None) -> Iterator[webdriver.Chrome]:
    created = driver is None
    active = driver or _create_driver()
    try:
        yield active
    finally:
        if created:
            active.quit()


#### replace user agent with this to avoid captcha
# def _fetch_page_source(driver: webdriver.Chrome, url: str) -> str:
#     driver.get(url)
#     try:
#         WebDriverWait(driver, LOAD_TIMEOUT_SECONDS).until(
#             EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='result-list-restaurants']"))
#         )
#     except TimeoutException:
#         pass
#     return driver.page_source



def _fetch_page_source(driver: webdriver.Chrome, url: str) -> str:
    driver.get(url)
    try:
        WebDriverWait(driver, LOAD_TIMEOUT_SECONDS).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='result-list-restaurants']"))
        )
    except TimeoutException:
        print(f"Timed out on: {driver.title}")
    time.sleep(random.uniform(1.5, 3.5))  # mimic human reading time
    return driver.page_source


def scrape_restaurants(base_url: str | None = None, pages: int = 3, driver: webdriver.Chrome | None = None) -> list[dict]:
    url = base_url or DEFAULT_SEARCH_URL
    total_pages = max(1, pages)
    restaurants: list[dict] = []

    with browser(driver) as drv:
        for page in range(1, total_pages + 1):
            page_url = _build_page_url(url, page)
            print(page_url)
            html = _fetch_page_source(drv, page_url)
            print(html)
            soup = BeautifulSoup(html, "html.parser")
            restaurants.extend(_extract_restaurants(soup))
            if page < total_pages:
                time.sleep(REQUEST_THROTTLE_SECONDS)

    return restaurants


__all__ = ["scrape_restaurants"]

