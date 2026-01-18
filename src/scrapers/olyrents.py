"""Scraper for Olympic Landlord & Rental Services (olyrents.com)."""

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, ScrapedListing


class OlyrentsScraper(BaseScraper):
    """Scraper for olyrents.com property listings."""

    def __init__(self, url: str = "https://olyrents.com/properties/olympia/"):
        super().__init__(source_name="olyrents", base_url=url)
        # Add referer header to look like we came from their site
        self.client.headers["Referer"] = "https://olyrents.com/"

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all listings from olyrents.com."""
        listings = []

        try:
            print(f"[olyrents] Fetching page...")
            soup = self.fetch_page(self.base_url)

            print(f"[olyrents] Page title: {soup.title.string if soup.title else 'No title'}")

            listing_elements = self._find_listing_elements(soup)
            print(f"[olyrents] Found {len(listing_elements)} listing elements")

            for element in listing_elements:
                listing = self._parse_listing(element)
                if listing:
                    listings.append(listing)
                    print(f"[olyrents] Parsed: {listing.title[:40]}... - ${listing.rent or 'N/A'}")

            print(f"[olyrents] Found {len(listings)} listings")

        except Exception as e:
            print(f"[olyrents] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    def _find_listing_elements(self, soup: BeautifulSoup) -> list[Tag]:
        """Find all listing elements on the page."""
        # Try the exact selectors from the olyrents site structure
        selectors = [
            ".list_item",  # Main listing container
            ".card.card--flat",  # Card wrapper
            ".card-property",  # Property card
            ".property-listing", ".property-item", ".property-card",
            ".listing-item", ".listing-card", ".rental-listing",
            "[class*='property']", "[class*='listing']",
            "article",
        ]

        for selector in selectors:
            elements = soup.select(selector)
            property_elements = [e for e in elements if self._looks_like_property(e)]
            if property_elements:
                print(f"[olyrents] Using selector: {selector} ({len(property_elements)} matches)")
                return property_elements

        # Fallback: find divs with property-like content
        candidates = []
        all_divs = soup.find_all("div")
        for div in all_divs:
            if len(div.get_text()) < 50:
                continue
            if not self._looks_like_property(div):
                continue

            child_divs = div.find_all("div", recursive=False)
            if len(child_divs) >= 2:
                has_image = div.find("img") is not None
                has_price = bool(re.search(r'\$[\d,]+', div.get_text()))
                if has_image and has_price:
                    candidates.append(div)

        # Deduplicate
        unique = []
        for c in candidates:
            is_nested = any(c in other.descendants for other in candidates if other != c)
            if not is_nested:
                unique.append(c)

        if unique:
            print(f"[olyrents] Found {len(unique)} via structure analysis")
            return unique[:30]

        # Last resort: find links to detail pages
        links = soup.find_all("a", href=re.compile(r"/propert(y|ies)/\d+|/listing/"))
        if links:
            seen = set()
            parents = []
            for link in links:
                parent = link.find_parent(["article", "div", "li"])
                if parent and id(parent) not in seen:
                    seen.add(id(parent))
                    if self._looks_like_property(parent):
                        parents.append(parent)
            if parents:
                print(f"[olyrents] Found {len(parents)} via link patterns")
                return parents

        print("[olyrents] Warning: Could not find listing elements")
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
            address = None
            rent = None

            # Extract image - try olyrents-specific .card-image first
            img_container = element.select_one(".card-image")
            img = img_container.find("img") if img_container else element.find("img")
            if img:
                image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.base_url, image_url)

            # Extract URL from link
            links = element.find_all("a", href=True)
            for link in links:
                href = link.get("href", "")
                if re.search(r"/propert(y|ies)/|/listing/|/\d{4,}", href, re.I):
                    detail_url = urljoin(self.base_url, href)
                    break

            if not detail_url and links:
                detail_url = urljoin(self.base_url, links[0]["href"])

            if not detail_url:
                detail_url = self.base_url

            # Extract rent
            rent = self._extract_rent(element)

            # Extract address
            address = self._extract_address_text(element)

            # Extract specs
            bedrooms, bathrooms, sqft = self._extract_specs(element)

            # City/state/zip
            text = element.get_text()
            zip_code = self.extract_zip_code(text)

            city = None
            state = None
            city_match = re.search(r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino)', text, re.I)
            if city_match:
                city = city_match.group(1).title()
                state = "WA"

            # Generate source ID
            source_id = None
            if detail_url:
                id_match = re.search(r"/(\d{4,})", detail_url)
                if id_match:
                    source_id = id_match.group(1)

            if not source_id:
                source_id = str(abs(hash(detail_url or address or text[:50])))[:12]

            title = address or f"OlyRents Property {source_id}"

            # Description
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
            print(f"[olyrents] Error parsing listing: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _extract_address_text(self, element: Tag) -> Optional[str]:
        """Extract address from element text."""
        # Try olyrents-specific selectors first
        for selector in [
            ".card-property-address-top",
            ".card-property-address-bottom",
            ".card-property-address",
            ".address", ".property-address", ".location", "h2", "h3", ".title"
        ]:
            addr_elem = element.select_one(selector)
            if addr_elem:
                text = self.clean_text(addr_elem.get_text())
                if text and len(text) > 5:
                    return text

        # Also try the title which often has address info
        title_elem = element.select_one(".card-property-title")
        if title_elem:
            text = self.clean_text(title_elem.get_text())
            if text and len(text) > 5:
                return text

        text = element.get_text()
        addr_match = re.search(r'(\d+\s+[\w\s]+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Way|Blvd)[^,\n]*)', text, re.I)
        if addr_match:
            return self.clean_text(addr_match.group(1))

        return None

    def _extract_rent(self, element: Tag) -> Optional[int]:
        """Extract rent amount."""
        # Try olyrents-specific selector first
        for selector in [".card-property-prices", ".price", ".rent", "[class*='price']", "[class*='rent']"]:
            price_elems = element.select(selector)
            for price_elem in price_elems:
                rent = self.parse_rent(price_elem.get_text())
                if rent and 500 <= rent <= 10000:
                    return rent

        text = element.get_text()
        matches = re.findall(r'\$\s*([\d,]+)', text)
        for match in matches:
            rent = self.parse_rent(match)
            if rent and 500 <= rent <= 10000:
                return rent

        return None

    def _extract_specs(self, element: Tag) -> tuple[Optional[int], Optional[float], Optional[int]]:
        """Extract bedrooms, bathrooms, and square footage."""
        bedrooms = None
        bathrooms = None
        sqft = None

        # Try olyrents-specific selectors
        details_elem = element.select_one(".card-property-details")
        area_elem = element.select_one(".card-property-area")

        # Get text from specific elements or fall back to full element text
        details_text = details_elem.get_text().lower() if details_elem else ""
        area_text = area_elem.get_text().lower() if area_elem else ""
        text = element.get_text().lower()

        # Bedrooms - check details first
        for t in [details_text, text]:
            bed_match = re.search(r'(\d+)\s*(?:bed|br|bedroom|bdrm)s?', t)
            if bed_match:
                bedrooms = int(bed_match.group(1))
                break

        # Bathrooms - check details first
        for t in [details_text, text]:
            bath_match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba|bathroom)s?', t)
            if bath_match:
                bathrooms = float(bath_match.group(1))
                break

        # Square footage - check area element first
        for t in [area_text, text]:
            sqft_match = re.search(r'([\d,]+)\s*(?:sq\.?\s*ft|sqft|sf)', t)
            if sqft_match:
                sqft = int(sqft_match.group(1).replace(',', ''))
                break

        return bedrooms, bathrooms, sqft

    def _extract_description(self, element: Tag) -> Optional[str]:
        """Extract listing description."""
        for selector in [".card-property-description", ".description", ".property-description", ".listing-description", "p"]:
            desc_elem = element.select_one(selector)
            if desc_elem:
                desc = self.clean_text(desc_elem.get_text())
                if len(desc) > 20:
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
            for selector in [".description", ".property-description", "[class*='description']", "p"]:
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
            print(f"[olyrents] Error scraping detail page {url}: {e}")

        return details
