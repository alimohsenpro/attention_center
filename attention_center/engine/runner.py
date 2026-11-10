"""Run one source for one user: fault isolation, timing and the per-user count cache (§4.7)."""

import inspect
import logging
import time
from collections.abc import Callable
from datetime import datetime
from functools import cache
from time import perf_counter
from typing import TypeVar

import frappe
from frappe.utils import cint

from attention_center.engine import doctype_query
from attention_center.engine.contract import ContractError, Item, normalize_count, normalize_items

SETTINGS = "Attention Center Settings"
COUNT_CACHE = "attention_center:count:{}"
SLOW_SECONDS = 2

T = TypeVar("T")


def run_count(source: frappe._dict, user: str, since: datetime | None = None) -> dict:
	"""The source's counts with `state` "ok", or zeros with `state` "error" when the source failed.

	`user` must be the session user and `since` their watermark for the source (naive, in the system time
	zone). A result, failed or not, is reused for `summary_cache_ttl` seconds while the watermark is the same,
	so a broken or slow source is not run again on every summary.
	"""
	cache_name = COUNT_CACHE.format(source.key)
	cached = frappe.cache.hget(cache_name, user)
	if cached and cached["since"] == since and time.time() - cached["stored_at"] < _cache_ttl():
		return cached["result"]

	counts = _run(source, user, lambda: normalize_count(_count(source, user, since)))
	result = {"state": "ok", **counts} if counts is not None else {"state": "error", **normalize_count(0)}
	frappe.cache.hset(cache_name, user, {"stored_at": time.time(), "since": since, "result": result})
	return result


def run_items(source: frappe._dict, user: str, start: int, page_length: int) -> dict:
	"""At most `page_length` normalised items with `state` "ok", or none with `state` "error".

	`user` must be the session user.
	"""
	items = _run(source, user, lambda: _items(source, user, start, page_length))
	return {"state": "ok", "items": items} if items is not None else {"state": "error", "items": []}


def _count(source: frappe._dict, user: str, since: datetime | None) -> object:
	if source.source_type != "Python":
		return doctype_query.get_count(source, user, since)
	get_count = frappe.get_attr(source.get_count)
	return get_count(user, since=since) if _accepts_since(get_count) else get_count(user)


def _items(source: frappe._dict, user: str, start: int, page_length: int) -> list[Item]:
	if source.source_type != "Python":
		items = doctype_query.get_items(source, user, start, page_length)
	else:
		items = frappe.get_attr(source.get_items)(user, start, page_length)
	return normalize_items(source.key, items)[:page_length]


@cache
def _accepts_since(function: Callable) -> bool:
	return "since" in inspect.signature(function).parameters


def _run(source: frappe._dict, user: str, call: Callable[[], T]) -> T | None:
	"""What `call` returns, or None when it raised: one source never breaks the others [FR-SRC-05].

	Logs carry the source key, the user, the duration and the exception type, because an exception message
	may quote a document [NFR-PRIV-01]; only the contract's own messages, which quote nothing, are added.
	Messages the failed source queued for the user are dropped: the source shows as an error, not a dialog.
	"""
	queued_messages = len(frappe.local.message_log)
	started = perf_counter()
	try:
		result = call()
	except Exception as error:
		del frappe.local.message_log[queued_messages:]
		reason = (
			f"{type(error).__name__}: {error}" if isinstance(error, ContractError) else type(error).__name__
		)
		_logger().error(f"source {source.key} failed for {user} after {_elapsed_ms(started)} ms: {reason}")
		return None

	elapsed_ms = _elapsed_ms(started)
	if elapsed_ms > SLOW_SECONDS * 1000:
		_logger().warning(f"source {source.key} was slow for {user}: {elapsed_ms} ms")
	return result


def _elapsed_ms(started: float) -> int:
	return round((perf_counter() - started) * 1000)


def _cache_ttl() -> int:
	return cint(frappe.get_cached_doc(SETTINGS).summary_cache_ttl)


def _logger() -> logging.Logger:
	return frappe.logger("attention_center")
