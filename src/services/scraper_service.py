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
from .notifier import NotificationService
from .dedup import find_cross_source_duplicate


class ScraperService:
    """Service for coordinating scraping and updating listings."""

    def __init__(self):
        self.config = get_config()
        self.matcher = MatchingService()
        self.geocoder = GeocodingService()
        self.notifier = NotificationService()

    def run_all_scrapers(self) -> dict:
        """
        Run all enabled scrapers and update the database.

        Returns summary of results.
        """
        results = {
            "total_found": 0,
            "new_listings": 0,
            "updated_listings": 0,
            "removed_listings": 0,
            "notifications_sent": 0,
            "errors": [],
            "by_source": {},
        }

        # Track all found source_ids per source_name (for scrapers used by multiple sources)
        all_found_ids_by_source: dict[str, set] = {}
        # Track new listings for notifications
        new_listings_for_notification: list[Listing] = []

        for source in self.config.sources:
            if not source.enabled:
                continue

            scraper_class = SCRAPERS.get(source.scraper)
            if not scraper_class:
                results["errors"].append(f"Unknown scraper: {source.scraper}")
                continue

            print(f"\n[scraper] Running {source.name}...")

            try:
                print(f"[scraper] Initializing {source.scraper} scraper...")
                with scraper_class(source.url) as scraper:
                    print(f"[scraper] Scraper initialized, starting scrape...")

                    # For scrapers that support incremental saving (PropertyWare)
                    incremental_results = {"found_ids": set(), "new": 0, "updated": 0, "new_listing_objects": []}
                    if hasattr(scraper, 'set_on_listing_callback'):
                        def on_listing(scraped):
                            """Save each listing immediately as it's parsed."""
                            result = self._process_single_listing(scraped, scraper.source_name)
                            if result:
                                incremental_results["found_ids"].add(result["source_id"])
                                if result["is_new"]:
                                    incremental_results["new"] += 1
                                    if result.get("listing"):
                                        incremental_results["new_listing_objects"].append(result["listing"])
                                        # Send notification immediately for new listing
                                        self.notifier.notify_new_listings([result["listing"]])
                                else:
                                    incremental_results["updated"] += 1

                        scraper.set_on_listing_callback(on_listing)

                    listings = scraper.scrape()

                    # If we used incremental saving, use those results
                    if hasattr(scraper, 'set_on_listing_callback') and incremental_results["found_ids"]:
                        source_results = {
                            "found": len(incremental_results["found_ids"]),
                            "new": incremental_results["new"],
                            "updated": incremental_results["updated"],
                            "found_ids": incremental_results["found_ids"],
                            "new_listing_objects": [],  # Already notified incrementally
                        }
                    else:
                        # Regular batch processing for other scrapers
                        source_results = self._process_listings(
                            listings,
                            scraper=scraper,
                            source_name=scraper.source_name,
                            remove_stale=False
                        )

                    # Accumulate found IDs for this source_name
                    if scraper.source_name not in all_found_ids_by_source:
                        all_found_ids_by_source[scraper.source_name] = set()
                    all_found_ids_by_source[scraper.source_name].update(
                        source_results.get("found_ids", set())
                    )

                results["total_found"] += source_results["found"]
                results["new_listings"] += source_results["new"]
                results["updated_listings"] += source_results["updated"]
                results["by_source"][source.name] = source_results

                # Collect new listings for notifications
                new_listings_for_notification.extend(source_results.get("new_listing_objects", []))

            except Exception as e:
                error_msg = f"Error with {source.name}: {str(e)}"
                print(f"[scraper] {error_msg}")
                import traceback
                traceback.print_exc()
                results["errors"].append(error_msg)

        # Now remove stale listings for each source_name
        removed = self._remove_stale_listings(all_found_ids_by_source)
        results["removed_listings"] = removed

        # Send notifications for new matching listings
        if new_listings_for_notification:
            notif_results = self.notifier.notify_new_listings(new_listings_for_notification)
            results["notifications_sent"] = notif_results.get("telegram_sent", 0)
            if results["notifications_sent"] > 0:
                print(f"[scraper] Sent {results['notifications_sent']} notifications")

        print(f"\n[scraper] Complete: {results['total_found']} found, "
              f"{results['new_listings']} new, {results['updated_listings']} updated, "
              f"{results['removed_listings']} removed, {results['notifications_sent']} notifications")

        return results

    def _remove_stale_listings(self, all_found_ids_by_source: dict[str, set]) -> int:
        """Remove listings that weren't found in the latest scrape."""
        removed = 0

        with SessionLocal() as session:
            for source_name, found_ids in all_found_ids_by_source.items():
                if not found_ids:
                    # Don't delete anything if scraper found nothing
                    continue

                stale_listings = session.query(Listing).filter(
                    Listing.source_name == source_name,
                    ~Listing.source_id.in_(found_ids)
                ).all()

                for stale in stale_listings:
                    print(f"[scraper] Removing stale listing: {stale.title}")
                    session.delete(stale)
                    removed += 1

            session.commit()

        return removed

    def _process_single_listing(self, scraped: ScrapedListing, source_name: str) -> Optional[dict]:
        """Process and save a single listing immediately. Used for incremental saving."""
        try:
            source_id = scraped.source_id or scraped.generate_id()

            with SessionLocal() as session:
                existing = self._find_existing(session, scraped)

                if existing:
                    price_drop = self._update_listing(existing, scraped)
                    session.commit()
                    if price_drop:
                        # Notify about price drop
                        self.notifier.notify_price_drop(price_drop)
                    return {"source_id": source_id, "is_new": False, "listing": None, "price_drop": price_drop}

                # Check for cross-source duplicate
                dupe = find_cross_source_duplicate(
                    session, scraped.address, scraped.source_name, scraped.rent
                )
                if dupe:
                    short = (scraped.address or scraped.title or "")[:40]
                    print(f"[scraper] Skipping duplicate: {short} (already from {dupe.source_name})")
                    return {"source_id": source_id, "is_new": False, "listing": None}

                listing = self._create_listing(scraped)
                session.add(listing)
                session.commit()
                session.refresh(listing)
                return {"source_id": source_id, "is_new": True, "listing": listing}

        except Exception as e:
            print(f"[scraper] Error saving listing: {e}")
            return None

    def _process_listings(self, scraped_listings: list[ScrapedListing], scraper=None, source_name: str = None, remove_stale: bool = True) -> dict:
        """Process scraped listings and update database.

        If scraper is provided and listing is missing key data, will fetch detail page.
        """
        results = {"found": len(scraped_listings), "new": 0, "updated": 0, "found_ids": set(), "new_listing_objects": []}

        with SessionLocal() as session:
            for scraped in scraped_listings:
                # Track this source_id as found
                source_id = scraped.source_id or scraped.generate_id()
                results["found_ids"].add(source_id)

                # Check if we're missing important data and should fetch detail page
                missing_key_data = (
                    scraped.bedrooms is None or
                    scraped.bathrooms is None or
                    scraped.sqft is None or
                    not scraped.features
                )

                if missing_key_data and scraper and scraped.url:
                    try:
                        print(f"[scraper] Fetching detail page: {scraped.url}")
                        details = scraper.scrape_detail_page(scraped.url)

                        # Fill in missing data
                        if details.get("bedrooms") and scraped.bedrooms is None:
                            scraped.bedrooms = details["bedrooms"]
                        if details.get("bathrooms") and scraped.bathrooms is None:
                            scraped.bathrooms = details["bathrooms"]
                        if details.get("sqft") and scraped.sqft is None:
                            scraped.sqft = details["sqft"]
                        if details.get("description") and not scraped.description:
                            scraped.description = details["description"]
                        if details.get("features"):
                            scraped.features = details["features"]

                    except Exception as e:
                        print(f"[scraper] Error fetching detail page: {e}")

                existing = self._find_existing(session, scraped)

                if existing:
                    # Update existing listing
                    price_drop = self._update_listing(existing, scraped)
                    results["updated"] += 1
                    if price_drop:
                        # Track for price drop notification
                        if "price_drops" not in results:
                            results["price_drops"] = []
                        results["price_drops"].append(price_drop)
                else:
                    # Check for cross-source duplicate (same address from different source)
                    dupe = find_cross_source_duplicate(
                        session, scraped.address, scraped.source_name, scraped.rent
                    )
                    if dupe:
                        short = (scraped.address or scraped.title or "")[:40]
                        print(f"[scraper] Skipping duplicate: {short} (already from {dupe.source_name})")
                        results["updated"] += 1
                        continue

                    # Create new listing
                    listing = self._create_listing(scraped)
                    session.add(listing)
                    results["new"] += 1
                    # Track for notifications (will be sent after commit)
                    results["new_listing_objects"].append(listing)

            session.commit()

            # Refresh listing objects to get IDs after commit
            for listing in results["new_listing_objects"]:
                session.refresh(listing)

            # Send price drop notifications
            if results.get("price_drops"):
                for price_drop in results["price_drops"]:
                    self.notifier.notify_price_drop(price_drop)

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
            image_url=scraped.image_url,
            is_new=True,
            is_active=True,
        )

        # Calculate distance if we have coordinates or address
        if scraped.latitude and scraped.longitude:
            listing.distance_miles = self.geocoder.calculate_distance(
                scraped.latitude, scraped.longitude
            )
        elif scraped.address:
            coords = self.geocoder.geocode_with_fallback(
                scraped.address,
                city=scraped.city,
                state=scraped.state or "WA",
                zip_code=scraped.zip_code,
            )
            if coords:
                listing.latitude = coords[0]
                listing.longitude = coords[1]
                listing.distance_miles = self.geocoder.calculate_distance(coords[0], coords[1])

        # Fill missing zip code via reverse geocoding
        if not listing.zip_code and listing.latitude and listing.longitude:
            listing.zip_code = self.geocoder.reverse_geocode_zip(
                listing.latitude, listing.longitude
            )
            if listing.zip_code:
                print(f"[scraper] Filled missing zip for '{(listing.title or 'Unknown')[:35]}' -> {listing.zip_code}")

        # Run matching
        self.matcher.update_listing_match(listing)

        # Log the result
        tier = listing.match_tier or "unknown"
        tier_emoji = {
            "best_match": "🌟",
            "match": "✅",
            "flexible": "🔶",
            "excluded": "❌"
        }.get(tier, "❓")

        short_title = (listing.title or "Unknown")[:35]
        reason = ""
        if tier == "excluded":
            # Try to identify why
            if listing.bedrooms and listing.bedrooms < 2:
                reason = "(1 bed)"
            elif listing.bathrooms and listing.bathrooms < 2:
                reason = "(< 2 bath)"
            elif listing.sqft and listing.sqft < 1200:
                reason = "(< 1200 sqft)"
            elif listing.rent and listing.rent > 2800:
                reason = "(over budget)"
            elif not listing.city:
                reason = "(unknown city)"
            else:
                reason = "(filtered)"

        print(f"[scraper] {tier_emoji} {tier.upper()}: {short_title}... {reason}")

        return listing

    def _update_listing(self, listing: Listing, scraped: ScrapedListing) -> Optional[dict]:
        """Update an existing listing with new scraped data.

        Returns price drop info if detected: {"old_rent": X, "new_rent": Y, "listing": listing}
        """
        price_drop = None

        # Check for price drop before updating
        if scraped.rent and listing.rent and scraped.rent < listing.rent:
            drop_amount = listing.rent - scraped.rent
            drop_percent = (drop_amount / listing.rent) * 100
            print(f"[scraper] 💰 PRICE DROP: {listing.title[:30]}... ${listing.rent} → ${scraped.rent} (-${drop_amount}, -{drop_percent:.1f}%)")
            price_drop = {
                "old_rent": listing.rent,
                "new_rent": scraped.rent,
                "drop_amount": drop_amount,
                "drop_percent": drop_percent,
            }

        # Update fields that might change
        listing.rent = scraped.rent or listing.rent
        listing.title = scraped.title or listing.title
        listing.description = scraped.description or listing.description
        listing.image_url = scraped.image_url or listing.image_url
        listing.url = scraped.url or listing.url  # Update URL in case it changed
        listing.is_active = True
        listing.last_seen = datetime.utcnow()

        # Update specs if newly found
        if scraped.bedrooms and not listing.bedrooms:
            listing.bedrooms = scraped.bedrooms
        if scraped.bathrooms and not listing.bathrooms:
            listing.bathrooms = scraped.bathrooms
        if scraped.sqft and not listing.sqft:
            listing.sqft = scraped.sqft

        # Update features if found
        if scraped.features:
            listing.features = ",".join(scraped.features)

        # Re-run matching in case criteria changed
        self.matcher.update_listing_match(listing)

        # Return price drop info if detected
        if price_drop:
            price_drop["listing"] = listing
        return price_drop

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
