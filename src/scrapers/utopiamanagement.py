"""Scraper for Utopia Management rental listings.

Custom WordPress-based site at utopiamanagement.com. Server-rendered HTML
with Tailwind CSS card layout. Each property card has data-property-id and
uses SVG icon refs (#bedrooms, #bathrooms, #sq-foot) for stats.
"""

import re
from typing import Optional
from urllib.parse import urljoin

from .base import BaseScraper, ScrapedListing


class UtopiaManagementScraper(BaseScraper):
    """Scraper for utopiamanagement.com rental listings."""

    def __init__(self, url: str = "https://utopiamanagement.com/rental-list/tacoma-wa"):
        super().__init__(source_name="utopiamanagement", base_url=url)

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all listings from Utopia Management."""
        listings = []

        try:
            print(f"[{self.source_name}] Fetching page...")
            soup = self.fetch_page(self.base_url)

            print(f"[{self.source_name}] Page title: {soup.title.string if soup.title else 'No title'}")

            # Each property card has data-property-id attribute
            cards = soup.select("[data-property-id]")
            print(f"[{self.source_name}] Found {len(cards)} property cards")

            for card in cards:
                listing = self._parse_listing(card)
                if listing:
                    listings.append(listing)
                    print(f"[{self.source_name}] Parsed: {listing.title[:40]}... - ${listing.rent or 'N/A'}")

            print(f"[{self.source_name}] Successfully parsed {len(listings)} listings")

        except Exception as e:
            print(f"[{self.source_name}] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    def _parse_listing(self, card) -> Optional[ScrapedListing]:
        """Parse a single Utopia Management property card."""
        try:
            property_id = card.get("data-property-id", "")

            # --- Detail URL and title from h3 > a ---
            detail_url = None
            address = None
            h3 = card.select_one("h3 a")
            if h3:
                detail_url = h3.get("href", "")
                if detail_url and not detail_url.startswith("http"):
                    detail_url = urljoin(self.base_url, detail_url)
                address = self.clean_text(h3.get_text())

            # --- Rent from the price div ---
            rent = None
            price_el = card.select_one(".text-secondary-500")
            if price_el:
                price_text = price_el.get_text()
                rent_match = re.search(r'\$?([\d,]+)', price_text)
                if rent_match:
                    rent = int(rent_match.group(1).replace(',', ''))

            # --- Description ---
            description = None
            desc_el = card.select_one(".content p")
            if desc_el:
                description = self.clean_text(desc_el.get_text())

            # --- Stats from footer: beds, baths, sqft ---
            # Pattern: <svg><use href="#bedrooms"></use></svg> <span>4</span>
            bedrooms = self._extract_stat(card, "#bedrooms")
            bathrooms = self._extract_stat_float(card, "#bathrooms")
            sqft = self._extract_sqft(card)

            # --- Image from first slide ---
            image_url = None
            img = card.select_one(".splide__slide img")
            if not img:
                img = card.select_one("img")
            if img:
                image_url = img.get("src") or img.get("data-src")
                if image_url and image_url.startswith("//"):
                    image_url = "https:" + image_url

            # --- City/state/zip from image alt text ---
            # Alt format: "1214 8th Street - Tacoma - Washington - 4 bed, 1.5 bath rental property"
            city = None
            state = None
            zip_code = None

            if img and img.get("alt"):
                alt = img.get("alt", "")
                alt_parts = [p.strip() for p in alt.split(" - ")]
                if len(alt_parts) >= 3:
                    city = alt_parts[1].title()
                    state_name = alt_parts[2].split(",")[0].strip()
                    if state_name.lower() == "washington":
                        state = "WA"

            # Fallback: extract city from address text
            if not city and address:
                city_match = re.search(
                    r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis|'
                    r'Rainier|Bucoda|Roy|Spanaway|Tacoma|Puyallup|Graham|Eatonville|'
                    r'Shelton|McCleary|Elma)',
                    address, re.I
                )
                if city_match:
                    city = city_match.group(1).title()
                    state = "WA"

            # Try to get zip from detail URL slug or description
            if description:
                zip_code = self.extract_zip_code(description)
            if not zip_code and detail_url:
                zip_code = self.extract_zip_code(detail_url)

            # Source ID
            source_id = f"utopia_{property_id}" if property_id else str(abs(hash(detail_url or address)))[:12]

            title = address or f"Utopia Property {property_id}"

            if not address:
                return None

            # Skip very cheap listings
            if rent and rent < 500:
                return None

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=detail_url or self.base_url,
                title=title,
                address=address,
                city=city,
                state=state or "WA",
                zip_code=zip_code,
                rent=rent,
                bedrooms=int(bedrooms) if bedrooms else None,
                bathrooms=bathrooms,
                sqft=int(sqft) if sqft else None,
                description=description,
                image_url=image_url,
            )

        except Exception as e:
            print(f"[{self.source_name}] Error parsing listing: {e}")
            return None

    def _extract_stat(self, card, icon_href: str) -> Optional[int]:
        """Extract an integer stat by finding the SVG icon and its adjacent span."""
        use_el = card.select_one(f'use[href="{icon_href}"]')
        if use_el:
            # The span with the value is a sibling of the parent svg's parent span
            svg = use_el.parent
            if svg:
                container = svg.parent
                if container:
                    val_span = container.select_one("span.inline-block")
                    if val_span:
                        text = val_span.get_text(strip=True)
                        match = re.search(r'(\d+)', text)
                        if match:
                            return int(match.group(1))
        return None

    def _extract_stat_float(self, card, icon_href: str) -> Optional[float]:
        """Extract a float stat (e.g. bathrooms: 1.5)."""
        use_el = card.select_one(f'use[href="{icon_href}"]')
        if use_el:
            svg = use_el.parent
            if svg:
                container = svg.parent
                if container:
                    val_span = container.select_one("span.inline-block")
                    if val_span:
                        text = val_span.get_text(strip=True)
                        match = re.search(r'(\d+\.?\d*)', text)
                        if match:
                            return float(match.group(1))
        return None

    def _extract_sqft(self, card) -> Optional[int]:
        """Extract square footage from the sq-foot icon stat."""
        use_el = card.select_one('use[href="#sq-foot"]')
        if use_el:
            svg = use_el.parent
            if svg:
                container = svg.parent
                if container:
                    val_span = container.select_one("span.inline-block")
                    if val_span:
                        text = val_span.get_text(strip=True).replace(',', '')
                        match = re.search(r'(\d+)', text)
                        if match:
                            return int(match.group(1))
        return None
