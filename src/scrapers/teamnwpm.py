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

            # Debug: print a snippet of the HTML to help identify structure
            print(f"[teamnwpm] Page title: {soup.title.string if soup.title else 'No title'}")

            listing_elements = self._find_listing_elements(soup)
            print(f"[teamnwpm] Found {len(listing_elements)} listing elements")

            for i, element in enumerate(listing_elements):
                listing = self._parse_listing(element)
                if listing:
                    listings.append(listing)
                    print(f"[teamnwpm] Parsed: {listing.title} - ${listing.rent or 'N/A'} - {listing.url}")

            print(f"[teamnwpm] Successfully parsed {len(listings)} listings")

        except Exception as e:
            print(f"[teamnwpm] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    def _find_listing_elements(self, soup: BeautifulSoup) -> list[Tag]:
        """Find all listing elements on the page."""

        # Common property listing selectors - try most specific first
        selectors = [
            # Rent Manager / property management software patterns
            ".rm-property", ".rentmanager-listing", ".listing-item",
            # WordPress theme patterns
            ".property-listing", ".property-item", ".property-card",
            ".rental-listing", ".home-listing", ".available-home",
            # Generic patterns
            ".property", ".listing", ".rental",
            # Card layouts
            ".card", "article",
        ]

        for selector in selectors:
            elements = soup.select(selector)
            # Filter to those that look like property listings
            property_elements = [e for e in elements if self._looks_like_property(e)]
            if property_elements:
                print(f"[teamnwpm] Using selector: {selector} ({len(property_elements)} matches)")
                return property_elements

        # Fallback: find all links that look like property detail pages
        all_links = soup.find_all("a", href=True)
        property_links = []
        seen_hrefs = set()

        for link in all_links:
            href = link.get("href", "")
            # Look for property detail page patterns
            if re.search(r"/(property|home|listing|rental|unit|details)/|/\d{4,}|property[_-]?\d+", href, re.I):
                if href not in seen_hrefs:
                    seen_hrefs.add(href)
                    # Get the parent container
                    parent = link.find_parent(["article", "div", "li", "section"])
                    if parent and self._looks_like_property(parent):
                        property_links.append(parent)

        if property_links:
            print(f"[teamnwpm] Found {len(property_links)} via link patterns")
            return property_links

        # Last resort: look for any div/article with property-like content
        containers = soup.find_all(["div", "article", "li"])
        property_containers = [c for c in containers if self._looks_like_property(c) and len(c.get_text()) > 50]

        # Deduplicate by removing nested elements
        unique = []
        for c in property_containers:
            is_nested = any(c in other.descendants for other in property_containers if other != c)
            if not is_nested:
                unique.append(c)

        if unique:
            print(f"[teamnwpm] Found {len(unique)} via content analysis")
            return unique[:20]  # Limit to prevent too many false positives

        print("[teamnwpm] Warning: Could not find listing elements")
        return []

    def _looks_like_property(self, element: Tag) -> bool:
        """Check if an element looks like a property listing."""
        text = element.get_text().lower()

        # Must have property-like content
        has_price = bool(re.search(r'\$[\d,]+', text))
        has_beds = bool(re.search(r'\d+\s*(?:bed|br|bedroom)', text))
        has_baths = bool(re.search(r'\d+\.?\d*\s*(?:bath|ba)', text))
        has_address = bool(re.search(r'\d+\s+\w+\s+(?:st|street|ave|avenue|rd|road|dr|drive|ln|lane|ct|court|way|blvd)', text))
        has_sqft = bool(re.search(r'\d+\s*(?:sq|sf)', text))

        # Need at least 2 property indicators
        indicators = sum([has_price, has_beds, has_baths, has_address, has_sqft])
        return indicators >= 2

    def _parse_listing(self, element: Tag) -> Optional[ScrapedListing]:
        """Parse a single listing element."""
        try:
            # Extract URL - look for the main link
            url = self._extract_url(element)

            # Generate source ID from URL or content
            source_id = self._extract_source_id(url, element)

            # Extract all the details
            title = self._extract_title(element)
            rent = self._extract_rent(element)
            bedrooms, bathrooms, sqft = self._extract_specs(element)
            address, city, state, zip_code = self._extract_address(element, title)
            description = self._extract_description(element)
            image_url = self._extract_image(element)

            # Use address as title if no title found
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
                image_url=image_url,
            )

        except Exception as e:
            print(f"[teamnwpm] Error parsing listing: {e}")
            return None

    def _extract_url(self, element: Tag) -> str:
        """Extract the listing detail URL."""
        # Look for links that go to detail pages
        links = element.find_all("a", href=True)

        for link in links:
            href = link.get("href", "")
            # Prefer links that look like detail pages
            if re.search(r"/(property|home|listing|rental|unit|details)/|/\d{4,}", href, re.I):
                return urljoin(self.base_url, href)

        # Fallback to first link
        if links:
            return urljoin(self.base_url, links[0]["href"])

        return self.base_url

    def _extract_source_id(self, url: str, element: Tag) -> str:
        """Extract a unique source ID."""
        # Try to get ID from URL
        id_match = re.search(r"/(\d{4,})|property[_-]?(\d+)|listing[_-]?(\d+)", url, re.I)
        if id_match:
            return id_match.group(1) or id_match.group(2) or id_match.group(3)

        # Try data attributes
        for attr in ["data-id", "data-listing-id", "data-property-id", "id"]:
            val = element.get(attr)
            if val and re.search(r"\d+", str(val)):
                return str(val)

        # Generate from URL hash
        return str(abs(hash(url)))[:12]

    def _extract_title(self, element: Tag) -> Optional[str]:
        """Extract listing title."""
        # Try specific title selectors
        for selector in [".property-title", ".listing-title", ".address", "h2", "h3", "h4", ".title"]:
            title_elem = element.select_one(selector)
            if title_elem:
                text = self.clean_text(title_elem.get_text())
                # Skip if it's just a price or very short
                if text and len(text) > 5 and not text.startswith("$"):
                    return text

        # Look for address pattern in any text
        text = element.get_text()
        addr_match = re.search(r'(\d+\s+[\w\s]+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Way|Blvd)[^,]*)', text, re.I)
        if addr_match:
            return self.clean_text(addr_match.group(1))

        return None

    def _extract_rent(self, element: Tag) -> Optional[int]:
        """Extract rent amount."""
        # Look for price elements
        for selector in [".price", ".rent", ".listing-price", ".property-price", "[class*='price']", "[class*='rent']"]:
            price_elem = element.select_one(selector)
            if price_elem:
                rent = self.parse_rent(price_elem.get_text())
                if rent:
                    return rent

        # Find all dollar amounts
        text = element.get_text()
        matches = re.findall(r'\$\s*([\d,]+)', text)

        # Filter to reasonable rent amounts (exclude deposits, application fees)
        for match in matches:
            rent = self.parse_rent(match)
            if rent and 500 <= rent <= 10000:
                return rent

        return None

    def _extract_specs(self, element: Tag) -> tuple[Optional[int], Optional[float], Optional[int]]:
        """Extract bedrooms, bathrooms, and square footage."""
        text = element.get_text().lower()

        bedrooms = None
        bathrooms = None
        sqft = None

        # Bedrooms - try multiple patterns
        bed_patterns = [
            r'(\d+)\s*(?:bed|br|bedroom)s?',
            r'(\d+)\s*bd',
            r'beds?[:\s]*(\d+)',
            r'bedroom[:\s]*(\d+)',
        ]
        for pattern in bed_patterns:
            match = re.search(pattern, text)
            if match:
                bedrooms = int(match.group(1))
                break

        # Bathrooms
        bath_patterns = [
            r'(\d+\.?\d*)\s*(?:bath|ba|bathroom)s?',
            r'baths?[:\s]*(\d+\.?\d*)',
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

        # Try address selectors
        for selector in [".address", ".property-address", ".location", "[class*='address']"]:
            addr_elem = element.select_one(selector)
            if addr_elem:
                address = self.clean_text(addr_elem.get_text())
                break

        if not address and title:
            address = title

        text = element.get_text()

        # Extract ZIP code
        zip_code = self.extract_zip_code(text)

        # City pattern for local area
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
                    return desc[:500]  # Truncate long descriptions
        return None

    def _extract_image(self, element: Tag) -> Optional[str]:
        """Extract listing image URL."""
        # Look for img tags
        img = element.find("img")
        if img:
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if src:
                return urljoin(self.base_url, src)

        # Check for background image in style
        for elem in element.find_all(style=True):
            style = elem.get("style", "")
            bg_match = re.search(r'background(?:-image)?:\s*url\(["\']?([^"\')\s]+)', style)
            if bg_match:
                return urljoin(self.base_url, bg_match.group(1))

        return None
