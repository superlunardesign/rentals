"""Scraper for Olympic Landlord & Rental Services (olyrents.com).

Uses Playwright browser to render PropertyWare JavaScript content.
"""

import re
from typing import Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Tag

from .base import ScrapedListing
from .browser_scraper import BrowserScraper


class OlyrentsScraper(BrowserScraper):
    """Scraper for olyrents.com property listings via PropertyWare widget.

    Uses browser rendering because PropertyWare loads listing content via JavaScript.
    """

    def __init__(self, url: str = "https://olyrents.propertyware.com/"):
        super().__init__(source_name="olyrents", base_url=url)

    def scrape(self) -> list[ScrapedListing]:
        """Scrape all listings from olyrents PropertyWare widget."""
        listings = []

        try:
            print(f"[olyrents] Fetching PropertyWare widget (browser mode)...")
            soup = self.fetch_page(self.base_url)

            print(f"[olyrents] Page title: {soup.title.string if soup.title else 'No title'}")

            # Find all listing tables
            listing_tables = soup.select("table.listTable")
            print(f"[olyrents] Found {len(listing_tables)} listing tables")

            # Debug: check if there are any tables at all
            if not listing_tables:
                # Try other selectors
                all_tables = soup.select("table")
                print(f"[olyrents] Total tables on page: {len(all_tables)}")
                # Look for PropertyWare-specific classes
                pw_items = soup.select("[class*='pw_listing'], [class*='listing-item'], [class*='property']")
                print(f"[olyrents] PropertyWare items found: {len(pw_items)}")

            debug_count = 0
            for table in listing_tables:
                # Debug first 3 tables
                if debug_count < 3:
                    table_text = table.get_text(strip=True)[:200]
                    all_tds = table.select("td")
                    td_classes = []
                    for td in all_tds:
                        if td.get("class"):
                            td_classes.extend(td.get("class"))
                    print(f"[olyrents] Table {debug_count} TD classes: {set(td_classes)}")
                    print(f"[olyrents] Table {debug_count} text preview: {table_text[:100]}...")
                    debug_count += 1

                listing = self._parse_listing(table)
                if listing:
                    listings.append(listing)
                    print(f"[olyrents] Parsed: {listing.title[:40]}... - ${listing.rent or 'N/A'}")

            print(f"[olyrents] Found {len(listings)} listings")

        except Exception as e:
            print(f"[olyrents] Error scraping: {e}")
            import traceback
            traceback.print_exc()

        return listings

    def _parse_listing(self, table: Tag) -> Optional[ScrapedListing]:
        """Parse a single PropertyWare listing table."""
        try:
            image_url = None
            detail_url = None
            title = None
            address = None
            rent = None
            bedrooms = None
            bathrooms = None
            sqft = None
            description = None

            # Extract image
            img = table.select_one(".listItemImgTd img, .pw_listing_widget_tabs_list_item_img")
            if img:
                image_url = img.get("src")

            # Debug: show table structure (first table only)
            all_tds = table.select("td")
            all_classes = set()
            for td in all_tds:
                if td.get("class"):
                    all_classes.update(td.get("class"))

            # Try multiple selectors for description cell
            desc_td = table.select_one(".listItemDescTd")
            if not desc_td:
                # Try alternate selectors
                desc_td = table.select_one("td.listItemDescTd")
            if not desc_td:
                # Try the second td (first is usually image)
                if len(all_tds) >= 2:
                    second_td = all_tds[1]
                    text = second_td.get_text(strip=True)
                    # Check if it has listing-like content
                    if text and len(text) > 30:
                        desc_td = second_td
            if not desc_td:
                # Try any td with listing-like content
                for td in all_tds:
                    text = td.get_text(strip=True)
                    # Look for money amounts, bedroom counts, or address-like patterns
                    if text and len(text) > 30 and (
                        "$" in text or
                        "BR" in text or
                        "bed" in text.lower() or
                        re.search(r'\d+\s+\w+\s+(St|Ave|Rd|Dr|Way|Ln|Ct|Blvd)', text, re.I) or
                        "WA" in text
                    ):
                        desc_td = td
                        break

            # If no desc_td found, try parsing the whole table
            parse_target = desc_td if desc_td else table

            # Title is in the first <a> tag
            title_link = parse_target.select_one("a")
            if title_link:
                title = self.clean_text(title_link.get_text())
                # Extract detail index from javascript:gotoDetail(X)
                href = title_link.get("href", "")
                detail_match = re.search(r'gotoDetail\((\d+)\)', href)
                if detail_match:
                    detail_url = f"{self.base_url}#listing_{detail_match.group(1)}"

            # Get all text from parse target for regex extraction
            full_text = parse_target.get_text()

            # Address patterns
            addr_match = re.search(r'(\d+[^,]+,\s*\w+,\s*WA\s*\d{5}(?:-\d{4})?)', full_text)
            if addr_match:
                address = self.clean_text(addr_match.group(1))
            else:
                # Try simpler address pattern
                addr_match = re.search(r'(\d+\s+[A-Za-z\s]+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Way|Blvd|Ln|Lane|Ct|Court)[^,\n]*)', full_text, re.I)
                if addr_match:
                    address = self.clean_text(addr_match.group(1))

            # Extract specs - try multiple patterns
            # Monthly Rent
            rent_match = re.search(r'(?:Monthly Rent|Rent):\s*\$?([\d,]+)', full_text, re.I)
            if rent_match:
                rent = int(rent_match.group(1).replace(',', '').split('.')[0])
            else:
                # Try just finding a dollar amount
                rent_match = re.search(r'\$\s*([\d,]+)(?:\s*/\s*(?:mo|month))?', full_text, re.I)
                if rent_match:
                    rent = int(rent_match.group(1).replace(',', ''))

            # Bedrooms
            br_match = re.search(r'(?:BR|Bed|Bedroom)s?:\s*(\d+)', full_text, re.I)
            if br_match:
                bedrooms = int(br_match.group(1))
            else:
                br_match = re.search(r'(\d+)\s*(?:BR|Bed|Bedroom)s?', full_text, re.I)
                if br_match:
                    bedrooms = int(br_match.group(1))

            # Bathrooms
            ba_match = re.search(r'(?:BA|Bath|Bathroom)s?:\s*(\d+\.?\d*)', full_text, re.I)
            if ba_match:
                bathrooms = float(ba_match.group(1))
            else:
                ba_match = re.search(r'(\d+\.?\d*)\s*(?:BA|Bath|Bathroom)s?', full_text, re.I)
                if ba_match:
                    bathrooms = float(ba_match.group(1))

            # Description is in <p> tag
            desc_p = parse_target.select_one("p")
            if desc_p:
                description = self.clean_text(desc_p.get_text())

            # Try to extract sqft from full text
            sqft_text = full_text
            sqft_match = re.search(r'([\d,]+)\s*sq\.?\s*ft', sqft_text, re.I)
            if sqft_match:
                sqft = int(sqft_match.group(1).replace(',', ''))

            if not title and not address:
                # Debug: show why we're skipping this table
                text_preview = full_text[:150].replace('\n', ' ').strip()
                print(f"[olyrents] SKIP: no title/address. Text: {text_preview}...")
                return None

            # Extract city/state/zip from address
            city = None
            state = None
            zip_code = None
            if address:
                zip_code = self.extract_zip_code(address)
                city_match = re.search(r'(Tumwater|Olympia|Lacey|Yelm|Rochester|Tenino|Centralia|Chehalis)', address, re.I)
                if city_match:
                    city = city_match.group(1).title()
                    state = "WA"

            # Generate source ID from address or title
            source_id = None
            if address:
                # Use address hash as ID since PropertyWare doesn't expose IDs
                source_id = str(abs(hash(address)))[:12]
            else:
                source_id = str(abs(hash(title or str(rent))))[:12]

            return ScrapedListing(
                source_name=self.source_name,
                source_id=source_id,
                url=detail_url or self.base_url,
                title=title or address or f"OlyRents Property",
                address=address,
                city=city,  # Don't default - let matcher filter unknown cities
                state=state or "WA",
                zip_code=zip_code,
                rent=rent,
                bedrooms=bedrooms,
                bathrooms=bathrooms,
                sqft=sqft,
                description=description,
                image_url=image_url,
            )

        except Exception as e:
            print(f"[olyrents] Error parsing listing: {e}")
            import traceback
            traceback.print_exc()
            return None

    def scrape_detail_page(self, url: str) -> dict:
        """PropertyWare widget doesn't have separate detail pages."""
        return {
            "bedrooms": None,
            "bathrooms": None,
            "sqft": None,
            "description": None,
            "features": [],
        }
