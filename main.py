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
import uvicorn
from fastapi import FastAPI

from src.config import get_config
from src.models.database import init_db
from src.api.routes import router
from src.scheduler import RentalScheduler
from src.services import ScraperService


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    application = FastAPI(
        title="Rental Search",
        description="Property rental search for Tumwater/Olympia, WA",
        version="1.0.0"
    )

    # Include routes
    application.include_router(router)

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

    # Start scheduler if not disabled
    scheduler = None
    if not args.no_schedule:
        scheduler = RentalScheduler()
        scheduler.start()

    # Get host/port (use env PORT for cloud platforms like Render)
    host = args.host or os.environ.get("HOST", config.dashboard.host)
    port = args.port or int(os.environ.get("PORT", config.dashboard.port))

    print(f"\n[startup] Starting web dashboard at http://{host}:{port}")
    print("[startup] Press Ctrl+C to stop\n")

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        if scheduler:
            scheduler.stop()


if __name__ == "__main__":
    main()
