"""Scraper for Team NW Property Management (teamnwpm.com).

Based on XPath analysis from user:
- Listings are in main > div[2] containers
- Image/link: div[1]/a/div/img
- Property info card: div[2]
- Price: div[2]/div/dl/div[1]/dd (uses dl/dd description list)
"""

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

            print(f"[teamnwpm] Page title: {soup.title.string if soup.title else 'No title'}")

            # Based on XPath: main/div[2]/div[2] structure
            listing_elements = self._find_listing_elements(soup)
            print(f"[teamnwpm] Found {len(listing_elements)} listing elements")

            for i, element in enumerate(listing_elements):
                listing = self._parse_listing(element)
                if listing:
                    listings.append(listing)
                    print(f"[teamnwpm] Parsed: {listing.title[:50]}... - ${listing.rent or 'N/A'}")

            print(f"[teamnwpm] Successfully parsed {len(listings)} listings")

        except Exception as e:
            print(f"[teamnwpm] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    def _find_listing_elements(self, soup: BeautifulSoup) -> list[Tag]:
        """Find all listing elements on the page.

        XPath structure shows: main/div[2]/div[2]/div[1] for each listing
        Each property appears to be a div containing image div and info div.
        """
        # Find main element
        main = soup.find("main")
        if not main:
            main = soup  # Fallback to whole document

        # Look for containers with property-like content
        # The XPath div[2]/div[2] suggests nested div structure
        # Look for div containers that have both images and price info

        candidates = []

        # Try to find property containers
        # Common patterns: grid items, cards, listing containers
        selectors = [
            # Main content area patterns
            "main > div > div",
            # Card/grid patterns
            ".property-card", ".listing-card", ".home-card",
            ".property-item", ".listing-item", ".home-item",
            # Generic containers with property content
            "[class*='property']", "[class*='listing']", "[class*='home']",
        ]

        for selector in selectors:
            elements = soup.select(selector)
            # Filter to those that look like property listings
            property_elements = [e for e in elements if self._looks_like_property(e)]
            if property_elements:
                print(f"[teamnwpm] Using selector: {selector} ({len(property_elements)} matches)")
                return property_elements

        # Fallback: find divs that have the dl/dd structure (description list for specs)
        dl_elements = soup.find_all("dl")
        for dl in dl_elements:
            # Get parent container that includes both image and specs
            parent = dl.find_parent("div")
            if parent:
                # Go up to find the full listing container
                container = parent.find_parent("div")
                if container and self._looks_like_property(container):
                    candidates.append(container)

        if candidates:
            # Deduplicate
            seen = set()
            unique = []
            for c in candidates:
                c_id = id(c)
                if c_id not in seen:
                    seen.add(c_id)
                    unique.append(c)
            print(f"[teamnwpm] Found {len(unique)} via dl/dd pattern")
            return unique

        # Last resort: find all divs with property-like content
        all_divs = soup.find_all("div")
        property_divs = [d for d in all_divs if self._looks_like_property(d) and len(d.get_text()) > 50]

        # Deduplicate by removing nested elements
        unique = []
        for d in property_divs:
            is_nested = any(d in other.descendants for other in property_divs if other != d)
            if not is_nested:
                unique.append(d)

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
        """Parse a single listing element.

        XPath structure:
        - div[1]/a/div/img = image and link
        - div[2]/div/dl/div/dd = specs using description list
        """
        try:
            # Get child divs - typically div[1] is image, div[2] is info
            child_divs = element.find_all("div", recursive=False)

            image_url = None
            detail_url = None

            # Try to find image and link
            # Look for img and anchor elements
            img = element.find("img")
            if img:
                image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.base_url, image_url)

            # Find primary link
            links = element.find_all("a", href=True)
            for link in links:
                href = link.get("href", "")
                # Prefer links that look like detail pages
                if re.search(r"/(property|home|listing|rental|unit|details)/|\d{4,}", href, re.I):
                    detail_url = urljoin(self.base_url, href)
                    break

            # Fallback to first link
            if not detail_url and links:
                detail_url = urljoin(self.base_url, links[0]["href"])

            if not detail_url:
                detail_url = self.base_url

            # Extract rent from dl/dd structure (description list)
            rent = self._extract_rent_from_dl(element)
            if not rent:
                rent = self._extract_rent(element)

            # Extract specs
            bedrooms, bathrooms, sqft = self._extract_specs(element)

            # Extract address/title
            title = self._extract_title(element)
            address, city, state, zip_code = self._extract_address(element, title)

            # Use address as title if no title found
            if not title:
                title = address or f"Property"

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
        """Extract rent from dl/dd description list structure.

        XPath: div/dl/div[1]/dd for price
        """
        # Find dl (description list) elements
        dls = element.find_all("dl")
        for dl in dls:
            # Look for price in dd elements
            dds = dl.find_all("dd")
            for dd in dds:
                text = dd.get_text()
                rent = self.parse_rent(text)
                if rent and 500 <= rent <= 10000:
                    return rent

            # Also check dt/dd pairs
            dts = dl.find_all("dt")
            for dt in dts:
                dt_text = dt.get_text().lower()
                if "rent" in dt_text or "price" in dt_text or "$" in dt_text:
                    # Get next sibling dd
                    dd = dt.find_next_sibling("dd")
                    if dd:
                        rent = self.parse_rent(dd.get_text())
                        if rent:
                            return rent

        return None

    def _extract_rent(self, element: Tag) -> Optional[int]:
        """Extract rent amount (fallback method)."""
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

    def _extract_specs(self, element: Tag) -> tuple[Optional[int], Optional[float], Optional[int]]:
        """Extract bedrooms, bathrooms, and square footage."""
        text = element.get_text().lower()

        bedrooms = None
        bathrooms = None
        sqft = None

        # Check dl/dd structure first
        dls = element.find_all("dl")
        for dl in dls:
            dl_text = dl.get_text().lower()

            # Bedrooms
            bed_match = re.search(r'(\d+)\s*(?:bed|br|bedroom)s?', dl_text)
            if bed_match:
                bedrooms = int(bed_match.group(1))

            # Bathrooms
            bath_match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba|bathroom)s?', dl_text)
            if bath_match:
                bathrooms = float(bath_match.group(1))

            # Square footage
            sqft_match = re.search(r'([\d,]+)\s*(?:sq\.?\s*ft|sqft|sf)', dl_text)
            if sqft_match:
                sqft = int(sqft_match.group(1).replace(',', ''))

        # Fallback to full element text
        if not bedrooms:
            bed_patterns = [
                r'(\d+)\s*(?:bed|br|bedroom)s?',
                r'(\d+)\s*bd',
                r'beds?[:\s]*(\d+)',
            ]
            for pattern in bed_patterns:
                match = re.search(pattern, text)
                if match:
                    bedrooms = int(match.group(1))
                    break

        if not bathrooms:
            bath_patterns = [
                r'(\d+\.?\d*)\s*(?:bath|ba|bathroom)s?',
                r'baths?[:\s]*(\d+\.?\d*)',
            ]
            for pattern in bath_patterns:
                match = re.search(pattern, text)
                if match:
                    bathrooms = float(match.group(1))
                    break

        if not sqft:
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

            # Extract specs from dl/dd structure if present
            dls = soup.find_all("dl")
            for dl in dls:
                dl_text = dl.get_text().lower()

                bed_match = re.search(r'(\d+)\s*(?:bed|br|bedroom)s?', dl_text)
                if bed_match and not details["bedrooms"]:
                    details["bedrooms"] = int(bed_match.group(1))

                bath_match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba|bathroom)s?', dl_text)
                if bath_match and not details["bathrooms"]:
                    details["bathrooms"] = float(bath_match.group(1))

                sqft_match = re.search(r'([\d,]+)\s*(?:sq\.?\s*ft|sqft|sf)', dl_text)
                if sqft_match and not details["sqft"]:
                    details["sqft"] = int(sqft_match.group(1).replace(',', ''))

            # Fallback to full page text
            if not details["bedrooms"]:
                bed_match = re.search(r'(\d+)\s*(?:bed|br|bedroom)s?', text_lower)
                if bed_match:
                    details["bedrooms"] = int(bed_match.group(1))

            if not details["bathrooms"]:
                bath_match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba|bathroom)s?', text_lower)
                if bath_match:
                    details["bathrooms"] = float(bath_match.group(1))

            if not details["sqft"]:
                sqft_match = re.search(r'([\d,]+)\s*(?:sq\.?\s*ft|sqft|sf|square feet)', text_lower)
                if sqft_match:
                    details["sqft"] = int(sqft_match.group(1).replace(',', ''))

            # Look for description
            for selector in [".description", ".property-description", "[class*='description']", ".content", "p"]:
                elems = soup.select(selector)
                for elem in elems:
                    desc = self.clean_text(elem.get_text())
                    if len(desc) > 50:
                        details["description"] = desc[:1000]
                        break
                if details["description"]:
                    break

            # Extract keywords/features
            details["features"] = self.extract_keywords(text)

        except Exception as e:
            print(f"[teamnwpm] Error scraping detail page {url}: {e}")

        return details
