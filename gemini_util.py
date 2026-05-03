"""
Ortak Gemini çağrısı: 429 kota / rate limit için bekleme + yeniden deneme.

Not: Google One / Gemini Advanced (sohbet) aboneliği, AI Studio API anahtarının
ücretsiz/ücretli kotasına otomatik eklenmez. Kotayı artırmak için genelde aynı
projede faturalandırma açılır: https://ai.google.dev/gemini-api/docs/rate-limits
"""

from __future__ import annotations

import os
import re
import time

import google.generativeai as genai

_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
genai.configure(api_key=_API_KEY)

# gemini-2.5-flash: güncel GA Flash; 2.0 bazı hesaplarda ücretsiz kota 0 gösterebiliyor.
# Daha güçlü çıktı: GEMINI_MODEL=gemini-2.5-pro
_DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
_model = genai.GenerativeModel(_DEFAULT_MODEL)

_MIN_INTERVAL_SEC = float(os.environ.get("GEMINI_MIN_INTERVAL_SEC", "2.5"))
_MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES", "12"))

_last_call_monotonic = 0.0


def _pace() -> None:
    global _last_call_monotonic
    now = time.monotonic()
    wait = _MIN_INTERVAL_SEC - (now - _last_call_monotonic)
    if wait > 0:
        time.sleep(wait)
    _last_call_monotonic = time.monotonic()


def _retry_sleep_seconds(exc: BaseException, attempt: int) -> float:
    msg = str(exc)
    m = re.search(r"retry in ([0-9.]+)\s*s", msg, re.I)
    if m:
        return min(float(m.group(1)) + 1.0, 120.0)
    m2 = re.search(r"seconds:\s*(\d+)", msg)
    if m2:
        return min(int(m2.group(1)) + 1, 120)
    return min(2.0**attempt, 90.0)


def _is_quota_or_rate_limit(exc: BaseException) -> bool:
    name = type(exc).__name__
    msg = str(exc).lower()
    if "ResourceExhausted" in name or "resource exhausted" in msg:
        return True
    if "429" in str(exc):
        return True
    if "quota" in msg and ("exceed" in msg or "limit" in msg):
        return True
    return False


def generate_text(prompt: str) -> str:
    """Tek metin üretimi; kota aşımında sunucunun önerdiği süre + üstel geri deneme."""
    last: BaseException | None = None
    for attempt in range(_MAX_RETRIES):
        _pace()
        try:
            resp = _model.generate_content(prompt)
            text = (resp.text or "").strip()
            if text:
                return text
            last = RuntimeError("Boş veya güvenlik filtresi nedeniyle yanıt yok")
            time.sleep(min(2.0**attempt, 15.0))
        except Exception as e:
            last = e
            if not _is_quota_or_rate_limit(e):
                raise
            delay = _retry_sleep_seconds(e, attempt)
            time.sleep(delay)
    if last:
        raise last
    raise RuntimeError("generate_text: deneme limiti aşıldı")
