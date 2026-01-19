"""Scraper for Blue Summit Realty property listings.

Custom website with clean HTML structure - all data in listing cards.
"""

import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from .base import BaseScraper, ScrapedListing


class BlueSummitScraper(BaseScraper):
    """Scraper for bluesummitrealty.com rentals."""

    def __init__(self, url: str = "https://www.bluesummitrealty.com/property-management/"):
        super().__init__(source_name="bluesummit", base_url=url)
        # Add referer header to avoid 403
        self.client.headers["Referer"] = "https://www.bluesummitrealty.com/"
        self.client.headers["Origin"] = "https://www.bluesummitrealty.com"

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all rental listings from Blue Summit Realty."""
        listings = []
        page_num = 1

        while True:
            # Build URL for current page
            if page_num == 1:
                url = self.base_url
            else:
                url = f"{self.base_url}?p={page_num}"

            print(f"[{self.source_name}] Fetching page {page_num}: {url}")

            try:
                response = self.client.get(url)
                response.raise_for_status()
            except Exception as e:
                print(f"[{self.source_name}] Error fetching page {page_num}: {e}")
                break

            soup = BeautifulSoup(response.text, "lxml")

            # Find all listing cards
            cards = soup.select("a.teaser__card")

            if not cards:
                print(f"[{self.source_name}] No listings found on page {page_num}")
                break

            print(f"[{self.source_name}] Found {len(cards)} listings on page {page_num}")

            for card in cards:
                listing = self._parse_card(card)
                if listing:
                    listings.append(listing)

            # Check for next page
            next_link = soup.select_one('a.button:contains("Next")')
            if not next_link:
                # Also check by href pattern
                next_link = soup.select_one(f'a[href*="?p={page_num + 1}"]')

            if not next_link:
                break

            page_num += 1

            # Safety limit
            if page_num > 10:
                print(f"[{self.source_name}] Reached page limit")
                break

        print(f"[{self.source_name}] Total: {len(listings)} listings")
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

            # Parse city from address (format: "123 Street, City")
            city, state, zip_code = None, "WA", None
            if address:
                # Check for known cities
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
                # Extract slug from URL like /listing/cms/5424-93rd-ave-se/
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
