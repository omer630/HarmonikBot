"""Telegram Bot API için ince istemci (sadece `requests`). Ek bot kütüphanesi gerekmez."""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Optional

import requests

log = logging.getLogger("hbot.tg")


class TelegramError(Exception):
    def __init__(self, msg: str, code: int = 0):
        super().__init__(msg)
        self.code = code


class Telegram:
    def __init__(self, token: str, base: str = "https://api.telegram.org", min_gap: float = 1.1):
        self.url = f"{base.rstrip('/')}/bot{token}"
        self.s = requests.Session()
        self.min_gap = min_gap
        self._send_lock = threading.Lock()
        self._last_send = 0.0

    # ── temel çağrı ──
    def call(self, method: str, data: Optional[dict] = None, files: Optional[dict] = None, timeout: float = 30,
             retries: int = 3):
        data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in (data or {}).items() if v is not None}
        err: Optional[Exception] = None
        for attempt in range(retries):
            try:
                r = self.s.post(f"{self.url}/{method}", data=data, files=files, timeout=timeout)
                js = r.json()
            except Exception as e:  # noqa: BLE001  (ağ hatası, JSON hatası)
                err = e
                time.sleep(1.5 * (attempt + 1))
                continue
            if js.get("ok"):
                return js.get("result")
            code = int(js.get("error_code", r.status_code))
            desc = js.get("description", "")
            if code == 429:
                wait = float((js.get("parameters") or {}).get("retry_after", 3)) + 0.5
                log.warning("Telegram 429, %.1fs bekleniyor", wait)
                time.sleep(wait)
                err = TelegramError(desc, code)
                continue
            if code >= 500:
                err = TelegramError(desc, code)
                time.sleep(1.5 * (attempt + 1))
                continue
            raise TelegramError(desc, code)
        raise TelegramError(f"{method} başarısız: {err}")

    def _throttle(self) -> None:
        with self._send_lock:
            wait = self.min_gap - (time.time() - self._last_send)
            if wait > 0:
                time.sleep(wait)
            self._last_send = time.time()

    # ── gönderim ──
    def send_message(self, chat_id, text: str, reply_to: Optional[int] = None, reply_markup: Optional[dict] = None,
                     preview: bool = False) -> int:
        self._throttle()
        data = dict(chat_id=chat_id, text=text[:4000], parse_mode="HTML", reply_markup=reply_markup,
                    link_preview_options={"is_disabled": not preview})
        if reply_to:
            data["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        return int(self.call("sendMessage", data)["message_id"])

    def send_photo(self, chat_id, png: bytes, caption: str = "", reply_to: Optional[int] = None) -> int:
        self._throttle()
        data = dict(chat_id=chat_id, caption=caption[:1024], parse_mode="HTML")
        if reply_to:
            data["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        return int(self.call("sendPhoto", data, files={"photo": ("card.png", png, "image/png")}, timeout=60)["message_id"])

    def edit_message_text(self, chat_id, message_id: int, text: str, reply_markup: Optional[dict] = None) -> None:
        try:
            self.call("editMessageText", dict(chat_id=chat_id, message_id=message_id, text=text[:4000], parse_mode="HTML",
                                              reply_markup=reply_markup, link_preview_options={"is_disabled": True}))
        except TelegramError as e:
            if "not modified" not in str(e):
                raise

    def answer_callback(self, cb_id: str, text: str = "") -> None:
        try:
            self.call("answerCallbackQuery", dict(callback_query_id=cb_id, text=text[:190] or None), retries=1)
        except TelegramError:
            pass

    def get_updates(self, offset: int, timeout: int = 25) -> list:
        return self.call("getUpdates", dict(offset=offset, timeout=timeout, allowed_updates=["message", "callback_query"]),
                         timeout=timeout + 15, retries=1) or []

    def set_commands(self, cmds: list[tuple[str, str]]) -> None:
        try:
            self.call("setMyCommands", dict(commands=[dict(command=c, description=d) for c, d in cmds]), retries=1)
        except TelegramError as e:
            log.warning("setMyCommands: %s", e)
