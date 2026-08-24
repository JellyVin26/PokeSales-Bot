"""Database queries for the pokebot application."""

from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User, Card, Sale, SaleItem, SalePhoto, SheetSyncQueue


# ---- Users ----

async def get_user(session: AsyncSession, telegram_user_id: int) -> User | None:
    result = await session.execute(
        select(User).where(User.telegram_user_id == telegram_user_id)
    )
    return result.scalar_one_or_none()


async def upsert_user(
    session: AsyncSession,
    telegram_user_id: int,
    username: str | None = None,
    first_name: str | None = None,
) -> User:
    user = await get_user(session, telegram_user_id)
    if user is None:
        user = User(telegram_user_id=telegram_user_id)
        session.add(user)
    if username is not None:
        user.username = username
    if first_name is not None:
        user.first_name = first_name
    await session.flush()
    return user


# ---- Sales ----

async def next_sale_id(session: AsyncSession) -> str:
    """Generate next sequential sale id: S-0001."""
    count = await session.scalar(select(func.count(Sale.id)))
    return f"S-{(count or 0) + 1:04d}"


async def create_draft_sale(
    session: AsyncSession,
    telegram_user_id: int,
    total_amount: float | None = None,
    currency: str = "MYR",
    payment_method: str = "Unknown",
) -> Sale:
    sale = Sale(
        id=await next_sale_id(session),
        telegram_user_id=telegram_user_id,
        total_amount=total_amount or 0.0,
        currency=currency,
        payment_method=payment_method,
        status="AWAITING_CONFIRMATION",
    )
    session.add(sale)
    await session.flush()
    return sale


async def confirm_sale(session: AsyncSession, sale_id: str) -> Sale | None:
    sale = await session.get(Sale, sale_id)
    if sale is None:
        return None
    sale.status = "CONFIRMED"
    sale.confirmed_at = datetime.now(timezone.utc)
    await session.flush()
    return sale


async def cancel_sale(session: AsyncSession, sale_id: str) -> Sale | None:
    sale = await session.get(Sale, sale_id)
    if sale is None:
        return None
    sale.status = "CANCELLED"
    sale.cancelled_at = datetime.now(timezone.utc)
    await session.flush()
    return sale


async def get_sale(session: AsyncSession, sale_id: str) -> Sale | None:
    return await session.get(Sale, sale_id)


async def get_sale_with_items(session: AsyncSession, sale_id: str) -> Sale | None:
    from sqlalchemy.orm import selectinload

    result = await session.execute(
        select(Sale).options(selectinload(Sale.items)).where(Sale.id == sale_id)
    )
    return result.scalar_one_or_none()


async def recent_sales(session: AsyncSession, limit: int = 10) -> list[Sale]:
    result = await session.execute(
        select(Sale)
        .where(Sale.status == "CONFIRMED")
        .order_by(Sale.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def today_summary(session: AsyncSession) -> dict:
    """Aggregate confirmed sales for today (UTC date)."""
    today = datetime.now(timezone.utc).date()
    stmt = (
        select(
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.total_amount), 0.0),
        )
        .where(Sale.status == "CONFIRMED")
        .where(func.date(Sale.created_at) == today.isoformat())
    )
    txns, revenue = (await session.execute(stmt)).one()

    cards_stmt = (
        select(func.coalesce(func.sum(SaleItem.quantity), 0))
        .join(Sale, SaleItem.sale_id == Sale.id)
        .where(Sale.status == "CONFIRMED")
        .where(func.date(Sale.created_at) == today.isoformat())
    )
    cards_sold = await session.scalar(cards_stmt)

    return {"transactions": txns, "revenue": float(revenue), "cards_sold": int(cards_sold)}


async def sales_in_range(
    session: AsyncSession, start: datetime, end: datetime
) -> list[Sale]:
    stmt = (
        select(Sale)
        .where(Sale.status == "CONFIRMED")
        .where(Sale.created_at >= start)
        .where(Sale.created_at < end)
        .order_by(Sale.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---- Sale items ----

async def replace_items(
    session: AsyncSession, sale_id: str, items: list[dict]
) -> None:
    """Replace all items of a draft sale (used by edit flow)."""
    await session.execute(delete(SaleItem).where(SaleItem.sale_id == sale_id))
    for it in items:
        session.add(
            SaleItem(
                sale_id=sale_id,
                card_name=it["card_name"],
                set_name=it.get("set_name"),
                set_id=it.get("set_id"),
                card_number=it.get("card_number"),
                quantity=it.get("quantity", 1),
                confidence=it.get("confidence"),
            )
        )
    await session.flush()


# ---- Photos / audit ----

async def add_photo(
    session: AsyncSession,
    sale_id: str,
    telegram_file_id: str,
    detected_cards_json: dict | None = None,
    quality_score: float | None = None,
) -> SalePhoto:
    photo = SalePhoto(
        sale_id=sale_id,
        telegram_file_id=telegram_file_id,
        detected_cards_json=detected_cards_json,
        quality_score=quality_score,
    )
    session.add(photo)
    await session.flush()
    return photo


# ---- Cards ----

async def find_card(session: AsyncSession, name: str) -> Card | None:
    result = await session.execute(
        select(Card).where(func.lower(Card.official_name) == name.lower())
    )
    return result.scalar_one_or_none()


# ---- Card stats (/card command) ----

async def card_stats(session: AsyncSession, card_name: str) -> dict | None:
    name_lower = card_name.lower()
    total_qty, txn_count = (
        await session.execute(
            select(
                func.coalesce(func.sum(SaleItem.quantity), 0),
                func.count(func.distinct(SaleItem.sale_id)),
            )
            .join(Sale, SaleItem.sale_id == Sale.id)
            .where(Sale.status == "CONFIRMED")
            .where(func.lower(SaleItem.card_name) == name_lower)
        )
    ).one()
    if total_qty == 0:
        return None
    return {"sold": int(total_qty), "transactions": int(txn_count)}


# ---- Google Sheets retry queue ----

async def enqueue_sheet_sync(
    session: AsyncSession, sale_id: str, payload: dict
) -> SheetSyncQueue:
    row = SheetSyncQueue(sale_id=sale_id, payload_json=payload)
    session.add(row)
    await session.flush()
    return row


async def pending_syncs(session: AsyncSession, limit: int = 50) -> list[SheetSyncQueue]:
    result = await session.execute(
        select(SheetSyncQueue)
        .where(SheetSyncQueue.synced_at.is_(None))
        .order_by(SheetSyncQueue.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def mark_synced(session: AsyncSession, row_id: int) -> None:
    row = await session.get(SheetSyncQueue, row_id)
    if row:
        row.synced_at = datetime.now(timezone.utc)
        await session.flush()