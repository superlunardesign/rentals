"""Scraper for AMH (American Homes 4 Rent) - amh.com.

Note: AMH is a JavaScript-heavy SPA that loads listings via API.
This scraper attempts to use their API directly.
"""

import re
import json
from typing import Optional
from urllib.parse import urlencode

from .base import BaseScraper, ScrapedListing


class AMHScraper(BaseScraper):
    """Scraper for amh.com property listings.

    AMH uses a React frontend with an API backend. We try to hit
    their API directly for better reliability.
    """

    # AMH API endpoint (discovered from their site)
    API_BASE = "https://www.amh.com/api/properties/search"

    def __init__(self, url: str = "https://www.amh.com/query?criteria=Tumwater%2C+WA"):
        super().__init__(source_name="amh", base_url=url)
        # Extract search criteria from URL
        self.search_location = "Tumwater, WA"

    def scrape(self) -> list[ScrapedListing]:
        """Scrape listings from AMH."""
        listings = []

        # Try API approach first
        api_listings = self._scrape_via_api()
        if api_listings:
            listings.extend(api_listings)
        else:
            # Fallback to HTML parsing
            html_listings = self._scrape_via_html()
            listings.extend(html_listings)

        print(f"[amh] Found {len(listings)} listings")
        return listings

    def _scrape_via_api(self) -> list[ScrapedListing]:
        """Try to scrape via AMH's API."""
        listings = []

        try:
            # AMH API search parameters (based on their web app)
            params = {
                "city": "Tumwater",
                "state": "WA",
                "radius": 25,
                "limit": 100,
            }

            # Try different API endpoint patterns
            api_urls = [
                f"https://www.amh.com/api/properties/search?{urlencode(params)}",
                "https://www.amh.com/api/v1/properties/search",
                "https://www.amh.com/api/homes/search",
            ]

            for api_url in api_urls:
                try:
                    response = self.client.get(api_url)
                    if response.status_code == 200:
                        data = response.json()
                        listings = self._parse_api_response(data)
                        if listings:
                            return listings
                except Exception:
                    continue

        except Exception as e:
            print(f"[amh] API scraping failed: {e}")

        return listings

    def _parse_api_response(self, data: dict) -> list[ScrapedListing]:
        """Parse AMH API response."""
        listings = []

        # Try different response structures
        items = data.get("properties") or data.get("homes") or data.get("results") or data.get("data") or []

        if isinstance(data, list):
            items = data

        for item in items:
            try:
                listing = ScrapedListing(
                    source_name=self.source_name,
                    source_id=str(item.get("id") or item.get("propertyId") or item.get("homeId", "")),
                    url=item.get("url") or f"https://www.amh.com/homes/{item.get('id', '')}",
                    title=item.get("address") or item.get("title") or "AMH Rental",
                    address=item.get("address") or item.get("streetAddress"),
                    city=item.get("city"),
                    state=item.get("state"),
                    zip_code=item.get("zipCode") or item.get("zip"),
                    rent=item.get("rent") or item.get("price") or item.get("monthlyRent"),
                    bedrooms=item.get("bedrooms") or item.get("beds"),
                    bathrooms=item.get("bathrooms") or item.get("baths"),
                    sqft=item.get("sqft") or item.get("squareFeet") or item.get("squareFootage"),
                    description=item.get("description"),
                    latitude=item.get("latitude") or item.get("lat"),
                    longitude=item.get("longitude") or item.get("lng") or item.get("lon"),
                )
                listings.append(listing)
            except Exception as e:
                print(f"[amh] Error parsing API item: {e}")
                continue

        return listings

    def _scrape_via_html(self) -> list[ScrapedListing]:
        """Fallback HTML scraping for AMH."""
        listings = []

        try:
            soup = self.fetch_page(self.base_url)

            # Look for JSON data embedded in the page (common in React apps)
            scripts = soup.find_all("script")
            for script in scripts:
                if script.string and ("properties" in script.string or "homes" in script.string):
                    # Try to extract JSON data
                    json_match = re.search(r'(\{[\s\S]*"(?:properties|homes)"[\s\S]*\})', script.string)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(1))
                            return self._parse_api_response(data)
                        except json.JSONDecodeError:
                            continue

            # Try finding listing cards in HTML
            selectors = [
                ".property-card",
                ".home-card",
                "[data-testid='property-card']",
                ".listing-card",
                ".rental-card",
            ]

            for selector in selectors:
                elements = soup.select(selector)
                if elements:
                    for elem in elements:
                        listing = self._parse_html_listing(elem)
                        if listing:
                            listings.append(listing)
                    break

        except Exception as e:
            print(f"[amh] HTML scraping failed: {e}")

        return listings

    def _parse_html_listing(self, element) -> Optional[ScrapedListing]:
        """Parse a listing from HTML element."""
        try:
            # Extract URL
            link = element.find("a", href=True)
            url = link["href"] if link else self.base_url
            if not url.startswith("http"):
                url = f"https://www.amh.com{url}"

            # Extract source ID from URL
            id_match = re.search(r"/homes?/([^/]+)", url)
            source_id = id_match.group(1) if id_match else str(hash(url))[:12]

            text = element.get_text()

            # Extract details
            title = None
            for sel in [".address", "h2", "h3", ".title"]:
                title_elem = element.select_one(sel)
                if title_elem:
                    title = self.clean_text(title_elem.get_text())
                    break

            rent = None
            rent_match = re.search(r'\$\s*([\d,]+)', text)
            if rent_match:
                rent = self.parse_rent(rent_match.group(1))

            bedrooms = self.parse_bedrooms(text)
            bathrooms = self.parse_bathrooms(text)
            sqft = self.parse_sqft(text)
            zip_code = self.extract_zip_code(text)

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=url,
                title=title or "AMH Rental",
                city="Tumwater",
                state="WA",
                zip_code=zip_code,
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=sqft,
            )

        except Exception as e:
            print(f"[amh] Error parsing HTML listing: {e}")
            return None
