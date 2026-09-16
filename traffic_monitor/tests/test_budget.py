from __future__ import annotations

import time

from app.budget import ROLLING_WINDOW_SECONDS, BudgetGuard


def test_starts_empty_and_allows(tmp_path):
    guard = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=100)
    assert guard.used() == 0
    assert guard.remaining() == 100
    assert guard.allow() is True
    assert guard.is_warning() is False
    assert guard.is_exhausted() is False


def test_record_increments_usage(tmp_path):
    guard = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=100)
    guard.record(5)
    assert guard.used() == 5
    assert guard.remaining() == 95


def test_warning_threshold(tmp_path):
    guard = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=100, warn_threshold=0.8)
    guard.record(79)
    assert guard.is_warning() is False
    guard.record(1)
    assert guard.is_warning() is True
    assert guard.is_exhausted() is False


def test_exhausted_blocks_further_requests(tmp_path):
    guard = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=10)
    guard.record(10)
    assert guard.is_exhausted() is True
    assert guard.allow() is False
    assert guard.remaining() == 0


def test_remaining_never_negative(tmp_path):
    guard = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=10)
    guard.record(15)
    assert guard.remaining() == 0


def test_persists_across_instances(tmp_path):
    path = tmp_path / "usage.json"
    BudgetGuard(path=path, monthly_limit=100).record(30)

    reloaded = BudgetGuard(path=path, monthly_limit=100)
    assert reloaded.used() == 30


def test_entries_older_than_30_days_are_pruned(tmp_path):
    guard = BudgetGuard(path=tmp_path / "usage.json", monthly_limit=100)
    now = time.time()
    old = now - ROLLING_WINDOW_SECONDS - 3600  # just past the window
    recent = now - 3600  # an hour ago, well within the window

    guard.record(count=1, now=old)
    guard.record(count=1, now=recent)

    # used() with 'now' prunes as of that moment
    assert guard.used(now=now) == 1
