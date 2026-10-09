from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, List

from sqlalchemy import text

from app.core.database_pool import db_pool


async def _get_pool():
    """Return the shared, lazily-initialized database pool."""
    if not db_pool.session_factory:
        await db_pool.initialize()
    if not db_pool.session_factory:
        raise Exception("Database pool not available")
    return db_pool


async def calculate_monthly_revenue(property_id: str, tenant_id: str, month: int, year: int) -> Decimal:
    """
    Calculates revenue for a specific month.

    Month boundaries are evaluated in the PROPERTY's local timezone, not UTC.
    e.g. a check-in at 2024-02-29 23:30 UTC is 2024-03-01 00:30 in Europe/Paris
    and therefore belongs to March for a Paris property.
    """

    start_date = datetime(year, month, 1)
    if month < 12:
        end_date = datetime(year, month + 1, 1)
    else:
        end_date = datetime(year + 1, 1, 1)

    # check_in_date is TIMESTAMPTZ; "AT TIME ZONE p.timezone" converts it to the
    # property's local wall-clock time, which we compare to naive local month bounds.
    query = text("""
        SELECT COALESCE(SUM(r.total_amount), 0) AS total
        FROM reservations r
        JOIN properties p
          ON p.id = r.property_id AND p.tenant_id = r.tenant_id
        WHERE r.property_id = :property_id
          AND r.tenant_id = :tenant_id
          AND (r.check_in_date AT TIME ZONE p.timezone) >= :start_date
          AND (r.check_in_date AT TIME ZONE p.timezone) < :end_date
    """)

    pool = await _get_pool()
    async with pool.get_session() as session:
        result = await session.execute(query, {
            "property_id": property_id,
            "tenant_id": tenant_id,
            "start_date": start_date,
            "end_date": end_date,
        })
        total = result.scalar()

    return Decimal(str(total or 0))


async def calculate_total_revenue(property_id: str, tenant_id: str) -> Dict[str, Any]:
    """
    Aggregates revenue from database.

    NOTE: errors are intentionally NOT swallowed. Previously a DB failure fell back
    to hardcoded mock figures, so clients silently saw fake (and tenant-agnostic)
    numbers instead of an error.
    """
    pool = await _get_pool()
    async with pool.get_session() as session:
        query = text("""
            SELECT
                property_id,
                SUM(total_amount) as total_revenue,
                COUNT(*) as reservation_count,
                MIN(currency) as currency
            FROM reservations
            WHERE property_id = :property_id AND tenant_id = :tenant_id
            GROUP BY property_id
        """)

        result = await session.execute(query, {
            "property_id": property_id,
            "tenant_id": tenant_id
        })
        row = result.fetchone()

    if row:
        total_revenue = Decimal(str(row.total_revenue))
        return {
            "property_id": property_id,
            "tenant_id": tenant_id,
            "total": str(total_revenue),
            "currency": row.currency or "USD",
            "count": row.reservation_count
        }

    # No reservations found for this property (for this tenant)
    return {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "total": "0.00",
        "currency": "USD",
        "count": 0
    }


async def list_tenant_properties(tenant_id: str) -> List[Dict[str, Any]]:
    """Returns only the properties belonging to the given tenant."""
    pool = await _get_pool()
    async with pool.get_session() as session:
        result = await session.execute(
            text("SELECT id, name, timezone FROM properties WHERE tenant_id = :tenant_id ORDER BY id"),
            {"tenant_id": tenant_id},
        )
        return [{"id": r.id, "name": r.name, "timezone": r.timezone} for r in result.fetchall()]
