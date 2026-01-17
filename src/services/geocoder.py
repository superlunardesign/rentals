"""Geocoding service for calculating distances."""

from functools import lru_cache
from typing import Optional
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

from ..config import get_config


class GeocodingService:
    """Service for geocoding addresses and calculating distances."""

    def __init__(self):
        self.geolocator = Nominatim(user_agent="rental_search_app")
        self.config = get_config()

        # Center point from config
        self.center = (
            self.config.location.latitude,
            self.config.location.longitude
        )

    @lru_cache(maxsize=1000)
    def geocode_address(self, address: str) -> Optional[tuple[float, float]]:
        """
        Convert an address to coordinates.

        Returns (latitude, longitude) or None if geocoding fails.
        """
        try:
            # Add state context for better results
            if "WA" not in address.upper() and "WASHINGTON" not in address.upper():
                address = f"{address}, WA"

            location = self.geolocator.geocode(address, timeout=10)
            if location:
                return (location.latitude, location.longitude)
        except Exception as e:
            print(f"[geocoder] Error geocoding '{address}': {e}")

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
