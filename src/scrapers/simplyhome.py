"""Scraper for Simply Home Realty LLC.

Uses their main website which has a cleaner HTML structure than PropertyWare.
"""

import re
from typing import Optional
from bs4 import BeautifulSoup, Tag

from .base import ScrapedListing
from .browser_scraper import BrowserScraper


class SimplyHomeScraper(BrowserScraper):
    """Scraper for Simply Home Realty property listings.

    Uses their main website which has all listing data in a clean list layout.
    """

    def __init__(self, url: str = "https://www.simplyhomerealty.com/lacey-homes-for-rent"):
        super().__init__(source_name="simplyhome", base_url=url)
        self._on_listing_callback = None

    def set_on_listing_callback(self, callback):
        """Set a callback to be called for each listing as it's parsed."""
        self._on_listing_callback = callback

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all listings from the main website."""
        listings = []

        try:
            print(f"[{self.source_name}] Fetching main website...")
            listings = self._run_async(self._scrape_main_site())
            print(f"[{self.source_name}] Found {len(listings)} listings")

        except Exception as e:
            print(f"[{self.source_name}] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    async def _scrape_main_site(self) -> list[ScrapedListing]:
        """Scrape listings from the main simplyhomerealty.com website."""
        listings = []

        browser = await self._get_browser_async()
        page = await browser.new_page()

        try:
            await page.set_viewport_size({"width": 1920, "height": 1080})

            print(f"[{self.source_name}] Loading page...")
            await page.goto(self.base_url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            # Wait for listing items to load
            print(f"[{self.source_name}] Waiting for listings to load...")
            try:
                await page.wait_for_selector('.nhw-list__item', timeout=10000)
                print(f"[{self.source_name}] Listings container found")
            except:
                print(f"[{self.source_name}] Primary selector not found, trying alternatives...")
                # Try alternative selectors
                found = False
                for selector in ['.property-item', '.listing', '[class*="list"]', '[class*="property"]', 'article']:
                    try:
                        count = await page.locator(selector).count()
                        if count > 0:
                            print(f"[{self.source_name}] Found {count} elements with '{selector}'")
                            found = True
                            break
                    except:
                        continue
                if not found:
                    # Dump classes for debugging
                    html = await page.content()
                    soup = BeautifulSoup(html, "lxml")
                    body = soup.body
                    if body:
                        elements_with_class = body.find_all(attrs={"class": True})[:30]
                        classes_found = set()
                        for el in elements_with_class:
                            for cls in el.get("class", []):
                                classes_found.add(cls)
                        print(f"[{self.source_name}] Classes on page: {sorted(classes_found)[:50]}")
                    print(f"[{self.source_name}] No listings found on page")
                    return listings

            # Get the page HTML
            html = await page.content()
            soup = BeautifulSoup(html, "lxml")

            # Find all listing items
            list_items = soup.select('.nhw-list__item')
            print(f"[{self.source_name}] Found {len(list_items)} listing items")

            for i, item in enumerate(list_items):
                try:
                    listing = self._parse_item(item, i)
                    if listing:
                        listings.append(listing)
                        print(f"[{self.source_name}] Parsed {i+1}/{len(list_items)}: {listing.address or listing.title[:40]}... - ${listing.rent or 'N/A'}")
                        if self._on_listing_callback:
                            self._on_listing_callback(listing)
                except Exception as e:
                    print(f"[{self.source_name}] Error parsing item {i+1}: {e}")
                    continue

        except Exception as e:
            print(f"[{self.source_name}] Error scraping main site: {e}")
            import traceback
            traceback.print_exc()

        finally:
            # Close page AND browser to free memory
            await page.close()
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

        return listings

    def _parse_item(self, item: Tag, index: int) -> Optional[ScrapedListing]:
        """Parse a listing item from the main website."""
        try:
            # Get listing URL from the main link
            listing_url = self.base_url
            link_el = item.select_one('a[href*="/_system/listings/"]') or item.select_one('a[href]')
            if link_el:
                href = link_el.get('href', '')
                if href:
                    if href.startswith('/'):
                        listing_url = f"https://www.simplyhomerealty.com{href}"
                    elif href.startswith('http'):
                        listing_url = href
                    if index == 0:
                        print(f"[{self.source_name}] Listing URL found: {listing_url[:60]}...")

            # Get address from .nhw-list__location
            location_el = item.select_one('.nhw-list__location')
            address = location_el.get_text(strip=True) if location_el else None

            # Get price from .nhw-list__price
            price_el = item.select_one('.nhw-list__price')
            rent = None
            if price_el:
                price_text = price_el.get_text(strip=True)
                rent_match = re.search(r'\$?([\d,]+)', price_text)
                if rent_match:
                    rent = int(rent_match.group(1).replace(',', ''))

            # Get beds/baths from .nhw-list__details ul li
            bedrooms = None
            bathrooms = None
            detail_items = item.select('.nhw-list__details ul li')
            for li in detail_items:
                text = li.get_text(strip=True).lower()
                if 'beds' in text or 'bed' in text:
                    bed_match = re.search(r'(\d+)', text)
                    if bed_match:
                        bedrooms = int(bed_match.group(1))
                elif 'baths' in text or 'bath' in text:
                    bath_match = re.search(r'([\d.]+)', text)
                    if bath_match:
                        bathrooms = float(bath_match.group(1))

            # Get property type
            type_el = item.select_one('.nhw-list__prop-type')
            prop_type = type_el.get_text(strip=True) if type_el else None

            # Get availability
            avail_el = item.select_one('.nhw-list__availability')
            availability = avail_el.get_text(strip=True) if avail_el else None

            # Get image - try src first, then data-src
            image_url = None
            img_el = item.select_one('.f-carousel__slide img')
            if img_el:
                image_url = img_el.get('src') or img_el.get('data-src')
                # Make absolute URL if relative
                if image_url and image_url.startswith('/'):
                    image_url = f"https://www.simplyhomerealty.com{image_url}"

            # Parse city/state/zip from address
            city, state, zip_code = None, None, None
            if address:
                zip_match = re.search(r'(\d{5})(?:-\d{4})?', address)
                if zip_match:
                    zip_code = zip_match.group(1)

                city_match = re.search(r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis|Rainier|Shelton|Roy|Tacoma)', address, re.I)
                if city_match:
                    city = city_match.group(1).title()
                    state = "WA"

            # Generate stable source ID based on address (don't include index which changes with order)
            source_id = f"simplyhome_{abs(hash(address or ''))}"
            # If no address, fall back to rent-based ID
            if not address and rent:
                source_id = f"simplyhome_rent_{rent}"

            if not address and not rent:
                return None

            features = []
            if prop_type:
                features.append(prop_type.lower())
            if availability:
                features.append(availability)

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=listing_url,
                title=address or f"SimplyHome Property #{index}",
                address=address,
                city=city,
                state=state or "WA",
                zip_code=zip_code,
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=None,  # Not shown in list view
                description=None,  # Not shown in list view
                features=features,
                image_url=image_url,
            )

        except Exception as e:
            print(f"[{self.source_name}] Error parsing item: {e}")
            return None
