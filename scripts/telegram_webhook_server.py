#!/usr/bin/env python3
"""Lightweight Telegram webhook receiver for copybot.

Receives Telegram updates over HTTPS (via nginx proxy) and appends them to a local
JSONL queue so multiple instances can consume without getUpdates conflicts.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from aiohttp import web


def _safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _queue_path() -> Path:
    raw = os.getenv("TELEGRAM_WEBHOOK_QUEUE_PATH", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent.parent / "logs" / "telegram_updates.jsonl"


def _queue_max_lines() -> int:
    return _safe_int(os.getenv("TELEGRAM_WEBHOOK_QUEUE_MAX_LINES", "2000"), 2000)


def _expected_secret() -> str:
    return os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()


def _append_update(update: dict) -> None:
    queue_path = _queue_path()
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(update, ensure_ascii=True, separators=(",", ":"))
    with queue_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

    max_lines = _queue_max_lines()
    if max_lines <= 0:
        return
    try:
        with queue_path.open("r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        if len(lines) <= max_lines:
            return
        tail = lines[-max_lines:]
        with queue_path.open("w", encoding="utf-8") as f:
            f.write("\n".join(tail) + "\n")
    except Exception:
        # Best-effort trimming only.
        return


async def handle_webhook(request: web.Request) -> web.Response:
    secret = _expected_secret()
    if secret:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if got != secret:
            return web.Response(status=401, text="unauthorized")

    try:
        payload = await request.json()
    except Exception:
        return web.Response(status=400, text="invalid json")

    if isinstance(payload, dict):
        _append_update(payload)
    return web.json_response({"ok": True})


async def handle_health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram webhook receiver")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()

    app = web.Application()
    app.router.add_post("/telegram-webhook", handle_webhook)
    app.router.add_get("/health", handle_health)
    web.run_app(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
