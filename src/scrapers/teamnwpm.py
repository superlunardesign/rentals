"""Scraper for Team NW Property Management (teamnwpm.com)."""

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, ScrapedListing


class TeamNWPMScraper(BaseScraper):
    """Scraper for teamnwpm.com property listings."""

    def __init__(self, url: str = "https://teamnwpm.com/available-homes/"):
        super().__init__(source_name="teamnwpm", base_url=url)

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all listings from teamnwpm.com."""
        listings = []

        try:
            soup = self.fetch_page(self.base_url)

            # Debug: uncomment to see the HTML structure
            # print(soup.prettify()[:5000])

            listing_elements = self._find_listing_elements(soup)

            for element in listing_elements:
                listing = self._parse_listing(element)
                if listing:
                    listings.append(listing)

            print(f"[teamnwpm] Found {len(listings)} listings")

        except Exception as e:
            print(f"[teamnwpm] Error scraping: {e}")

        return listings

    def _find_listing_elements(self, soup: BeautifulSoup) -> list[Tag]:
        """Find all listing elements on the page."""
        # Common selectors for property listings
        selectors = [
            ".property-listing",
            ".property-item",
            ".listing-item",
            ".property-card",
            ".rental-listing",
            ".property",
            ".home-listing",
            ".available-home",
            # Rent Manager / property management software patterns
            ".rm-property",
            ".rentmanager-listing",
            # WordPress theme patterns
            ".property-box",
            ".listing-box",
            "[class*='property']",
        ]

        for selector in selectors:
            elements = soup.select(selector)
            if elements:
                print(f"[teamnwpm] Found listings using selector: {selector}")
                return elements

        # Look for listing containers by examining the page structure
        # Many sites use cards/grid layouts
        cards = soup.select(".card, .grid-item, article")
        if cards:
            # Filter to only those that look like property listings
            property_cards = [c for c in cards if self._looks_like_property(c)]
            if property_cards:
                print(f"[teamnwpm] Found {len(property_cards)} property cards")
                return property_cards

        # Fallback: look for links containing property patterns
        links = soup.find_all("a", href=re.compile(r"/(property|home|listing|rental)/", re.I))
        if links:
            parents = []
            seen = set()
            for link in links:
                parent = link.find_parent(["article", "div", "li", "section"])
                if parent and id(parent) not in seen:
                    seen.add(id(parent))
                    parents.append(parent)
            if parents:
                print(f"[teamnwpm] Found {len(parents)} listings via links")
                return parents

        print("[teamnwpm] Warning: Could not find listing elements")
        return []

    def _looks_like_property(self, element: Tag) -> bool:
        """Check if an element looks like a property listing."""
        text = element.get_text().lower()
        # Must have at least a price OR bed/bath info
        has_price = bool(re.search(r'\$[\d,]+', text))
        has_beds = bool(re.search(r'\d+\s*(?:bed|br)', text))
        return has_price or has_beds

    def _parse_listing(self, element: Tag) -> Optional[ScrapedListing]:
        """Parse a single listing element."""
        try:
            # Extract URL
            link = element.find("a", href=True)
            url = urljoin(self.base_url, link["href"]) if link else self.base_url

            # Generate source ID
            source_id = re.search(r"/(\d+)|property[_-]?(\d+)", url, re.I)
            if source_id:
                source_id = source_id.group(1) or source_id.group(2)
            else:
                source_id = str(hash(url))[:12]

            # Extract details
            title = self._extract_title(element)
            rent = self._extract_rent(element)
            bedrooms, bathrooms, sqft = self._extract_specs(element)
            address, city, state, zip_code = self._extract_address(element, title)
            description = self._extract_description(element)

            if not title:
                title = address or f"Property {source_id}"

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
            print(f"[teamnwpm] Error parsing listing: {e}")
            return None

    def _extract_title(self, element: Tag) -> Optional[str]:
        """Extract listing title."""
        for selector in [".property-title", ".listing-title", "h2", "h3", "h4", ".title", ".address"]:
            title_elem = element.select_one(selector)
            if title_elem:
                text = self.clean_text(title_elem.get_text())
                if text and len(text) > 3:
                    return text
        return None

    def _extract_rent(self, element: Tag) -> Optional[int]:
        """Extract rent amount."""
        for selector in [".price", ".rent", ".listing-price", ".property-price", "[class*='price']", "[class*='rent']"]:
            price_elem = element.select_one(selector)
            if price_elem:
                rent = self.parse_rent(price_elem.get_text())
                if rent:
                    return rent

        # Fallback: find dollar amounts in text
        text = element.get_text()
        matches = re.findall(r'\$\s*([\d,]+)', text)
        for match in matches:
            rent = self.parse_rent(match)
            if rent and rent > 500:  # Filter out deposits/fees typically shown
                return rent

        return None

    def _extract_specs(self, element: Tag) -> tuple[Optional[int], Optional[float], Optional[int]]:
        """Extract bedrooms, bathrooms, and square footage."""
        bedrooms = None
        bathrooms = None
        sqft = None

        text = element.get_text().lower()

        # Bedrooms - various formats
        bed_patterns = [
            r'(\d+)\s*(?:bed|br|bedroom)',
            r'(\d+)\s*bd',
            r'beds?:\s*(\d+)',
        ]
        for pattern in bed_patterns:
            match = re.search(pattern, text)
            if match:
                bedrooms = int(match.group(1))
                break

        # Bathrooms
        bath_patterns = [
            r'(\d+\.?\d*)\s*(?:bath|ba|bathroom)',
            r'baths?:\s*(\d+\.?\d*)',
        ]
        for pattern in bath_patterns:
            match = re.search(pattern, text)
            if match:
                bathrooms = float(match.group(1))
                break

        # Square footage
        sqft_patterns = [
            r'([\d,]+)\s*(?:sq\.?\s*ft|sqft|sf)',
            r'([\d,]+)\s*square\s*feet',
        ]
        for pattern in sqft_patterns:
            match = re.search(pattern, text)
            if match:
                sqft = int(match.group(1).replace(',', ''))
                break

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

        # City, State pattern
        cs_match = re.search(r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino)[\s,]+([A-Z]{2})', text, re.I)
        if cs_match:
            city = cs_match.group(1).title()
            state = cs_match.group(2).upper()

        return address, city, state, zip_code

    def _extract_description(self, element: Tag) -> Optional[str]:
        """Extract listing description."""
        for selector in [".description", ".property-description", ".excerpt", ".summary", "p"]:
            desc_elem = element.select_one(selector)
            if desc_elem:
                desc = self.clean_text(desc_elem.get_text())
                if len(desc) > 30:
                    return desc
        return None
