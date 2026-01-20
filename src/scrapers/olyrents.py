"""Scraper for Olympic Landlord & Rental Services (olyrents.com).

Uses Playwright browser to render PropertyWare JavaScript content.
Clicks through each listing detail view for complete data.
"""

import asyncio
import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Tag

from .base import ScrapedListing
from .browser_scraper import BrowserScraper


class OlyrentsScraper(BrowserScraper):
    """Scraper for olyrents.com property listings via PropertyWare widget.

    Uses browser rendering because PropertyWare loads listing content via JavaScript.
    Navigates through detail views to get complete listing data.
    """

    def __init__(self, url: str = "https://olyrents.propertyware.com/"):
        super().__init__(source_name="olyrents", base_url=url)
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
        """Scrape listings from the list view (faster and more reliable)."""
        listings = []

        browser = await self._get_browser_async()
        page = await browser.new_page()

        try:
            await page.set_viewport_size({"width": 1920, "height": 1080})

            print(f"[{self.source_name}] Loading page...")
            await page.goto(self.base_url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)  # Initial wait

            # Wait for PropertyWare widget to load
            print(f"[{self.source_name}] Waiting for PropertyWare widget...")
            try:
                await page.wait_for_selector('#pw_listing_widget_tabs_list', timeout=10000)
                print(f"[{self.source_name}] Widget container found")
            except:
                print(f"[{self.source_name}] Widget container not found")
                return listings

            # Give it more time for content to populate
            await page.wait_for_timeout(2000)

            # Get the full page HTML and parse list view
            html = await page.content()
            soup = BeautifulSoup(html, "lxml")

            # Find all visible listing items in the list view
            list_items = soup.select('li.pw_listing_widget_tabs_list_item')
            visible_items = [item for item in list_items if 'display: none' not in item.get('style', '')]

            print(f"[{self.source_name}] Found {len(visible_items)} listings in list view")

            for i, item in enumerate(visible_items):
                try:
                    listing = self._parse_list_item(item, i)
                    if listing:
                        listings.append(listing)
                        print(f"[{self.source_name}] Parsed {i+1}/{len(visible_items)}: {listing.title[:40]}... - ${listing.rent or 'N/A'}")
                        # Call callback to save immediately
                        if self._on_listing_callback:
                            self._on_listing_callback(listing)
                except Exception as e:
                    print(f"[{self.source_name}] Error parsing list item {i+1}: {e}")
                    continue

        except Exception as e:
            print(f"[{self.source_name}] Error scraping list view: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await page.close()

        return listings

    def _parse_list_item(self, item: Tag, index: int) -> Optional[ScrapedListing]:
        """Parse a listing from the list view item."""
        try:
            # Get the listing title/address from the link
            title_link = item.select_one('a[href*="gotoDetail"]')
            title = title_link.get_text(strip=True) if title_link else None

            # Get address from title or separate element
            address = title

            # Get price
            price_el = item.select_one('.listRent, .listPrice')
            rent = None
            if price_el:
                price_text = price_el.get_text(strip=True)
                rent_match = re.search(r'\$?([\d,]+)', price_text)
                if rent_match:
                    rent = int(rent_match.group(1).replace(',', ''))

            # Get beds/baths - usually in format "3 Bed / 2 Bath" or similar
            beds_el = item.select_one('.listBed')
            baths_el = item.select_one('.listBath')

            bedrooms = None
            if beds_el:
                bed_text = beds_el.get_text(strip=True)
                bed_match = re.search(r'(\d+)', bed_text)
                if bed_match:
                    bedrooms = int(bed_match.group(1))

            bathrooms = None
            if baths_el:
                bath_text = baths_el.get_text(strip=True)
                bath_match = re.search(r'(\d+\.?\d*)', bath_text)
                if bath_match:
                    bathrooms = float(bath_match.group(1))

            # Get square footage if available
            sqft_el = item.select_one('.listSqFt, .listArea')
            sqft = None
            if sqft_el:
                sqft_text = sqft_el.get_text(strip=True).replace(',', '')
                sqft_match = re.search(r'(\d+)', sqft_text)
                if sqft_match:
                    sqft = int(sqft_match.group(1))

            # Get image
            img_el = item.select_one('img.listPhoto')
            image_url = img_el.get('src') if img_el else None

            # Get property type
            type_el = item.select_one('.listType')
            prop_type = type_el.get_text(strip=True) if type_el else None

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

            # Generate source ID from address
            source_id = f"olyrents_{index}_{abs(hash(address or str(rent)))}"[:20]

            if not address and not rent:
                return None

            features = []
            if prop_type:
                features.append(prop_type.lower())

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=self.base_url,
                title=address or f"OlyRents Property #{index}",
                address=address,
                city=city,
                state=state or "WA",
                zip_code=zip_code,
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=sqft,
                features=features,
                image_url=image_url,
            )

        except Exception as e:
            print(f"[{self.source_name}] Error parsing list item: {e}")
            return None

    def _parse_detail_view(self, soup: BeautifulSoup, index: int) -> Optional[ScrapedListing]:
        """Parse listing data from the PropertyWare detail view."""
        try:
            # Address - the key field!
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
            bedrooms = None
            if bed_el:
                bed_text = bed_el.get_text(strip=True)
                if bed_text:
                    try:
                        bedrooms = int(bed_text)
                    except ValueError:
                        pass

            # Bathrooms
            bath_el = soup.select_one("#pw_listing_widget_tabs_detail_bath")
            bathrooms = None
            if bath_el:
                bath_text = bath_el.get_text(strip=True)
                if bath_text:
                    try:
                        bathrooms = float(bath_text)
                    except ValueError:
                        pass

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
            source_id = f"olyrents_{index}_{abs(hash(address or str(rent)))}"[:20]

            if not address and not rent:
                return None

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=self.base_url,
                title=address or f"OlyRents Property #{index}",
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
