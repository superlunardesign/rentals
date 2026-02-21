#!/usr/bin/env python3
"""
Rental Search - Tumwater/Olympia, WA

A web scraper and dashboard for finding rental properties.

Usage:
    python main.py              # Start the web dashboard with scheduler
    python main.py --scrape     # Run scrapers once (no web server)
    python main.py --no-schedule # Start web server without auto-scraping
"""

import argparse
import os

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from fastapi import FastAPI

from src.config import get_config
from src.models.database import init_db
from src.api.routes import router
from src.scheduler import RentalScheduler
from src.services import ScraperService


# Global scheduler reference for status endpoint
_scheduler = None


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    global _scheduler

    application = FastAPI(
        title="Rental Search",
        description="Property rental search for Tumwater/Olympia, WA",
        version="1.0.0"
    )

    # Include routes
    application.include_router(router)

    # Start scheduler on startup (works with uvicorn main:app on Render)
    @application.on_event("startup")
    async def startup_event():
        global _scheduler
        config = get_config()

        # Check if scheduler is disabled via env var (set by --no-schedule flag)
        if os.environ.get("DISABLE_SCHEDULER") == "1":
            print("[startup] Scheduler disabled via DISABLE_SCHEDULER env var")
            return

        # Start the scheduler for periodic scraping
        _scheduler = RentalScheduler()
        _scheduler.start()
        print(f"[startup] Scheduler started - scraping every {config.scheduler.interval_hours} hour(s)")

    @application.on_event("shutdown")
    async def shutdown_event():
        global _scheduler
        if _scheduler:
            _scheduler.stop()
            print("[shutdown] Scheduler stopped")

    # Scheduler status endpoint
    @application.get("/scheduler/status")
    async def scheduler_status():
        """Get scheduler status and next run times."""
        global _scheduler
        if not _scheduler:
            return {"status": "not running", "jobs": [], "interval_minutes": 60}

        jobs = []
        for job in _scheduler.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "next_run_human": job.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if job.next_run_time else None,
            })

        return {
            "status": "running",
            "jobs": jobs,
            "interval_minutes": _scheduler.get_interval_minutes(),
        }

    @application.post("/scheduler/interval/{minutes}")
    async def set_scheduler_interval(minutes: int):
        """Update the scheduler interval (in minutes)."""
        global _scheduler

        # Validate minutes (5 min to 24 hours)
        if minutes < 5 or minutes > 1440:
            return {"success": False, "error": "Interval must be between 5 and 1440 minutes"}

        if not _scheduler:
            return {"success": False, "error": "Scheduler not running"}

        _scheduler.update_interval(minutes)

        if minutes >= 60:
            interval_str = f"{minutes // 60} hour(s)"
        else:
            interval_str = f"{minutes} minute(s)"

        return {
            "success": True,
            "interval_minutes": minutes,
            "message": f"Scrape interval updated to {interval_str}",
        }

    return application


# Create app at module level for uvicorn import (e.g., uvicorn main:app)
print("[startup] Initializing database...")
init_db()
app = create_app()


def main():
    """Main entry point for CLI usage."""
    parser = argparse.ArgumentParser(description="Rental property search tool")
    parser.add_argument(
        "--scrape",
        action="store_true",
        help="Run scrapers once and exit (don't start web server)"
    )
    parser.add_argument(
        "--no-schedule",
        action="store_true",
        help="Start web server without automatic scraping"
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host to bind to (default: from config)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind to (default: from config)"
    )

    args = parser.parse_args()

    config = get_config()

    # If scrape-only mode, just run scrapers and exit
    if args.scrape:
        print("[startup] Running scrapers...")
        service = ScraperService()
        results = service.run_all_scrapers()
        print(f"\n[complete] Results: {results}")
        return

    # Disable scheduler if requested
    if args.no_schedule:
        os.environ["DISABLE_SCHEDULER"] = "1"

    # Get host/port (use env PORT for cloud platforms like Render)
    host = args.host or os.environ.get("HOST", config.dashboard.host)
    port = args.port or int(os.environ.get("PORT", config.dashboard.port))

    print(f"\n[startup] Starting web dashboard at http://{host}:{port}")
    if not args.no_schedule:
        print("[startup] Scheduler will start automatically on app startup")
    print("[startup] Press Ctrl+C to stop\n")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
