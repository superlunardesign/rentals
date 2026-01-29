"""Scraper for Blue Summit Realty property listings.

Uses browser-based scraping since the page renders listings with JavaScript.
"""

import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import ScrapedListing
from .browser_scraper import BrowserScraper


class BlueSummitScraper(BrowserScraper):
    """Scraper for bluesummitrealty.com rentals.

    Uses Playwright browser to render JavaScript content.
    """

    def __init__(self, url: str = "https://www.bluesummitrealty.com/property-management/#listings"):
        super().__init__(source_name="bluesummit", base_url=url)
        self._on_listing_callback = None

    def set_on_listing_callback(self, callback):
        """Set a callback to be called for each listing as it's parsed."""
        self._on_listing_callback = callback

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all rental listings from Blue Summit Realty."""
        listings = []

        try:
            print(f"[{self.source_name}] Fetching page with browser...")
            listings = self._run_async(self._scrape_listings())
            print(f"[{self.source_name}] Total: {len(listings)} listings")

        except Exception as e:
            print(f"[{self.source_name}] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    async def _scrape_listings(self) -> list[ScrapedListing]:
        """Scrape listings using Playwright browser."""
        listings = []

        # Use Chromium specifically for this site (Firefox gets 403)
        from playwright.async_api import async_playwright
        print(f"[{self.source_name}] Starting Playwright with Chromium...")
        self._playwright = await async_playwright().start()
        browser = await self._playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled']
        )
        page, context = await self._create_stealth_page(browser)
        self._browser = browser

        try:
            print(f"[{self.source_name}] Loading page: {self.base_url}")
            # Use networkidle to ensure all JS resources are fully loaded
            await page.goto(self.base_url, wait_until="networkidle", timeout=60000)

            # Wait for potential Cloudflare challenge to resolve
            print(f"[{self.source_name}] Waiting for page to fully load...")
            await page.wait_for_timeout(3000)

            # Check for Cloudflare challenge page and wait it out
            page_title = await page.title()
            if "Just a moment" in page_title or "Checking" in page_title:
                print(f"[{self.source_name}] Cloudflare challenge detected, waiting...")
                await page.wait_for_timeout(10000)
                page_title = await page.title()

            # Wait for the #listings container to exist first (Vue.js app mounts here)
            print(f"[{self.source_name}] Waiting for #listings container...")
            try:
                await page.wait_for_selector('#listings', timeout=10000)
                print(f"[{self.source_name}] #listings container found")
            except Exception:
                print(f"[{self.source_name}] #listings container not found")

            # Wait for .snippet-listings which contains the actual cards
            print(f"[{self.source_name}] Waiting for .snippet-listings...")
            try:
                await page.wait_for_selector('.snippet-listings', timeout=10000)
                print(f"[{self.source_name}] .snippet-listings found")
            except Exception:
                print(f"[{self.source_name}] .snippet-listings not found")

            # Scroll to the listings section to ensure visibility
            print(f"[{self.source_name}] Scrolling to listings section...")
            try:
                await page.evaluate("""
                    const listingsSection = document.querySelector('#listings');
                    if (listingsSection) {
                        listingsSection.scrollIntoView({ behavior: 'instant', block: 'start' });
                    }
                """)
                await page.wait_for_timeout(2000)
            except Exception as e:
                print(f"[{self.source_name}] Scroll to section failed: {e}")

            # Wait specifically for the teaser cards to render (Vue.js content)
            print(f"[{self.source_name}] Waiting for listing cards to render...")
            found_selector = None

            # Primary selector - this matches the actual HTML structure
            try:
                await page.wait_for_selector('#listings .snippet-listings a.teaser__card', timeout=15000)
                found_selector = '#listings .snippet-listings a.teaser__card'
                print(f"[{self.source_name}] Listings found with selector: {found_selector}")
            except Exception:
                print(f"[{self.source_name}] Primary selector timed out, trying alternatives...")

            # Fallback selectors
            if not found_selector:
                selectors_to_try = [
                    'a.teaser.teaser__card',
                    'a.teaser__card',
                    '.teasers a.teaser__card',
                    '.snippet-listings a[href*="/listing/"]',
                    '#listings a[href*="/listing/"]',
                    'a[href*="/listing/cms/"]',
                ]
                for selector in selectors_to_try:
                    try:
                        await page.wait_for_selector(selector, timeout=3000)
                        found_selector = selector
                        print(f"[{self.source_name}] Listings found with fallback selector: {selector}")
                        break
                    except Exception:
                        continue

            if not found_selector:
                print(f"[{self.source_name}] No listings found with standard selectors, analyzing page...")
                current_url = page.url
                print(f"[{self.source_name}] Current URL: {current_url}")
                print(f"[{self.source_name}] Page title: {page_title}")

                # Get HTML and analyze structure
                html = await page.content()
                soup = BeautifulSoup(html, "lxml")

                # Look for listing-related classes
                all_classes = set()
                for el in soup.find_all(class_=True):
                    for cls in el.get('class', []):
                        if any(kw in cls.lower() for kw in ['teaser', 'listing', 'property', 'card', 'rental']):
                            all_classes.add(cls)
                print(f"[{self.source_name}] Listing-related classes: {sorted(all_classes)}")

                # Check for listing links
                links = soup.find_all('a', href=True)
                listing_links = [a['href'] for a in links if '/listing/' in a.get('href', '')]
                print(f"[{self.source_name}] Found {len(listing_links)} listing links on page")
                if listing_links:
                    print(f"[{self.source_name}] Sample links: {listing_links[:3]}")

                # Check for iframes that might contain listings
                iframes = soup.find_all('iframe')
                if iframes:
                    print(f"[{self.source_name}] Found {len(iframes)} iframes")
                    for iframe in iframes:
                        print(f"[{self.source_name}]   iframe src: {iframe.get('src', 'no src')}")

                return listings

            # Get page HTML
            html = await page.content()
            soup = BeautifulSoup(html, "lxml")

            # Find all listing cards using the working selector
            cards = soup.select(found_selector)
            print(f"[{self.source_name}] Found {len(cards)} listing cards with '{found_selector}'")

            for i, card in enumerate(cards):
                try:
                    listing = self._parse_card(card)
                    if listing:
                        listings.append(listing)
                        print(f"[{self.source_name}] Parsed {i+1}/{len(cards)}: {listing.address or listing.title[:40]}... - ${listing.rent or 'N/A'}")
                        if self._on_listing_callback:
                            self._on_listing_callback(listing)
                except Exception as e:
                    print(f"[{self.source_name}] Error parsing card {i+1}: {e}")
                    continue

        except Exception as e:
            print(f"[{self.source_name}] Error during scrape: {e}")
            import traceback
            traceback.print_exc()

        finally:
            # Close page, context AND browser to free memory
            await page.close()
            await context.close()
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

        return listings

    def _parse_card(self, card: Tag) -> Optional[ScrapedListing]:
        """Parse a single listing card."""
        try:
            # URL - try href attribute or find first link
            url = card.get("href", "")
            if not url:
                link_el = card.select_one("a[href]")
                if link_el:
                    url = link_el.get("href", "")
            if url and not url.startswith("http"):
                url = urljoin(self.base_url, url)

            # Get all text from card for fallback parsing
            all_text = card.get_text(" ", strip=True)

            # Price - try multiple selectors
            price_selectors = [
                ".teaser__price__title",
                ".teaser__price",
                "[class*='price']",
                ".rent",
                "[class*='rent']",
            ]
            rent = None
            for selector in price_selectors:
                price_el = card.select_one(selector)
                if price_el:
                    price_text = price_el.get_text(strip=True)
                    rent_match = re.search(r'\$?([\d,]+)', price_text)
                    if rent_match:
                        rent = int(rent_match.group(1).replace(',', ''))
                        if 100 < rent < 50000:  # Sanity check
                            break
                        rent = None

            # Fallback: find price in all text
            if not rent:
                rent_match = re.search(r'\$\s*([\d,]+)(?:\s*/\s*mo)?', all_text)
                if rent_match:
                    rent = int(rent_match.group(1).replace(',', ''))
                    if not (100 < rent < 50000):
                        rent = None

            # Address - try multiple selectors
            address_selectors = [
                ".teaser__address",
                "[class*='address']",
                ".property-address",
                ".listing-address",
            ]
            address = None
            for selector in address_selectors:
                address_el = card.select_one(selector)
                if address_el:
                    address = address_el.get_text(strip=True)
                    if address and len(address) > 5:
                        break
                    address = None

            # Fallback: find address pattern in text
            if not address:
                addr_match = re.search(
                    r'(\d+\s+[\w\s]+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Way|Blvd|Circle|Cir|Place|Pl)[^,\n]*)',
                    all_text, re.I
                )
                if addr_match:
                    address = addr_match.group(1).strip()

            # Parse city from address
            city, state, zip_code = None, "WA", None
            if address:
                city_match = re.search(
                    r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis|Rainier|Bucoda|DuPont|Steilacoom)',
                    address, re.I
                )
                if city_match:
                    city = city_match.group(1).title()
                # Extract zip code
                zip_match = re.search(r'\b(\d{5})\b', address)
                if zip_match:
                    zip_code = zip_match.group(1)

            # Beds, Baths, SqFt - try multiple approaches
            info_selectors = [
                ".teaser__additional-info span",
                "[class*='info'] span",
                "[class*='specs'] span",
                "[class*='detail'] span",
            ]
            bedrooms, bathrooms, sqft = None, None, None

            for selector in info_selectors:
                info_spans = card.select(selector)
                if info_spans:
                    for span in info_spans:
                        text = span.get_text(strip=True)

                        if "Bed" in text and not bedrooms:
                            bed_match = re.search(r'([\d.]+)', text)
                            if bed_match:
                                bedrooms = int(float(bed_match.group(1)))

                        elif "Bath" in text and not bathrooms:
                            bath_match = re.search(r'([\d.]+)', text)
                            if bath_match:
                                bathrooms = float(bath_match.group(1))

                        elif "SqFt" in text or "sq" in text.lower() and not sqft:
                            sqft_match = re.search(r'([\d,]+)', text)
                            if sqft_match:
                                sqft = int(sqft_match.group(1).replace(',', ''))
                    if bedrooms or bathrooms or sqft:
                        break

            # Fallback: parse from all text
            if not bedrooms:
                bed_match = re.search(r'(\d+)\s*(?:bed|br|bd)', all_text, re.I)
                if bed_match:
                    bedrooms = int(bed_match.group(1))
            if not bathrooms:
                bath_match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba)', all_text, re.I)
                if bath_match:
                    bathrooms = float(bath_match.group(1))
            if not sqft:
                sqft_match = re.search(r'([\d,]+)\s*(?:sq\.?\s*ft|sqft|sf)', all_text, re.I)
                if sqft_match:
                    sqft = int(sqft_match.group(1).replace(',', ''))

            # Image - try multiple selectors
            img_selectors = [
                ".teaser__img img",
                "[class*='image'] img",
                "[class*='photo'] img",
                "img",
            ]
            image_url = None
            for selector in img_selectors:
                img_el = card.select_one(selector)
                if img_el:
                    # Prefer data-src (full image) over src (placeholder)
                    image_url = img_el.get("data-src") or img_el.get("data-lazy-src") or img_el.get("src")
                    # Skip placeholder images
                    if image_url and ("placeholder" in image_url or "/util/" in image_url or "no-image" in image_url or "data:image" in image_url):
                        image_url = img_el.get("data-src") or img_el.get("data-original")
                    if image_url and not image_url.startswith("http"):
                        image_url = urljoin(self.base_url, image_url)
                    if image_url and "placeholder" not in image_url and "data:image" not in image_url:
                        break
                    image_url = None

            # Generate source ID from URL
            source_id = None
            if url:
                slug_match = re.search(r'/listing/(?:cms/)?([^/]+)/?', url)
                if slug_match:
                    source_id = f"bluesummit_{slug_match.group(1)}"

            if not source_id:
                source_id = f"bluesummit_{abs(hash(url or address))}"

            if not address and not rent:
                return None

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=url,
                title=address or "Blue Summit Property",
                address=address,
                city=city,
                state=state,
                zip_code=zip_code,
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=sqft,
                image_url=image_url,
            )

        except Exception as e:
            print(f"[{self.source_name}] Error parsing card: {e}")
            import traceback
            traceback.print_exc()
            return None
