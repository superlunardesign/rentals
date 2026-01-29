"""Scraper for Blue Summit Realty property listings.

Uses HTTP-based scraping since listings appear to be server-rendered.
"""

import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import Tag

from .base import BaseScraper, ScrapedListing


class BlueSummitScraper(BaseScraper):
    """Scraper for bluesummitrealty.com rentals.

    Uses HTTP requests - listings are server-side rendered.
    """

    def __init__(self, url: str = "https://www.bluesummitrealty.com/property-management/"):
        super().__init__(source_name="bluesummit", base_url=url)
        self._on_listing_callback = None

    def set_on_listing_callback(self, callback):
        """Set a callback to be called for each listing as it's parsed."""
        self._on_listing_callback = callback

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all rental listings from Blue Summit Realty."""
        listings = []

        try:
            print(f"[{self.source_name}] Fetching page via HTTP...")
            soup = self.fetch_page(self.base_url)

            page_title = soup.title.string if soup.title else "No title"
            print(f"[{self.source_name}] Page title: {page_title}")

            # Check if we got blocked
            if "403" in page_title or "forbidden" in page_title.lower():
                print(f"[{self.source_name}] Got 403 - site is blocking requests")
                # Log some HTML for debugging
                html_preview = str(soup)[:1000]
                print(f"[{self.source_name}] HTML preview: {html_preview}")
                return listings

            # Find listing cards
            cards = soup.select("a.teaser__card")
            if not cards:
                cards = soup.select("a.teaser.teaser__card")
            if not cards:
                cards = soup.select('[class*="teaser"][class*="card"]')

            print(f"[{self.source_name}] Found {len(cards)} listing cards")

            if not cards:
                # Debug: show what we got
                all_links = soup.find_all('a', href=True)
                listing_links = [a['href'] for a in all_links if '/listing/' in a.get('href', '')]
                print(f"[{self.source_name}] Found {len(listing_links)} listing links")
                if listing_links:
                    print(f"[{self.source_name}] Sample: {listing_links[:3]}")

            for i, card in enumerate(cards):
                try:
                    listing = self._parse_card(card)
                    if listing:
                        listings.append(listing)
                        print(f"[{self.source_name}] Parsed {i+1}/{len(cards)}: {listing.address or listing.title[:40]}... - ${listing.rent or 'N/A'}")
                        if self._on_listing_callback:
                            self._on_listing_callback(listing)
                except Exception as e:
                    print(f"[{self.source_name}] Error parsing card {i+1}: {e}")
                    continue

            print(f"[{self.source_name}] Total: {len(listings)} listings")

        except Exception as e:
            print(f"[{self.source_name}] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    def _parse_card(self, card: Tag) -> Optional[ScrapedListing]:
        """Parse a single listing card."""
        try:
            # URL
            url = card.get("href", "")
            if url and not url.startswith("http"):
                url = urljoin(self.base_url, url)

            # Price
            price_el = card.select_one(".teaser__price__title")
            if not price_el:
                price_el = card.select_one(".teaser__price")
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
                city_match = re.search(
                    r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis|Rainier|Bucoda|DuPont|Steilacoom)',
                    address, re.I
                )
                if city_match:
                    city = city_match.group(1).title()
                # Extract zip code
                zip_match = re.search(r'\b(\d{5})\b', address)
                if zip_match:
                    zip_code = zip_match.group(1)

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
                image_url = img_el.get("data-src") or img_el.get("src")
                if image_url and ("no-image" in image_url or "/util/" in image_url):
                    image_url = None
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.base_url, image_url)

            # Generate source ID from URL
            source_id = None
            if url:
                slug_match = re.search(r'/listing/(?:cms/)?([^/]+)/?', url)
                if slug_match:
                    source_id = f"bluesummit_{slug_match.group(1)}"

            if not source_id:
                source_id = f"bluesummit_{abs(hash(address or url))}"

            if not address and not rent:
                return None

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=url,
                title=address or "Blue Summit Property",
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
