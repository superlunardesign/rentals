"""Notification service for alerting about new matching listings."""

import os
from typing import Optional

import httpx

from ..config import get_config
from ..models.listing import Listing


class TelegramNotifier:
    """Send notifications via Telegram bot."""

    def __init__(self):
        config = get_config()
        notif_config = getattr(config, 'notifications', None)
        telegram_config = getattr(notif_config, 'telegram', None) if notif_config else None

        # Get credentials from config or environment
        self.bot_token = (
            os.environ.get("TELEGRAM_BOT_TOKEN") or
            (telegram_config.bot_token if telegram_config else None)
        )
        self.chat_id = (
            os.environ.get("TELEGRAM_CHAT_ID") or
            (telegram_config.chat_id if telegram_config else None)
        )

        # Enable if:
        # 1. Config says enabled=true AND we have credentials, OR
        # 2. No config but we have credentials from env vars (auto-enable)
        config_enabled = telegram_config.enabled if telegram_config else True  # Default true if no config
        self.enabled = config_enabled and bool(self.bot_token) and bool(self.chat_id)

        # Which tiers to notify about
        self.notify_tiers = (
            telegram_config.notify_tiers if telegram_config else ["BEST_MATCH", "MATCH", "FLEXIBLE"]
        )

        if self.enabled:
            print(f"[telegram] Notifications enabled for tiers: {self.notify_tiers}")
            print(f"[telegram] Bot token: {'***' + self.bot_token[-6:] if self.bot_token else 'None'}")
            print(f"[telegram] Chat ID: {self.chat_id}")
            # Send test message on startup
            self._send_startup_message()
        else:
            print(f"[telegram] Disabled - enabled={telegram_config.enabled if telegram_config else 'N/A'}, "
                  f"bot_token={'set' if self.bot_token else 'missing'}, "
                  f"chat_id={'set' if self.chat_id else 'missing'}")

    def _send_startup_message(self):
        """Send a test message on startup to verify bot is working."""
        try:
            message = "🏠 *Rental Scraper Started*\n\nBot is online and monitoring for new listings!"
            if self._send_message(message):
                print("[telegram] Startup message sent successfully")
            else:
                print("[telegram] Failed to send startup message")
        except Exception as e:
            print(f"[telegram] Error sending startup message: {e}")

    def should_notify(self, listing: Listing) -> bool:
        """Check if we should send notification for this listing."""
        if not self.enabled:
            return False

        # Check if listing tier is in notify_tiers (case-insensitive)
        tier = (listing.match_tier or "EXCLUDED").upper()
        notify_tiers_upper = [t.upper() for t in self.notify_tiers]
        return tier in notify_tiers_upper

    def notify_new_listing(self, listing: Listing) -> bool:
        """Send notification about a new matching listing."""
        tier = (listing.match_tier or "EXCLUDED").upper()
        print(f"[telegram] Checking listing: {listing.title[:30] if listing.title else 'Unknown'}... tier={tier}")

        if not self.should_notify(listing):
            print(f"[telegram] Skipping - tier {tier} not in notify_tiers {self.notify_tiers}")
            return False

        try:
            print(f"[telegram] Sending notification for: {listing.title}")
            print(f"[telegram] Image URL: {listing.image_url if listing.image_url else 'None'}")
            message = self._format_listing_message(listing)

            # If listing has an image, send as photo with caption
            if listing.image_url:
                return self._send_photo(listing.image_url, message)
            else:
                return self._send_message(message)
        except Exception as e:
            print(f"[telegram] Error sending notification: {e}")
            return False

    def notify_multiple_listings(self, listings: list[Listing]) -> int:
        """Send individual notifications for each new listing. Returns count sent."""
        sent = 0
        for listing in listings:
            if self.notify_new_listing(listing):
                sent += 1
        return sent

    def _format_listing_line(self, listing: Listing) -> str:
        """Format a single listing as a compact line."""
        # Price and address
        price = f"${listing.rent:,}/mo" if listing.rent else "Price N/A"
        price = self._escape_markdown(price)
        address = self._escape_markdown(listing.title or listing.address or "Unknown")

        # Specs
        specs = []
        if listing.bedrooms is not None:
            specs.append(f"{listing.bedrooms} bd")
        if listing.bathrooms is not None:
            bath_str = str(listing.bathrooms).rstrip('0').rstrip('.')
            specs.append(f"{bath_str} ba")
        if listing.sqft:
            specs.append(f"{listing.sqft:,} sq ft")
        specs_str = self._escape_markdown(", ".join(specs) if specs else "Specs N/A")

        # URL - use markdown link format (URLs inside links don't need escaping)
        url = listing.url or ""
        url_line = f"[View Listing]({url})" if url else ""

        return f"*{price}* \\| {address}\n{specs_str}\n{url_line}"

    def _format_listing_message(self, listing: Listing) -> str:
        """Format a single listing into a Telegram message (for individual notifications)."""
        dashboard_url = os.environ.get("RENDER_EXTERNAL_URL", "https://rentals-09tb.onrender.com")

        # Emoji based on tier
        tier_emoji = {
            "BEST_MATCH": "🌟",
            "MATCH": "✅",
            "FLEXIBLE": "🔶",
        }.get(listing.match_tier, "📋")

        tier_label = (listing.match_tier or "Listing").replace("_", " ").title()

        lines = [
            f"🏠 *New {tier_label} Found\\!*",
            "",
            f"[View Dashboard]({dashboard_url})",
            "",
            self._format_listing_line(listing),
        ]

        return "\n".join(lines)

    def _escape_markdown(self, text: str) -> str:
        """Escape special markdown characters for Telegram."""
        if not text:
            return ""
        # Escape these chars: _ * [ ] ( ) ~ ` > # + - = | { } . !
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        return text

    def _send_message(self, message: str) -> bool:
        """Send a message via Telegram API."""
        if not self.bot_token or not self.chat_id:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(url, json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "MarkdownV2",
                    "disable_web_page_preview": False,
                })

                if response.status_code == 200:
                    print(f"[telegram] Notification sent successfully")
                    return True
                else:
                    print(f"[telegram] API error: {response.status_code} - {response.text}")
                    # Try again without markdown if parsing failed
                    if "can't parse" in response.text.lower():
                        return self._send_plain_message(message)
                    return False

        except Exception as e:
            print(f"[telegram] Request error: {e}")
            return False

    def _send_photo(self, photo_url: str, caption: str) -> bool:
        """Send a photo with caption via Telegram API."""
        if not self.bot_token or not self.chat_id:
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"

        try:
            with httpx.Client(timeout=15) as client:
                response = client.post(url, json={
                    "chat_id": self.chat_id,
                    "photo": photo_url,
                    "caption": caption,
                    "parse_mode": "MarkdownV2",
                })

                if response.status_code == 200:
                    print(f"[telegram] Photo notification sent successfully")
                    return True
                else:
                    print(f"[telegram] Photo API error: {response.status_code} - {response.text}")
                    error_text = response.text.lower()

                    # Try again without markdown if parsing failed
                    if "can't parse" in error_text:
                        return self._send_plain_photo(photo_url, caption)

                    # If photo fails for any URL/content reason, fall back to text-only
                    # Common errors: wrong file identifier, failed to get HTTP URL,
                    # wrong type of web page content (S3 URLs), etc.
                    if any(err in error_text for err in [
                        "wrong file", "failed to get", "wrong type",
                        "bad request", "url", "content"
                    ]):
                        print(f"[telegram] Photo URL not accessible, sending text-only")
                        return self._send_message(caption)

                    return False

        except Exception as e:
            print(f"[telegram] Photo request error: {e}")
            # Fall back to text-only
            return self._send_message(caption)

    def _send_plain_photo(self, photo_url: str, caption: str) -> bool:
        """Fallback: send photo without markdown parsing."""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        plain_caption = caption.replace('*', '').replace('_', '').replace('\\', '')

        try:
            with httpx.Client(timeout=15) as client:
                response = client.post(url, json={
                    "chat_id": self.chat_id,
                    "photo": photo_url,
                    "caption": plain_caption,
                })
                if response.status_code == 200:
                    return True
                # If photo still fails, try text only
                return self._send_plain_message(caption)
        except:
            return self._send_plain_message(caption)

    def _send_plain_message(self, message: str) -> bool:
        """Fallback: send without markdown parsing."""
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        # Strip markdown
        plain = message.replace('*', '').replace('_', '').replace('\\', '')

        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(url, json={
                    "chat_id": self.chat_id,
                    "text": plain,
                })
                return response.status_code == 200
        except:
            return False

    def send_test_message(self) -> bool:
        """Send a test message to verify configuration."""
        if not self.enabled:
            print("[telegram] Cannot send test - notifications not enabled")
            return False

        message = "🔔 *Rental Tracker Test*\n\nTelegram notifications are working\\!"
        return self._send_message(message)

    def notify_price_drop(self, price_drop: dict) -> bool:
        """Send notification about a price drop."""
        if not self.enabled:
            return False

        listing = price_drop.get("listing")
        if not listing:
            return False

        # Only notify for tiers we care about
        tier = (listing.match_tier or "EXCLUDED").upper()
        notify_tiers_upper = [t.upper() for t in self.notify_tiers]
        if tier not in notify_tiers_upper:
            print(f"[telegram] Skipping price drop - tier {tier} not in notify_tiers")
            return False

        try:
            message = self._format_price_drop_message(price_drop)
            print(f"[telegram] Sending price drop notification: {listing.title[:30]}...")

            # If listing has an image, send as photo with caption
            if listing.image_url:
                return self._send_photo(listing.image_url, message)
            else:
                return self._send_message(message)
        except Exception as e:
            print(f"[telegram] Error sending price drop notification: {e}")
            return False

    def _format_price_drop_message(self, price_drop: dict) -> str:
        """Format a price drop notification message."""
        listing = price_drop["listing"]
        old_rent = price_drop["old_rent"]
        new_rent = price_drop["new_rent"]
        drop_amount = price_drop["drop_amount"]
        drop_percent = price_drop["drop_percent"]

        dashboard_url = os.environ.get("RENDER_EXTERNAL_URL", "https://rentals-09tb.onrender.com")

        address = self._escape_markdown(listing.title or listing.address or "Unknown")

        # Specs
        specs = []
        if listing.bedrooms is not None:
            specs.append(f"{listing.bedrooms} bd")
        if listing.bathrooms is not None:
            bath_str = str(listing.bathrooms).rstrip('0').rstrip('.')
            specs.append(f"{bath_str} ba")
        if listing.sqft:
            specs.append(f"{listing.sqft:,} sq ft")
        specs_str = self._escape_markdown(", ".join(specs) if specs else "Specs N/A")

        lines = [
            "💰 *Price Drop\\!*",
            "",
            f"*${old_rent:,}* → *${new_rent:,}* \\(\\-${drop_amount:,}, \\-{drop_percent:.0f}%\\)",
            "",
            f"{address}",
            f"{specs_str}",
            "",
            f"[View Dashboard]({dashboard_url})",
        ]

        if listing.url:
            lines.append(f"[View Listing]({listing.url})")

        return "\n".join(lines)


class NotificationService:
    """Main notification service that coordinates all notification channels."""

    def __init__(self):
        self.telegram = TelegramNotifier()

    def notify_new_listings(self, listings: list[Listing]) -> dict:
        """Send notifications for new listings that match criteria."""
        results = {
            "telegram_sent": 0,
            "telegram_enabled": self.telegram.enabled,
        }

        if self.telegram.enabled:
            results["telegram_sent"] = self.telegram.notify_multiple_listings(listings)

        return results

    def notify_price_drop(self, price_drop: dict) -> bool:
        """Send notification about a price drop."""
        if self.telegram.enabled:
            return self.telegram.notify_price_drop(price_drop)
        return False

    def send_test(self) -> dict:
        """Send test notifications to verify all channels work."""
        return {
            "telegram": self.telegram.send_test_message() if self.telegram.enabled else None,
        }
