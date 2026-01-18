"""Scraper for Team NW Property Management (teamnwpm.com).

Uses Playwright browser to bypass bot protection.
"""

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Tag

from .browser_scraper import BrowserScraper, ScrapedListing


class TeamNWPMScraper(BrowserScraper):
    """Scraper for teamnwpm.com property listings using browser."""

    def __init__(self, url: str = "https://teamnwpm.com/available-homes/"):
        super().__init__(source_name="teamnwpm", base_url=url)

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all listings from teamnwpm.com."""
        listings = []

        try:
            print(f"[teamnwpm] Fetching page with browser...")
            soup = self.fetch_page(self.base_url)

            print(f"[teamnwpm] Page title: {soup.title.string if soup.title else 'No title'}")

            listing_elements = self._find_listing_elements(soup)
            print(f"[teamnwpm] Found {len(listing_elements)} listing elements")

            for element in listing_elements:
                listing = self._parse_listing(element)
                if listing:
                    listings.append(listing)
                    print(f"[teamnwpm] Parsed: {listing.title[:40]}... - ${listing.rent or 'N/A'}")

            print(f"[teamnwpm] Successfully parsed {len(listings)} listings")

        except Exception as e:
            print(f"[teamnwpm] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    def _find_listing_elements(self, soup: BeautifulSoup) -> list[Tag]:
        """Find all listing elements on the page."""
        candidates = []

        # Try common property listing selectors
        selectors = [
            ".property-card", ".listing-card", ".home-card",
            ".property-item", ".listing-item", ".home-item",
            "[class*='property']", "[class*='listing']",
            "main > div > div",
            "article",
        ]

        for selector in selectors:
            elements = soup.select(selector)
            property_elements = [e for e in elements if self._looks_like_property(e)]
            if property_elements:
                print(f"[teamnwpm] Using selector: {selector} ({len(property_elements)} matches)")
                return property_elements

        # Fallback: find divs with dl/dd (description list for specs)
        dl_elements = soup.find_all("dl")
        for dl in dl_elements:
            parent = dl.find_parent("div")
            if parent:
                container = parent.find_parent("div")
                if container and self._looks_like_property(container):
                    candidates.append(container)

        if candidates:
            seen = set()
            unique = []
            for c in candidates:
                c_id = id(c)
                if c_id not in seen:
                    seen.add(c_id)
                    unique.append(c)
            print(f"[teamnwpm] Found {len(unique)} via dl/dd pattern")
            return unique

        # Last resort: find divs with property content
        all_divs = soup.find_all("div")
        property_divs = [d for d in all_divs if self._looks_like_property(d) and len(d.get_text()) > 50]

        unique = []
        for d in property_divs:
            is_nested = any(d in other.descendants for other in property_divs if other != d)
            if not is_nested:
                unique.append(d)

        if unique:
            print(f"[teamnwpm] Found {len(unique)} via content analysis")
            return unique[:20]

        print("[teamnwpm] Warning: Could not find listing elements")
        return []

    def _looks_like_property(self, element: Tag) -> bool:
        """Check if an element looks like a property listing."""
        text = element.get_text().lower()

        has_price = bool(re.search(r'\$[\d,]+', text))
        has_beds = bool(re.search(r'\d+\s*(?:bed|br|bedroom)', text))
        has_baths = bool(re.search(r'\d+\.?\d*\s*(?:bath|ba)', text))
        has_address = bool(re.search(r'\d+\s+\w+\s+(?:st|street|ave|avenue|rd|road|dr|drive|ln|lane|ct|court|way|blvd)', text))
        has_sqft = bool(re.search(r'\d+\s*(?:sq|sf)', text))

        indicators = sum([has_price, has_beds, has_baths, has_address, has_sqft])
        return indicators >= 2

    def _parse_listing(self, element: Tag) -> Optional[ScrapedListing]:
        """Parse a single listing element."""
        try:
            image_url = None
            detail_url = None

            # Find image
            img = element.find("img")
            if img:
                image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.base_url, image_url)

            # Find link
            links = element.find_all("a", href=True)
            for link in links:
                href = link.get("href", "")
                if re.search(r"/(property|home|listing|rental|unit|details)/|\d{4,}", href, re.I):
                    detail_url = urljoin(self.base_url, href)
                    break

            if not detail_url and links:
                detail_url = urljoin(self.base_url, links[0]["href"])

            if not detail_url:
                detail_url = self.base_url

            # Extract rent
            rent = self._extract_rent_from_dl(element)
            if not rent:
                rent = self._extract_rent(element)

            # Extract specs
            bedrooms, bathrooms, sqft = self._extract_specs(element)

            # Extract title/address
            title = self._extract_title(element)
            address, city, state, zip_code = self._extract_address(element, title)

            if not title:
                title = address or "Property"

            # Generate source ID
            source_id = self._extract_source_id(detail_url, element)

            # Extract description
            description = self._extract_description(element)

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=detail_url,
                title=title,
                address=address,
                city=city or "Olympia",
                state=state or "WA",
                zip_code=zip_code,
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=sqft,
                description=description,
                image_url=image_url,
            )

        except Exception as e:
            print(f"[teamnwpm] Error parsing listing: {e}")
            return None

    def _extract_rent_from_dl(self, element: Tag) -> Optional[int]:
        """Extract rent from dl/dd description list."""
        dls = element.find_all("dl")
        for dl in dls:
            dds = dl.find_all("dd")
            for dd in dds:
                text = dd.get_text()
                rent = self.parse_rent(text)
                if rent and 500 <= rent <= 10000:
                    return rent
        return None

    def _extract_rent(self, element: Tag) -> Optional[int]:
        """Extract rent amount."""
        for selector in [".price", ".rent", "[class*='price']", "[class*='rent']"]:
            price_elem = element.select_one(selector)
            if price_elem:
                rent = self.parse_rent(price_elem.get_text())
                if rent:
                    return rent

        text = element.get_text()
        matches = re.findall(r'\$\s*([\d,]+)', text)
        for match in matches:
            rent = self.parse_rent(match)
            if rent and 500 <= rent <= 10000:
                return rent

        return None

    def _extract_source_id(self, url: str, element: Tag) -> str:
        """Extract a unique source ID."""
        id_match = re.search(r"/(\d{4,})|property[_-]?(\d+)|listing[_-]?(\d+)", url, re.I)
        if id_match:
            return id_match.group(1) or id_match.group(2) or id_match.group(3)

        for attr in ["data-id", "data-listing-id", "data-property-id", "id"]:
            val = element.get(attr)
            if val and re.search(r"\d+", str(val)):
                return str(val)

        return str(abs(hash(url)))[:12]

    def _extract_title(self, element: Tag) -> Optional[str]:
        """Extract listing title."""
        for selector in [".property-title", ".listing-title", ".address", "h2", "h3", "h4", ".title"]:
            title_elem = element.select_one(selector)
            if title_elem:
                text = self.clean_text(title_elem.get_text())
                if text and len(text) > 5 and not text.startswith("$"):
                    return text

        text = element.get_text()
        addr_match = re.search(r'(\d+\s+[\w\s]+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Way|Blvd)[^,]*)', text, re.I)
        if addr_match:
            return self.clean_text(addr_match.group(1))

        return None

    def _extract_specs(self, element: Tag) -> tuple[Optional[int], Optional[float], Optional[int]]:
        """Extract bedrooms, bathrooms, and square footage."""
        text = element.get_text().lower()
        bedrooms = None
        bathrooms = None
        sqft = None

        # Bedrooms
        bed_match = re.search(r'(\d+)\s*(?:bed|br|bedroom)s?', text)
        if bed_match:
            bedrooms = int(bed_match.group(1))

        # Bathrooms
        bath_match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba|bathroom)s?', text)
        if bath_match:
            bathrooms = float(bath_match.group(1))

        # Square footage
        sqft_match = re.search(r'([\d,]+)\s*(?:sq\.?\s*ft|sqft|sf)', text)
        if sqft_match:
            sqft = int(sqft_match.group(1).replace(',', ''))

        return bedrooms, bathrooms, sqft

    def _extract_address(self, element: Tag, title: str) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Extract address components."""
        address = None
        city = None
        state = None
        zip_code = None

        for selector in [".address", ".property-address", ".location", "[class*='address']"]:
            addr_elem = element.select_one(selector)
            if addr_elem:
                address = self.clean_text(addr_elem.get_text())
                break

        if not address and title:
            address = title

        text = element.get_text()
        zip_code = self.extract_zip_code(text)

        city_pattern = r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis)[\s,]+([A-Z]{2})?'
        cs_match = re.search(city_pattern, text, re.I)
        if cs_match:
            city = cs_match.group(1).title()
            state = cs_match.group(2).upper() if cs_match.group(2) else "WA"

        return address, city, state, zip_code

    def _extract_description(self, element: Tag) -> Optional[str]:
        """Extract listing description."""
        for selector in [".description", ".property-description", ".excerpt", ".summary", "p"]:
            desc_elem = element.select_one(selector)
            if desc_elem:
                desc = self.clean_text(desc_elem.get_text())
                if len(desc) > 30:
                    return desc[:500]
        return None

    def scrape_detail_page(self, url: str) -> dict:
        """Scrape additional details from individual listing page."""
        details = {
            "bedrooms": None,
            "bathrooms": None,
            "sqft": None,
            "description": None,
            "features": [],
        }

        try:
            soup = self.fetch_page(url)
            text = soup.get_text()
            text_lower = text.lower()

            # Extract specs
            bed_match = re.search(r'(\d+)\s*(?:bed|br|bedroom)s?', text_lower)
            if bed_match:
                details["bedrooms"] = int(bed_match.group(1))

            bath_match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba|bathroom)s?', text_lower)
            if bath_match:
                details["bathrooms"] = float(bath_match.group(1))

            sqft_match = re.search(r'([\d,]+)\s*(?:sq\.?\s*ft|sqft|sf|square feet)', text_lower)
            if sqft_match:
                details["sqft"] = int(sqft_match.group(1).replace(',', ''))

            # Description
            for selector in [".description", ".property-description", "[class*='description']", ".content", "p"]:
                elems = soup.select(selector)
                for elem in elems:
                    desc = self.clean_text(elem.get_text())
                    if len(desc) > 50:
                        details["description"] = desc[:1000]
                        break
                if details["description"]:
                    break

            # Keywords
            details["features"] = self.extract_keywords(text)

        except Exception as e:
            print(f"[teamnwpm] Error scraping detail page {url}: {e}")

        return details
