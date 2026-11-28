"""Authenticated delivery reservation/receipt API, without a historical backfill."""
from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ..db import SessionLocal
from ..internal_auth import require_internal_token
from ..services.telegram_delivery import acknowledge_delivery, reserve_ready_delivery

router = APIRouter(prefix='/api/payments/telegram/delivery', tags=['delivery'],
                   dependencies=[Depends(require_internal_token)])


class ReserveRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    order_id: int = Field(strict=True, gt=0, le=2147483647)
    story_id: int = Field(strict=True, gt=0, le=2147483647)
    external_user_id: str = Field(strict=True, pattern=r'^[1-9][0-9]{0,15}$')
    expected_sha256: str = Field(strict=True, pattern=r'^[a-f0-9]{64}$')


class ReceiptRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    order_id: int = Field(strict=True, gt=0, le=2147483647)
    token: str = Field(strict=True, pattern=r'^[a-f0-9]{32}$')
    message_id: int = Field(strict=True, gt=0, le=2147483647)


def delivery_sessions():
    return SessionLocal


@router.post('/reserve')
def reserve(payload: ReserveRequest, sessions=Depends(delivery_sessions)):
    # The caller preflights the transport and verified PDF before claiming.
    # No distinction between unavailable, unowned and already reserved books.
    claim = reserve_ready_delivery(sessions, **payload.model_dump())
    return {'reservation': asdict(claim) if claim is not None else None}


@router.post('/acknowledge')
def acknowledge(payload: ReceiptRequest, sessions=Depends(delivery_sessions)):
    # Trusted bot adapter must verify the returned chat and document identity.
    # This endpoint persists a receipt; it cannot attest that Telegram sent it.
    return {'acknowledged': acknowledge_delivery(sessions, **payload.model_dump())}
