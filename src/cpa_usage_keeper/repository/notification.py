"""Notification channel & rule CRUD, rule evaluation, and webhook delivery."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import NotificationChannel, NotificationRule, UsageEvent

# ── Channel CRUD ──────────────────────────────────────────────────────────────


def list_channels(db: Session) -> list[dict[str, Any]]:
    rows = db.query(NotificationChannel).order_by(NotificationChannel.id.asc()).all()
    return [_channel_to_dict(r) for r in rows]


def get_channel(db: Session, channel_id: int) -> NotificationChannel | None:
    return db.query(NotificationChannel).filter(NotificationChannel.id == channel_id).first()


def create_channel(
    db: Session,
    name: str,
    channel_type: str,
    config: dict[str, Any],
    enabled: bool = True,
) -> dict[str, Any]:
    ch = NotificationChannel(
        name=name.strip(),
        channel_type=channel_type.strip(),
        config=config,
        enabled=enabled,
    )
    db.add(ch)
    db.commit()
    db.refresh(ch)
    return _channel_to_dict(ch)


def update_channel(
    db: Session,
    channel_id: int,
    name: str | None = None,
    channel_type: str | None = None,
    config: dict[str, Any] | None = None,
    enabled: bool | None = None,
) -> dict[str, Any] | None:
    ch = get_channel(db, channel_id)
    if ch is None:
        return None
    if name is not None:
        ch.name = name.strip()
    if channel_type is not None:
        ch.channel_type = channel_type.strip()
    if config is not None:
        ch.config = config
    if enabled is not None:
        ch.enabled = enabled
    db.commit()
    db.refresh(ch)
    return _channel_to_dict(ch)


def delete_channel(db: Session, channel_id: int) -> bool:
    """Delete a channel and its associated rules."""
    ch = get_channel(db, channel_id)
    if ch is None:
        return False
    # Cascade delete rules
    db.query(NotificationRule).filter(NotificationRule.channel_id == channel_id).delete()
    db.delete(ch)
    db.commit()
    return True


# ── Rule CRUD ─────────────────────────────────────────────────────────────────


def list_rules(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(NotificationRule, NotificationChannel.name.label("channel_name"))
        .outerjoin(
            NotificationChannel,
            NotificationRule.channel_id == NotificationChannel.id,
        )
        .order_by(NotificationRule.id.asc())
        .all()
    )
    result = []
    for rule, channel_name in rows:
        d = _rule_to_dict(rule)
        d["channel_name"] = channel_name or ""
        result.append(d)
    return result


def get_rule(db: Session, rule_id: int) -> NotificationRule | None:
    return db.query(NotificationRule).filter(NotificationRule.id == rule_id).first()


def create_rule(
    db: Session,
    name: str,
    channel_id: int,
    rule_type: str,
    config: dict[str, Any],
    enabled: bool = True,
    cooldown_minutes: int = 30,
) -> dict[str, Any]:
    rule = NotificationRule(
        name=name.strip(),
        channel_id=channel_id,
        rule_type=rule_type.strip(),
        config=config,
        enabled=enabled,
        cooldown_minutes=cooldown_minutes,
    )
    # Validate channel exists
    ch = get_channel(db, channel_id)
    if ch is None:
        raise ValueError(f"NotificationChannel with id={channel_id} not found")
    db.add(rule)
    db.commit()
    db.refresh(rule)
    ch_name = ch.name
    d = _rule_to_dict(rule)
    d["channel_name"] = ch_name
    return d


def update_rule(
    db: Session,
    rule_id: int,
    name: str | None = None,
    channel_id: int | None = None,
    rule_type: str | None = None,
    config: dict[str, Any] | None = None,
    enabled: bool | None = None,
    cooldown_minutes: int | None = None,
) -> dict[str, Any] | None:
    rule = get_rule(db, rule_id)
    if rule is None:
        return None
    if name is not None:
        rule.name = name.strip()
    if channel_id is not None:
        if get_channel(db, channel_id) is None:
            raise ValueError(f"NotificationChannel with id={channel_id} not found")
        rule.channel_id = channel_id
    if rule_type is not None:
        rule.rule_type = rule_type.strip()
    if config is not None:
        rule.config = config
    if enabled is not None:
        rule.enabled = enabled
    if cooldown_minutes is not None:
        rule.cooldown_minutes = cooldown_minutes
    db.commit()
    db.refresh(rule)
    d = _rule_to_dict(rule)
    ch = get_channel(db, rule.channel_id)
    d["channel_name"] = ch.name if ch else ""
    return d


def delete_rule(db: Session, rule_id: int) -> bool:
    rule = get_rule(db, rule_id)
    if rule is None:
        return False
    db.delete(rule)
    db.commit()
    return True


# ── Rule Evaluation ───────────────────────────────────────────────────────────


def evaluate_rules(db: Session) -> list[dict[str, Any]]:
    """Evaluate all enabled rules and schedule notifications for triggered ones.

    IMPORTANT: This function only evaluates rules against the database and queues
    up pending notifications. The actual webhook sending is done by the caller
    (NotificationRunner) so the DB session is not held during HTTP calls —
    with pool_size=1 a 15-second webhook timeout would block all other requests.

    Returns a list of dicts describing triggered evaluations (without sending).
    """
    now = datetime.now(timezone.utc)
    pending: list[dict[str, Any]] = []

    rules = (
        db.query(NotificationRule, NotificationChannel)
        .join(NotificationChannel, NotificationRule.channel_id == NotificationChannel.id)
        .filter(NotificationRule.enabled == True)  # noqa: E712
        .filter(NotificationChannel.enabled == True)  # noqa: E712
        .all()
    )

    # ── Evaluator dispatch ─────────────────────────────────────
    _EVALUATORS = {
        "token_threshold": _eval_token_threshold,
        "connection_failure": _eval_connection_failure,
    }

    for rule, channel in rules:
        # Cooldown check
        if rule.last_notified_at is not None:
            cooldown_end = rule.last_notified_at.replace(tzinfo=timezone.utc) + timedelta(
                minutes=rule.cooldown_minutes
            )
            if now < cooldown_end:
                continue

        # Delegate evaluation via dispatch dict
        evaluator = _EVALUATORS.get(rule.rule_type)
        if evaluator is None:
            continue
        triggered_flag, message = evaluator(db, rule.config)

        if not triggered_flag:
            continue

        pending.append({
            "rule_id": rule.id,
            "rule_name": rule.name,
            "channel_name": channel.name,
            "channel_config": channel.config,
            "message": message,
            "now": now,
            "cooldown_minutes": rule.cooldown_minutes,
        })

    return pending


def send_pending_notifications(
    db: Session, pending: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Deliver pending notifications outside the evaluation transaction.

    Sends each webhook, then updates last_notified_at on success.
    Caller owns the DB session and should close it afterward.
    """
    results: list[dict[str, Any]] = []
    for p in pending:
        try:
            _send_wecom(p["channel_config"], p["rule_name"], p["message"])
        except Exception as exc:
            logger.error(
                f"Failed to send notification for rule '{p['rule_name']}' "
                f"via channel '{p['channel_name']}': {exc}"
            )
            results.append({
                "rule_id": p["rule_id"],
                "rule_name": p["rule_name"],
                "channel_name": p["channel_name"],
                "sent": False,
                "error": str(exc),
            })
            continue

        # Update last_notified_at with a single UPDATE query (no N+1 SELECT)
        db.query(NotificationRule).filter(
            NotificationRule.id == p["rule_id"]
        ).update(
            {"last_notified_at": p["now"].replace(tzinfo=None)}
        )

        results.append({
            "rule_id": p["rule_id"],
            "rule_name": p["rule_name"],
            "channel_name": p["channel_name"],
            "sent": True,
        })

    # Single batch commit — avoids N fsyncs on SQLite WAL.
    if results:
        db.commit()

    return results


