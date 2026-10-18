"""Test yardımcıları: sahte veri merkezi ve sahte Telegram (ağ gerektirmez)."""
from __future__ import annotations
from hbot.models import Bars


class FakeHub:
    """Tam bir sentetik mum dizisini 'canlı akış' gibi k mum görünür şekilde verir."""
    def __init__(self, bars: Bars, k: int | None = None):
        self.full, self.k = bars, k or len(bars)
        self.errors = []

    def get_bars(self, inst, tf, limit=800, ttl=0):
        return self.full.head_until(self.k - 1).tail(limit)


class FakeTG:
    def __init__(self):
        self.sent = []          # (tip, chat, metin, reply_to, png_bayt)
        self._id = 100

    def send_message(self, chat, text, reply_to=None, reply_markup=None, preview=False):
        self._id += 1
        self.sent.append(("msg", chat, text, reply_to, 0, reply_markup, self._id))
        return self._id

    def send_photo(self, chat, png, caption="", reply_to=None):
        self._id += 1
        self.sent.append(("photo", chat, caption, reply_to, len(png), None, self._id))
        return self._id

    def edit_message_text(self, chat, mid, text, reply_markup=None):
        self.sent.append(("edit", chat, text, mid, 0, reply_markup, mid))

    def answer_callback(self, cb_id, text=""):
        self.sent.append(("cb", 0, text, None, 0, None, 0))

    def set_commands(self, cmds):
        pass
