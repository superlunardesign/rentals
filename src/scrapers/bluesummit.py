"""Scraper for Blue Summit Realty property listings.

Tries HTTP first, falls back to browser if needed.
"""

import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapedListing


class BlueSummitScraper(BaseScraper):
    """Scraper for bluesummitrealty.com rentals."""

    def __init__(self, url: str = "https://www.bluesummitrealty.com/rental-listings/"):
        super().__init__(source_name="bluesummit", base_url=url)

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all rental listings from Blue Summit Realty."""
        listings = []

        try:
            print(f"[{self.source_name}] Fetching page via HTTP...")

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }

            with httpx.Client(timeout=30, follow_redirects=True) as client:
                response = client.get(self.base_url, headers=headers)
                print(f"[{self.source_name}] HTTP status: {response.status_code}")

                if response.status_code != 200:
                    print(f"[{self.source_name}] Failed to fetch page")
                    return listings

                html = response.text
                soup = BeautifulSoup(html, "lxml")

                # Debug: show page title
                title = soup.find("title")
                print(f"[{self.source_name}] Page title: {title.get_text() if title else 'None'}")

                # Try multiple selectors
                selectors_to_try = [
                    "a.teaser__card",
                    ".teaser__card",
                    ".property-card",
                    ".listing-card",
                    ".rental-listing",
                    "[class*='teaser']",
                    "[class*='property']",
                    "[class*='listing']",
                    ".card",
                    "article",
                ]

                cards = []
                for sel in selectors_to_try:
                    found = soup.select(sel)
                    if found:
                        print(f"[{self.source_name}] Found {len(found)} with '{sel}'")
                        if not cards:
                            cards = found

                if not cards:
                    # Debug: show sample of page content
                    all_classes = set()
                    for el in soup.find_all(class_=True)[:50]:
                        for cls in el.get('class', []):
                            all_classes.add(cls)
                    print(f"[{self.source_name}] Page classes: {list(all_classes)[:30]}")

                    # Show some of the page structure
                    body = soup.find('body')
                    if body:
                        children = [c.name for c in body.children if hasattr(c, 'name') and c.name][:10]
                        print(f"[{self.source_name}] Body children: {children}")

                for card in cards:
                    listing = self._parse_card(card)
                    if listing:
                        listings.append(listing)
                        print(f"[{self.source_name}] Parsed: {listing.title[:40] if listing.title else 'Unknown'}... - ${listing.rent or 'N/A'}")

            print(f"[{self.source_name}] Total: {len(listings)} listings")

        except Exception as e:
            print(f"[{self.source_name}] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    def _parse_card(self, card) -> ScrapedListing | None:
        """Parse a single listing card."""
        try:
            # URL
            url = card.get("href", "")
            if url and not url.startswith("http"):
                url = urljoin(self.base_url, url)

            # Price
            price_el = card.select_one(".teaser__price__title")
            rent = None
            if price_el:
                price_text = price_el.get_text(strip=True)
                rent_match = re.search(r'\$?([\d,]+)', price_text)
                if rent_match:
                    rent = int(rent_match.group(1).replace(',', ''))

            # Address
            address_el = card.select_one(".teaser__address")
            address = address_el.get_text(strip=True) if address_el else None

            # Parse city from address
            city, state, zip_code = None, "WA", None
            if address:
                city_match = re.search(r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis)', address, re.I)
                if city_match:
                    city = city_match.group(1).title()

            # Beds, Baths, SqFt from additional info spans
            info_spans = card.select(".teaser__additional-info span")
            bedrooms, bathrooms, sqft = None, None, None

            for span in info_spans:
                text = span.get_text(strip=True)

                if "Bed" in text:
                    bed_match = re.search(r'([\d.]+)', text)
                    if bed_match:
                        bedrooms = int(float(bed_match.group(1)))

                elif "Bath" in text:
                    bath_match = re.search(r'([\d.]+)', text)
                    if bath_match:
                        bathrooms = float(bath_match.group(1))

                elif "SqFt" in text:
                    sqft_match = re.search(r'([\d,]+)', text)
                    if sqft_match:
                        sqft = int(sqft_match.group(1).replace(',', ''))

            # Image
            img_el = card.select_one(".teaser__img img")
            image_url = None
            if img_el:
                image_url = img_el.get("src") or img_el.get("data-src")
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.base_url, image_url)

            # Generate source ID from URL
            source_id = None
            if url:
                slug_match = re.search(r'/listing/cms/([^/]+)/?', url)
                if slug_match:
                    source_id = f"bluesummit_{slug_match.group(1)}"

            if not source_id:
                source_id = f"bluesummit_{abs(hash(url or address))}"

            if not address and not rent:
                return None

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=url,
                title=address or f"Blue Summit Property",
                address=address,
                city=city,
                state=state,
                zip_code=zip_code,
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=sqft,
                image_url=image_url,
            )

        except Exception as e:
            print(f"[{self.source_name}] Error parsing card: {e}")
            return None
