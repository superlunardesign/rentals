"""Geocoding service for calculating distances."""

import re
from typing import Optional
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

from ..config import get_config


def clean_address_for_geocoding(address: str) -> str:
    """Clean address to improve geocoding success with Nominatim."""
    if not address:
        return ""

    # Remove quotes (e.g., 'S "I" St' -> 'S I St')
    cleaned = address.replace('"', '').replace("'", "")

    # Split into comma-separated parts
    parts = [p.strip() for p in cleaned.split(',')]

    # Clean the street portion (first part)
    street = parts[0] if parts else ""

    # Remove unit/apartment identifiers from the end of street part
    # Handles: "- Unit A", "- D8", "- #2", "- C5", "- 200"
    street = re.sub(r'\s*[-–]\s*(?:Unit|Apt|Spc|Suite|Ste)?\.?\s*#?\s*[A-Za-z]?\d*[A-Za-z]?\s*$', '', street, flags=re.IGNORECASE)
    # Handles: "#2", "#A107", "#504", "# S"
    street = re.sub(r'\s*#\s*[A-Za-z0-9-]*\s*$', '', street, flags=re.IGNORECASE)
    # Handles: "Unit A", "Unit 101", "Apt 4", "Apt. #20", "Suite C", "Spc 5", "unit D"
    street = re.sub(r'\s+(?:Unit|Apt\.?|Suite|Ste\.?|Spc)\s*#?\s*[A-Za-z0-9-]+\s*$', '', street, flags=re.IGNORECASE)

    # Fix missing space between street number and name (e.g., "1415Evergreen" -> "1415 Evergreen")
    street = re.sub(r'^(\d+)([A-Z])', r'\1 \2', street)

    parts[0] = street.strip()

    # Filter out parts that look like unit numbers or duplicate city names
    cleaned_parts = []
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue

        # Skip parts that are just unit/apt numbers (e.g., "1415-104", "201A", "A6")
        if i > 0 and re.match(r'^(?:Unit\s*)?(?:\d+[A-Za-z]?|\d+-\d+[A-Za-z]?|[A-Za-z]\d+)$', part, re.IGNORECASE):
            continue

        # Skip duplicate parts (e.g., "Lacey, Lacey, WA")
        if cleaned_parts and part.upper() == cleaned_parts[-1].upper():
            continue

        cleaned_parts.append(part)

    cleaned = ', '.join(cleaned_parts)

    # Clean up extra whitespace and trailing punctuation
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = cleaned.strip(' ,')

    return cleaned


class GeocodingService:
    """Service for geocoding addresses and calculating distances."""

    def __init__(self):
        self.geolocator = Nominatim(user_agent="rental_search_app")
        self.config = get_config()
        self._cache = {}

        # Center point from config
        self.center = (
            self.config.location.latitude,
            self.config.location.longitude
        )

    def geocode_address(self, address: str) -> Optional[tuple[float, float]]:
        """
        Convert an address to coordinates.
        Only caches successful results.

        Returns (latitude, longitude) or None if geocoding fails.
        """
        # Check cache (only successful results are cached)
        if address in self._cache:
            return self._cache[address]

        try:
            # Add state context for better results
            query = address
            if "WA" not in address.upper() and "WASHINGTON" not in address.upper():
                query = f"{address}, WA"

            location = self.geolocator.geocode(query, timeout=10)
            if location:
                result = (location.latitude, location.longitude)
                self._cache[address] = result
                return result
        except Exception as e:
            print(f"[geocoder] Error geocoding '{address}': {e}")

        return None

    def geocode_with_fallback(self, address: str, city: str = None, state: str = None, zip_code: str = None) -> Optional[tuple[float, float]]:
        """
        Try geocoding with progressively simpler address forms.
        """
        # First: try the cleaned full address
        cleaned = clean_address_for_geocoding(address)
        if cleaned:
            result = self.geocode_address(cleaned)
            if result:
                return result

        # Second: try just the street number + street name + city + state
        # Extract just the street number and name (strip everything after the number+name)
        if cleaned:
            # Try to extract just "123 Main St" from "123 Main St SE - Unit 4"
            street_match = re.match(r'^(\d+\s+\S+(?:\s+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Blvd|Boulevard|Ln|Lane|Way|Ct|Court|Pl|Place|Loop|Cir|Circle|Hwy|Highway|Pkwy|Parkway)\.?)(?:\s+(?:NE|NW|SE|SW|N|S|E|W))?)', cleaned, re.IGNORECASE)
            if street_match and city:
                simple = f"{street_match.group(1)}, {city}"
                if state:
                    simple += f", {state}"
                result = self.geocode_address(simple)
                if result:
                    return result

        # Third: try with just zip code for approximate location
        if zip_code:
            result = self.geocode_address(f"{zip_code}, WA")
            if result:
                return result

        return None

    def calculate_distance(
        self,
        lat: Optional[float],
        lon: Optional[float],
        address: Optional[str] = None
    ) -> Optional[float]:
        """
        Calculate distance in miles from the center point.

        If lat/lon not provided, will attempt to geocode the address.
        """
        # If we have coordinates, use them
        if lat is not None and lon is not None:
            point = (lat, lon)
        elif address:
            # Try to geocode the address
            coords = self.geocode_address(address)
            if coords:
                point = coords
            else:
                return None
        else:
            return None

        try:
            distance = geodesic(self.center, point).miles
            return round(distance, 2)
        except Exception as e:
            print(f"[geocoder] Error calculating distance: {e}")
            return None

    def is_within_radius(
        self,
        lat: Optional[float],
        lon: Optional[float],
        address: Optional[str] = None,
        radius_miles: Optional[float] = None
    ) -> bool:
        """Check if a location is within the configured radius."""
        if radius_miles is None:
            radius_miles = self.config.location.radius_miles

        distance = self.calculate_distance(lat, lon, address)
        if distance is None:
            return False

        return distance <= radius_miles

    def is_within_flexible_radius(
        self,
        lat: Optional[float],
        lon: Optional[float],
        address: Optional[str] = None
    ) -> bool:
        """Check if a location is within the flexible radius."""
        return self.is_within_radius(
            lat, lon, address,
            radius_miles=self.config.location.flexible_radius_miles
        )