def test_webhook(db: Session, channel_id: int) -> bool:
    """Send a test message to a channel's webhook."""
    ch = get_channel(db, channel_id)
    if ch is None:
        raise ValueError(f"NotificationChannel with id={channel_id} not found")
    _send_wecom(ch.config, "测试消息", "这是一条来自 CPA Usage Keeper 的测试消息。\n如果你的企业微信收到了这条消息，说明通知配置正确。")
    return True


# ── Rule Evaluators ───────────────────────────────────────────────────────────


def _eval_token_threshold(
    db: Session, config: dict[str, Any]
) -> tuple[bool, str]:
    """Check if total tokens in the window exceed the threshold."""
    window = int(config.get("window_minutes", 60))
    threshold = float(config.get("threshold", 0))

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window)
    row = db.query(func.coalesce(func.sum(UsageEvent.total_tokens), 0)).filter(
        UsageEvent.timestamp >= cutoff
    ).first()
    total_tokens = row[0] if row else 0

    if total_tokens < threshold:
        return False, ""

    # Build detail: model breakdown
    model_rows = (
        db.query(
            UsageEvent.model,
            func.sum(UsageEvent.total_tokens),
            func.count(UsageEvent.id),
        )
        .filter(UsageEvent.timestamp >= cutoff)
        .group_by(UsageEvent.model)
        .order_by(func.sum(UsageEvent.total_tokens).desc())
        .limit(10)
        .all()
    )

    lines = [
        f"**Token 用量告警**\n"
        f"> **时间窗口**: 过去 {window} 分钟\n"
        f"> **当前用量**: {total_tokens:,} tokens\n"
        f"> **告警阈值**: {int(threshold):,} tokens\n"
    ]
    if model_rows:
        lines.append("\n**模型用量 TOP 10**:")
        for m, tokens, count in model_rows:
            model_name = m.strip() if m else "unknown"
            lines.append(f"> {model_name}: {tokens:,} tokens ({count} 次请求)")

    return True, "\n".join(lines)


