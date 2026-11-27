"""Internal Telegram checkout contracts; photographs stay outside the database."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Identifier = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
ShortText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)]


class TelegramInvoiceCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')

    external_user_id: Identifier
    channel: Literal['telegram'] = 'telegram'
    child_id: int | None = Field(default=None, strict=True, gt=0)
    child_name: ShortText | None = None
    age: int | None = Field(default=None, strict=True, ge=2, le=12)
    gender: ShortText = 'neutral'
    style: ShortText = 'auto'
    image_style: ShortText = 'watercolor'
    purpose: ShortText = 'bedtime'
    parent_note: str | None = Field(default=None, strict=True, max_length=4000)
    favorite_animal: ShortText | None = None
    favorite_color: ShortText | None = None
    hobby: ShortText | None = None
    favorite_place: ShortText | None = None
    photo_enabled: bool = Field(default=False, strict=True)
    photo_consent: bool = Field(default=False, strict=True)
    photo_file_id: str | None = Field(default=None, strict=True, min_length=1, max_length=512)
    client_request_id: str | None = Field(
        default=None, strict=True, pattern=r'^[a-f0-9]{32}$',
    )

    @model_validator(mode='after')
    def complete_questionnaire(self):
        if self.child_id is None and (not self.child_name or self.age is None):
            raise ValueError('A new child requires a name and age')
        if self.photo_enabled and (not self.photo_consent or not self.photo_file_id):
            raise ValueError('Photo generation requires consent and a Telegram file reference')
        if not self.photo_enabled and (self.photo_consent or self.photo_file_id is not None):
            raise ValueError('Photo reference and consent require photo generation')
        return self


class TelegramCheckoutCheck(BaseModel):
    model_config = ConfigDict(extra='forbid')

    invoice_payload: Identifier
    external_user_id: Identifier
    currency: Literal['XTR']
    total_amount: int = Field(strict=True, gt=0)


class TelegramReceiptCreate(TelegramCheckoutCheck):
    telegram_payment_charge_id: Identifier


class TelegramInvoiceResponse(BaseModel):
    order_id: int
    invoice_payload: str
    currency: Literal['XTR']
    total_amount: int
    child_name: str
    photo_enabled: bool


class TelegramPrecheckoutResponse(BaseModel):
    ok: Literal[True]
    order_id: int


class TelegramReceiptResponse(BaseModel):
    order_id: int
    child_id: int
    status: Literal['paid']
    replayed: bool
    ready_story_id: int | None = None
    generation_payload: dict
    photo_file_id: str | None
