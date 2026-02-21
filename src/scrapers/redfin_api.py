"""Redfin API scraper using RapidAPI realfin-us endpoint."""

import os
import re
from typing import Optional

import httpx

from .base import BaseScraper, ScrapedListing


class RedfinAPIScraper(BaseScraper):
    """Scraper that fetches rental listings from Redfin via RapidAPI.

    Requires RAPIDAPI_KEY environment variable.

    Config url format: "redfin://<location>" where location is a city/state
    string (e.g. "Olympia, WA, USA").
    """

    RAPIDAPI_HOST = "realfin-us.p.rapidapi.com"

    def __init__(self, url: str = "redfin://Olympia, WA, USA"):
        location = url.replace("redfin://", "").strip()
        super().__init__(source_name="redfin_api", base_url=url)
        self.location = location
        self.api_key = os.environ.get("RAPIDAPI_KEY", "")

    def scrape(self) -> list[ScrapedListing]:
        """Fetch rental listings from Redfin API."""
        if not self.api_key:
            print(f"[{self.source_name}] RAPIDAPI_KEY not set, skipping")
            return []

        listings = []

        try:
            results = self._fetch_results()
            if not results:
                return []

            homes = results.get("data") or results.get("homes") or results.get("properties") or []
            if isinstance(results, list):
                homes = results

            if homes:
                import json
                print(f"[{self.source_name}] First item keys: {list(homes[0].keys()) if isinstance(homes[0], dict) else type(homes[0])}")
                print(f"[{self.source_name}] First item preview: {json.dumps(homes[0], default=str)[:1500]}")

            for home in homes:
                listing = self._parse_property(home)
                if listing:
                    listings.append(listing)

        except Exception as e:
            print(f"[{self.source_name}] Error: {e}")
            import traceback
            traceback.print_exc()

        print(f"[{self.source_name}] Found {len(listings)} listings from Redfin API")
        return listings

    def _fetch_results(self) -> Optional[dict]:
        """Fetch rental results from the Redfin API.

        Uses /search/location/for-rent with pre-encoded URL to match
        RapidAPI's exact format.
        """
        headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": self.RAPIDAPI_HOST,
        }

        from urllib.parse import quote
        url = (
            f"https://{self.RAPIDAPI_HOST}/search/location/for-rent"
            f"?location={quote(self.location)}"
            f"&sort=days-on-redfin-asc"
            f"&minPrice=2000"
            f"&maxPrice=3000"
            f"&numBeds=2"
            f"&numBaths=2"
            f"&homeType={quote('1,2,3')}"
            f"&minSquareFeet=1000"
            f"&booleanFilters=excl_ar"
        )

        try:
            response = self.client.get(
                url,
                headers=headers,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            # Debug: show response structure
            if isinstance(data, dict):
                print(f"[{self.source_name}] Response keys: {list(data.keys())}")
                for k, v in data.items():
                    if isinstance(v, list):
                        print(f"[{self.source_name}]   {k}: list with {len(v)} items")
                    elif isinstance(v, dict):
                        print(f"[{self.source_name}]   {k}: dict with keys {list(v.keys())[:10]}")
                    else:
                        print(f"[{self.source_name}]   {k}: {str(v)[:200]}")
            else:
                print(f"[{self.source_name}] Response type: {type(data).__name__}, preview: {str(data)[:300]}")

            # Handle different response formats
            if isinstance(data, dict):
                return data
            elif isinstance(data, list):
                return {"homes": data}
            return None

        except httpx.HTTPStatusError as e:
            print(f"[{self.source_name}] API error: {e.response.status_code} - {e.response.text[:200]}")
            return None
        except httpx.ConnectError as e:
            print(f"[{self.source_name}] Connection error: {e}")
            return None
        except Exception as e:
            print(f"[{self.source_name}] Request error: {type(e).__name__}: {e}")
            return None

    def _parse_property(self, prop: dict) -> Optional[ScrapedListing]:
        """Parse a Redfin property object into a ScrapedListing.

        Actual structure (from API):
          {
            "homeData": {
              "propertyId": "198938710",
              "url": "/WA/Olympia/8915-52nd-Ave-SE-98513/home/198938710",
              "addressInfo": {
                "formattedStreetLine": "8915 52nd Ave SE",
                "city": "Olympia", "state": "WA", "zip": "98513",
                "centroid": {"centroid": {"latitude": 47.0, "longitude": -122.7}}
              },
              "staticMapUrl": "https://maps.google.com/..."
            },
            "rentalExtension": {
              "rentalId": "...",
              "rentPriceRange": {"min": 2925, "max": 2990},
              "bedRange": {"min": 3, "max": 4},
              "bathRange": {"min": 2.5, "max": 2.5},
              "sqftRange": {"min": 1752, "max": 1967},
              "propertyName": "Manor House"
            }
          }
        """
        try:
            home_data = prop.get("homeData", {}) or {}
            rental = prop.get("rentalExtension", {}) or {}
            addr_info = home_data.get("addressInfo", {}) or {}

            # ID
            prop_id = str(
                rental.get("rentalId")
                or home_data.get("propertyId")
                or ""
            )
            if not prop_id:
                return None

            # Address
            street = addr_info.get("formattedStreetLine", "")
            city = addr_info.get("city", "")
            state = addr_info.get("state", "")
            zipcode = addr_info.get("zip", "")

            if street and city:
                address_str = f"{street}, {city}, {state} {zipcode}".strip()
            elif street:
                address_str = street
            else:
                return None

            # Rent — use min of rentPriceRange
            price_range = rental.get("rentPriceRange", {}) or {}
            rent = price_range.get("min") or price_range.get("max")
            if isinstance(rent, str):
                rent = self.parse_rent(rent)
            elif isinstance(rent, (int, float)):
                rent = int(rent)

            # Beds/baths/sqft — use min of ranges
            bed_range = rental.get("bedRange", {}) or {}
            bath_range = rental.get("bathRange", {}) or {}
            sqft_range = rental.get("sqftRange", {}) or {}
            bedrooms = bed_range.get("min")
            bathrooms = bath_range.get("min")
            sqft = sqft_range.get("min")

            # Location — nested centroid inside homeData.addressInfo
            centroid_outer = addr_info.get("centroid", {}) or {}
            centroid = centroid_outer.get("centroid", {}) or {}
            lat = centroid.get("latitude")
            lon = centroid.get("longitude")

            # URL — from homeData
            url = home_data.get("url") or ""
            if url and not url.startswith("http"):
                url = f"https://www.redfin.com{url}"
            if not url:
                url = f"https://www.redfin.com/rentals"

            # Property name as title if available
            prop_name = rental.get("propertyName", "")
            title = prop_name if prop_name else address_str

            # Note: staticMapUrl is a Google Maps image, not a property photo.
            # photosInfo has ranges but no direct URLs. Skip image for now.
            image_url = ""

            return ScrapedListing(
                source_name=self.source_name,
                source_id=f"redfin_{prop_id}",
                url=url,
                title=title,
                address=address_str,
                city=city or None,
                state=state or "WA",
                zip_code=str(zipcode)[:5] if zipcode else None,
                rent=rent,
                bedrooms=int(bedrooms) if bedrooms else None,
                bathrooms=float(bathrooms) if bathrooms else None,
                sqft=int(sqft) if sqft else None,
                latitude=float(lat) if lat else None,
                longitude=float(lon) if lon else None,
                image_url=image_url or None,
            )

        except Exception as e:
            print(f"[{self.source_name}] Error parsing property: {e}")
            return None
