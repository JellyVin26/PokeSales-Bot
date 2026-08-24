"""Google Sheets sync with DB-backed retry queue.

Confirmed sales always live in Postgres first. Sheets sync is best-effort:
failures enqueue a row in sheet_sync_queue and a periodic job retries.
"""

import asyncio
import logging

import gspread
from google.oauth2.service_account import Credentials
from sqlalchemy.ext.asyncio import AsyncSession

from pokebot.db import queries as q

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def make_client(service_account_file: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
    return gspread.authorize(creds)


def _ensure_worksheets(spreadsheet: gspread.Spreadsheet) -> tuple[gspread.Worksheet, gspread.Worksheet]:
    try:
        sales_ws = spreadsheet.worksheet("Sales")
    except gspread.WorksheetNotFound:
        sales_ws = spreadsheet.add_worksheet("Sales", 1000, 10)
        sales_ws.append_row(
            ["Sale ID", "Date", "Time", "Seller", "Total", "Currency",
             "Payment Method", "Card Count", "Status", "Photo"]
        )
    try:
        items_ws = spreadsheet.worksheet("Sale Items")
    except gspread.WorksheetNotFound:
        items_ws = spreadsheet.add_worksheet("Sale Items", 10000, 6)
        items_ws.append_row(
            ["Sale ID", "Card Name", "Set", "Card Number", "Quantity", "Confidence"]
        )
    return sales_ws, items_ws


def push_sale(client: gspread.Client, spreadsheet_id: str, payload: dict) -> None:
    """Push one sale + its items. Raises on failure (caller enqueues retry)."""
    spreadsheet = client.open_by_key(spreadsheet_id)
    sales_ws, items_ws = _ensure_worksheets(spreadsheet)

    sales_ws.append_row(
        [
            payload["sale_id"], payload["date"], payload["time"],
            payload["seller"], payload["total"], payload["currency"],
            payload["payment_method"], payload["card_count"],
            payload["status"], payload.get("photo_id", ""),
        ]
    )
    for item in payload.get("items", []):
        items_ws.append_row(
            [
                payload["sale_id"], item["card_name"], item.get("set_name") or "",
                item.get("card_number") or "", item.get("quantity", 1),
                item.get("confidence", ""),
            ]
        )


async def sync_sale_or_enqueue(
    client: gspread.Client | None,
    spreadsheet_id: str,
    session: AsyncSession,
    sale_id: str,
) -> bool:
    """Try to push a confirmed sale; on failure enqueue for retry."""
    from pokebot.db.session import make_session_factory
    # ponytail: syncs run inline with the request session; move to worker when volume demands it

    sale = await q.get_sale_with_items(session, sale_id)
    if sale is None or sale.status != "CONFIRMED":
        return False

    payload = {
        "sale_id": sale.id,
        "date": sale.confirmed_at.strftime("%Y-%m-%d") if sale.confirmed_at else "",
        "time": sale.confirmed_at.strftime("%H:%M:%S") if sale.confirmed_at else "",
        "seller": str(sale.telegram_user_id),
        "total": sale.total_amount,
        "currency": sale.currency,
        "payment_method": sale.payment_method,
        "card_count": sum(i.quantity for i in sale.items),
        "status": sale.status,
        "items": [
            {
                "card_name": i.card_name,
                "set_name": i.set_name,
                "card_number": i.card_number,
                "quantity": i.quantity,
                "confidence": i.confidence,
            }
            for i in sale.items
        ],
    }

    if client is None:
        await q.enqueue_sheet_sync(session, sale_id, payload)
        return False

    try:
        await asyncio.to_thread(push_sale, client, spreadsheet_id, payload)
        return True
    except Exception as e:  # noqa: BLE001 - any sheets error must not lose the sale
        log.warning("Sheets sync failed for %s, queued: %s", sale_id, e)
        await q.enqueue_sheet_sync(session, sale_id, payload)
        return False


async def flush_sync_queue(
    client: gspread.Client, spreadsheet_id: str, session: AsyncSession
) -> int:
    """Retry pending sheet syncs. Returns count synced."""
    rows = await q.pending_syncs(session)
    done = 0
    for row in rows:
        try:
            await asyncio.to_thread(push_sale, client, spreadsheet_id, row.payload_json)
            await q.mark_synced(session, row.id)
            done += 1
        except Exception as e:  # noqa: BLE001
            row.attempts += 1
            row.last_error = str(e)[:500]
    await session.commit()
    return done