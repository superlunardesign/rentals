"""Scheduler for running scrapers periodically."""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import get_config
from .services.scraper_service import ScraperService


class RentalScheduler:
    """Scheduler for periodic scraping jobs."""

    def __init__(self):
        self.config = get_config()
        self.scheduler = BackgroundScheduler()
        self.scraper_service = ScraperService()
        self._current_interval_minutes = self.config.scheduler.interval_hours * 60

    def start(self):
        """Start the scheduler."""
        interval_hours = self.config.scheduler.interval_hours
        self._current_interval_minutes = interval_hours * 60

        # Add the scraping job
        self.scheduler.add_job(
            self._run_scrape_job,
            trigger=IntervalTrigger(hours=interval_hours),
            id="scrape_listings",
            name="Scrape rental listings",
            replace_existing=True,
        )

        # Add cleanup job (runs daily)
        self.scheduler.add_job(
            self._run_cleanup_job,
            trigger=IntervalTrigger(hours=24),
            id="cleanup_stale",
            name="Mark stale listings inactive",
            replace_existing=True,
        )

        self.scheduler.start()
        print(f"[scheduler] Started - scraping every {interval_hours} hour(s)")

        # Run immediately if configured (in background thread so server can start)
        if self.config.scheduler.run_on_startup:
            import threading
            import time

            def delayed_scrape():
                # Wait for server to fully start and bind port (Render needs this)
                time.sleep(5)
                self._run_scrape_job()

            print("[scheduler] Initial scrape will start in 5 seconds...")
            thread = threading.Thread(target=delayed_scrape, daemon=True)
            thread.start()

    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown()
        print("[scheduler] Stopped")

    def update_interval(self, minutes: int):
        """Update the scraping interval dynamically."""
        self._current_interval_minutes = minutes

        # Remove existing job and add with new interval
        self.scheduler.remove_job("scrape_listings")
        self.scheduler.add_job(
            self._run_scrape_job,
            trigger=IntervalTrigger(minutes=minutes),
            id="scrape_listings",
            name="Scrape rental listings",
            replace_existing=True,
        )

        if minutes >= 60:
            interval_str = f"{minutes // 60} hour(s)"
        else:
            interval_str = f"{minutes} minute(s)"
        print(f"[scheduler] Updated interval to {interval_str}")

    def get_interval_minutes(self) -> int:
        """Get the current scraping interval in minutes."""
        return self._current_interval_minutes

    def _run_scrape_job(self):
        """Run the scraping job."""
        print("\n" + "=" * 50)
        print("[scheduler] Starting scrape job...")
        print("=" * 50)

        try:
            results = self.scraper_service.run_all_scrapers()
            print(f"[scheduler] Scrape complete: {results}")
        except Exception as e:
            print(f"[scheduler] Error in scrape job: {e}")

    def _run_cleanup_job(self):
        """Run the cleanup job."""
        print("[scheduler] Running cleanup...")
        try:
            self.scraper_service.mark_stale_inactive()
        except Exception as e:
            print(f"[scheduler] Error in cleanup job: {e}")

    def run_now(self):
        """Manually trigger a scrape immediately."""
        self._run_scrape_job()
