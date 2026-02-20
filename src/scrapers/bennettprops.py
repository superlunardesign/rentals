"""Scraper for Bennett Properties.

Uses AppFolio listings at bennettprops.appfolio.com.
"""

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import Tag

from .base import BaseScraper, ScrapedListing


class BennettPropsScraper(BaseScraper):
    """Scraper for Bennett Properties via AppFolio."""

    def __init__(self, url: str = "https://bennettprops.appfolio.com/listings"):
        super().__init__(source_name="bennettprops", base_url=url)
        self.client.headers["Referer"] = "https://bennettprops.appfolio.com/"

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all listings from bennettprops.appfolio.com."""
        listings = []

        try:
            print(f"[bennettprops] Fetching page...")
            soup = self.fetch_page(self.base_url)

            print(f"[bennettprops] Page title: {soup.title.string if soup.title else 'No title'}")

            # AppFolio listings have IDs like "listing_521"
            listing_elements = soup.select("[id^='listing_']")
            if not listing_elements:
                listing_elements = soup.select(".listing-item")

            print(f"[bennettprops] Found {len(listing_elements)} listing elements")

            for element in listing_elements:
                listing = self._parse_listing(element)
                if listing:
                    listings.append(listing)
                    print(f"[bennettprops] Parsed: {listing.title[:40]}... - ${listing.rent or 'N/A'}")

            print(f"[bennettprops] Successfully parsed {len(listings)} listings")

        except Exception as e:
            print(f"[bennettprops] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    def _parse_listing(self, element: Tag) -> Optional[ScrapedListing]:
        """Parse a single AppFolio listing element."""
        try:
            image_url = None
            detail_url = None

            # AppFolio structure: image is in .listing-item__image class
            img = element.select_one(".listing-item__image img")
            if not img:
                img = element.select_one("a img")
            if not img:
                img = element.find("img")
            if img:
                image_url = (
                    img.get("data-original") or
                    img.get("data-src") or
                    img.get("data-lazy-src") or
                    img.get("src")
                )
                if image_url and ("placeholder" in image_url.lower() or "loading" in image_url.lower() or "data:image" in image_url.lower()):
                    image_url = img.get("data-original") or img.get("data-src")
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.base_url, image_url)

            link = element.select_one("a[href]")
            if link:
                detail_url = urljoin(self.base_url, link.get("href", ""))
            else:
                detail_url = self.base_url

            dd_elements = element.select("dl dd")
            rent = None
            sqft = None
            bedrooms = None
            bathrooms = None

            for dd in dd_elements:
                text = dd.get_text().strip()
                if "$" in text and not rent:
                    rent = self.parse_rent(text)
                elif "sq" in text.lower() or "ft" in text.lower():
                    sqft = self.parse_sqft(text)
                elif re.search(r'\d+\s*(bed|br|bd)', text.lower()):
                    bed_match = re.search(r'(\d+)', text)
                    if bed_match:
                        bedrooms = int(bed_match.group(1))
                elif re.search(r'\d+\.?\d*\s*(bath|ba)', text.lower()):
                    bath_match = re.search(r'(\d+\.?\d*)', text)
                    if bath_match:
                        bathrooms = float(bath_match.group(1))

            all_text = element.get_text()
            if not rent:
                rent = self.parse_rent(all_text)
            if not bedrooms:
                bed_match = re.search(r'(\d+)\s*(?:bed|br)', all_text, re.I)
                if bed_match:
                    bedrooms = int(bed_match.group(1))
            if not bathrooms:
                bath_match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba)', all_text, re.I)
                if bath_match:
                    bathrooms = float(bath_match.group(1))
            if not sqft:
                sqft = self.parse_sqft(all_text)

            address = None
            addr_elem = element.select_one("p span")
            if addr_elem:
                address = self.clean_text(addr_elem.get_text())

            if not address:
                text = element.get_text()
                addr_match = re.search(r'(\d+\s+[\w\s]+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Way|Blvd)[^,\n]*)', text, re.I)
                if addr_match:
                    address = self.clean_text(addr_match.group(1))

            city = None
            state = None
            zip_code = None
            if address:
                zip_code = self.extract_zip_code(address)
                city_match = re.search(r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis|Rainier|Bucoda|Roy|Spanaway|Tacoma|Puyallup|Graham|Eatonville|Shelton|McCleary|Elma)', address, re.I)
                if city_match:
                    city = city_match.group(1).title()
                    state = "WA"
                if not state:
                    state_match = re.search(r',\s*(WA|Washington)\s*\d{5}', address, re.I)
                    if state_match:
                        state = "WA"

            source_id = element.get("id", "")
            if not source_id or not source_id.startswith("listing_"):
                source_id = str(abs(hash(detail_url)))[:12]

            title = address or f"Property {source_id}"

            if not address or len(address) < 10:
                return None

            if rent and rent < 500:
                return None

            if "/yr" in all_text.lower() or "per year" in all_text.lower():
                return None

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=detail_url,
                title=title,
                address=address,
                city=city,
                state=state or "WA",
                zip_code=zip_code,
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=sqft,
                image_url=image_url,
            )

        except Exception as e:
            print(f"[bennettprops] Error parsing listing: {e}")
            return None
