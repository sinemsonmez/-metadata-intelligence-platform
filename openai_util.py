"""
OpenAI Chat Completions API — 429 / kota için akıllı yeniden deneme.

Ortam: OPENAI_API_KEY (zorunlu; .env okunur).
İsteğe bağlı: OPENAI_MODEL (gpt-4o-mini), OPENAI_MIN_INTERVAL_SEC (varsayılan 0 = istekler arası bekleme yok),
OPENAI_MAX_RETRIES.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path


def _load_dotenv() -> None:
    """Proje kökündeki .env dosyasını yükle (python-dotenv)."""
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    except ImportError:
        pass


_load_dotenv()

from openai import OpenAI

_DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
# Varsayılan 0: ardışık çağrılar arasında yapay gecikme yok (maksimum hız).
_MIN_INTERVAL_SEC = float(
    os.environ.get("OPENAI_MIN_INTERVAL_SEC")
    or os.environ.get("GEMINI_MIN_INTERVAL_SEC")
    or "0"
)
_MAX_RETRIES = int(
    os.environ.get("OPENAI_MAX_RETRIES")
    or os.environ.get("GEMINI_MAX_RETRIES", "12")
)

_client: OpenAI | None = None

_last_call_monotonic = 0.0


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY yok. Proje kökünde .env içinde OPENAI_API_KEY=... "
                "veya ortam değişkeni tanımlayın."
            )
        _client = OpenAI(api_key=key)
    return _client


def _pace() -> None:
    """OPENAI_MIN_INTERVAL_SEC > 0 ise istekler arası minimum süre (kota için manuel yavaşlatma)."""
    global _last_call_monotonic
    if _MIN_INTERVAL_SEC <= 0:
        _last_call_monotonic = time.monotonic()
        return
    now = time.monotonic()
    wait = _MIN_INTERVAL_SEC - (now - _last_call_monotonic)
    if wait > 0:
        time.sleep(wait)
    _last_call_monotonic = time.monotonic()


def _retry_sleep_seconds(exc: BaseException, attempt: int) -> float:
    msg = str(exc).lower()
    m = re.search(r"try again in ([0-9.]+)\s*s", msg)
    if m:
        return min(float(m.group(1)) + 1.0, 120.0)
    m2 = re.search(r"retry[_-]?after[:\s]+([0-9]+)", msg)
    if m2:
        return min(int(m2.group(1)) + 1, 120)
    return min(0.5 * (2.0**attempt), 60.0)


def _is_quota_or_rate_limit(exc: BaseException) -> bool:
    msg = str(exc).lower()
    name = type(exc).__name__
    if "ratelimit" in name or "rate_limit" in msg:
        return True
    if "429" in str(exc) or "429" in msg:
        return True
    if "quota" in msg and ("exceed" in msg or "limit" in msg):
        return True
    if "too many requests" in msg:
        return True
    # openai.APIStatusError
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    return False


def generate_text(prompt: str) -> str:
    """Tek kullanıcı mesajı ile metin üretir; 429 vb. için yeniden dener."""
    last: BaseException | None = None
    model = os.environ.get("OPENAI_MODEL", _DEFAULT_MODEL)

    for attempt in range(_MAX_RETRIES):
        _pace()
        try:
            resp = _get_client().chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
                temperature=0.3,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return text
            last = RuntimeError("Boş model yanıtı")
            time.sleep(min(0.15 * (attempt + 1), 2.0))
        except Exception as e:
            last = e
            if not _is_quota_or_rate_limit(e):
                raise
            delay = _retry_sleep_seconds(e, attempt)
            time.sleep(delay)

    if last:
        raise last
    raise RuntimeError("generate_text: deneme limiti aşıldı")
