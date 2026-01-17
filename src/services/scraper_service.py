"""Scraper coordination service."""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..config import get_config
from ..models.database import SessionLocal
from ..models.listing import Listing
from ..scrapers import SCRAPERS
from ..scrapers.base import ScrapedListing
from .matcher import MatchingService
from .geocoder import GeocodingService


class ScraperService:
    """Service for coordinating scraping and updating listings."""

    def __init__(self):
        self.config = get_config()
        self.matcher = MatchingService()
        self.geocoder = GeocodingService()

    def run_all_scrapers(self) -> dict:
        """
        Run all enabled scrapers and update the database.

        Returns summary of results.
        """
        results = {
            "total_found": 0,
            "new_listings": 0,
            "updated_listings": 0,
            "errors": [],
            "by_source": {},
        }

        for source in self.config.sources:
            if not source.enabled:
                continue

            scraper_class = SCRAPERS.get(source.scraper)
            if not scraper_class:
                results["errors"].append(f"Unknown scraper: {source.scraper}")
                continue

            print(f"\n[scraper] Running {source.name}...")

            try:
                with scraper_class(source.url) as scraper:
                    listings = scraper.scrape()

                source_results = self._process_listings(listings)
                results["total_found"] += source_results["found"]
                results["new_listings"] += source_results["new"]
                results["updated_listings"] += source_results["updated"]
                results["by_source"][source.name] = source_results

            except Exception as e:
                error_msg = f"Error with {source.name}: {str(e)}"
                print(f"[scraper] {error_msg}")
                results["errors"].append(error_msg)

        print(f"\n[scraper] Complete: {results['total_found']} found, "
              f"{results['new_listings']} new, {results['updated_listings']} updated")

        return results

    def _process_listings(self, scraped_listings: list[ScrapedListing]) -> dict:
        """Process scraped listings and update database."""
        results = {"found": len(scraped_listings), "new": 0, "updated": 0}

        with SessionLocal() as session:
            for scraped in scraped_listings:
                existing = self._find_existing(session, scraped)

                if existing:
                    # Update existing listing
                    self._update_listing(existing, scraped)
                    results["updated"] += 1
                else:
                    # Create new listing
                    listing = self._create_listing(scraped)
                    session.add(listing)
                    results["new"] += 1

            session.commit()

        return results

    def _find_existing(self, session: Session, scraped: ScrapedListing) -> Optional[Listing]:
        """Find an existing listing by source and source_id."""
        return session.query(Listing).filter(
            Listing.source_name == scraped.source_name,
            Listing.source_id == scraped.source_id
        ).first()

    def _create_listing(self, scraped: ScrapedListing) -> Listing:
        """Create a new Listing from scraped data."""
        listing = Listing(
            source_name=scraped.source_name,
            source_id=scraped.source_id or scraped.generate_id(),
            url=scraped.url,
            title=scraped.title,
            address=scraped.address,
            city=scraped.city,
            state=scraped.state,
            zip_code=scraped.zip_code,
            rent=scraped.rent,
            deposit=scraped.deposit,
            bedrooms=scraped.bedrooms,
            bathrooms=scraped.bathrooms,
            sqft=scraped.sqft,
            description=scraped.description,
            features=",".join(scraped.features) if scraped.features else None,
            latitude=scraped.latitude,
            longitude=scraped.longitude,
            is_new=True,
            is_active=True,
        )

        # Calculate distance if we have coordinates or address
        if scraped.latitude and scraped.longitude:
            listing.distance_miles = self.geocoder.calculate_distance(
                scraped.latitude, scraped.longitude
            )
        elif scraped.address:
            full_addr = f"{scraped.address}, {scraped.city or ''}, {scraped.state or 'WA'}"
            listing.distance_miles = self.geocoder.calculate_distance(None, None, full_addr)

        # Run matching
        self.matcher.update_listing_match(listing)

        return listing

    def _update_listing(self, listing: Listing, scraped: ScrapedListing):
        """Update an existing listing with new scraped data."""
        # Update fields that might change
        listing.rent = scraped.rent or listing.rent
        listing.title = scraped.title or listing.title
        listing.description = scraped.description or listing.description
        listing.is_active = True
        listing.last_seen = datetime.utcnow()

        # Re-run matching in case criteria changed
        self.matcher.update_listing_match(listing)

    def mark_stale_inactive(self, hours: int = 48):
        """Mark listings not seen in X hours as inactive."""
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(hours=hours)

        with SessionLocal() as session:
            stale = session.query(Listing).filter(
                Listing.last_seen < cutoff,
                Listing.is_active == True
            ).all()

            for listing in stale:
                listing.is_active = False

            session.commit()

            if stale:
                print(f"[scraper] Marked {len(stale)} listings as inactive")
