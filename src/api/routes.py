"""API routes for the rental search dashboard."""

from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..config import get_config
from ..models.database import SessionLocal
from ..models.listing import Listing
from ..services import MatchTier, ScraperService

router = APIRouter()

# Templates directory
templates = Jinja2Templates(directory="src/templates")


def get_db():
    """Database session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    tier: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    min_beds: Optional[int] = Query(None),
    max_rent: Optional[int] = Query(None),
    show_inactive: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Main dashboard view."""
    config = get_config()

    # Build query
    query = db.query(Listing)

    # Filter by active status
    if not show_inactive:
        query = query.filter(Listing.is_active == True)

    # Filter hidden
    query = query.filter(Listing.is_hidden == False)

    # Filter by tier
    if tier:
        query = query.filter(Listing.match_tier == tier)

    # Filter by source
    if source:
        query = query.filter(Listing.source_name == source)

    # Filter by bedrooms
    if min_beds:
        query = query.filter(Listing.bedrooms >= min_beds)

    # Filter by rent
    if max_rent:
        query = query.filter(Listing.rent <= max_rent)

    # Order by match tier priority, then score
    tier_order = {
        MatchTier.BEST_MATCH.value: 1,
        MatchTier.MATCH.value: 2,
        MatchTier.FLEXIBLE.value: 3,
        MatchTier.EXCLUDED.value: 4,
    }

    listings = query.all()

    # Sort in Python since SQLite doesn't have CASE easily
    listings.sort(key=lambda x: (
        tier_order.get(x.match_tier, 5),
        -(x.match_score or 0),
        x.rent or 99999,
    ))

    # Group by tier for display
    grouped = {
        "best_match": [],
        "match": [],
        "flexible": [],
    }

    for listing in listings:
        if listing.match_tier in grouped:
            grouped[listing.match_tier].append(listing)

    # Get unique sources for filter dropdown
    sources = db.query(Listing.source_name).distinct().all()
    sources = [s[0] for s in sources]

    # Count new listings
    new_count = sum(1 for l in listings if l.is_new)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "grouped": grouped,
            "sources": sources,
            "config": config,
            "new_count": new_count,
            "total_count": len(listings),
            "filters": {
                "tier": tier,
                "source": source,
                "min_beds": min_beds,
                "max_rent": max_rent,
                "show_inactive": show_inactive,
            },
        },
    )


@router.post("/listings/{listing_id}/favorite")
async def toggle_favorite(listing_id: int, db: Session = Depends(get_db)):
    """Toggle favorite status for a listing."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if listing:
        listing.is_favorite = not listing.is_favorite
        db.commit()
        return {"status": "ok", "is_favorite": listing.is_favorite}
    return {"status": "error", "message": "Listing not found"}


@router.post("/listings/{listing_id}/hide")
async def hide_listing(listing_id: int, db: Session = Depends(get_db)):
    """Hide a listing from the dashboard."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if listing:
        listing.is_hidden = True
        db.commit()
        return {"status": "ok"}
    return {"status": "error", "message": "Listing not found"}


@router.post("/listings/{listing_id}/mark-seen")
async def mark_seen(listing_id: int, db: Session = Depends(get_db)):
    """Mark a listing as seen (no longer new)."""
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if listing:
        listing.is_new = False
        db.commit()
        return {"status": "ok"}
    return {"status": "error", "message": "Listing not found"}


@router.post("/listings/mark-all-seen")
async def mark_all_seen(db: Session = Depends(get_db)):
    """Mark all listings as seen."""
    db.query(Listing).filter(Listing.is_new == True).update({"is_new": False})
    db.commit()
    return {"status": "ok"}


@router.post("/scrape/run")
async def run_scrape():
    """Manually trigger a scrape."""
    service = ScraperService()
    results = service.run_all_scrapers()
    return {"status": "ok", "results": results}


@router.get("/api/listings")
async def get_listings(
    tier: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """API endpoint to get listings as JSON."""
    query = db.query(Listing).filter(
        Listing.is_active == True,
        Listing.is_hidden == False,
    )

    if tier:
        query = query.filter(Listing.match_tier == tier)
    if source:
        query = query.filter(Listing.source_name == source)

    listings = query.all()

    return [
        {
            "id": l.id,
            "title": l.title,
            "url": l.url,
            "rent": l.rent,
            "bedrooms": l.bedrooms,
            "bathrooms": l.bathrooms,
            "sqft": l.sqft,
            "address": l.full_address,
            "match_tier": l.match_tier,
            "match_score": l.match_score,
            "matched_keywords": l.keyword_list,
            "is_new": l.is_new,
            "is_favorite": l.is_favorite,
            "source": l.source_name,
            "distance_miles": l.distance_miles,
        }
        for l in listings
    ]
