from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    channel: Mapped[str] = mapped_column(String(32), default='telegram')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Child(Base):
    __tablename__ = 'children'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    age: Mapped[int] = mapped_column(Integer)
    gender: Mapped[str] = mapped_column(String(32), default='neutral')
    preferred_style: Mapped[str] = mapped_column(String(32), default='auto')
    parent_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Story(Base):
    __tablename__ = 'stories'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    child_id: Mapped[int] = mapped_column(ForeignKey('children.id'), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey('orders.id'), nullable=True)
    episode_number: Mapped[int] = mapped_column(Integer, index=True)
    style: Mapped[str] = mapped_column(String(32), default='auto')
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    story_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    recap: Mapped[list] = mapped_column(JSONB, default=list)
    memory: Mapped[dict] = mapped_column(JSONB, default=dict)
    next_hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    images_urls: Mapped[list] = mapped_column(JSONB, default=list)
    pdf_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default='queued', index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Order(Base):
    __tablename__ = 'orders'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    child_id: Mapped[int] = mapped_column(ForeignKey('children.id'), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    tariff: Mapped[str] = mapped_column(String(64))
    amount_rub: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default='created', index=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
