"""Tests for circuit breaker state machine and fallback behavior."""

from reliability_lab.circuit_breaker import CircuitBreaker, CircuitState
from reliability_lab.gateway import ReliabilityGateway
from reliability_lab.providers import FakeLLMProvider


def test_circuit_opens_after_consecutive_failures() -> None:
    provider = FakeLLMProvider("primary", fail_rate=1.0, base_latency_ms=1, cost_per_1k_tokens=0.001)
    breaker = CircuitBreaker("primary", failure_threshold=3, reset_timeout_seconds=60)
    for _ in range(3):
        try:
            breaker.call(provider.complete, "test")
        except Exception:
            pass
    assert breaker.state == CircuitState.OPEN
    assert not breaker.allow_request()


def test_circuit_transitions_in_log() -> None:
    provider = FakeLLMProvider("primary", fail_rate=1.0, base_latency_ms=1, cost_per_1k_tokens=0.001)
    breaker = CircuitBreaker("primary", failure_threshold=2, reset_timeout_seconds=0.1)
    for _ in range(2):
        try:
            breaker.call(provider.complete, "test")
        except Exception:
            pass
    assert breaker.state == CircuitState.OPEN
    assert len(breaker.transition_log) >= 1
    assert breaker.transition_log[0]["from"] == "closed"
    assert breaker.transition_log[0]["to"] == "open"


def test_backup_serves_when_primary_open() -> None:
    primary = FakeLLMProvider("primary", fail_rate=1.0, base_latency_ms=1, cost_per_1k_tokens=0.01)
    backup = FakeLLMProvider("backup", fail_rate=0.0, base_latency_ms=1, cost_per_1k_tokens=0.006)
    breaker_p = CircuitBreaker("primary", failure_threshold=2, reset_timeout_seconds=60)
    breaker_b = CircuitBreaker("backup", failure_threshold=5, reset_timeout_seconds=60)
    gateway = ReliabilityGateway(
        [primary, backup],
        {"primary": breaker_p, "backup": breaker_b},
    )
    for _ in range(2):
        try:
            gateway.complete("test")
        except Exception:
            pass
    result = gateway.complete("test")
    assert result.provider == "backup"
    assert result.route.startswith("fallback")


def test_static_fallback_when_all_providers_fail() -> None:
    primary = FakeLLMProvider("primary", fail_rate=1.0, base_latency_ms=1, cost_per_1k_tokens=0.01)
    backup = FakeLLMProvider("backup", fail_rate=1.0, base_latency_ms=1, cost_per_1k_tokens=0.006)
    breaker_p = CircuitBreaker("primary", failure_threshold=2, reset_timeout_seconds=60)
    breaker_b = CircuitBreaker("backup", failure_threshold=2, reset_timeout_seconds=60)
    gateway = ReliabilityGateway(
        [primary, backup],
        {"primary": breaker_p, "backup": breaker_b},
    )
    for _ in range(4):
        try:
            gateway.complete("test")
        except Exception:
            pass
    result = gateway.complete("test")
    assert result.route == "static_fallback"
    assert "degraded" in result.text.lower()
