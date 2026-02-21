"""Zillow API scraper using RapidAPI zillow-real-estate-api endpoint."""

import os
import re
from typing import Optional

import httpx

from .base import BaseScraper, ScrapedListing


class ZillowAPIScraper(BaseScraper):
    """Scraper that fetches rental listings from Zillow via RapidAPI.

    Uses the zillow-real-estate-api batch search endpoint.
    Requires RAPIDAPI_KEY environment variable.

    Config url format: "zillow://location" where location is a city/state or zip.
    Example: "zillow://Olympia, WA" or "zillow://98512"

    Multiple locations can be comma-separated:
    "zillow://Olympia, WA|Tumwater, WA|Lacey, WA"
    """

    RAPIDAPI_HOST = "zillow-real-estate-api.p.rapidapi.com"
    SEARCH_URL = f"https://{RAPIDAPI_HOST}/v1/batch/search"

    def __init__(self, url: str = "zillow://Olympia, WA"):
        raw = url.replace("zillow://", "").strip()
        super().__init__(source_name="zillow_api", base_url=url)
        # Support multiple locations separated by |
        self.locations = [loc.strip() for loc in raw.split("|") if loc.strip()]
        self.api_key = os.environ.get("RAPIDAPI_KEY", "")

    def scrape(self) -> list[ScrapedListing]:
        """Fetch rental listings from Zillow API."""
        if not self.api_key:
            print(f"[{self.source_name}] RAPIDAPI_KEY not set, skipping")
            return []

        listings = []
        seen_ids = set()

        try:
            results = self._fetch_results()
            if not results:
                return []

            # Response may be a list of search results (one per location)
            # or a single result dict
            search_results = results if isinstance(results, list) else [results]

            for result in search_results:
                props = self._extract_properties(result)
                for prop in props:
                    listing = self._parse_property(prop)
                    if listing and listing.source_id not in seen_ids:
                        seen_ids.add(listing.source_id)
                        listings.append(listing)

        except Exception as e:
            print(f"[{self.source_name}] Error: {e}")
            import traceback
            traceback.print_exc()

        print(f"[{self.source_name}] Found {len(listings)} listings from Zillow API")
        return listings

    def _fetch_results(self) -> Optional[list]:
        """Fetch rental results using batch search."""
        headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": self.RAPIDAPI_HOST,
            "Content-Type": "application/json",
        }

        searches = []
        for location in self.locations:
            searches.append({
                "location": location,
                "status": "for_rent",
                "result_type": "list",
                "page_size": 40,
                "sort": "relevance",
            })

        body = {"searches": searches}

        try:
            response = self.client.post(
                self.SEARCH_URL,
                headers=headers,
                json=body,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict):
                # Could be {"results": [...]} or {"data": [...]} or direct
                return data.get("results") or data.get("data") or [data]
            elif isinstance(data, list):
                return data
            return None

        except httpx.HTTPStatusError as e:
            print(f"[{self.source_name}] API error: {e.response.status_code} - {e.response.text[:200]}")
            return None
        except Exception as e:
            print(f"[{self.source_name}] Request error: {e}")
            return None

    def _extract_properties(self, result: dict) -> list[dict]:
        """Extract property list from a search result, handling various response shapes."""
        if not isinstance(result, dict):
            return []

        # Try common keys for the property list
        for key in ("props", "properties", "listings", "homes", "results", "searchResults", "data"):
            val = result.get(key)
            if isinstance(val, list):
                return val
            # Nested: {"searchResults": {"listResults": [...]}}
            if isinstance(val, dict):
                for subkey in ("listResults", "results", "properties", "props"):
                    subval = val.get(subkey)
                    if isinstance(subval, list):
                        return subval

        return []

    def _parse_property(self, prop: dict) -> Optional[ScrapedListing]:
        """Parse a Zillow property object into a ScrapedListing."""
        try:
            # Zillow uses zpid as unique ID
            zpid = str(
                prop.get("zpid")
                or prop.get("id")
                or prop.get("propertyId")
                or prop.get("listingId")
                or ""
            )
            if not zpid:
                return None

            # Address parsing - handle nested or flat formats
            address_obj = prop.get("address", {})
            if isinstance(address_obj, dict):
                street = address_obj.get("streetAddress", "") or address_obj.get("line", "")
                city = address_obj.get("city", "")
                state = address_obj.get("state", "") or address_obj.get("stateOrProvince", "")
                zipcode = address_obj.get("zipcode", "") or address_obj.get("postalCode", "") or address_obj.get("zip", "")
            elif isinstance(address_obj, str):
                street = address_obj
                city = prop.get("city", "")
                state = prop.get("state", "")
                zipcode = prop.get("zipcode", "") or prop.get("zip", "")
            else:
                street = prop.get("streetAddress", "") or prop.get("address", "")
                city = prop.get("city", "")
                state = prop.get("state", "")
                zipcode = prop.get("zipcode", "") or prop.get("zip", "")

            # Also try top-level fields as fallbacks
            if not street:
                street = prop.get("streetAddress", "")
            if not city:
                city = prop.get("city", "")
            if not state:
                state = prop.get("state", "")
            if not zipcode:
                zipcode = prop.get("zipcode", "") or prop.get("zip", "")

            # Build full address
            if street and city:
                address_str = f"{street}, {city}, {state} {zipcode}".strip()
            elif street:
                address_str = street
            else:
                address_str = ""

            if not address_str:
                return None

            # Rent/price
            rent = (
                prop.get("price")
                or prop.get("rent")
                or prop.get("listPrice")
                or prop.get("rentZestimate")
                or prop.get("unformattedPrice")
            )
            if isinstance(rent, str):
                rent = self.parse_rent(rent)
            elif isinstance(rent, (int, float)):
                rent = int(rent)

            bedrooms = prop.get("bedrooms") or prop.get("beds")
            bathrooms = prop.get("bathrooms") or prop.get("baths")
            sqft = prop.get("livingArea") or prop.get("sqft") or prop.get("area")

            lat = prop.get("latitude") or prop.get("lat")
            lon = prop.get("longitude") or prop.get("lng") or prop.get("lon")
            # Handle nested latLong
            if not lat and isinstance(prop.get("latLong"), dict):
                lat = prop["latLong"].get("latitude") or prop["latLong"].get("lat")
                lon = prop["latLong"].get("longitude") or prop["latLong"].get("lng")

            # URL
            detail_url = prop.get("detailUrl") or prop.get("url") or prop.get("listingUrl") or ""
            if detail_url and not detail_url.startswith("http"):
                detail_url = f"https://www.zillow.com{detail_url}"
            if not detail_url:
                detail_url = f"https://www.zillow.com/homedetails/{zpid}_zpid/"

            image_url = prop.get("imgSrc") or prop.get("image") or prop.get("photo") or ""

            title = address_str or f"Zillow Property {zpid}"

            return ScrapedListing(
                source_name=self.source_name,
                source_id=f"zillow_{zpid}",
                url=detail_url,
                title=title,
                address=address_str or None,
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
