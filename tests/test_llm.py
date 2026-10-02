import time

from app.llm import RateLimiter, split_spec


def test_model_specs():
    assert split_spec("gemini:gemini-3.5-flash-lite") == ("gemini", "gemini-3.5-flash-lite")
    assert split_spec("ollama:llama3.1:8b") == ("ollama", "llama3.1:8b")
    assert split_spec("claude-opus-5") == ("anthropic", "claude-opus-5")
    assert split_spec("gemini-3.8-flash") == ("gemini", "gemini-3.8-flash")
    assert split_spec("llama3.1:8b") == ("ollama", "llama3.1:8b")


def test_rate_limiter_enforces_requests_and_tokens_per_minute(monkeypatch):
    clock = {"t": 1000.0}
    slept: list[float] = []

    def fake_sleep(s):
        slept.append(s)
        clock["t"] += s

    monkeypatch.setattr(time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(time, "sleep", fake_sleep)
    rl = RateLimiter(rpm={"m": 2}, tpm={"t": 10_000})
    rl.wait("m")
    rl.wait("m")
    assert not slept
    rl.wait("m")  # third request in the same minute waits for the window to roll
    assert 59 < sum(slept) < 61
    slept.clear()
    rl.wait("t", 8000)
    rl.wait("t", 8000)  # 16K tokens would exceed the 10K/minute budget
    assert 59 < sum(slept) < 61
    slept.clear()
    rl.wait("unlimited", 10**9)
    assert not slept


def test_quota_fallback_switches_model_for_the_rest_of_the_day():
    from app.config import Settings
    from app.llm import LLM, QuotaExhausted

    llm = LLM(Settings(answer_model="gemini:primary", quota_fallback_model="gemini:backup", llm_rpm={}, llm_tpm={}))
    calls: list[str] = []

    def fake(model, *_):
        calls.append(model)
        if model == "primary":
            raise QuotaExhausted("spent")
        return {"ok": model}

    llm._gemini = fake
    assert llm.json(system="s", user="u", schema={}, role="answer") == {"ok": "backup"}
    assert llm.json(system="s", user="u", schema={}, role="answer") == {"ok": "backup"}
    assert calls == ["primary", "backup", "backup"]  # the spent model isn't retried


def test_no_quota_fallback_in_benchmarks():
    import pytest

    from app.config import Settings
    from app.llm import LLM, QuotaExhausted

    llm = LLM(Settings(answer_model="gemini:primary", quota_fallback_model=None, llm_rpm={}, llm_tpm={}))

    def fake(model, *_):
        raise QuotaExhausted("spent")

    llm._gemini = fake
    with pytest.raises(QuotaExhausted):
        llm.json(system="s", user="u", schema={}, role="answer")
