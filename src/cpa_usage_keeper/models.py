"""SQLAlchemy ORM models matching the Go GORM schema."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class SnapshotRun(Base):
    __tablename__ = "snapshot_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fetched_at = Column(DateTime, index=True)
    cpa_base_url = Column(String, default="")
    exported_at = Column(DateTime, nullable=True)
    version = Column(String, default="")
    status = Column(String, default="pending", index=True)
    http_status = Column(Integer, default=0)
    payload_hash = Column(String, default="")
    raw_payload = Column(LargeBinary, nullable=True)
    backup_file_path = Column(String, default="")
    error_message = Column(String, default="")
    inserted_events = Column(Integer, default=0)
    deduped_events = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_key = Column(String, unique=True, nullable=False)
    snapshot_run_id = Column(Integer, default=0)
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
    snapshot_run_id = Column(Integer, nullable=True, index=True)
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
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


ALL_MODELS = [SnapshotRun, UsageEvent, RedisUsageInbox, AuthFile, ProviderMetadata, ModelPriceSetting]
