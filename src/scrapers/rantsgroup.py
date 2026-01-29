"""Scraper for Rants Group Property Management.

Uses AppFolio listings at rantsgroup.appfolio.com.
Requires browser-based scraping due to bot protection.
"""

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Tag

from .base import ScrapedListing
from .browser_scraper import BrowserScraper


class RantsGroupScraper(BrowserScraper):
    """Scraper for Rants Group Property Management via AppFolio.

    Uses browser-based scraping to bypass bot protection.
    """

    def __init__(self, url: str = "https://rantsgroup.appfolio.com/listings"):
        super().__init__(source_name="rantsgroup", base_url=url)
        self._on_listing_callback = None

    def set_on_listing_callback(self, callback):
        """Set a callback to be called for each listing as it's parsed."""
        self._on_listing_callback = callback

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all listings from rantsgroup.appfolio.com."""
        listings = []

        try:
            print(f"[{self.source_name}] Fetching page with browser...")
            listings = self._run_async(self._scrape_with_browser())
            print(f"[{self.source_name}] Total: {len(listings)} listings")

        except Exception as e:
            print(f"[{self.source_name}] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    async def _scrape_with_browser(self) -> list[ScrapedListing]:
        """Scrape listings using Playwright browser."""
        listings = []

        browser = await self._get_browser_async()
        page, context = await self._create_stealth_page(browser)

        try:
            print(f"[{self.source_name}] Loading page: {self.base_url}")
            await page.goto(self.base_url, wait_until="networkidle", timeout=60000)
            await page.wait_for_timeout(2000)

            page_title = await page.title()
            print(f"[{self.source_name}] Page title: {page_title}")

            # Wait for listings to load
            try:
                await page.wait_for_selector("[id^='listing_']", timeout=15000)
                print(f"[{self.source_name}] Listings found")
            except Exception:
                print(f"[{self.source_name}] No listings found with primary selector")
                # Check for alternative selectors
                try:
                    await page.wait_for_selector(".listing-item", timeout=5000)
                except Exception:
                    print(f"[{self.source_name}] No listings found")
                    return listings

            # Get page HTML
            html = await page.content()
            soup = BeautifulSoup(html, "lxml")

            # AppFolio listings have IDs like "listing_521"
            listing_elements = soup.select("[id^='listing_']")
            if not listing_elements:
                listing_elements = soup.select(".listing-item")

            print(f"[{self.source_name}] Found {len(listing_elements)} listing elements")

            for element in listing_elements:
                listing = self._parse_listing(element)
                if listing:
                    listings.append(listing)
                    print(f"[{self.source_name}] Parsed: {listing.title[:40]}... - ${listing.rent or 'N/A'}")
                    if self._on_listing_callback:
                        self._on_listing_callback(listing)

        except Exception as e:
            print(f"[{self.source_name}] Error during scrape: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await page.close()
            await context.close()
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

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
                # AppFolio uses data-original for lazy loading - check it first
                image_url = (
                    img.get("data-original") or
                    img.get("data-src") or
                    img.get("data-lazy-src") or
                    img.get("src")
                )
                # Skip placeholder/loading images
                if image_url and ("placeholder" in image_url.lower() or "loading" in image_url.lower() or "data:image" in image_url.lower()):
                    image_url = img.get("data-original") or img.get("data-src")
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.base_url, image_url)

            # Find link to detail page
            link = element.select_one("a[href]")
            if link:
                detail_url = urljoin(self.base_url, link.get("href", ""))
            else:
                detail_url = self.base_url

            # AppFolio uses dl/dd for specs
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

            # Fallback: try regex on all text
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

            # Address from p > span (AppFolio pattern)
            address = None
            addr_elem = element.select_one("p span")
            if addr_elem:
                address = self.clean_text(addr_elem.get_text())

            if not address:
                text = element.get_text()
                addr_match = re.search(r'(\d+\s+[\w\s]+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Way|Blvd)[^,\n]*)', text, re.I)
                if addr_match:
                    address = self.clean_text(addr_match.group(1))

            # Extract city/state/zip
            city = None
            state = None
            zip_code = None
            if address:
                zip_code = self.extract_zip_code(address)
                # Thurston County and surrounding WA cities
                city_match = re.search(r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis|Rainier|Bucoda|Roy|Spanaway|Tacoma|Puyallup|Graham|Eatonville|Shelton|McCleary|Elma)', address, re.I)
                if city_match:
                    city = city_match.group(1).title()
                    state = "WA"
                # Fallback: check for state abbreviation
                if not state:
                    state_match = re.search(r',\s*(WA|Washington)\s*\d{5}', address, re.I)
                    if state_match:
                        state = "WA"

            # Source ID from element ID
            source_id = element.get("id", "")
            if not source_id or not source_id.startswith("listing_"):
                source_id = str(abs(hash(detail_url)))[:12]

            title = address or f"Property {source_id}"

            # Skip listings without valid address (likely storage units, etc.)
            if not address or len(address) < 10:
                return None

            # Skip very cheap listings (likely storage units)
            if rent and rent < 500:
                return None

            # Skip listings with annual pricing indicators
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
            print(f"[rantsgroup] Error parsing listing: {e}")
            return None
