"""Scraper for Team NW Property Management (teamnwpm.com).

They use an AppFolio iframe embed, so we scrape the AppFolio listings directly.
"""

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, ScrapedListing


class TeamNWPMScraper(BaseScraper):
    """Scraper for teamnwpm.com property listings via AppFolio."""

    def __init__(self, url: str = "https://capitalproperties.appfolio.com/listings"):
        super().__init__(source_name="teamnwpm", base_url=url)
        # Add referer header
        self.client.headers["Referer"] = "https://teamnwpm.com/"

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all listings from teamnwpm.com."""
        listings = []

        try:
            print(f"[teamnwpm] Fetching page...")
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
            # Don't crash - just return empty list
            if "403" in str(e):
                print("[teamnwpm] Site is blocking requests (403 Forbidden)")

        return listings

    def _find_listing_elements(self, soup: BeautifulSoup) -> list[Tag]:
        """Find all listing elements on the page."""
        # AppFolio listings have IDs like "listing_521"
        selectors = [
            "[id^='listing_']",  # AppFolio listing cards
            ".listing-item",
            ".property-card",
            "[class*='listing']",
        ]

        for selector in selectors:
            elements = soup.select(selector)
            if elements:
                print(f"[teamnwpm] Using selector: {selector} ({len(elements)} matches)")
                return elements

        # Fallback: find divs with dl/dd (description list for specs)
        dl_elements = soup.find_all("dl")
        candidates = []
        for dl in dl_elements:
            parent = dl.find_parent("div")
            if parent:
                container = parent.find_parent("div")
                if container and self._looks_like_property(container):
                    candidates.append(container)

        if candidates:
            seen = set()
            unique = [c for c in candidates if not (id(c) in seen or seen.add(id(c)))]
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
        # Check for Houzez-specific classes first
        classes = " ".join(element.get("class", []))
        if any(x in classes for x in ["item-wrap", "property-item", "houzez", "property-box"]):
            return True

        text = element.get_text().lower()

        has_price = bool(re.search(r'\$[\d,]+', text))
        has_beds = bool(re.search(r'\d+\s*(?:bed|br|bedroom)', text))
        has_baths = bool(re.search(r'\d+\.?\d*\s*(?:bath|ba)', text))
        has_address = bool(re.search(r'\d+\s+\w+\s+(?:st|street|ave|avenue|rd|road|dr|drive|ln|lane|ct|court|way|blvd)', text))
        has_sqft = bool(re.search(r'\d+\s*(?:sq|sf)', text))

        indicators = sum([has_price, has_beds, has_baths, has_address, has_sqft])
        return indicators >= 2

    def _parse_listing(self, element: Tag) -> Optional[ScrapedListing]:
        """Parse a single AppFolio listing element."""
        try:
            image_url = None
            detail_url = None

            # AppFolio structure: image is in .listing-item__image class or a > div > img
            img = element.select_one(".listing-item__image img")
            if not img:
                img = element.select_one(".listing-item__image")
            if not img:
                img = element.select_one("a img")
            if not img:
                img = element.find("img")
            if img:
                # Check various image attributes (lazy loading may use different attrs)
                image_url = (
                    img.get("src") or
                    img.get("data-src") or
                    img.get("data-lazy-src") or
                    img.get("data-original") or
                    img.get("data-image")
                )
                # Debug: show what we found
                print(f"[teamnwpm] Image found - src={img.get('src')}, data-src={img.get('data-src')}")
                # Skip placeholder/loading images
                if image_url and ("placeholder" in image_url.lower() or "loading" in image_url.lower()):
                    image_url = img.get("data-src") or img.get("data-lazy-src")
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.base_url, image_url)

            # Find link to detail page
            link = element.select_one("a[href]")
            if link:
                detail_url = urljoin(self.base_url, link.get("href", ""))
            else:
                detail_url = self.base_url

            # AppFolio uses dl/dd for specs - find all dd elements
            dd_elements = element.select("dl dd")
            rent = None
            sqft = None
            bedrooms = None
            bathrooms = None

            for dd in dd_elements:
                text = dd.get_text().strip()
                # Check what type of data this is
                if "$" in text and not rent:
                    rent = self.parse_rent(text)
                elif "sq" in text.lower() or "ft" in text.lower():
                    sqft = self.parse_sqft(text)
                elif re.search(r'\d+\s*(bed|br|bd)', text.lower()):
                    bedrooms = self.parse_bedrooms(text)
                elif re.search(r'\d+\.?\d*\s*(bath|ba)', text.lower()):
                    bathrooms = self.parse_bathrooms(text)

            # If structured parsing didn't work, try regex on all text
            if not rent or not bedrooms:
                all_text = element.get_text()
                if not rent:
                    rent = self.parse_rent(all_text)
                if not bedrooms:
                    bedrooms = self.parse_bedrooms(all_text)
                if not bathrooms:
                    bathrooms = self.parse_bathrooms(all_text)
                if not sqft:
                    sqft = self.parse_sqft(all_text)

            # AppFolio address is in p > span
            address = None
            addr_elem = element.select_one("p span")
            if addr_elem:
                address = self.clean_text(addr_elem.get_text())

            if not address:
                # Fallback: look for address pattern in text
                text = element.get_text()
                addr_match = re.search(r'(\d+\s+[\w\s]+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Way|Blvd)[^,\n]*)', text, re.I)
                if addr_match:
                    address = self.clean_text(addr_match.group(1))

            # Extract city/state/zip from address
            city = None
            state = None
            zip_code = None
            if address:
                zip_code = self.extract_zip_code(address)
                city_match = re.search(r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis)', address, re.I)
                if city_match:
                    city = city_match.group(1).title()
                    state = "WA"

            # Source ID from element ID (e.g., "listing_521")
            source_id = element.get("id", "")
            if not source_id or not source_id.startswith("listing_"):
                source_id = str(abs(hash(detail_url)))[:12]

            title = address or f"Property {source_id}"

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
                image_url=image_url,
            )

        except Exception as e:
            print(f"[teamnwpm] Error parsing listing: {e}")
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

        bed_match = re.search(r'(\d+)\s*(?:bed|br|bedroom)s?', text)
        if bed_match:
            bedrooms = int(bed_match.group(1))

        bath_match = re.search(r'(\d+\.?\d*)\s*(?:bath|ba|bathroom)s?', text)
        if bath_match:
            bathrooms = float(bath_match.group(1))

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
