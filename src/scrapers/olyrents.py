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

            # Try to get listing data directly from PropertyWare's JavaScript
            print(f"[{self.source_name}] Extracting listing data from JavaScript...")
            listing_data = await page.evaluate("""
                () => {
                    // Try to get data from PropertyWare's internal state
                    if (typeof pw_listing_widget !== 'undefined') {
                        let listings = [];

                        // Try different data sources
                        let source = null;
                        if (pw_listing_widget.listings) {
                            source = pw_listing_widget.listings;
                        } else if (pw_listing_widget.data && pw_listing_widget.data.listings) {
                            source = pw_listing_widget.data.listings;
                        } else if (pw_listing_widget.listingData) {
                            source = Object.values(pw_listing_widget.listingData);
                        }

                        if (source) {
                            for (let item of source) {
                                listings.push({
                                    address: item.address || item.streetAddress || item.fullAddress || '',
                                    city: item.city || '',
                                    state: item.state || 'WA',
                                    zip: item.zip || item.postalCode || '',
                                    rent: item.rent || item.targetRent || item.marketRent || 0,
                                    beds: item.bedrooms || item.beds || 0,
                                    baths: item.bathrooms || item.baths || 0,
                                    sqft: item.sqft || item.area || item.totalArea || 0,
                                    type: item.type || item.unitType || '',
                                    description: item.description || '',
                                    image: item.image || item.imageUrl || item.primaryImage || '',
                                    id: item.id || item.unitId || ''
                                });
                            }
                            return { success: true, listings: listings, source: 'pw_listing_widget' };
                        }
                    }

                    // Fallback: parse from visible list items
                    let listings = [];
                    document.querySelectorAll('li.pw_listing_widget_tabs_list_item').forEach((li, idx) => {
                        if (li.style.display === 'none') return;

                        let listing = { index: idx };

                        // Get image
                        let img = li.querySelector('img.pw_listing_widget_tabs_list_item_img');
                        if (img) listing.image = img.src;

                        // Parse the description table
                        let descTd = li.querySelector('.listItemDescTd');
                        if (descTd) {
                            let text = descTd.innerText;

                            // Extract rent
                            let rentMatch = text.match(/Monthly Rent:\\s*\\$([\\d,]+)/);
                            if (rentMatch) listing.rent = parseInt(rentMatch[1].replace(',', ''));

                            // Extract BR
                            let brMatch = text.match(/BR:\\s*(\\d+)/);
                            if (brMatch) listing.beds = parseInt(brMatch[1]);

                            // Extract BA
                            let baMatch = text.match(/BA:\\s*([\\d.]+)/);
                            if (baMatch) listing.baths = parseFloat(baMatch[1]);

                            // Extract type
                            let typeMatch = text.match(/Type:\\s*([^\\n]+)/);
                            if (typeMatch) listing.type = typeMatch[1].trim();

                            // Get description paragraph
                            let p = descTd.querySelector('p');
                            if (p) listing.description = p.innerText.trim();
                        }

                        listings.push(listing);
                    });

                    return { success: true, listings: listings, source: 'dom_parsing' };
                }
            """)

            print(f"[{self.source_name}] Data source: {listing_data.get('source', 'unknown')}")

            js_listings = listing_data.get('listings', [])
            print(f"[{self.source_name}] Found {len(js_listings)} listings from JavaScript")

            # Check if we got addresses from JavaScript
            has_addresses = any(data.get('address') for data in js_listings)

            if has_addresses:
                # Great - we have all data from JavaScript
                for i, data in enumerate(js_listings):
                    try:
                        address = data.get('address', '')
                        listing = self._create_listing_from_data(data, address, i)
                        if listing:
                            listings.append(listing)
                            print(f"[{self.source_name}] Parsed {i+1}/{len(js_listings)}: {listing.title[:40]}... - ${listing.rent or 'N/A'}")
                            if self._on_listing_callback:
                                self._on_listing_callback(listing)
                    except Exception as e:
                        print(f"[{self.source_name}] Error processing listing {i+1}: {e}")
                        continue
            else:
                # Need to navigate detail views to get addresses
                # First activate the Detail tab by clicking its link
                print(f"[{self.source_name}] Activating Detail tab for navigation...")
                try:
                    await page.click('#pw_listing_widget_tabs_detail_link')
                    await page.wait_for_timeout(1500)
                except Exception as e:
                    print(f"[{self.source_name}] Could not activate Detail tab: {e}")
                    return listings

                # Now iterate through listings using gotoNextBuilding()
                total_listings = len(js_listings)
                for i in range(total_listings):
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
                        if address:
                            listing = self._create_listing_from_data(detail_data, address, i)
                            if listing:
                                listings.append(listing)
                                print(f"[{self.source_name}] Parsed {i+1}/{total_listings}: {listing.title[:40]}... - ${listing.rent or 'N/A'}")
                                if self._on_listing_callback:
                                    self._on_listing_callback(listing)

                        # Navigate to next listing (except for last one)
                        if i < total_listings - 1:
                            await page.evaluate("gotoNextBuilding()")
                            await page.wait_for_timeout(1000)

                    except Exception as e:
                        print(f"[{self.source_name}] Error processing listing {i+1}: {e}")
                        continue

        except Exception as e:
            print(f"[{self.source_name}] Error scraping list view: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await page.close()

        return listings

    def _create_listing_from_data(self, data: dict, address: str, index: int) -> Optional[ScrapedListing]:
        """Create a ScrapedListing from JavaScript-extracted data."""
        try:
            rent = data.get('rent')
            if isinstance(rent, str):
                rent = int(rent.replace(',', '').replace('$', '')) if rent else None
            elif rent:
                rent = int(rent)

            beds = data.get('beds')
            if isinstance(beds, str):
                beds = int(beds) if beds else None
            elif beds:
                beds = int(beds)

            baths = data.get('baths')
            if isinstance(baths, str):
                baths = float(baths) if baths else None
            elif baths:
                baths = float(baths)

            sqft = data.get('sqft')
            if isinstance(sqft, str):
                sqft = int(sqft.replace(',', '')) if sqft else None
            elif sqft:
                sqft = int(sqft)

            prop_type = data.get('type', '')
            description = data.get('description', '')
            image_url = data.get('image', '')

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
                bedrooms=beds,
                bathrooms=baths,
                sqft=sqft,
                description=description,
                features=features,
                image_url=image_url,
            )

        except Exception as e:
            print(f"[{self.source_name}] Error creating listing from data: {e}")
            return None

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
