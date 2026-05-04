"""Pricing CRUD operations."""
from __future__ import annotations
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..models import ModelPriceSetting, UsageEvent

def list_used_models(db: Session) -> list[str]:
    rows = db.query(func.distinct(func.trim(UsageEvent.model))).filter(
        func.trim(UsageEvent.model) != "").order_by(func.trim(UsageEvent.model).asc()).all()
    return [m for (m,) in rows]

def list_pricing(db: Session) -> list[ModelPriceSetting]:
    return db.query(ModelPriceSetting).order_by(ModelPriceSetting.model.asc()).all()

def upsert_pricing(db: Session, model: str, prompt: float, completion: float, cache: float) -> ModelPriceSetting:
    model = model.strip()
    if not model:
        raise ValueError("model is required")
    existing = db.query(ModelPriceSetting).filter(ModelPriceSetting.model == model).first()
    if existing:
        existing.prompt_price_per_1m = prompt
        existing.completion_price_per_1m = completion
        existing.cache_price_per_1m = cache
        db.commit()
        db.refresh(existing)
        return existing
    setting = ModelPriceSetting(model=model, prompt_price_per_1m=prompt,
                                completion_price_per_1m=completion, cache_price_per_1m=cache)
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting

def delete_pricing(db: Session, model: str) -> None:
    model = model.strip()
    if not model:
        raise ValueError("model is required")
    db.query(ModelPriceSetting).filter(ModelPriceSetting.model == model).delete()
    db.commit()
