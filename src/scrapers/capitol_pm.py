"""Scraper for Capitol Property Management (ManageBuilding platform)."""

import re
from typing import Optional
from urllib.parse import urljoin

from .base import BaseScraper, ScrapedListing


class CapitolPMScraper(BaseScraper):
    """Scraper for capitol-pm.managebuilding.com listings."""

    def __init__(self, url: str = "https://capitol-pm.managebuilding.com/Resident/Public/Rentals"):
        super().__init__(source_name="capitol_pm", base_url=url)

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all listings from Capitol PM."""
        print(f"[{self.source_name}] Fetching ManageBuilding listings...")

        soup = self.fetch_page(self.base_url)
        listings = []

        # Find all listing cards
        cards = soup.select("a.featured-listing")
        print(f"[{self.source_name}] Found {len(cards)} listing cards")

        for card in cards:
            try:
                listing = self._parse_listing(card)
                if listing:
                    listings.append(listing)
            except Exception as e:
                print(f"[{self.source_name}] Error parsing listing: {e}")
                continue

        print(f"[{self.source_name}] Parsed {len(listings)} listings")
        return listings

    def _parse_listing(self, card) -> Optional[ScrapedListing]:
        """Parse a single listing card."""
        # Get data from data attributes (very reliable)
        bedrooms = card.get("data-bedrooms")
        bathrooms = card.get("data-bathrooms")
        rent = card.get("data-rent")
        sqft = card.get("data-square-feet")
        prop_type = card.get("data-type")
        location = card.get("data-location", "")  # Format: "Olympia,WA|98502"

        # Parse location
        city, state, zip_code = None, None, None
        if location:
            parts = location.split("|")
            if len(parts) >= 1:
                city_state = parts[0].split(",")
                if len(city_state) >= 1:
                    city = city_state[0].strip()
                if len(city_state) >= 2:
                    state = city_state[1].strip()
            if len(parts) >= 2:
                zip_code = parts[1].strip()

        # Get URL
        href = card.get("href", "")
        url = urljoin(self.base_url, href) if href else None

        # Get title/address
        title_el = card.select_one(".featured-listing__title")
        title = title_el.get_text(strip=True) if title_el else None

        # Get full address line
        address_el = card.select_one(".featured-listing__address")
        address_text = address_el.get_text(strip=True) if address_el else None

        # Combine title (street) with city for full address
        address = title if title else None

        # Get image
        img_el = card.select_one(".featured-listing__image")
        image_url = None
        if img_el and img_el.get("src"):
            image_url = urljoin(self.base_url, img_el["src"])

        # Get description
        desc_el = card.select_one(".featured-listing__description")
        description = desc_el.get_text(strip=True) if desc_el else None

        # Build features list
        features = []
        if prop_type:
            # Convert camelCase to readable: "SingleFamily" -> "Single Family"
            readable_type = re.sub(r'([a-z])([A-Z])', r'\1 \2', prop_type)
            features.append(readable_type.lower())
        if description:
            # Extract keywords from description
            desc_lower = description.lower()
            if "garage" in desc_lower:
                features.append("garage")
            if "duplex" in desc_lower:
                features.append("duplex")
            if "parking" in desc_lower:
                features.append("parking")
            if "washer" in desc_lower or "w/d" in desc_lower:
                features.append("washer/dryer")
            if "yard" in desc_lower:
                features.append("yard")
            if "pet" in desc_lower:
                features.append("pets")

        # Generate source ID from URL
        source_id = None
        if href:
            # Extract ID from URL like "/Resident/public/rentals/8689"
            match = re.search(r'/rentals/(\d+)', href)
            if match:
                source_id = f"capitol_pm_{match.group(1)}"

        listing = ScrapedListing(
            source_name=self.source_name,
            source_id=source_id,
            url=url,
            title=title,
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            rent=int(float(rent)) if rent else None,
            bedrooms=int(bedrooms) if bedrooms else None,
            bathrooms=float(bathrooms) if bathrooms else None,
            sqft=int(sqft) if sqft else None,
            description=description,
            features=features,
            image_url=image_url,
        )

        return listing

    def scrape_detail_page(self, url: str) -> dict:
        """Fetch additional details from a listing's detail page."""
        try:
            soup = self.fetch_page(url)
            details = {}

            # Look for more detailed description
            desc_el = soup.select_one(".listing-description, .property-description")
            if desc_el:
                details["description"] = desc_el.get_text(strip=True)

            # Look for amenities/features list
            amenities = soup.select(".amenity, .feature-item, li.amenity")
            if amenities:
                details["features"] = [a.get_text(strip=True) for a in amenities]

            return details

        except Exception as e:
            print(f"[{self.source_name}] Error fetching detail page: {e}")
            return {}
