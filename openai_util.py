"""
OpenAI Chat Completions API — paralel çağrı ve 429 için yeniden deneme.

Ortam: OPENAI_API_KEY (zorunlu; .env okunur).
İsteğe bağlı: OPENAI_MODEL, OPENAI_MAX_TOKENS, OPENAI_MAX_WORKERS,
OPENAI_MIN_INTERVAL_SEC, OPENAI_MAX_RETRIES.
"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    except ImportError:
        pass


_load_dotenv()

from openai import OpenAI

_DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
_MIN_INTERVAL_SEC = float(os.environ.get("OPENAI_MIN_INTERVAL_SEC", "0"))
_MAX_RETRIES = int(os.environ.get("OPENAI_MAX_RETRIES", "8"))
_MAX_WORKERS = int(os.environ.get("OPENAI_MAX_WORKERS", "16"))
_DEFAULT_MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "512"))

_client: OpenAI | None = None
_last_call_monotonic = 0.0
_pace_lock = None


def _get_pace_lock():
    global _pace_lock
    if _pace_lock is None:
        import threading

        _pace_lock = threading.Lock()
    return _pace_lock


def get_max_workers() -> int:
    return max(1, _MAX_WORKERS)


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
    global _last_call_monotonic
    if _MIN_INTERVAL_SEC <= 0:
        _last_call_monotonic = time.monotonic()
        return
    with _get_pace_lock():
        now = time.monotonic()
        wait = _MIN_INTERVAL_SEC - (now - _last_call_monotonic)
        if wait > 0:
            time.sleep(wait)
        _last_call_monotonic = time.monotonic()


def _retry_sleep_seconds(exc: BaseException, attempt: int) -> float:
    msg = str(exc).lower()
    m = re.search(r"try again in ([0-9.]+)\s*s", msg)
    if m:
        return min(float(m.group(1)) + 0.5, 60.0)
    m2 = re.search(r"retry[_-]?after[:\s]+([0-9]+)", msg)
    if m2:
        return min(int(m2.group(1)) + 0.5, 60)
    return min(0.25 * (2.0**attempt), 30.0)


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
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    return False


def generate_text(prompt: str, *, max_tokens: int | None = None) -> str:
    """Tek kullanıcı mesajı ile metin üretir; 429 vb. için yeniden dener."""
    last: BaseException | None = None
    model = os.environ.get("OPENAI_MODEL", _DEFAULT_MODEL)
    tokens = max_tokens if max_tokens is not None else _DEFAULT_MAX_TOKENS

    for attempt in range(_MAX_RETRIES):
        _pace()
        try:
            resp = _get_client().chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=tokens,
                temperature=0.2,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return text
            last = RuntimeError("Boş model yanıtı")
            time.sleep(min(0.1 * (attempt + 1), 1.0))
        except Exception as e:
            last = e
            if not _is_quota_or_rate_limit(e):
                raise
            time.sleep(_retry_sleep_seconds(e, attempt))

    if last:
        raise last
    raise RuntimeError("generate_text: deneme limiti aşıldı")


def run_parallel(
    tasks: list[T],
    fn: Callable[[T], object],
    *,
    max_workers: int | None = None,
    label: str = "API",
) -> list[object]:
    """Görev listesini paralel çalıştırır; sonuçlar gönderim sırasıyla döner."""
    if not tasks:
        return []
    workers = max_workers if max_workers is not None else get_max_workers()
    if len(tasks) == 1:
        return [fn(tasks[0])]

    results: list[object | None] = [None] * len(tasks)
    with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
        future_map = {pool.submit(fn, task): i for i, task in enumerate(tasks)}
        done = 0
        total = len(tasks)
        for fut in as_completed(future_map):
            idx = future_map[fut]
            results[idx] = fut.result()
            done += 1
            if done % 10 == 0 or done == total:
                print(f"  ⚡ {label}: {done}/{total}")
    return results  # type: ignore[return-value]
