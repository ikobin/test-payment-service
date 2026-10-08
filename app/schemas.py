import uuid
from datetime import datetime
from decimal import Decimal
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models import PaymentStatus


class PaymentCreateRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, max_digits=10, decimal_places=2)
    currency: str = Field(..., pattern="^(RUB|USD|EUR)$")
    description: str | None = Field(None, max_length=255)
    metadata: dict[str, Any] | None = Field(default=None, alias="metadata")
    webhook_url: HttpUrl

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("webhook_url")
    @classmethod
    def reject_private_urls(cls, v: HttpUrl) -> HttpUrl:
        host = urlparse(str(v)).hostname
        if host is None:
            raise ValueError("webhook URL обязан иметь host")

        try:
            ip = ip_address(host)
        except ValueError:
            return v
        
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("private/loopback/link-local webhook URLs не разрешены")

        return v


class PaymentCreateResponse(BaseModel):
    payment_id: uuid.UUID
    status: PaymentStatus
    created_at: datetime


class PaymentDetailResponse(BaseModel):
    id: uuid.UUID
    amount: Decimal
    currency: str
    description: str | None = None
    metadata_info: dict[str, Any] | None = Field(
        default=None, serialization_alias="metadata",
    )
    status: PaymentStatus
    webhook_url: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
