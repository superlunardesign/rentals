"""Redfin API scraper using RapidAPI redfin-com endpoint."""

import os
import re
from typing import Optional

import httpx

from .base import BaseScraper, ScrapedListing


class RedfinAPIScraper(BaseScraper):
    """Scraper that fetches rental listings from Redfin via RapidAPI.

    Requires RAPIDAPI_KEY environment variable.

    Config url format: "redfin://location" where location is a city/state or zip.
    Example: "redfin://Olympia, WA" or "redfin://98512"
    """

    RAPIDAPI_HOST = "redfin-com-data.p.rapidapi.com"
    SEARCH_URL = f"https://{RAPIDAPI_HOST}/properties/search-rent"

    def __init__(self, url: str = "redfin://Olympia, WA"):
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

            homes = results.get("homes") or results.get("properties") or []
            if isinstance(results, list):
                homes = results

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
        """Fetch rental results from the Redfin API."""
        headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": self.RAPIDAPI_HOST,
        }
        params = {
            "location": self.location,
            "status": "ForRent",
        }

        try:
            response = self.client.get(
                self.SEARCH_URL,
                headers=headers,
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

            # Handle different response formats
            if isinstance(data, dict):
                return data
            elif isinstance(data, list):
                return {"homes": data}
            return None

        except httpx.HTTPStatusError as e:
            print(f"[{self.source_name}] API error: {e.response.status_code} - {e.response.text[:200]}")
            return None
        except Exception as e:
            print(f"[{self.source_name}] Request error: {e}")
            return None

    def _parse_property(self, prop: dict) -> Optional[ScrapedListing]:
        """Parse a Redfin property object into a ScrapedListing."""
        try:
            # Redfin uses various ID fields
            prop_id = str(
                prop.get("propertyId")
                or prop.get("listingId")
                or prop.get("mlsId")
                or prop.get("id", "")
            )
            if not prop_id:
                return None

            # Address can be in different formats
            address_obj = prop.get("address", {})
            if isinstance(address_obj, dict):
                street = address_obj.get("streetAddress", "") or address_obj.get("line", "")
                city = address_obj.get("city", "")
                state = address_obj.get("stateOrProvince", "") or address_obj.get("state", "")
                zipcode = address_obj.get("postalCode", "") or address_obj.get("zip", "")
            elif isinstance(address_obj, str):
                street = address_obj
                city = prop.get("city", "")
                state = prop.get("state", "")
                zipcode = prop.get("zip", "")
            else:
                street = prop.get("streetAddress", "") or prop.get("address", "")
                city = prop.get("city", "")
                state = prop.get("state", "")
                zipcode = prop.get("zipcode", "") or prop.get("zip", "")

            if street and city:
                address_str = f"{street}, {city}, {state} {zipcode}".strip()
            else:
                address_str = str(street or "")

            if not address_str:
                return None

            # Rent/price
            rent = (
                prop.get("price")
                or prop.get("rent")
                or prop.get("listPrice")
                or prop.get("priceLabel")
            )
            if isinstance(rent, str):
                rent = self.parse_rent(rent)
            elif isinstance(rent, (int, float)):
                rent = int(rent)

            bedrooms = prop.get("beds") or prop.get("bedrooms")
            bathrooms = prop.get("baths") or prop.get("bathrooms")
            sqft = prop.get("sqFt") or prop.get("sqft") or prop.get("livingArea")

            lat = prop.get("latitude") or prop.get("lat")
            lon = prop.get("longitude") or prop.get("lng") or prop.get("lon")

            url = prop.get("url") or prop.get("listingUrl") or ""
            if url and not url.startswith("http"):
                url = f"https://www.redfin.com{url}"
            if not url:
                url = f"https://www.redfin.com/search?location={self.location}"

            image_url = prop.get("photo") or prop.get("primaryPhoto") or prop.get("imgSrc")

            title = address_str or f"Redfin Property {prop_id}"

            return ScrapedListing(
                source_name=self.source_name,
                source_id=f"redfin_{prop_id}",
                url=url,
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
