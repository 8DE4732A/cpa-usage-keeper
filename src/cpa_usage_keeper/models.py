"""SQLAlchemy ORM models matching the Go GORM schema."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_key = Column(String, unique=True, nullable=False)
    api_group_key = Column(String, default="", index=True)
    model = Column(String, default="", index=True)
    timestamp = Column(DateTime, index=True)
    source = Column(String, default="", index=True)
    auth_index = Column(String, default="", index=True)
    failed = Column(Boolean, default=False, index=True)
    latency_ms = Column(Integer, default=0)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    reasoning_tokens = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())


class RedisUsageInbox(Base):
    __tablename__ = "redis_usage_inboxes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    queue_key = Column(String, nullable=False, index=True)
    message_hash = Column(String, nullable=False, index=True)
    raw_message = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    last_error = Column(String, default="")
    usage_event_key = Column(String, default="", index=True)
    popped_at = Column(DateTime, nullable=False, index=True)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class AuthFile(Base):
    __tablename__ = "auth_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    auth_index = Column(String, unique=True, nullable=False)
    name = Column(String, default="")
    email = Column(String, default="")
    type = Column(String, default="")
    provider = Column(String, default="")
    label = Column(String, default="")
    status = Column(String, default="")
    source = Column(String, default="")
    disabled = Column(Boolean, default=False)
    unavailable = Column(Boolean, default=False)
    runtime_only = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime, nullable=True, index=True)


class ProviderMetadata(Base):
    __tablename__ = "provider_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lookup_key = Column(String, unique=True, nullable=False)
    provider_type = Column(String, default="", index=True)
    display_name = Column(String, default="")
    provider_key = Column(String, default="", index=True)
    match_kind = Column(String, default="")
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime, nullable=True, index=True)


class ModelPriceSetting(Base):
    __tablename__ = "model_price_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model = Column(String, unique=True, nullable=False)
    prompt_price_per_1m = Column(Float, default=0.0)
    completion_price_per_1m = Column(Float, default=0.0)
    cache_price_per_1m = Column(Float, default=0.0)
    openrouter_model_id = Column(String, nullable=True)
    openrouter_prompt_price_per_1m = Column(Float, nullable=True)
    openrouter_completion_price_per_1m = Column(Float, nullable=True)
    openrouter_cache_price_per_1m = Column(Float, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class NotificationChannel(Base):
    __tablename__ = "notification_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    channel_type = Column(String(50), nullable=False)  # "wecom_bot"
    config = Column(JSON, nullable=False)  # {"webhook_url": "https://qyapi.weixin.qq.com/..."}
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class NotificationRule(Base):
    __tablename__ = "notification_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    channel_id = Column(Integer, ForeignKey("notification_channels.id", ondelete="CASCADE"), nullable=False)
    rule_type = Column(String(50), nullable=False)  # "token_threshold" | "connection_failure"
    config = Column(JSON, nullable=False)
    # token_threshold:    {"threshold": 1000000, "window_minutes": 60}
    # connection_failure: {"window_minutes": 60}
    enabled = Column(Boolean, default=True)
    cooldown_minutes = Column(Integer, default=30)
    last_notified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


ALL_MODELS = [
    UsageEvent, RedisUsageInbox, AuthFile, ProviderMetadata,
    ModelPriceSetting, NotificationChannel, NotificationRule,
]
