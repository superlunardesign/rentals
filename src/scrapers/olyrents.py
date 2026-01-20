"""Scraper for Olympic Landlord & Rental Services (olyrents.com).

Uses their main website which has a cleaner HTML structure than PropertyWare.
"""

import re
from typing import Optional
from bs4 import BeautifulSoup, Tag

from .base import ScrapedListing
from .browser_scraper import BrowserScraper


class OlyrentsScraper(BrowserScraper):
    """Scraper for olyrents.com property listings.

    Uses their main website at /properties/ which has all listing data
    in a clean card-based layout.
    """

    def __init__(self, url: str = "https://olyrents.com/properties/"):
        super().__init__(source_name="olyrents", base_url=url)
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
        """Scrape listings from the main olyrents.com website."""
        listings = []

        browser = await self._get_browser_async()
        page = await browser.new_page()

        try:
            await page.set_viewport_size({"width": 1920, "height": 1080})

            print(f"[{self.source_name}] Loading page...")
            await page.goto(self.base_url, wait_until="networkidle", timeout=30000)

            # Wait longer for JavaScript content to load
            await page.wait_for_timeout(5000)

            # Debug: print page title and URL to verify we're on the right page
            title = await page.title()
            url = page.url
            print(f"[{self.source_name}] Page loaded: {title} ({url})")

            # Try multiple selectors
            selectors_to_try = ['.list_item', '.card', '.property-card', '.listing', '[class*="list"]']

            found_selector = None
            for selector in selectors_to_try:
                try:
                    await page.wait_for_selector(selector, timeout=3000)
                    count = await page.locator(selector).count()
                    if count > 0:
                        print(f"[{self.source_name}] Found {count} elements with selector '{selector}'")
                        found_selector = selector
                        break
                except:
                    continue

            if not found_selector:
                # Debug: dump some page info
                html = await page.content()
                print(f"[{self.source_name}] Page length: {len(html)} chars")
                # Print first 500 chars of body
                soup = BeautifulSoup(html, "lxml")
                body = soup.find('body')
                if body:
                    body_text = body.get_text()[:500]
                    print(f"[{self.source_name}] Body preview: {body_text[:200]}...")
                    # Find all divs with class attributes
                    divs_with_class = soup.find_all('div', class_=True)[:10]
                    classes = [' '.join(d.get('class', [])) for d in divs_with_class]
                    print(f"[{self.source_name}] Sample div classes: {classes}")
                return listings

            # Get the page HTML
            html = await page.content()
            soup = BeautifulSoup(html, "lxml")

            # Find all listing cards using the selector that worked
            list_items = soup.select(found_selector)
            print(f"[{self.source_name}] Found {len(list_items)} listing cards")

            for i, item in enumerate(list_items):
                try:
                    listing = self._parse_card(item, i)
                    if listing:
                        listings.append(listing)
                        print(f"[{self.source_name}] Parsed {i+1}/{len(list_items)}: {listing.address or listing.title[:40]}... - ${listing.rent or 'N/A'}")
                        if self._on_listing_callback:
                            self._on_listing_callback(listing)
                except Exception as e:
                    print(f"[{self.source_name}] Error parsing card {i+1}: {e}")
                    continue

        except Exception as e:
            print(f"[{self.source_name}] Error scraping main site: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await page.close()

        return listings

    def _parse_card(self, card: Tag, index: int) -> Optional[ScrapedListing]:
        """Parse a listing card from the main website."""
        try:
            # Get address
            address_el = card.select_one('.card-property-address')
            address = address_el.get_text(strip=True) if address_el else None

            # Get title
            title_el = card.select_one('.card-property-title')
            title = title_el.get_text(strip=True) if title_el else None

            # Get price
            price_el = card.select_one('.card-property-price span')
            rent = None
            if price_el:
                price_text = price_el.get_text(strip=True)
                rent_match = re.search(r'\$?([\d,]+)', price_text)
                if rent_match:
                    rent = int(rent_match.group(1).replace(',', ''))

            # Get beds/baths from .card-property-detail spans
            detail_spans = card.select('.card-property-detail span')
            bedrooms = None
            bathrooms = None

            details = card.select('.card-property-detail')
            for detail in details:
                text = detail.get_text(strip=True).lower()
                num_el = detail.select_one('span')
                if num_el:
                    num_text = num_el.get_text(strip=True)
                    try:
                        if 'bd' in text:
                            bedrooms = int(num_text)
                        elif 'ba' in text:
                            bathrooms = float(num_text)
                    except ValueError:
                        pass

            # Get square footage
            area_el = card.select_one('.card-property-area')
            sqft = None
            if area_el:
                area_text = area_el.get_text(strip=True).replace(',', '')
                sqft_match = re.search(r'(\d+)', area_text)
                if sqft_match:
                    sqft = int(sqft_match.group(1))

            # Get description
            desc_el = card.select_one('.card-property-description')
            description = desc_el.get_text(strip=True) if desc_el else None

            # Get image from slider background-image
            image_url = None
            slider_img = card.select_one('.slider_image')
            if slider_img:
                style = slider_img.get('style', '')
                img_match = re.search(r'url\(["\']?([^"\']+)["\']?\)', style)
                if img_match:
                    image_url = img_match.group(1)

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
                title=title or address or f"OlyRents Property #{index}",
                address=address,
                city=city,
                state=state or "WA",
                zip_code=zip_code,
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=sqft,
                description=description,
                features=[],
                image_url=image_url,
            )

        except Exception as e:
            print(f"[{self.source_name}] Error parsing card: {e}")
            return None
