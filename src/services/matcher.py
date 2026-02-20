"""Matching and scoring service for rental listings."""

import re
from enum import Enum
from typing import Optional
from dataclasses import dataclass

from ..config import get_config
from ..models.listing import Listing
from .geocoder import GeocodingService


class MatchTier(str, Enum):
    """Matching tiers for listings."""
    BEST_MATCH = "best_match"  # Perfect match - meets all ideal criteria
    MATCH = "match"            # Close match - within budget, meets minimums
    FLEXIBLE = "flexible"      # Outliers - has some good qualities
    EXCLUDED = "excluded"      # Dealbreakers or way over budget


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

        Tiers:
        - BEST_MATCH: 3+ bed, 1500+ sqft, has keywords, within budget
        - MATCH: Within budget ($2600), 2+ bedrooms
        - FLEXIBLE: Slightly over budget ($2600-$2800) OR missing data but looks promising
        - EXCLUDED: Has dealbreakers OR way over budget
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

        # Check if city is allowed
        city_allowed = self._is_city_allowed(listing)
        if city_allowed is False:  # Explicitly False = city is known but not allowed
            return MatchResult(
                tier=MatchTier.EXCLUDED,
                score=0,
                matched_keywords=[],
                reasons=[f"City not in allowed list: {listing.city}"]
            )
        # city_allowed is None means unknown city - will go to FLEXIBLE tier later

        # Exclude 1-bedroom listings - need at least 2 bedrooms
        if listing.bedrooms is not None and listing.bedrooms < 2:
            return MatchResult(
                tier=MatchTier.EXCLUDED,
                score=0,
                matched_keywords=[],
                reasons=[f"Only {listing.bedrooms} bedroom (need 2+)"]
            )

        # Exclude listings with less than 2 bathrooms
        if listing.bathrooms is not None and listing.bathrooms < 2:
            return MatchResult(
                tier=MatchTier.EXCLUDED,
                score=0,
                matched_keywords=[],
                reasons=[f"Only {listing.bathrooms} bath (need 2+)"]
            )

        # Get all the checks
        budget_status = self._check_budget(listing)
        rooms_status = self._check_rooms(listing)
        distance_status = self._check_distance(listing)
        matched_keywords = self._find_matched_keywords(listing)

        # Build score and reasons
        score += budget_status["score"]
        score += rooms_status["score"]
        score += distance_status["score"]
        score += min(len(matched_keywords) * 5, 20)  # Up to +20 for keywords

        # Bonus for preferred zip codes
        preferred_zips = self.config.location.preferred_zips
        if preferred_zips and listing.zip_code:
            listing_zip = listing.zip_code[:5] if len(listing.zip_code) >= 5 else listing.zip_code
            if listing_zip in preferred_zips:
                score += 5

        reasons.extend(budget_status["reasons"])
        reasons.extend(rooms_status["reasons"])
        reasons.extend(distance_status["reasons"])
        if matched_keywords:
            reasons.append(f"Has keywords: {', '.join(matched_keywords)}")

        # Determine tier
        tier = self._determine_tier(
            listing=listing,
            budget_status=budget_status["status"],
            rooms_status=rooms_status,
            distance_status=distance_status["status"],
            keywords=matched_keywords,
            city_allowed=city_allowed
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
        """Check if listing contains any dealbreaker keywords.

        Smart matching: skips false positives like "no roommates" when looking for "roommate"
        """
        dealbreakers = [kw.lower() for kw in self.config.keywords.dealbreakers]
        text = f"{listing.title or ''} {listing.description or ''} {listing.features or ''}".lower()

        for dealbreaker in dealbreakers:
            if dealbreaker in text:
                # Check for false positives - "no X" or "not X" patterns
                # e.g., "no roommates" shouldn't trigger "roommate" dealbreaker
                false_positive_patterns = [
                    f"no {dealbreaker}",
                    f"no {dealbreaker}s",
                    f"not {dealbreaker}",
                    f"not {dealbreaker}s",
                ]
                is_false_positive = any(fp in text for fp in false_positive_patterns)
                if not is_false_positive:
                    return True
        return False

    # Zip code to city mapping for Thurston County area
    ZIP_TO_CITY = {
        "98501": "Olympia",
        "98502": "Olympia",
        "98503": "Lacey",
        "98506": "Olympia",
        "98512": "Tumwater",
        "98513": "Lacey",
        "98516": "Lacey",
    }

    def _is_city_allowed(self, listing: Listing) -> bool:
        """Check if listing's city is in the allowed list.

        Returns:
            True: City is known and in allowed list
            False: City is known but NOT in allowed list, OR zip code is outside our area
            None: City is unknown but zip code is in our local area (goes to FLEXIBLE)
        """
        allowed_cities = self.config.location.allowed_cities

        # If no allowed_cities configured, allow all
        if not allowed_cities:
            return True

        allowed_lower = [c.lower() for c in allowed_cities]

        # First check if city is set
        if listing.city:
            city_lower = listing.city.lower()
            # If city is in allowed list, it's allowed
            if city_lower in allowed_lower:
                return True
            # If city is NOT in allowed list, check if it's just a variation
            # or if it's actually a different city outside our area
            return False  # City is explicitly set to something not allowed

        # No city set - check if zip code is in our known local area
        if listing.zip_code:
            zip_5 = listing.zip_code[:5] if len(listing.zip_code) >= 5 else listing.zip_code
            inferred_city = self.ZIP_TO_CITY.get(zip_5)
            if inferred_city:
                # Zip is in our area - return True if city is allowed, None if unknown
                if inferred_city.lower() in allowed_lower:
                    return True
                # Zip maps to a city not in allowed list (shouldn't happen with current mapping)
                return None
            else:
                # Zip code is NOT in our known Thurston County area - EXCLUDE it
                return False

        # No city and no zip code - unknown, go to FLEXIBLE for manual review
        return None

    def _infer_city_from_zip(self, listing: Listing) -> str:
        """Try to infer city from zip code."""
        if listing.zip_code:
            return self.ZIP_TO_CITY.get(listing.zip_code[:5], None)
        return None

    def _check_budget(self, listing: Listing) -> dict:
        """Check if listing is within budget."""
        result = {"score": 0, "reasons": [], "status": "unknown"}

        if listing.rent is None:
            result["reasons"].append("Rent unknown")
            result["status"] = "unknown"
            return result

        max_budget = self.config.budget.max_rent  # $2600
        flexible_max = max_budget + 200  # $2800 for flexible range

        if listing.rent <= max_budget:
            result["score"] = 20
            result["reasons"].append(f"Within budget (${listing.rent})")
            result["status"] = "within"
        elif listing.rent <= flexible_max:
            result["score"] = 5
            over_by = listing.rent - max_budget
            result["reasons"].append(f"${over_by} over budget (${listing.rent})")
            result["status"] = "flexible"
        else:
            result["score"] = -20
            over_by = listing.rent - max_budget
            result["reasons"].append(f"Over budget by ${over_by} (${listing.rent})")
            result["status"] = "over"

        return result

    def _check_distance(self, listing: Listing) -> dict:
        """Check if listing is within distance radius."""
        result = {"score": 0, "reasons": [], "status": "unknown"}

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

        radius = self.config.location.radius_miles  # 15 miles
        flexible_radius = self.config.location.flexible_radius_miles  # 20 miles

        if distance <= radius:
            result["score"] = 10
            result["reasons"].append(f"{distance:.1f} miles away")
            result["status"] = "within"
        elif distance <= flexible_radius:
            result["score"] = 0
            result["reasons"].append(f"{distance:.1f} miles (slightly far)")
            result["status"] = "flexible"
        else:
            result["score"] = -10
            result["reasons"].append(f"Too far: {distance:.1f} miles")
            result["status"] = "over"

        return result

    def _check_rooms(self, listing: Listing) -> dict:
        """Check room requirements."""
        result = {
            "score": 0,
            "reasons": [],
            "meets_minimum": True,
            "meets_best_match": False,
            "has_bonus_room": False,
            "bedrooms": listing.bedrooms,
            "sqft": listing.sqft,
        }

        min_beds = self.config.rooms.min_bedrooms  # 2
        best_beds = self.config.rooms.best_match_bedrooms  # 3
        best_sqft = self.config.rooms.best_match_sqft  # 1500

        # Check for bonus room keywords (office, bonus room, basement, attic, den, etc.)
        # These make a 2-bedroom effectively a 3-room home
        bonus_keywords = ["office", "bonus room", "bonus", "basement", "attic", "den", "flex room", "flex space"]
        text = f"{listing.title or ''} {listing.description or ''} {listing.features or ''}".lower()
        for kw in bonus_keywords:
            if kw in text:
                result["has_bonus_room"] = True
                result["reasons"].append(f"Has {kw}")
                result["score"] += 10
                break

        # Check bedrooms - 1 bedroom is excluded (handled in match_listing)
        if listing.bedrooms is not None:
            if listing.bedrooms >= best_beds:
                result["score"] += 15
                result["reasons"].append(f"{listing.bedrooms} bedrooms")
            elif listing.bedrooms >= min_beds:
                result["score"] += 5
                result["reasons"].append(f"{listing.bedrooms} bedrooms")
                # 2-bedroom with bonus room gets extra boost
                if result["has_bonus_room"]:
                    result["score"] += 5
            else:
                result["score"] -= 10
                result["reasons"].append(f"Only {listing.bedrooms} bedrooms (need {min_beds}+)")
                result["meets_minimum"] = False

        # Check bathrooms
        if listing.bathrooms is not None:
            if listing.bathrooms >= 2:
                result["score"] += 5
            result["reasons"].append(f"{listing.bathrooms} bath")

        # Check square footage
        if listing.sqft is not None:
            if listing.sqft >= best_sqft:
                result["score"] += 10
                result["reasons"].append(f"{listing.sqft:,} sqft")
            elif listing.sqft >= self.config.rooms.min_sqft:
                result["score"] += 3
                result["reasons"].append(f"{listing.sqft:,} sqft")
            else:
                # Penalize listings below minimum sqft
                result["score"] -= 15
                result["reasons"].append(f"Too small: {listing.sqft:,} sqft (need {self.config.rooms.min_sqft}+)")
                result["meets_minimum"] = False

        # Check if meets best match criteria
        # 3+ beds with good sqft, OR 2 beds with bonus room and good sqft
        beds_ok = listing.bedrooms is not None and listing.bedrooms >= best_beds
        beds_with_bonus_ok = (listing.bedrooms is not None and
                              listing.bedrooms >= min_beds and
                              result["has_bonus_room"])
        sqft_ok = listing.sqft is not None and listing.sqft >= best_sqft
        result["meets_best_match"] = (beds_ok or beds_with_bonus_ok) and sqft_ok

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
        listing: Listing,
        budget_status: str,
        rooms_status: dict,
        distance_status: str,
        keywords: list[str],
        city_allowed: bool = True
    ) -> MatchTier:
        """
        Determine the matching tier.

        BEST_MATCH (Perfect): 3+ bed, 1500+ sqft, has keywords, within budget
        MATCH (Close): Within budget, meets minimum requirements
        FLEXIBLE (Outliers): Slightly over budget, or has some good qualities
        EXCLUDED: Way over budget or has dealbreakers
        """
        # Debug helper
        title_short = (listing.title or "Unknown")[:30]

        # Excluded: way over budget (more than $200 over)
        if budget_status == "over":
            return MatchTier.EXCLUDED

        # Excluded: too small (below minimum sqft)
        if rooms_status.get("sqft") is not None and rooms_status["sqft"] < self.config.rooms.min_sqft:
            return MatchTier.EXCLUDED

        # Unknown city (city_allowed is None) - put in FLEXIBLE tier for manual review
        if city_allowed is None:
            print(f"[matcher] {title_short}: FLEXIBLE (unknown city, city={listing.city}, zip={listing.zip_code})")
            return MatchTier.FLEXIBLE

        # Check zip code preference - listings outside preferred zips go to FLEXIBLE
        # This catches cases where city says "Olympia" but zip is actually further out
        preferred_zips = self.config.location.preferred_zips
        if preferred_zips:
            listing_zip = listing.zip_code[:5] if listing.zip_code and len(listing.zip_code) >= 5 else listing.zip_code
            if listing_zip and listing_zip not in preferred_zips:
                print(f"[matcher] {title_short}: FLEXIBLE (zip {listing_zip} not in preferred zips)")
                return MatchTier.FLEXIBLE
            elif not listing_zip:
                # No zip code available - can't verify location, always FLEXIBLE
                print(f"[matcher] {title_short}: FLEXIBLE (no zip code, can't verify preferred location)")
                return MatchTier.FLEXIBLE

        # Townhouses, duplexes, and multi-unit properties are always FLEXIBLE tier
        text = f"{listing.title or ''} {listing.address or ''} {listing.description or ''} {listing.features or ''}"
        text_lower = text.lower()
        # Check for property type keywords (use word boundaries to avoid false matches)
        for prop_type in ["townhouse", "townhome", "duplex", "triplex", "fourplex"]:
            if prop_type in text_lower:
                print(f"[matcher] {title_short}: FLEXIBLE (property type: {prop_type})")
                return MatchTier.FLEXIBLE
        # Check for unit references that indicate multi-unit or specific unit designation
        # Match: "unit 1", "unit a", "unit #", "2 unit", "multi-unit", but NOT "laundry unit", "hvac unit", "community"
        unit_match = re.search(r'\b(?:multi[- ]?unit|\d+[- ]?unit|unit\s*[#]?\s*[a-z0-9])\b', text_lower)
        if unit_match:
            # Make sure it's not a false positive like "laundry unit", "hvac unit", "ac unit"
            false_positives = ["laundry unit", "hvac unit", "ac unit", "storage unit", "washer unit", "dryer unit"]
            matched_text = unit_match.group()
            is_false_positive = any(fp in text_lower for fp in false_positives)
            if not is_false_positive:
                print(f"[matcher] {title_short}: FLEXIBLE (unit indicator: '{matched_text}')")
                return MatchTier.FLEXIBLE
        # Check for unit indicators in address like "#1", "#2", or trailing "A"/"B"
        addr_unit_match = re.search(r'#\d+|\s[ab]\s*$|\s[ab],', text_lower)
        if addr_unit_match:
            print(f"[matcher] {title_short}: FLEXIBLE (address unit: '{addr_unit_match.group()}')")
            return MatchTier.FLEXIBLE

        # BEST MATCH: Perfect listing
        # Must be within budget, meet best match room criteria, and have keywords
        if budget_status == "within":
            if rooms_status["meets_best_match"] and len(keywords) >= 1:
                return MatchTier.BEST_MATCH

        # MATCH: Close match
        # Within budget, meets minimum room requirements
        if budget_status == "within" and rooms_status["meets_minimum"]:
            return MatchTier.MATCH

        # FLEXIBLE: Has potential
        # - Slightly over budget but otherwise good
        # - Unknown budget but looks promising
        # - Within budget but doesn't meet all room requirements
        if budget_status == "flexible":
            return MatchTier.FLEXIBLE

        if budget_status == "unknown":
            # Unknown price - show as flexible so user can check
            return MatchTier.FLEXIBLE

        if budget_status == "within":
            # Within budget but room requirements not met
            return MatchTier.FLEXIBLE

        return MatchTier.FLEXIBLE

    def update_listing_match(self, listing: Listing) -> Listing:
        """Update a listing with match information."""
        result = self.match_listing(listing)

        listing.match_tier = result.tier.value
        listing.match_score = result.score
        listing.matched_keywords = ",".join(result.matched_keywords) if result.matched_keywords else None

        return listing
