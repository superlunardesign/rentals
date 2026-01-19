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
    city: Optional[str] = Query(None),
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

    # Filter by city
    if city:
        query = query.filter(Listing.city == city)

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
    # Within each tier: highest rent first (most expensive to least)
    listings.sort(key=lambda x: (
        tier_order.get(x.match_tier, 5),
        -(x.rent or 0),  # Most expensive first
        -(x.match_score or 0),
    ))

    # Group by tier for display
    # Use manual_tier if set, otherwise use automatic match_tier
    grouped = {
        "favorites": [],
        "best_match": [],
        "match": [],
        "flexible": [],
        "excluded": [],
    }

    for listing in listings:
        # Determine effective tier (manual override takes precedence)
        effective_tier = listing.manual_tier or listing.match_tier

        if listing.is_favorite:
            grouped["favorites"].append(listing)
        elif effective_tier == "excluded":
            grouped["excluded"].append(listing)
        elif effective_tier in grouped:
            grouped[effective_tier].append(listing)

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


@router.post("/listings/{listing_id}/set-tier/{tier}")
async def set_manual_tier(listing_id: int, tier: str, db: Session = Depends(get_db)):
    """Manually set a listing's tier (overrides automatic matching)."""
    valid_tiers = ["best_match", "match", "flexible", "excluded", "clear"]
    if tier not in valid_tiers:
        return {"status": "error", "message": f"Invalid tier. Must be one of: {valid_tiers}"}

    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if listing:
        if tier == "clear":
            listing.manual_tier = None  # Clear override, use automatic
        else:
            listing.manual_tier = tier
        db.commit()
        return {"status": "ok", "manual_tier": listing.manual_tier}
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
    """Manually trigger a scrape in background."""
    import threading

    def run_in_background():
        try:
            service = ScraperService()
            results = service.run_all_scrapers()
            print(f"[manual scrape] Complete: {results}")
        except Exception as e:
            print(f"[manual scrape] Error: {e}")

    thread = threading.Thread(target=run_in_background, daemon=True)
    thread.start()

    return {"status": "ok", "message": "Scrape started in background", "results": {"total_found": "pending", "new_listings": "pending"}}


@router.get("/scrape/debug/{scraper_name}")
async def debug_scraper(scraper_name: str):
    """Debug a specific scraper - returns detailed info about what's happening."""
    import traceback
    import io
    import sys

    from ..scrapers import OlyrentsScraper, TeamNWPMScraper, AMHScraper

    scrapers = {
        "olyrents": OlyrentsScraper,
        "teamnwpm": TeamNWPMScraper,
        "amh": AMHScraper,
    }

    if scraper_name not in scrapers:
        return {"error": f"Unknown scraper: {scraper_name}. Available: {list(scrapers.keys())}"}

    # Capture stdout
    old_stdout = sys.stdout
    sys.stdout = captured = io.StringIO()

    result = {
        "scraper": scraper_name,
        "success": False,
        "listings_found": 0,
        "listings": [],
        "logs": "",
        "error": None,
        "html_preview": None,
        "http_status": None,
    }

    try:
        scraper_class = scrapers[scraper_name]
        print(f"[debug] Starting {scraper_name} scraper...")

        with scraper_class() as scraper:
            print(f"[debug] Fetching URL: {scraper.base_url}")

            # First, get the raw HTML to see what we're dealing with
            try:
                response = scraper.client.get(scraper.base_url)
                result["http_status"] = response.status_code
                html = response.text
                # Show first 1000 chars of HTML for debugging
                result["html_preview"] = html[:1000] if html else "Empty response"
                print(f"[debug] HTTP Status: {response.status_code}")
                print(f"[debug] Response length: {len(html)} chars")
            except Exception as e:
                result["html_preview"] = f"Failed to fetch: {e}"
                print(f"[debug] Fetch failed: {e}")

            listings = scraper.scrape()

            result["success"] = True
            result["listings_found"] = len(listings)
            result["listings"] = [
                {
                    "title": l.title[:50] if l.title else None,
                    "url": l.url,
                    "rent": l.rent,
                    "bedrooms": l.bedrooms,
                    "bathrooms": l.bathrooms,
                    "sqft": l.sqft,
                    "image_url": l.image_url[:100] if l.image_url else None,
                }
                for l in listings[:10]  # Limit to first 10 for debug
            ]

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {str(e)}"
        result["traceback"] = traceback.format_exc()
        print(f"[debug] ERROR: {e}")
        traceback.print_exc()

    finally:
        sys.stdout = old_stdout
        result["logs"] = captured.getvalue()

    return result


@router.post("/listings/rematch")
async def rematch_all_listings(db: Session = Depends(get_db)):
    """Re-run matching on all listings with current criteria."""
    from ..services import MatchingService

    matcher = MatchingService()
    listings = db.query(Listing).all()

    updated = 0
    for listing in listings:
        old_tier = listing.match_tier
        matcher.update_listing_match(listing)
        if listing.match_tier != old_tier:
            updated += 1

    db.commit()

    # Count by tier
    tier_counts = {}
    for listing in listings:
        tier = listing.match_tier or "unknown"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    return {
        "status": "ok",
        "total": len(listings),
        "updated": updated,
        "by_tier": tier_counts
    }


@router.post("/telegram/test")
async def test_telegram():
    """Test Telegram notification setup."""
    from ..services.notifier import TelegramNotifier

    notifier = TelegramNotifier()
    result = {
        "enabled": notifier.enabled,
        "bot_token_set": bool(notifier.bot_token),
        "chat_id": notifier.chat_id,
        "notify_tiers": notifier.notify_tiers,
    }

    if notifier.enabled:
        success = notifier.send_test_message()
        result["test_sent"] = success
    else:
        result["test_sent"] = False
        result["reason"] = "Telegram not enabled - check bot_token and chat_id"

    return result


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
