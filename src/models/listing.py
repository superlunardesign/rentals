"""Listing model for rental properties."""

from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean
from sqlalchemy.orm import Mapped

from .database import Base


class Listing(Base):
    """A rental property listing."""

    __tablename__ = "listings"

    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True)

    # Source information
    source_name: Mapped[str] = Column(String(100), nullable=False)  # e.g., "olyrents"
    source_id: Mapped[str] = Column(String(255), nullable=False)  # Unique ID from source
    url: Mapped[str] = Column(String(500), nullable=False)

    # Property details
    title: Mapped[str] = Column(String(500), nullable=False)
    address: Mapped[Optional[str]] = Column(String(500))
    city: Mapped[Optional[str]] = Column(String(100))
    state: Mapped[Optional[str]] = Column(String(50))
    zip_code: Mapped[Optional[str]] = Column(String(20))

    # Pricing
    rent: Mapped[Optional[int]] = Column(Integer)  # Monthly rent in dollars
    deposit: Mapped[Optional[int]] = Column(Integer)

    # Property specs
    bedrooms: Mapped[Optional[int]] = Column(Integer)
    bathrooms: Mapped[Optional[float]] = Column(Float)
    sqft: Mapped[Optional[int]] = Column(Integer)

    # Description and features
    description: Mapped[Optional[str]] = Column(Text)
    features: Mapped[Optional[str]] = Column(Text)  # Comma-separated list

    # Location (for distance calculations)
    latitude: Mapped[Optional[float]] = Column(Float)
    longitude: Mapped[Optional[float]] = Column(Float)
    distance_miles: Mapped[Optional[float]] = Column(Float)

    # Matching
    match_tier: Mapped[Optional[str]] = Column(String(20))  # best_match, match, flexible, excluded
    match_score: Mapped[Optional[int]] = Column(Integer)  # 0-100 score
    matched_keywords: Mapped[Optional[str]] = Column(Text)  # Comma-separated matched keywords

    # Status
    is_active: Mapped[bool] = Column(Boolean, default=True)
    is_new: Mapped[bool] = Column(Boolean, default=True)  # New since last view
    is_favorite: Mapped[bool] = Column(Boolean, default=False)
    is_hidden: Mapped[bool] = Column(Boolean, default=False)  # User manually hidden

    # Timestamps
    first_seen: Mapped[datetime] = Column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[datetime] = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at: Mapped[datetime] = Column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Listing {self.id}: {self.title} - ${self.rent}>"

    @property
    def full_address(self) -> str:
        """Get formatted full address."""
        parts = [self.address, self.city, self.state, self.zip_code]
        return ", ".join(p for p in parts if p)

    @property
    def keyword_list(self) -> list[str]:
        """Get matched keywords as a list."""
        if self.matched_keywords:
            return [k.strip() for k in self.matched_keywords.split(",")]
        return []

    @property
    def feature_list(self) -> list[str]:
        """Get features as a list."""
        if self.features:
            return [f.strip() for f in self.features.split(",")]
        return []
