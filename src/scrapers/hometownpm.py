"""Scraper for Hometown Property Management (hometownpm.com).

Uses AppFolio data displayed on their main website.
"""

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, ScrapedListing


class HometownPMScraper(BaseScraper):
    """Scraper for hometownpm.com property listings."""

    def __init__(self, url: str = "https://www.hometownpm.com/"):
        super().__init__(source_name="hometownpm", base_url=url)
        # Try to look like a real browser
        self.client.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.google.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
        })

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all WA listings from hometownpm.com."""
        listings = []

        try:
            print(f"[hometownpm] Fetching page...")
            soup = self.fetch_page(self.base_url)

            print(f"[hometownpm] Page title: {soup.title.string if soup.title else 'No title'}")

            # Find all listing articles
            listing_articles = soup.select("article")
            print(f"[hometownpm] Found {len(listing_articles)} article elements")

            for article in listing_articles:
                listing = self._parse_listing(article)
                if listing:
                    # Only include WA listings
                    if listing.state == "WA":
                        listings.append(listing)
                        print(f"[hometownpm] Parsed: {listing.address[:40]}... - ${listing.rent or 'N/A'}")
                    else:
                        print(f"[hometownpm] Skipping non-WA: {listing.address}")

            print(f"[hometownpm] Found {len(listings)} WA listings")

        except Exception as e:
            print(f"[hometownpm] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    def _parse_listing(self, article: Tag) -> Optional[ScrapedListing]:
        """Parse a single listing article element."""
        try:
            image_url = None
            detail_url = None
            address_line1 = None
            address_line2 = None
            rent = None
            bedrooms = None
            bathrooms = None
            sqft = None
            description = None

            # Extract image from img tag
            img = article.select_one("img")
            if img:
                image_url = img.get("src")
                if image_url:
                    print(f"[hometownpm] Found image: {image_url[:60]}...")

            # Extract detail URL from first link
            detail_link = article.select_one("a[href*='/listings/detail/']")
            if detail_link:
                detail_url = urljoin(self.base_url, detail_link.get("href", ""))

            # Extract address from the overlay div
            # Structure: div.text-lg.font-bold > div (address line 1) + div (city, state zip)
            address_div = article.select_one(".drop-shadow")
            if address_div:
                divs = address_div.find_all("div", recursive=False)
                if len(divs) >= 2:
                    address_line1 = self.clean_text(divs[0].get_text())
                    address_line2 = self.clean_text(divs[1].get_text())

            # Extract rent - look for the bold price
            rent_elem = article.select_one(".text-2xl.font-bold")
            if rent_elem:
                rent_text = rent_elem.get_text()
                rent = self.parse_rent(rent_text)

            # Extract specs - beds, baths, sqft from the icon sections
            spec_divs = article.select(".leading-5.text-center")
            for spec_div in spec_divs:
                text = spec_div.get_text().lower().strip()

                if "bed" in text or "studio" in text:
                    if "studio" in text:
                        bedrooms = 0
                    else:
                        bed_match = re.search(r'(\d+)', text)
                        if bed_match:
                            bedrooms = int(bed_match.group(1))

                elif "bath" in text:
                    bath_match = re.search(r'([\d.]+)', text)
                    if bath_match:
                        bathrooms = float(bath_match.group(1))

                elif "sqft" in text:
                    sqft_match = re.search(r'([\d,]+)', text)
                    if sqft_match:
                        sqft = int(sqft_match.group(1).replace(',', ''))

            # Extract description
            desc_elem = article.select_one(".line-clamp-3")
            if desc_elem:
                description = self.clean_text(desc_elem.get_text())

            if not address_line1 and not address_line2:
                return None

            # Parse city/state/zip from address_line2 (e.g., "Lacey, WA 98516")
            city = None
            state = None
            zip_code = None

            if address_line2:
                # Pattern: City, ST ZIPCODE
                match = re.match(r'([^,]+),\s*([A-Z]{2})\s*(\d{5})?', address_line2)
                if match:
                    city = match.group(1).strip()
                    state = match.group(2)
                    zip_code = match.group(3)

            # Full address
            address = f"{address_line1}, {address_line2}" if address_line1 and address_line2 else (address_line1 or address_line2)

            # Generate source ID from detail URL UUID
            source_id = None
            if detail_url:
                uuid_match = re.search(r'/detail/([a-f0-9-]+)', detail_url)
                if uuid_match:
                    source_id = uuid_match.group(1)

            if not source_id:
                source_id = str(abs(hash(address or str(rent))))[:12]

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=detail_url or self.base_url,
                title=description or address or "Hometown PM Property",
                address=address,
                city=city,
                state=state,
                zip_code=zip_code,
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=sqft,
                description=description,
                image_url=image_url,
            )

        except Exception as e:
            print(f"[hometownpm] Error parsing listing: {e}")
            import traceback
            traceback.print_exc()
            return None

    def scrape_detail_page(self, url: str) -> dict:
        """Scrape additional details from a listing detail page."""
        return {
            "bedrooms": None,
            "bathrooms": None,
            "sqft": None,
            "description": None,
            "features": [],
        }
