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

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all listings from olyrents.com."""
        listings = []

        try:
            soup = self.fetch_page(self.base_url)

            # Debug: uncomment to see the HTML structure
            # print(soup.prettify()[:5000])

            # Try multiple common selectors for property listings
            listing_elements = self._find_listing_elements(soup)

            for element in listing_elements:
                listing = self._parse_listing(element)
                if listing:
                    listings.append(listing)

            print(f"[olyrents] Found {len(listings)} listings")

        except Exception as e:
            print(f"[olyrents] Error scraping: {e}")

        return listings

    def _find_listing_elements(self, soup: BeautifulSoup) -> list[Tag]:
        """Find all listing elements on the page."""
        # Try common selectors used by property management sites
        selectors = [
            ".property-listing",
            ".property-item",
            ".listing-item",
            ".property-card",
            ".rental-listing",
            "article.property",
            ".property",
            "[data-property]",
            ".card.property",
            ".listing",
            # AppFolio (common property management software) selectors
            ".listing-item__inner",
            ".js-listing-item",
        ]

        for selector in selectors:
            elements = soup.select(selector)
            if elements:
                print(f"[olyrents] Found listings using selector: {selector}")
                return elements

        # Fallback: look for links to property detail pages
        links = soup.find_all("a", href=re.compile(r"/propert(y|ies)/\d+|/listing/"))
        if links:
            print(f"[olyrents] Found {len(links)} property links")
            # Get unique parent containers
            parents = []
            seen = set()
            for link in links:
                parent = link.find_parent(["article", "div", "li"])
                if parent and id(parent) not in seen:
                    seen.add(id(parent))
                    parents.append(parent)
            return parents

        print("[olyrents] Warning: Could not find listing elements. Page structure may have changed.")
        return []

    def _parse_listing(self, element: Tag) -> Optional[ScrapedListing]:
        """Parse a single listing element."""
        try:
            # Extract URL
            link = element.find("a", href=True)
            if not link:
                return None

            url = urljoin(self.base_url, link["href"])

            # Generate source ID from URL
            source_id = re.search(r"/(\d+)", url)
            source_id = source_id.group(1) if source_id else url.split("/")[-1]

            # Extract title/address
            title = self._extract_title(element)
            if not title:
                title = f"Property {source_id}"

            # Extract price
            rent = self._extract_rent(element)

            # Extract bed/bath/sqft
            bedrooms, bathrooms, sqft = self._extract_specs(element)

            # Extract address components
            address, city, state, zip_code = self._extract_address(element, title)

            # Extract description
            description = self._extract_description(element)

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=url,
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
            )

        except Exception as e:
            print(f"[olyrents] Error parsing listing: {e}")
            return None

    def _extract_title(self, element: Tag) -> Optional[str]:
        """Extract listing title."""
        # Try common title selectors
        for selector in [".property-title", ".listing-title", "h2", "h3", ".title", ".address"]:
            title_elem = element.select_one(selector)
            if title_elem:
                return self.clean_text(title_elem.get_text())
        return None

    def _extract_rent(self, element: Tag) -> Optional[int]:
        """Extract rent amount."""
        # Look for price elements
        for selector in [".price", ".rent", ".listing-price", ".property-price", ".amount"]:
            price_elem = element.select_one(selector)
            if price_elem:
                rent = self.parse_rent(price_elem.get_text())
                if rent:
                    return rent

        # Fallback: search text for dollar amounts
        text = element.get_text()
        match = re.search(r'\$\s*([\d,]+)', text)
        if match:
            return self.parse_rent(match.group(1))

        return None

    def _extract_specs(self, element: Tag) -> tuple[Optional[int], Optional[float], Optional[int]]:
        """Extract bedrooms, bathrooms, and square footage."""
        bedrooms = None
        bathrooms = None
        sqft = None

        text = element.get_text().lower()

        # Bedrooms
        bed_match = re.search(r'(\d+)\s*(?:bed|br|bedroom)', text)
        if bed_match:
            bedrooms = int(bed_match.group(1))

        # Bathrooms
        bath_match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba|bathroom)', text)
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

        # Try to find address element
        for selector in [".address", ".property-address", ".location", ".listing-address"]:
            addr_elem = element.select_one(selector)
            if addr_elem:
                addr_text = self.clean_text(addr_elem.get_text())
                address = addr_text
                break

        # If no specific address found, use title
        if not address:
            address = title

        # Extract ZIP code
        text = element.get_text()
        zip_code = self.extract_zip_code(text)

        # Look for city/state pattern
        cs_match = re.search(r'([\w\s]+),\s*([A-Z]{2})', text)
        if cs_match:
            city = cs_match.group(1).strip()
            state = cs_match.group(2)

        return address, city, state, zip_code

    def _extract_description(self, element: Tag) -> Optional[str]:
        """Extract listing description."""
        for selector in [".description", ".property-description", ".listing-description", "p"]:
            desc_elem = element.select_one(selector)
            if desc_elem:
                desc = self.clean_text(desc_elem.get_text())
                if len(desc) > 20:  # Minimum length for a real description
                    return desc
        return None
