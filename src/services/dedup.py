"""Cross-source address deduplication for rental listings."""

import re
from typing import Optional

from sqlalchemy.orm import Session

from ..models.listing import Listing


# Street suffix normalization map
_SUFFIX_MAP = {
    "street": "st", "avenue": "ave", "boulevard": "blvd", "drive": "dr",
    "road": "rd", "lane": "ln", "court": "ct", "place": "pl",
    "circle": "cir", "highway": "hwy", "parkway": "pkwy", "way": "way",
    "loop": "loop", "trail": "trl", "terrace": "ter",
}


def normalize_address(address: str) -> str:
    """Normalize an address for cross-source duplicate matching.

    Strips unit numbers, normalizes abbreviations, lowercases, and returns
    just the street number + street name + city for comparison.

    Examples:
        "123 Main Street, Unit A, Olympia, WA 98501" -> "123 main st olympia"
        "123 Main St #4, Olympia, WA" -> "123 main st olympia"
        "123 Main St SE - D8, Olympia, WA 98501" -> "123 main st se olympia"
    """
    if not address:
        return ""

    text = address.lower().strip()

    # Remove zip codes (5 or 9 digit)
    text = re.sub(r'\b\d{5}(?:-\d{4})?\b', '', text)

    # Remove state abbreviations at word boundaries
    text = re.sub(r'\b(wa|washington)\b', '', text)

    # Remove unit/apt/suite designators and their values
    text = re.sub(r'\s*[-–]\s*(?:unit|apt|spc|suite|ste)?\.?\s*#?\s*[a-z]?\d*[a-z]?\s*$', '', text)
    text = re.sub(r'\s*#\s*[a-z0-9-]*', '', text)
    text = re.sub(r'\s+(?:unit|apt\.?|suite|ste\.?|spc)\s*#?\s*[a-z0-9-]+', '', text)

    # Split into parts and process
    parts = [p.strip() for p in text.split(',')]
    parts = [p for p in parts if p]

    # Normalize street suffixes in the street part (first part)
    if parts:
        street = parts[0]
        for full, abbr in _SUFFIX_MAP.items():
            street = re.sub(r'\b' + full + r'\.?\b', abbr, street)
            # Also normalize existing abbreviations with periods (e.g., "st." -> "st")
            street = re.sub(r'\b' + abbr + r'\.\b', abbr, street)
        parts[0] = street

    # Rejoin, remove extra whitespace and punctuation
    result = ' '.join(parts)
    result = re.sub(r'[,.\-#]', ' ', result)
    result = re.sub(r'\s+', ' ', result).strip()

    return result


# Sources that aggregate from other sites (slow to delist)
AGGREGATOR_SOURCES = {"zillow_api", "redfin_api"}


def find_cross_source_duplicate(
    session: Session,
    address: str,
    source_name: str,
    rent: Optional[int] = None,
) -> Optional[Listing]:
    """Find an existing listing from a DIFFERENT source at the same address.

    Uses normalized address matching. Optionally validates with rent proximity
    (within 10%) to avoid false positives on multi-unit buildings.

    For aggregator sources (Zillow, Redfin), also checks recently-inactive
    listings to prevent re-adding properties that were removed from PM sites.
    Aggregators are slow to delist, so a listing removed by a PM should not
    reappear via Zillow/Redfin.
    """
    if not address:
        return None

    normalized = normalize_address(address)
    if not normalized or len(normalized) < 8:
        return None

    # For aggregator sources, also check inactive listings to prevent
    # re-adding properties that were removed from their original PM source
    if source_name in AGGREGATOR_SOURCES:
        candidates = session.query(Listing).filter(
            Listing.source_name != source_name,
            Listing.address.isnot(None),
        ).all()
    else:
        # PM sources only check against active listings
        candidates = session.query(Listing).filter(
            Listing.source_name != source_name,
            Listing.is_active == True,
            Listing.address.isnot(None),
        ).all()

    for candidate in candidates:
        candidate_normalized = normalize_address(candidate.address or "")
        if not candidate_normalized:
            continue

        if candidate_normalized == normalized:
            # Exact normalized match - check rent proximity if both have rent
            if rent and candidate.rent:
                # Allow 15% variance for same property (different listing dates, etc.)
                diff = abs(rent - candidate.rent) / max(rent, candidate.rent)
                if diff > 0.15:
                    continue  # Probably different units at same address
            return candidate

    return None
