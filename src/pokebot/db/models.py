"""Database models for the pokebot application."""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class User(Base):
    """Telegram user who can record sales."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_user_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(128), nullable=True)
    first_name = Column(String(128), nullable=True)
    last_name = Column(String(128), nullable=True)
    role = Column(String(32), nullable=False, default="seller")  # admin | seller
    is_authorized = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<User(id={self.id}, telegram_user_id={self.telegram_user_id}, authorized={self.is_authorized})>"


class Card(Base):
    """Pokémon TCG card resolved against the card database."""

    __tablename__ = "cards"

    id = Column(Integer, primary_key=True)
    official_name = Column(String(256), nullable=False, index=True)
    set_name = Column(String(256), nullable=True)
    set_id = Column(String(64), nullable=True)
    card_number = Column(String(64), nullable=True)
    rarity = Column(String(128), nullable=True)
    language = Column(String(64), nullable=True, default="English")
    card_image_url = Column(String(512), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    items = relationship("SaleItem", back_populates="card")

    def __repr__(self) -> str:
        return f"<Card(id={self.id}, name={self.official_name}, set={self.set_name})>"


class Sale(Base):
    """A sale transaction."""

    __tablename__ = "sales"

    id = Column(String(32), primary_key=True)  # e.g., "S-0001"
    telegram_user_id = Column(Integer, nullable=False, index=True)
    total_amount = Column(Float, nullable=False)
    currency = Column(String(16), nullable=False, default="MYR")
    payment_method = Column(String(64), nullable=False, default="Unknown")
    status = Column(String(32), nullable=False, default="DRAFT", index=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    ai_detection_json = Column(JSON, nullable=True)  # raw AI result (audit trail)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    items = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")
    photos = relationship("SalePhoto", back_populates="sale", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Sale(id={self.id}, amount={self.total_amount} {self.currency}, status={self.status})>"


class SaleItem(Base):
    """An individual card within a sale."""

    __tablename__ = "sale_items"

    id = Column(Integer, primary_key=True)
    sale_id = Column(String(32), ForeignKey("sales.id"), nullable=False, index=True)
    card_id = Column(Integer, ForeignKey("cards.id"), nullable=True, index=True)
    card_name = Column(String(256), nullable=False)
    set_name = Column(String(256), nullable=True)
    set_id = Column(String(64), nullable=True)
    card_number = Column(String(64), nullable=True)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Float, nullable=True)  # NULL unless seller provides it
    confidence = Column(Float, nullable=True)  # AI confidence score
    edited_by_user = Column(Boolean, default=False)

    sale = relationship("Sale", back_populates="items")
    card = relationship("Card", back_populates="items")

    def __repr__(self) -> str:
        return f"<SaleItem(sale={self.sale_id}, card={self.card_name}, qty={self.quantity})>"


class SalePhoto(Base):
    """A photo associated with a sale (audit trail)."""

    __tablename__ = "sale_photos"

    id = Column(Integer, primary_key=True)
    sale_id = Column(String(32), ForeignKey("sales.id"), nullable=False, index=True)
    telegram_file_id = Column(String(256), nullable=False)
    stored_path = Column(String(512), nullable=True)
    detected_cards_json = Column(JSON, nullable=True)  # per-photo AI result
    quality_score = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    sale = relationship("Sale", back_populates="photos")

    def __repr__(self) -> str:
        return f"<SalePhoto(sale={self.sale_id})>"


class SheetSyncQueue(Base):
    """Retry queue for Google Sheets sync failures."""

    __tablename__ = "sheet_sync_queue"

    id = Column(Integer, primary_key=True)
    sale_id = Column(String(32), nullable=False, index=True)
    payload_json = Column(JSON, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())