"""Matching and scoring service for rental listings."""

from enum import Enum
from typing import Optional
from dataclasses import dataclass

from ..config import get_config
from ..models.listing import Listing
from .geocoder import GeocodingService


class MatchTier(str, Enum):
    """Matching tiers for listings."""
    BEST_MATCH = "best_match"
    MATCH = "match"
    FLEXIBLE = "flexible"
    EXCLUDED = "excluded"


@dataclass
class MatchResult:
    """Result of matching a listing against criteria."""
    tier: MatchTier
    score: int  # 0-100
    matched_keywords: list[str]
    reasons: list[str]  # Why it matched/didn't match


class MatchingService:
    """Service for matching and scoring rental listings."""

    def __init__(self):
        self.config = get_config()
        self.geocoder = GeocodingService()

    def match_listing(self, listing: Listing) -> MatchResult:
        """
        Match a listing against user criteria.

        Returns a MatchResult with tier, score, and matched keywords.
        """
        reasons = []
        score = 50  # Base score
        matched_keywords = []

        # Check for dealbreakers first
        if self._has_dealbreakers(listing):
            return MatchResult(
                tier=MatchTier.EXCLUDED,
                score=0,
                matched_keywords=[],
                reasons=["Contains dealbreaker keywords"]
            )

        # Check budget
        budget_result = self._check_budget(listing)
        score += budget_result["score_adjustment"]
        reasons.extend(budget_result["reasons"])

        # Check location/distance
        distance_result = self._check_distance(listing)
        score += distance_result["score_adjustment"]
        reasons.extend(distance_result["reasons"])

        # Check room requirements
        rooms_result = self._check_rooms(listing)
        score += rooms_result["score_adjustment"]
        reasons.extend(rooms_result["reasons"])

        # Check for preferred keywords
        matched_keywords = self._find_matched_keywords(listing)
        keyword_bonus = min(len(matched_keywords) * 5, 20)  # Up to +20 for keywords
        score += keyword_bonus
        if matched_keywords:
            reasons.append(f"Has keywords: {', '.join(matched_keywords)}")

        # Determine tier based on results
        tier = self._determine_tier(
            budget_result["status"],
            distance_result["status"],
            rooms_result["status"],
            len(matched_keywords)
        )

        # Clamp score
        score = max(0, min(100, score))

        return MatchResult(
            tier=tier,
            score=score,
            matched_keywords=matched_keywords,
            reasons=reasons
        )

    def _has_dealbreakers(self, listing: Listing) -> bool:
        """Check if listing contains any dealbreaker keywords."""
        dealbreakers = [kw.lower() for kw in self.config.keywords.dealbreakers]

        # Check title and description
        text = f"{listing.title or ''} {listing.description or ''} {listing.features or ''}".lower()

        for dealbreaker in dealbreakers:
            if dealbreaker in text:
                return True

        return False

    def _check_budget(self, listing: Listing) -> dict:
        """Check if listing is within budget."""
        result = {"score_adjustment": 0, "reasons": [], "status": "unknown"}

        if listing.rent is None:
            result["reasons"].append("Rent unknown")
            result["status"] = "unknown"
            return result

        max_budget = self.config.budget.max_rent
        flexible_max = self.config.budget.flexible_max

        if listing.rent <= max_budget:
            result["score_adjustment"] = 15
            result["reasons"].append(f"Within budget (${listing.rent})")
            result["status"] = "within"
        elif listing.rent <= flexible_max:
            result["score_adjustment"] = 5
            over_by = listing.rent - max_budget
            result["reasons"].append(f"${over_by} over budget (${listing.rent})")
            result["status"] = "flexible"
        else:
            result["score_adjustment"] = -30
            over_by = listing.rent - max_budget
            result["reasons"].append(f"Over budget by ${over_by} (${listing.rent})")
            result["status"] = "over"

        return result

    def _check_distance(self, listing: Listing) -> dict:
        """Check if listing is within distance radius."""
        result = {"score_adjustment": 0, "reasons": [], "status": "unknown"}

        # Try to get distance
        distance = listing.distance_miles

        if distance is None and (listing.latitude and listing.longitude):
            distance = self.geocoder.calculate_distance(
                listing.latitude, listing.longitude
            )

        if distance is None and listing.full_address:
            distance = self.geocoder.calculate_distance(
                None, None, listing.full_address
            )

        if distance is None:
            result["reasons"].append("Distance unknown")
            result["status"] = "unknown"
            return result

        radius = self.config.location.radius_miles
        flexible_radius = self.config.location.flexible_radius_miles

        if distance <= radius:
            result["score_adjustment"] = 15
            result["reasons"].append(f"Within {distance:.1f} miles")
            result["status"] = "within"
        elif distance <= flexible_radius:
            result["score_adjustment"] = 5
            result["reasons"].append(f"{distance:.1f} miles (slightly far)")
            result["status"] = "flexible"
        else:
            result["score_adjustment"] = -30
            result["reasons"].append(f"Too far: {distance:.1f} miles")
            result["status"] = "over"

        return result

    def _check_rooms(self, listing: Listing) -> dict:
        """Check room requirements."""
        result = {"score_adjustment": 0, "reasons": [], "status": "within"}

        min_beds = self.config.rooms.min_bedrooms
        min_baths = self.config.rooms.min_bathrooms
        min_sqft = self.config.rooms.min_sqft

        # Bedrooms
        if listing.bedrooms is not None:
            if listing.bedrooms >= min_beds:
                result["score_adjustment"] += 5
                result["reasons"].append(f"{listing.bedrooms} bedrooms")
            else:
                result["score_adjustment"] -= 10
                result["reasons"].append(f"Only {listing.bedrooms} bedrooms (need {min_beds})")
                result["status"] = "under"

        # Bathrooms
        if listing.bathrooms is not None:
            if listing.bathrooms >= min_baths:
                result["score_adjustment"] += 3
            else:
                result["reasons"].append(f"Only {listing.bathrooms} bathrooms")

        # Square footage
        if listing.sqft is not None:
            if listing.sqft >= min_sqft:
                result["score_adjustment"] += 5
                result["reasons"].append(f"{listing.sqft} sqft")
            else:
                result["score_adjustment"] -= 5
                result["reasons"].append(f"Only {listing.sqft} sqft (want {min_sqft})")

        return result

    def _find_matched_keywords(self, listing: Listing) -> list[str]:
        """Find which preferred keywords are present in the listing."""
        preferred = [kw.lower() for kw in self.config.keywords.preferred]
        matched = []

        text = f"{listing.title or ''} {listing.description or ''} {listing.features or ''}".lower()

        for keyword in preferred:
            if keyword in text:
                matched.append(keyword)

        return matched

    def _determine_tier(
        self,
        budget_status: str,
        distance_status: str,
        rooms_status: str,
        keyword_count: int
    ) -> MatchTier:
        """Determine the matching tier based on individual checks."""

        # Excluded if way over budget or too far
        if budget_status == "over" or distance_status == "over":
            return MatchTier.EXCLUDED

        # Best match: within budget + within distance + has preferred keywords
        if budget_status == "within" and distance_status in ("within", "unknown"):
            if keyword_count >= 2:
                return MatchTier.BEST_MATCH

        # Match: within budget + within distance
        if budget_status == "within" and distance_status in ("within", "unknown"):
            return MatchTier.MATCH

        # Flexible: slightly over budget OR slightly far OR rooms don't quite meet requirements
        if budget_status == "flexible" or distance_status == "flexible":
            return MatchTier.FLEXIBLE

        # Unknown/incomplete data - show as flexible
        if budget_status == "unknown" or distance_status == "unknown":
            return MatchTier.FLEXIBLE

        return MatchTier.MATCH

    def update_listing_match(self, listing: Listing) -> Listing:
        """Update a listing with match information."""
        result = self.match_listing(listing)

        listing.match_tier = result.tier.value
        listing.match_score = result.score
        listing.matched_keywords = ",".join(result.matched_keywords) if result.matched_keywords else None

        return listing
