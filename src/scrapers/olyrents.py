"""Scraper for Olympic Landlord & Rental Services (olyrents.com).

Uses the PropertyWare widget directly instead of the JavaScript-rendered site.
"""

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, ScrapedListing


class OlyrentsScraper(BaseScraper):
    """Scraper for olyrents.com property listings via PropertyWare widget."""

    def __init__(self, url: str = "https://olyrents.propertyware.com/"):
        super().__init__(source_name="olyrents", base_url=url)

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all listings from olyrents PropertyWare widget."""
        listings = []

        try:
            print(f"[olyrents] Fetching PropertyWare widget...")
            soup = self.fetch_page(self.base_url)

            print(f"[olyrents] Page title: {soup.title.string if soup.title else 'No title'}")

            # Find all listing tables
            listing_tables = soup.select("table.listTable")
            print(f"[olyrents] Found {len(listing_tables)} listing tables")

            for table in listing_tables:
                listing = self._parse_listing(table)
                if listing:
                    listings.append(listing)
                    print(f"[olyrents] Parsed: {listing.title[:40]}... - ${listing.rent or 'N/A'}")

            print(f"[olyrents] Found {len(listings)} listings")

        except Exception as e:
            print(f"[olyrents] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    def _parse_listing(self, table: Tag) -> Optional[ScrapedListing]:
        """Parse a single PropertyWare listing table."""
        try:
            image_url = None
            detail_url = None
            title = None
            address = None
            rent = None
            bedrooms = None
            bathrooms = None
            sqft = None
            description = None

            # Extract image
            img = table.select_one(".listItemImgTd img, .pw_listing_widget_tabs_list_item_img")
            if img:
                image_url = img.get("src")
                if image_url:
                    print(f"[olyrents] Found image: {image_url[:50]}...")

            # Extract title from the first link in description cell
            desc_td = table.select_one(".listItemDescTd")
            if desc_td:
                # Title is in the first <a> tag
                title_link = desc_td.select_one("a")
                if title_link:
                    title = self.clean_text(title_link.get_text())
                    # Extract detail index from javascript:gotoDetail(X)
                    href = title_link.get("href", "")
                    detail_match = re.search(r'gotoDetail\((\d+)\)', href)
                    if detail_match:
                        detail_url = f"{self.base_url}#listing_{detail_match.group(1)}"

                # Address is after the title, before the nested table
                # Get all text nodes and find the address pattern
                full_text = desc_td.get_text()
                addr_match = re.search(r'(\d+[^,]+,\s*\w+,\s*WA\s*\d{5}(?:-\d{4})?)', full_text)
                if addr_match:
                    address = self.clean_text(addr_match.group(1))

                # Extract specs from the nested table
                spec_table = desc_td.select_one("table")
                if spec_table:
                    spec_text = spec_table.get_text()

                    # Monthly Rent
                    rent_match = re.search(r'Monthly Rent:\s*\$?([\d,]+)', spec_text)
                    if rent_match:
                        rent = int(rent_match.group(1).replace(',', '').split('.')[0])

                    # Bedrooms
                    br_match = re.search(r'BR:\s*(\d+)', spec_text)
                    if br_match:
                        bedrooms = int(br_match.group(1))

                    # Bathrooms
                    ba_match = re.search(r'BA:\s*(\d+\.?\d*)', spec_text)
                    if ba_match:
                        bathrooms = float(ba_match.group(1))

                # Description is in <p> tag
                desc_p = desc_td.select_one("p")
                if desc_p:
                    description = self.clean_text(desc_p.get_text())

                # Try to extract sqft from title or description
                sqft_text = f"{title or ''} {description or ''}"
                sqft_match = re.search(r'([\d,]+)\s*sq\.?\s*ft', sqft_text, re.I)
                if sqft_match:
                    sqft = int(sqft_match.group(1).replace(',', ''))

            if not title and not address:
                return None

            # Extract city/state/zip from address
            city = None
            state = None
            zip_code = None
            if address:
                zip_code = self.extract_zip_code(address)
                city_match = re.search(r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis)', address, re.I)
                if city_match:
                    city = city_match.group(1).title()
                    state = "WA"

            # Generate source ID from address or title
            source_id = None
            if address:
                # Use address hash as ID since PropertyWare doesn't expose IDs
                source_id = str(abs(hash(address)))[:12]
            else:
                source_id = str(abs(hash(title or str(rent))))[:12]

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=detail_url or self.base_url,
                title=title or address or f"OlyRents Property",
                address=address,
                city=city,  # Don't default - let matcher filter unknown cities
                state=state or "WA",
                zip_code=zip_code,
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=sqft,
                description=description,
                image_url=image_url,
            )

        except Exception as e:
            print(f"[olyrents] Error parsing listing: {e}")
            import traceback
            traceback.print_exc()
            return None

    def scrape_detail_page(self, url: str) -> dict:
        """PropertyWare widget doesn't have separate detail pages."""
        return {
            "bedrooms": None,
            "bathrooms": None,
            "sqft": None,
            "description": None,
            "features": [],
        }
