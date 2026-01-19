"""Scraper for Simply Home Realty LLC.

Uses Playwright browser to render PropertyWare JavaScript content.
Clicks through each listing detail view for complete data.
"""

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import Tag, BeautifulSoup

from .base import ScrapedListing
from .browser_scraper import BrowserScraper


class SimplyHomeScraper(BrowserScraper):
    """Scraper for Simply Home Realty via PropertyWare.

    Uses browser rendering because PropertyWare loads listing content via JavaScript.
    Navigates through detail views to get complete listing data.
    """

    def __init__(self, url: str = "https://simplyhomerealtyllc.propertyware.com/rentals.html"):
        super().__init__(source_name="simplyhome", base_url=url)
        self._on_listing_callback = None

    def set_on_listing_callback(self, callback):
        """Set a callback to be called for each listing as it's parsed."""
        self._on_listing_callback = callback

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all listings by clicking through detail views."""
        listings = []

        try:
            print(f"[{self.source_name}] Fetching PropertyWare widget (browser mode)...")

            # Use the detail view scraping method
            listings = self._run_async(self._scrape_with_detail_views())

            print(f"[{self.source_name}] Found {len(listings)} listings")

        except Exception as e:
            print(f"[{self.source_name}] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    async def _scrape_with_detail_views(self) -> list[ScrapedListing]:
        """Navigate through each listing's detail view to extract complete data."""
        listings = []

        browser = await self._get_browser_async()
        page = await browser.new_page()

        try:
            await page.set_viewport_size({"width": 1920, "height": 1080})

            print(f"[{self.source_name}] Loading page...")
            await page.goto(self.base_url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(3000)  # Wait for JS to render

            # Count how many listings are available
            # Use the pw_listing_widget's internal data if available, otherwise count tables
            listing_count = await page.evaluate("""
                () => {
                    // Try to get count from PropertyWare's internal state
                    if (typeof pw_listing_widget !== 'undefined' && pw_listing_widget.listings) {
                        return pw_listing_widget.listings.length;
                    }
                    // Fallback: count tables in the list view
                    const tables = document.querySelectorAll('#pw_listing_widget_tabs_list table.listTable');
                    return tables.length;
                }
            """)
            print(f"[{self.source_name}] Found {listing_count} listing tables")

            if listing_count == 0:
                return listings

            # Loop through all listings by calling gotoDetail(i) directly
            for i in range(listing_count):
                try:
                    print(f"[{self.source_name}] Loading listing {i+1}/{listing_count}...")

                    # Navigate to detail view
                    await page.evaluate(f"gotoDetail({i})")

                    # Wait for the detail view to update - watch for address to change
                    # Use a longer initial wait to let the JS render
                    await page.wait_for_timeout(2000)

                    # Try to get the detail content with retries
                    for attempt in range(3):
                        try:
                            # Wait for address element
                            await page.wait_for_selector("#pw_listing_widget_tabs_detail_address", timeout=8000, state="visible")

                            # Get the page content
                            html = await page.content()
                            soup = BeautifulSoup(html, "lxml")

                            # Extract listing from detail view
                            listing = self._parse_detail_view(soup, i)
                            if listing:
                                listings.append(listing)
                                print(f"[{self.source_name}] Parsed: {listing.title[:40]}... - ${listing.rent or 'N/A'}")
                                # Call callback to save immediately
                                if self._on_listing_callback:
                                    self._on_listing_callback(listing)
                            break  # Success, exit retry loop

                        except Exception as retry_e:
                            if attempt < 2:
                                print(f"[{self.source_name}] Retry {attempt+1} for listing {i}...")
                                await page.wait_for_timeout(1000)
                            else:
                                raise retry_e

                except Exception as e:
                    print(f"[{self.source_name}] Error on listing {i}: {e}")
                    continue

        except Exception as e:
            print(f"[{self.source_name}] Error in detail scraping: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await page.close()

        return listings

    def _parse_detail_view(self, soup: BeautifulSoup, index: int) -> Optional[ScrapedListing]:
        """Parse listing data from the PropertyWare detail view."""
        try:
            # Address - the key field we were missing!
            address_el = soup.select_one("#pw_listing_widget_tabs_detail_address")
            address = address_el.get_text(strip=True) if address_el else None

            # Price
            price_el = soup.select_one("#pw_listing_widget_tabs_detail_price")
            rent = None
            if price_el:
                price_text = price_el.get_text(strip=True)
                rent_match = re.search(r'\$?([\d,]+)', price_text)
                if rent_match:
                    rent = int(rent_match.group(1).replace(',', ''))

            # Bedrooms
            bed_el = soup.select_one("#pw_listing_widget_tabs_detail_bed")
            bedrooms = int(bed_el.get_text(strip=True)) if bed_el else None

            # Bathrooms
            bath_el = soup.select_one("#pw_listing_widget_tabs_detail_bath")
            bathrooms = float(bath_el.get_text(strip=True)) if bath_el else None

            # Square footage
            area_el = soup.select_one("#pw_listing_widget_tabs_detail_area")
            sqft = None
            if area_el:
                area_text = area_el.get_text(strip=True).replace(',', '')
                area_match = re.search(r'([\d.]+)', area_text)
                if area_match:
                    sqft = int(float(area_match.group(1)))

            # Property type
            type_el = soup.select_one("#pw_listing_widget_tabs_detail_type")
            prop_type = type_el.get_text(strip=True) if type_el else None

            # Description
            desc_el = soup.select_one("#pw_listing_widget_tabs_detail_description_p")
            description = desc_el.get_text(strip=True) if desc_el else None

            # Image
            img_el = soup.select_one("#pw_listing_widget_tabs_detail_image")
            image_url = img_el.get("src") if img_el else None

            # Deposit
            deposit_el = soup.select_one("#pw_listing_widget_tabs_detail_deposit")
            deposit = None
            if deposit_el:
                dep_match = re.search(r'\$?([\d,]+)', deposit_el.get_text())
                if dep_match:
                    deposit = int(dep_match.group(1).replace(',', ''))

            # Pets allowed
            pets_el = soup.select_one("#pw_listing_widget_tabs_detail_pets")
            pets_allowed = pets_el.get_text(strip=True).lower() if pets_el else ""

            # Amenities
            amenities_el = soup.select_one("#pw_listing_widget_tabs_detail_description_amenities_ul")
            features = []
            if amenities_el:
                for li in amenities_el.select("li"):
                    features.append(li.get_text(strip=True))

            # Add property type to features
            if prop_type:
                features.insert(0, prop_type.lower())

            # Parse city/state/zip from address
            city, state, zip_code = None, None, None
            if address:
                zip_match = re.search(r'(\d{5})(?:-\d{4})?', address)
                if zip_match:
                    zip_code = zip_match.group(1)

                city_match = re.search(r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis|Rainier|Shelton)', address, re.I)
                if city_match:
                    city = city_match.group(1).title()
                    state = "WA"

            # Generate source ID
            source_id = f"simplyhome_{index}_{abs(hash(address or str(rent)))}"[:20]

            if not address and not rent:
                return None

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=self.base_url,
                title=address or f"SimplyHome Property #{index}",
                address=address,
                city=city,
                state=state or "WA",
                zip_code=zip_code,
                rent=rent,
                deposit=deposit,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=sqft,
                description=description,
                features=features,
                image_url=image_url,
            )

        except Exception as e:
            print(f"[{self.source_name}] Error parsing detail view: {e}")
            return None
