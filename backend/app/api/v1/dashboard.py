from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Dict, Any, List, Optional
from decimal import Decimal, ROUND_HALF_UP
from app.services.cache import get_revenue_summary
from app.services.reservations import calculate_monthly_revenue, list_tenant_properties
from app.core.auth import authenticate_request as get_current_user

router = APIRouter()

CENTS = Decimal("0.01")


def _to_money(value) -> float:
    """
    Round to cents using Decimal (ROUND_HALF_UP) BEFORE converting to
    float. Amounts are stored as NUMERIC(10,3); converting the raw sum straight to
    float and rounding on the client produced totals that were off by a cent.
    """
    return float(Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP))


def _require_tenant(current_user) -> str:
    tenant_id = getattr(current_user, "tenant_id", None)
    if not tenant_id:
        # Never fall back to a shared/default tenant for financial data.
        raise HTTPException(status_code=403, detail="No tenant associated with this user")
    return tenant_id


@router.get("/dashboard/properties")
async def get_dashboard_properties(
    current_user: dict = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    tenant_id = _require_tenant(current_user)
    return await list_tenant_properties(tenant_id)


@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str,
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    current_user: dict = Depends(get_current_user)
) -> Dict[str, Any]:

    tenant_id = _require_tenant(current_user)

    try:
        revenue_data = await get_revenue_summary(property_id, tenant_id)
        response = {
            "property_id": revenue_data['property_id'],
            "total_revenue": _to_money(revenue_data['total']),
            "currency": revenue_data['currency'],
            "reservations_count": revenue_data['count']
        }

        if month and year:
            monthly = await calculate_monthly_revenue(property_id, tenant_id, month, year)
            response.update({"month": month, "year": year, "monthly_revenue": _to_money(monthly)})
    except HTTPException:
        raise
    except Exception as e:
        # Surface failures instead of returning fabricated numbers.
        raise HTTPException(status_code=503, detail=f"Revenue data unavailable: {e}")

    return response
