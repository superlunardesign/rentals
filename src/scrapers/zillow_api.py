"""Zillow API scraper using RapidAPI zillow-com1 endpoint."""

import os
import re
from typing import Optional

import httpx

from .base import BaseScraper, ScrapedListing


class ZillowAPIScraper(BaseScraper):
    """Scraper that fetches rental listings from Zillow via RapidAPI.

    Requires RAPIDAPI_KEY environment variable.

    Config url format: "zillow://location" where location is a city/state or zip.
    Example: "zillow://Olympia, WA" or "zillow://98512"
    """

    # zillow-com1 was deprecated Dec 2025, successor is us-housing-market-data1
    RAPIDAPI_HOST = "us-housing-market-data1.p.rapidapi.com"
    SEARCH_URL = f"https://{RAPIDAPI_HOST}/propertyExtendedSearch"

    def __init__(self, url: str = "zillow://Olympia, WA"):
        # Parse the location from the url scheme
        location = url.replace("zillow://", "").strip()
        super().__init__(source_name="zillow_api", base_url=url)
        self.location = location
        self.api_key = os.environ.get("RAPIDAPI_KEY", "")

    def scrape(self) -> list[ScrapedListing]:
        """Fetch rental listings from Zillow API."""
        if not self.api_key:
            print(f"[{self.source_name}] RAPIDAPI_KEY not set, skipping")
            return []

        listings = []
        page = 1

        while True:
            try:
                results = self._fetch_page(page)
                if not results:
                    break

                props = results.get("props") or []
                if not props:
                    break

                for prop in props:
                    listing = self._parse_property(prop)
                    if listing:
                        listings.append(listing)

                # Check if there are more pages
                total_pages = results.get("totalPages", 1)
                if page >= total_pages or page >= 5:  # Cap at 5 pages to limit API calls
                    break
                page += 1

            except Exception as e:
                print(f"[{self.source_name}] Error fetching page {page}: {e}")
                break

        print(f"[{self.source_name}] Found {len(listings)} listings from Zillow API")
        return listings

    def _fetch_page(self, page: int = 1) -> Optional[dict]:
        """Fetch a page of rental results from the API."""
        headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": self.RAPIDAPI_HOST,
        }
        params = {
            "location": self.location,
            "status_type": "ForRent",
            "page": str(page),
        }

        try:
            response = self.client.get(
                self.SEARCH_URL,
                headers=headers,
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            print(f"[{self.source_name}] API error: {e.response.status_code} - {e.response.text[:200]}")
            return None
        except Exception as e:
            print(f"[{self.source_name}] Request error: {e}")
            return None

    def _parse_property(self, prop: dict) -> Optional[ScrapedListing]:
        """Parse a Zillow property object into a ScrapedListing."""
        try:
            zpid = str(prop.get("zpid", ""))
            if not zpid:
                return None

            address_str = prop.get("address", "")
            street = prop.get("streetAddress", "")
            city = prop.get("city", "")
            state = prop.get("state", "")
            zipcode = prop.get("zipcode", "")

            # Build full address if we have parts
            if street and city and state:
                address_str = f"{street}, {city}, {state} {zipcode}".strip()

            rent = prop.get("price")
            if isinstance(rent, str):
                rent = self.parse_rent(rent)
            elif isinstance(rent, (int, float)):
                rent = int(rent)

            bedrooms = prop.get("bedrooms")
            bathrooms = prop.get("bathrooms")
            sqft = prop.get("livingArea")

            lat = prop.get("latitude")
            lon = prop.get("longitude")

            detail_url = prop.get("detailUrl", "")
            if detail_url and not detail_url.startswith("http"):
                detail_url = f"https://www.zillow.com{detail_url}"
            if not detail_url:
                detail_url = f"https://www.zillow.com/homedetails/{zpid}_zpid/"

            image_url = prop.get("imgSrc") or prop.get("image", "")

            title = address_str or f"Zillow Property {zpid}"

            return ScrapedListing(
                source_name=self.source_name,
                source_id=f"zillow_{zpid}",
                url=detail_url,
                title=title,
                address=address_str,
                city=city or None,
                state=state or "WA",
                zip_code=zipcode or None,
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
