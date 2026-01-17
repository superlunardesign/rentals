"""Scraper for AMH (American Homes 4 Rent) - amh.com.

Based on XPath analysis from user:
- Listings are in ul > li elements
- Image/link: li/div/div[1]/div/a/div/img
- Address: li/div/div[2]/a
- Price: li/div/div[2]/div[1]/div[1]/span[1]
"""

import re
import json
from typing import Optional
from urllib.parse import urlencode, urljoin

from .base import BaseScraper, ScrapedListing


class AMHScraper(BaseScraper):
    """Scraper for amh.com property listings."""

    def __init__(self, url: str = "https://www.amh.com/query?criteria=Tumwater%2C+WA"):
        super().__init__(source_name="amh", base_url=url)

    def scrape(self) -> list[ScrapedListing]:
        """Scrape listings from AMH."""
        listings = []

        try:
            soup = self.fetch_page(self.base_url)
            print(f"[amh] Page title: {soup.title.string if soup.title else 'No title'}")

            # Try to find embedded JSON data first (React apps often embed data)
            json_listings = self._extract_json_data(soup)
            if json_listings:
                listings.extend(json_listings)
                print(f"[amh] Found {len(listings)} listings via JSON")
                return listings

            # Fallback to HTML parsing with XPath-based selectors
            # Based on XPath: listings are in ul > li elements
            all_lis = soup.select("ul li")

            # Filter to property listings (those with price patterns)
            property_lis = []
            for li in all_lis:
                text = li.get_text()
                # Must have a price like $X,XXX and look like a property
                if re.search(r'\$[\d,]+', text) and re.search(r'bed|bath|sq\s*ft', text, re.I):
                    property_lis.append(li)

            print(f"[amh] Found {len(property_lis)} property li elements")

            for li in property_lis:
                listing = self._parse_listing_li(li)
                if listing:
                    listings.append(listing)
                    print(f"[amh] Parsed: {listing.title[:50]}... - ${listing.rent or 'N/A'}")

        except Exception as e:
            print(f"[amh] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        print(f"[amh] Total: {len(listings)} listings")
        return listings

    def _extract_json_data(self, soup) -> list[ScrapedListing]:
        """Try to extract listings from embedded JSON (React hydration data)."""
        listings = []

        try:
            scripts = soup.find_all("script")
            for script in scripts:
                if not script.string:
                    continue

                # Look for Next.js/React data
                if "__NEXT_DATA__" in script.string or "properties" in script.string.lower():
                    # Try to find JSON object
                    json_patterns = [
                        r'__NEXT_DATA__["\s]*=\s*(\{[\s\S]*?\})\s*(?:;|<)',
                        r'"properties"\s*:\s*(\[[\s\S]*?\])',
                        r'"homes"\s*:\s*(\[[\s\S]*?\])',
                    ]

                    for pattern in json_patterns:
                        match = re.search(pattern, script.string)
                        if match:
                            try:
                                data = json.loads(match.group(1))
                                parsed = self._parse_json_listings(data)
                                if parsed:
                                    return parsed
                            except json.JSONDecodeError:
                                continue

        except Exception as e:
            print(f"[amh] JSON extraction failed: {e}")

        return listings

    def _parse_json_listings(self, data) -> list[ScrapedListing]:
        """Parse listings from JSON data."""
        listings = []

        # Handle different data structures
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # Try common keys
            for key in ["properties", "homes", "results", "data", "pageProps"]:
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        items = val
                        break
                    elif isinstance(val, dict) and "properties" in val:
                        items = val["properties"]
                        break

        for item in items:
            if not isinstance(item, dict):
                continue

            try:
                listing = ScrapedListing(
                    source_name=self.source_name,
                    source_id=str(item.get("id") or item.get("propertyId") or item.get("homeId") or ""),
                    url=item.get("url") or item.get("detailUrl") or f"https://www.amh.com/homes/{item.get('id', '')}",
                    title=item.get("address") or item.get("streetAddress") or item.get("title") or "AMH Rental",
                    address=item.get("address") or item.get("streetAddress"),
                    city=item.get("city"),
                    state=item.get("state") or "WA",
                    zip_code=item.get("zipCode") or item.get("zip") or item.get("postalCode"),
                    rent=item.get("rent") or item.get("price") or item.get("monthlyRent"),
                    bedrooms=item.get("bedrooms") or item.get("beds"),
                    bathrooms=item.get("bathrooms") or item.get("baths"),
                    sqft=item.get("sqft") or item.get("squareFeet") or item.get("squareFootage"),
                    description=item.get("description"),
                    latitude=item.get("latitude") or item.get("lat"),
                    longitude=item.get("longitude") or item.get("lng"),
                    image_url=item.get("imageUrl") or item.get("image") or item.get("photo"),
                )
                if listing.source_id:
                    listings.append(listing)
            except Exception as e:
                print(f"[amh] Error parsing JSON item: {e}")

        return listings

    def _parse_listing_li(self, li) -> Optional[ScrapedListing]:
        """Parse a listing from an li element based on AMH XPath structure.

        XPath structure:
        - li/div/div[1] = image container with link
        - li/div/div[2] = info container with address, price
        """
        try:
            # Get the main container div
            main_div = li.find("div", recursive=False)
            if not main_div:
                # Try finding any div
                main_div = li.find("div")

            if not main_div:
                return None

            # Get child divs (image container and info container)
            child_divs = main_div.find_all("div", recursive=False)

            image_url = None
            detail_url = None
            address = None
            rent = None

            # Parse image container (usually first div)
            if len(child_divs) >= 1:
                img_container = child_divs[0]

                # Find image: div/a/div/img or just img
                img = img_container.find("img")
                if img:
                    image_url = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
                    if image_url and not image_url.startswith("http"):
                        image_url = urljoin("https://www.amh.com", image_url)

                # Find link
                link = img_container.find("a", href=True)
                if link:
                    detail_url = urljoin("https://www.amh.com", link["href"])

            # Parse info container (usually second div)
            if len(child_divs) >= 2:
                info_container = child_divs[1]

                # Address is in an <a> tag: div[2]/a
                addr_link = info_container.find("a")
                if addr_link:
                    address = self.clean_text(addr_link.get_text())
                    if not detail_url:
                        href = addr_link.get("href")
                        if href:
                            detail_url = urljoin("https://www.amh.com", href)

                # Price is in a span: div[2]/div[1]/div[1]/span[1]
                price_span = info_container.find("span")
                if price_span:
                    price_text = price_span.get_text()
                    rent = self.parse_rent(price_text)

            # Fallback: search entire li for data
            if not rent:
                text = li.get_text()
                price_match = re.search(r'\$\s*([\d,]+)', text)
                if price_match:
                    rent = self.parse_rent(price_match.group(1))

            if not address:
                # Look for address pattern
                text = li.get_text()
                addr_match = re.search(r'(\d+\s+[\w\s]+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Ct|Way|Blvd)[^,]*)', text, re.I)
                if addr_match:
                    address = self.clean_text(addr_match.group(1))

            if not detail_url:
                # Find any link
                any_link = li.find("a", href=True)
                if any_link:
                    detail_url = urljoin("https://www.amh.com", any_link["href"])
                else:
                    detail_url = self.base_url

            # Extract specs from text
            text = li.get_text()
            bedrooms = self.parse_bedrooms(text)
            bathrooms = self.parse_bathrooms(text)
            sqft = self.parse_sqft(text)
            zip_code = self.extract_zip_code(text)

            # Extract city
            city = None
            city_match = re.search(r'(Tumwater|Olympia|Lacey|Yelm|Rochester)', text, re.I)
            if city_match:
                city = city_match.group(1).title()

            # Generate source ID
            source_id = None
            if detail_url:
                id_match = re.search(r'/homes?/([^/?\s]+)', detail_url)
                if id_match:
                    source_id = id_match.group(1)

            if not source_id:
                source_id = str(abs(hash(detail_url or address or text[:50])))[:12]

            title = address or f"AMH Property {source_id}"

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=detail_url,
                title=title,
                address=address,
                city=city,
                state="WA",
                zip_code=zip_code,
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=sqft,
                image_url=image_url,
            )

        except Exception as e:
            print(f"[amh] Error parsing li element: {e}")
            return None

    def scrape_detail_page(self, url: str) -> dict:
        """Scrape additional details from individual AMH listing page."""
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

            # AMH detail pages may have structured data
            # Try to find JSON-LD or embedded data first
            scripts = soup.find_all("script", type="application/ld+json")
            for script in scripts:
                if script.string:
                    try:
                        data = json.loads(script.string)
                        if isinstance(data, dict):
                            if data.get("@type") in ["House", "Apartment", "SingleFamilyResidence"]:
                                details["bedrooms"] = data.get("numberOfBedrooms")
                                details["bathrooms"] = data.get("numberOfBathroomsTotal")
                                if data.get("floorSize"):
                                    sqft_val = data["floorSize"].get("value")
                                    if sqft_val:
                                        details["sqft"] = int(sqft_val)
                                details["description"] = data.get("description")
                    except json.JSONDecodeError:
                        pass

            # Fallback to HTML parsing
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
            if not details["description"]:
                for selector in [".description", ".property-description", "[class*='description']", "p"]:
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
            print(f"[amh] Error scraping detail page {url}: {e}")

        return details