def _eval_connection_failure(
    db: Session, config: dict[str, Any]
) -> tuple[bool, str]:
    """Check if there were any failed connection events in the window."""
    window = int(config.get("window_minutes", 60))
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window)

    # Check for failed usage events
    row = db.query(
        func.count(UsageEvent.id),
    ).filter(
        UsageEvent.timestamp >= cutoff,
        UsageEvent.failed == True,  # noqa: E712
    ).first()
    fail_count = row[0] if row else 0

    if fail_count == 0:
        return False, ""

    # Get recent errors
    error_rows = (
        db.query(UsageEvent.model, UsageEvent.latency_ms)
        .filter(
            UsageEvent.timestamp >= cutoff,
            UsageEvent.failed == True,  # noqa: E712
        )
        .order_by(UsageEvent.timestamp.desc())
        .limit(5)
        .all()
    )

    lines = [
        f"**连接失败告警**\n"
        f"> **时间窗口**: 过去 {window} 分钟\n"
        f"> **失败请求数**: {fail_count}\n"
    ]
    if error_rows:
        lines.append("\n**最近失败记录**:")
        for model_name, latency in error_rows:
            mn = model_name.strip() if model_name else "unknown"
            lines.append(f"> {mn} (延迟: {latency}ms)")

    return True, "\n".join(lines)


# ── Webhook Delivery ──────────────────────────────────────────────────────────


def _send_wecom(config: dict[str, Any], title: str, content: str) -> None:
    """Send a markdown message to a WeCom (企业微信) Bot webhook."""
    webhook_url = (config.get("webhook_url") or "").strip()
    if not webhook_url:
        raise ValueError("webhook_url is required in channel config")

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": f"# {title}\n{content}",
        },
    }

    resp = httpx.post(webhook_url, json=payload, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    errcode = body.get("errcode", -1)
    if errcode != 0:
        raise RuntimeError(
            f"WeCom webhook returned errcode={errcode}: {body.get('errmsg', '')}"
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _channel_to_dict(ch: NotificationChannel) -> dict[str, Any]:
    return {
        "id": ch.id,
        "name": ch.name,
        "channel_type": ch.channel_type,
        "config": ch.config,
        "enabled": ch.enabled,
        "created_at": ch.created_at.isoformat() if ch.created_at else "",
        "updated_at": ch.updated_at.isoformat() if ch.updated_at else "",
    }


def _rule_to_dict(rule: NotificationRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "name": rule.name,
        "channel_id": rule.channel_id,
        "rule_type": rule.rule_type,
        "config": rule.config,
        "enabled": rule.enabled,
        "cooldown_minutes": rule.cooldown_minutes,
        "last_notified_at": rule.last_notified_at.isoformat() if rule.last_notified_at else None,
        "created_at": rule.created_at.isoformat() if rule.created_at else "",
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else "",
    }
