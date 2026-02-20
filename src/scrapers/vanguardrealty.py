"""Scraper for Vanguard Realty (PropertyWare platform).

Uses browser-based scraping for the PropertyWare widget at
vanguardrealty.propertyware.com.
"""

import re
from typing import Optional

from .base import ScrapedListing
from .browser_scraper import BrowserScraper


class VanguardRealtyScraper(BrowserScraper):
    """Scraper for vanguardrealty.propertyware.com listings."""

    def __init__(self, url: str = "https://vanguardrealty.propertyware.com/rentals.html"):
        super().__init__(source_name="vanguardrealty", base_url=url)
        self._on_listing_callback = None

    def set_on_listing_callback(self, callback):
        """Set a callback to be called for each listing as it's parsed."""
        self._on_listing_callback = callback

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all listings from PropertyWare."""
        listings = []

        try:
            listings = self._run_async(self._scrape_propertyware())
            print(f"[{self.source_name}] Found {len(listings)} listings")
        except Exception as e:
            print(f"[{self.source_name}] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    async def _scrape_propertyware(self) -> list[ScrapedListing]:
        """Scrape from PropertyWare widget."""
        listings = []

        browser = await self._get_browser_async()
        page = await browser.new_page()

        try:
            await page.set_viewport_size({"width": 1920, "height": 1080})

            print(f"[{self.source_name}] Loading page: {self.base_url}")
            await page.goto(self.base_url, wait_until="networkidle", timeout=60000)

            title = await page.title()
            print(f"[{self.source_name}] Page loaded: {title}")

            # Click Detail tab to activate it
            print(f"[{self.source_name}] Activating Detail tab...")
            try:
                await page.click('#pw_listing_widget_tabs_detail_link')
                await page.wait_for_timeout(1500)
            except Exception:
                print(f"[{self.source_name}] Could not click Detail tab")
                return listings

            # Count listings from list view
            list_count = await page.locator('li.pw_listing_widget_tabs_list_item').count()
            print(f"[{self.source_name}] Found {list_count} listings in PropertyWare")

            seen_addresses = set()
            max_iterations = list_count + 5  # Safety limit

            for i in range(max_iterations):
                try:
                    # Get current detail view data
                    detail_data = await page.evaluate("""
                        () => {
                            let address = document.querySelector('#pw_listing_widget_tabs_detail_address');
                            let price = document.querySelector('#pw_listing_widget_tabs_detail_price');
                            let bed = document.querySelector('#pw_listing_widget_tabs_detail_bed');
                            let bath = document.querySelector('#pw_listing_widget_tabs_detail_bath');
                            let area = document.querySelector('#pw_listing_widget_tabs_detail_area');
                            let type = document.querySelector('#pw_listing_widget_tabs_detail_type');
                            let desc = document.querySelector('#pw_listing_widget_tabs_detail_description_p');
                            let img = document.querySelector('#pw_listing_widget_tabs_detail_image');

                            return {
                                address: address ? address.innerText.trim() : '',
                                rent: price ? price.innerText.trim() : '',
                                beds: bed ? bed.innerText.trim() : '',
                                baths: bath ? bath.innerText.trim() : '',
                                sqft: area ? area.innerText.trim() : '',
                                type: type ? type.innerText.trim() : '',
                                description: desc ? desc.innerText.trim() : '',
                                image: img ? img.src : ''
                            };
                        }
                    """)

                    address = detail_data.get('address', '')

                    # Stop if we've seen this address (looped back to start)
                    if address in seen_addresses:
                        print(f"[{self.source_name}] Reached end (saw {address} again)")
                        break

                    if address:
                        seen_addresses.add(address)
                        listing = self._create_listing(detail_data, address)
                        if listing:
                            listings.append(listing)
                            print(f"[{self.source_name}] Parsed {len(listings)}: {address[:40]}... - ${listing.rent or 'N/A'}")
                            if self._on_listing_callback:
                                self._on_listing_callback(listing)

                    # Navigate to next listing
                    await page.evaluate("gotoNextBuilding()")
                    await page.wait_for_timeout(800)

                except Exception as e:
                    print(f"[{self.source_name}] Error on listing {i+1}: {e}")
                    break

        except Exception as e:
            print(f"[{self.source_name}] PropertyWare scrape error: {e}")
        finally:
            await page.close()
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

        return listings

    def _create_listing(self, data: dict, address: str) -> Optional[ScrapedListing]:
        """Create listing from PropertyWare detail view data."""
        try:
            rent = data.get('rent', '')
            if rent:
                rent_match = re.search(r'\$?([\d,]+)', rent)
                rent = int(rent_match.group(1).replace(',', '')) if rent_match else None
            else:
                rent = None

            beds = data.get('beds', '')
            beds = int(beds) if beds and beds.isdigit() else None

            baths = data.get('baths', '')
            try:
                baths = float(baths) if baths else None
            except (ValueError, TypeError):
                baths = None

            sqft = data.get('sqft', '').replace(',', '')
            sqft_match = re.search(r'(\d+)', sqft) if sqft else None
            sqft = int(sqft_match.group(1)) if sqft_match else None

            # Parse city from address
            city, state, zip_code = None, None, None
            if address:
                zip_match = re.search(r'(\d{5})(?:-\d{4})?', address)
                if zip_match:
                    zip_code = zip_match.group(1)
                city_match = re.search(r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis|Rainier|Shelton|Tacoma|Puyallup|Spanaway|Graham|Eatonville)', address, re.I)
                if city_match:
                    city = city_match.group(1).title()
                    state = "WA"

            source_id = f"vanguardrealty_{abs(hash(address))}"

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=self.base_url,
                title=address,
                address=address,
                city=city,
                state=state or "WA",
                zip_code=zip_code,
                rent=rent,
                bedrooms=beds,
                bathrooms=baths,
                sqft=sqft,
                description=data.get('description', ''),
                features=[data.get('type', '')] if data.get('type') else [],
                image_url=data.get('image', ''),
            )
        except Exception as e:
            print(f"[{self.source_name}] Error creating listing: {e}")
            return None
