"""Zillow API scraper using RapidAPI private-zillow endpoint (map bounds search)."""

import os
import re
from typing import Optional

import httpx

from .base import BaseScraper, ScrapedListing


class ZillowAPIScraper(BaseScraper):
    """Scraper that fetches rental listings from Zillow via RapidAPI.

    Uses the private-zillow /search/bymapbounds endpoint (GET).
    Requires RAPIDAPI_KEY environment variable.

    Config url format: "zillow://northLat,westLng,southLat,eastLng"
    Example: "zillow://47.12,-123.05,46.93,-122.72"
    """

    RAPIDAPI_HOST = "private-zillow.p.rapidapi.com"
    SEARCH_URL = f"https://{RAPIDAPI_HOST}/search/bymapbounds"

    def __init__(self, url: str = "zillow://47.12,-123.05,46.93,-122.72"):
        raw = url.replace("zillow://", "").strip()
        super().__init__(source_name="zillow_api", base_url=url)
        # Parse bounds: north,west,south,east
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) == 4:
            self.north_lat = parts[0]
            self.west_lng = parts[1]
            self.south_lat = parts[2]
            self.east_lng = parts[3]
        else:
            # Fallback: Olympia/Tumwater/Lacey area
            self.north_lat = "47.12"
            self.west_lng = "-123.05"
            self.south_lat = "46.93"
            self.east_lng = "-122.72"
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

            props = self._extract_properties(results)
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

    def _fetch_results(self) -> Optional[dict]:
        """Fetch rental results using GET /search/bymapbounds.

        Builds the query string directly in the URL (pre-encoded) to match
        the exact format RapidAPI expects, avoiding httpx param re-encoding
        issues with special chars like colons, commas, and slashes.
        """
        headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": self.RAPIDAPI_HOST,
        }

        # Build URL with pre-encoded query string (matches RapidAPI's code snippet)
        from urllib.parse import quote
        url = (
            f"https://{self.RAPIDAPI_HOST}/search/bymapbounds"
            f"?eastLongitude={self.east_lng}"
            f"&northLatitude={self.north_lat}"
            f"&southLatitude={self.south_lat}"
            f"&westLongitude={self.west_lng}"
            f"&page=1"
            f"&sortOrder=Newest"
            f"&listingStatus=For_Rent"
            f"&listPriceRange={quote('min:2000, max:3000')}"
            f"&bed_min=2"
            f"&bed_max=No_Max"
            f"&bathrooms=TwoPlus"
            f"&homeType={quote('Houses, Townhomes, Multi-family, Condos/Co-ops, Lots-Land, Apartments, Manufactured')}"
            f"&space={quote('Entire Place')}"
            f"&maxHOA=Any"
            f"&parkingSpots=Any"
            f"&squareFeetRange={quote('min:1200')}"
            f"&mustHaveBasement=No"
            f"&hide55plusComm=true"
            f"&daysOnZillow=Any"
            f"&soldInLast=Any"
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

            if isinstance(data, dict):
                return data
            elif isinstance(data, list):
                return {"results": data}
            return None

        except httpx.HTTPStatusError as e:
            print(f"[{self.source_name}] API error: {e.response.status_code} - {e.response.text[:500]}")
            return None
        except httpx.ConnectError as e:
            print(f"[{self.source_name}] Connection error: {e}")
            return None
        except Exception as e:
            print(f"[{self.source_name}] Request error: {type(e).__name__}: {e}")
            return None

    def _extract_properties(self, result: dict) -> list[dict]:
        """Extract property list from a search result.

        The API returns: {"searchResults": [{"property": {...}}, ...]}
        Each item wraps the actual data under a "property" key.
        """
        if not isinstance(result, dict):
            return []

        items = result.get("searchResults", [])
        if not isinstance(items, list):
            return []

        # Unwrap: each item has a "property" sub-dict with the actual data
        properties = []
        for item in items:
            if isinstance(item, dict):
                prop = item.get("property")
                if isinstance(prop, dict):
                    properties.append(prop)
                else:
                    # Fallback: item itself is the property
                    properties.append(item)

        if properties:
            import json
            print(f"[{self.source_name}] First item keys: {list(properties[0].keys())}")
            print(f"[{self.source_name}] First item preview: {json.dumps(properties[0], default=str)[:1500]}")

        return properties

    def _parse_property(self, prop: dict) -> Optional[ScrapedListing]:
        """Parse a Zillow property object into a ScrapedListing.

        Expected structure (from API):
          {
            "zpid": 123,
            "location": {"latitude": 47.05, "longitude": -122.82},
            "address": {"streetAddress": "...", "city": "...", "state": "...", "zipcode": "..."},
            "media": {"propertyPhotoLinks": {"highResolutionLink": "..."}},
            "price": ..., "bedrooms": ..., "bathrooms": ..., "livingArea": ...,
            "detailUrl": "..."
          }
        """
        try:
            zpid = str(prop.get("zpid") or prop.get("id") or "")
            if not zpid:
                return None

            # Address — nested under "address" dict
            address_obj = prop.get("address", {}) or {}
            street = address_obj.get("streetAddress", "")
            city = address_obj.get("city", "")
            state = address_obj.get("state", "")
            zipcode = address_obj.get("zipcode", "")

            if street and city:
                address_str = f"{street}, {city}, {state} {zipcode}".strip()
            elif street:
                address_str = street
            else:
                return None

            # Rent/price
            rent = prop.get("price") or prop.get("rentZestimate") or prop.get("unformattedPrice")
            if isinstance(rent, str):
                rent = self.parse_rent(rent)
            elif isinstance(rent, (int, float)):
                rent = int(rent)

            bedrooms = prop.get("bedrooms") or prop.get("beds")
            bathrooms = prop.get("bathrooms") or prop.get("baths")
            sqft = prop.get("livingArea") or prop.get("sqft") or prop.get("area")

            # Location — nested under "location" dict
            loc = prop.get("location", {}) or {}
            lat = loc.get("latitude") or prop.get("latitude")
            lon = loc.get("longitude") or prop.get("longitude")

            # URL
            detail_url = prop.get("detailUrl") or prop.get("url") or ""
            if detail_url and not detail_url.startswith("http"):
                detail_url = f"https://www.zillow.com{detail_url}"
            if not detail_url:
                detail_url = f"https://www.zillow.com/homedetails/{zpid}_zpid/"

            # Image — nested under "media.propertyPhotoLinks"
            media = prop.get("media", {}) or {}
            photo_links = media.get("propertyPhotoLinks", {}) or {}
            image_url = (
                photo_links.get("highResolutionLink")
                or photo_links.get("mediumSizeLink")
                or prop.get("imgSrc")
                or ""
            )

            return ScrapedListing(
                source_name=self.source_name,
                source_id=f"zillow_{zpid}",
                url=detail_url,
                title=address_str,
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
