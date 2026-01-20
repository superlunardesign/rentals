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

    def __init__(self, url: str = "https://olyrents.com/properties/olympia/"):
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

            print(f"[{self.source_name}] Loading page: {self.base_url}")
            await page.goto(self.base_url, wait_until="networkidle", timeout=30000)

            # Wait for JavaScript content to load
            await page.wait_for_timeout(3000)

            # Check where we actually ended up
            final_url = page.url
            title = await page.title()
            print(f"[{self.source_name}] Page loaded: {title}")
            print(f"[{self.source_name}] Final URL: {final_url}")

            # If we got redirected to PropertyWare, use PropertyWare selectors
            if 'propertyware' in final_url.lower():
                print(f"[{self.source_name}] Detected PropertyWare - using PW selectors")
                return await self._scrape_propertyware(page)

            # Otherwise try main site selectors
            selectors_to_try = ['.list_item', '.card', '.property-card', '.listing']

            found_selector = None
            for selector in selectors_to_try:
                try:
                    count = await page.locator(selector).count()
                    if count > 0:
                        print(f"[{self.source_name}] Found {count} elements with '{selector}'")
                        found_selector = selector
                        break
                except:
                    continue

            if not found_selector:
                print(f"[{self.source_name}] No listing elements found")
                return listings

            # Get the page HTML and parse
            html = await page.content()
            soup = BeautifulSoup(html, "lxml")
            list_items = soup.select(found_selector)

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

        except Exception as e:
            print(f"[{self.source_name}] Error scraping: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await page.close()

        return listings

    async def _scrape_propertyware(self, page) -> list[ScrapedListing]:
        """Scrape from PropertyWare widget when redirected there."""
        listings = []

        try:
            # Click Detail tab to activate it
            print(f"[{self.source_name}] Activating Detail tab...")
            try:
                await page.click('#pw_listing_widget_tabs_detail_link')
                await page.wait_for_timeout(1500)
            except:
                print(f"[{self.source_name}] Could not click Detail tab")
                return listings

            # Count listings by checking how many times we can click next
            # First get initial count from list view
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
                        listing = self._create_listing_from_pw_data(detail_data, address, i)
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

        return listings

    def _create_listing_from_pw_data(self, data: dict, address: str, index: int) -> Optional[ScrapedListing]:
        """Create listing from PropertyWare detail view data."""
        import re
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
            except:
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
                city_match = re.search(r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis|Rainier|Shelton)', address, re.I)
                if city_match:
                    city = city_match.group(1).title()
                    state = "WA"

            source_id = f"olyrents_{index}_{abs(hash(address))}"[:20]

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
