"""LLM wrapper for a free stack: Gemini (AI Studio free tier) by default, Ollama for unlimited local
runs, Claude optional.

Each role (answer / fast / judge) is configured as "provider:model", e.g. "gemini:gemini-2.5-flash",
"ollama:llama3.1:8b", "anthropic:claude-opus-5". Every call is structured-output JSON (the pipeline
never parses free text). Calls are throttled per model to stay under free-tier requests-per-minute
limits, and a spent daily quota raises QuotaExhausted so batch jobs can stop cleanly and resume.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager
from typing import Literal

import httpx

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

Role = Literal["answer", "fast", "judge", "summary"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]
PROVIDERS = ("gemini", "ollama", "anthropic")

# $ per 1M tokens (input, output) for cost reporting. Free-tier Gemini and local Ollama cost nothing.
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
# Gemini 2.5 takes a thinking token budget (0 = off, -1 = dynamic); Gemini 3+ takes a thinking level.
THINKING_BUDGET = {"low": 0, "medium": 2048, "high": 8192, "xhigh": -1, "max": -1}
THINKING_LEVEL = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}


# Runs provider calls so they can be abandoned after a deadline (an abandoned call finishes in the background).
_CALLS = ThreadPoolExecutor(max_workers=16, thread_name_prefix="llm")


def parse_json(text: str) -> dict:
    """Parse the first JSON object in a model reply, ignoring code fences and trailing text
    (smaller models sometimes add a second object or a sentence after the JSON)."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    start = t.find("{")
    if start == -1:
        raise json.JSONDecodeError("no JSON object", t, 0)
    obj, _ = json.JSONDecoder().raw_decode(t[start:])
    return obj


class LLMError(RuntimeError):
    pass


class QuotaExhausted(LLMError):
    """The provider's daily quota is spent; retrying today won't help."""


def split_spec(spec: str) -> tuple[str, str]:
    """'gemini:gemini-2.5-flash' -> ('gemini', 'gemini-2.5-flash'); bare names are inferred."""
    head, _, rest = spec.partition(":")
    if head in PROVIDERS and rest:
        return head, rest
    if spec.startswith("claude"):
        return "anthropic", spec
    if spec.startswith("gemini"):
        return "gemini", spec
    return "ollama", spec


class RateLimiter:
    """Keeps each model under its requests-per-minute and (estimated) input-tokens-per-minute limits,
    across threads. Gemma's free tier allows 30 requests but only 16K tokens a minute, so both matter."""

    def __init__(self, rpm: dict[str, int], tpm: dict[str, int]):
        self.rpm, self.tpm = rpm, tpm
        self.log: dict[str, deque[tuple[float, int]]] = defaultdict(deque)
        self.lock = threading.Lock()

    def wait(self, model: str, tokens: int = 0) -> None:
        rpm, tpm = self.rpm.get(model), self.tpm.get(model)
        if not rpm and not tpm:
            return
        tokens = min(tokens, tpm) if tpm else tokens
        while True:
            with self.lock:
                now = time.monotonic()
                q = self.log[model]
                while q and now - q[0][0] >= 60:
                    q.popleft()
                used = sum(t for _, t in q)
                if (not rpm or len(q) < rpm) and (not tpm or used + tokens <= tpm):
                    q.append((now, tokens))
                    return
                pause = 60 - (now - q[0][0]) + 0.05
            time.sleep(max(pause, 0.05))


def estimate_tokens(*texts: str) -> int:
    return sum(len(t) for t in texts) // 4 + 50


class LLM:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()
        self._clients: dict[str, object] = {}
        self._lock = threading.Lock()
        self._local = threading.local()
        self.limiter = RateLimiter(self.s.llm_rpm, self.s.llm_tpm)
        self._spent: set[str] = set()  # model specs whose daily quota ran out in this process
        self.usage: dict[str, dict[str, int]] = defaultdict(lambda: {"input_tokens": 0, "output_tokens": 0, "calls": 0})

    def model_for(self, role: Role) -> str:
        if self.s.model_override:
            return self.s.model_override
        return {
            "answer": self.s.answer_model,
            "fast": self.s.fast_model,
            "judge": self.s.judge_model,
            "summary": self.s.summary_model,
        }[role]

    def json(
        self,
        *,
        system: str,
        user: str,
        schema: dict,
        role: Role = "answer",
        effort: Effort = "medium",
        max_tokens: int = 16000,
    ) -> dict:
        spec = self.model_for(role)
        if spec in self._spent and self.s.quota_fallback_model:
            spec = self.s.quota_fallback_model
        provider, model = split_spec(spec)
        call = {"gemini": self._gemini, "ollama": self._ollama, "anthropic": self._anthropic}[provider]
        try:
            return call(model, system, user, schema, effort, max_tokens)
        except QuotaExhausted:
            fb = self.s.quota_fallback_model
            if not fb or fb == spec:
                raise
            log.warning("%s daily quota spent; using %s for the rest of the day", spec, fb)
            self._spent.add(spec)
            p2, m2 = split_spec(fb)
            call = {"gemini": self._gemini, "ollama": self._ollama, "anthropic": self._anthropic}[p2]
            return call(m2, system, user, schema, effort, max_tokens)

    # ------------------------------------------------------------------ usage accounting

    @contextmanager
    def track(self) -> Iterator[dict[str, int]]:
        """Collect token usage of calls made on this thread (one question = one thread in eval)."""
        acc = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
        prev = getattr(self._local, "acc", None)
        self._local.acc = acc
        try:
            yield acc
        finally:
            self._local.acc = prev

    def _record(self, model: str, inp: int, out: int) -> None:
        with self._lock:
            u = self.usage[model]
            u["input_tokens"] += inp
            u["output_tokens"] += out
            u["calls"] += 1
        acc = getattr(self._local, "acc", None)
        if acc is not None:
            acc["input_tokens"] += inp
            acc["output_tokens"] += out
            acc["calls"] += 1

    def cost_usd(self) -> float:
        total = 0.0
        for model, u in self.usage.items():
            pin, pout = PRICES.get(model, (0.0, 0.0))
            total += u["input_tokens"] / 1e6 * pin + u["output_tokens"] / 1e6 * pout
        return total

    def calls(self) -> dict[str, int]:
        return {m: u["calls"] for m, u in self.usage.items()}

    def _client(self, name: str, factory):
        with self._lock:
            if name not in self._clients:
                self._clients[name] = factory()
            return self._clients[name]

    # ------------------------------------------------------------------ Gemini (AI Studio free tier)

    def _gemini(self, model: str, system: str, user: str, schema: dict, effort: Effort, max_tokens: int) -> dict:
        from google import genai
        from google.genai import errors, types

        def make_client():
            try:
                # reads GEMINI_API_KEY / GOOGLE_API_KEY; without a timeout a stalled free-tier request can hang for minutes
                # The SDK's own retries are disabled so this loop decides when to give up and fall back.
                http = types.HttpOptions(timeout=self.s.llm_timeout_s * 1000, retry_options=types.HttpRetryOptions(attempts=1))
                return genai.Client(http_options=http)
            except ValueError as e:
                raise LLMError("no Gemini key: set GEMINI_API_KEY (free at aistudio.google.com)") from e

        client = self._client("gemini", make_client)
        use_schema, use_thinking, recitation_retry = True, True, False
        for attempt in range(6):
            cfg = dict(
                system_instruction=system, response_mime_type="application/json", temperature=0, max_output_tokens=max_tokens
            )
            if use_schema:
                cfg["response_json_schema"] = schema
            else:  # schema feature rejected: describe it in the prompt instead
                cfg["system_instruction"] = f"{system}\n\nReply with JSON matching this JSON Schema:\n{json.dumps(schema)}"
            if use_thinking and "2.5" in model:
                cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=THINKING_BUDGET[effort])
            elif use_thinking and re.search(r"gemini-[3-9]", model):
                cfg["thinking_config"] = types.ThinkingConfig(thinking_level=THINKING_LEVEL[effort])
            self.limiter.wait(model, estimate_tokens(system, user))
            try:
                # Hard wall-clock deadline: free-tier requests can sit in a server-side queue for many minutes
                # while the connection stays alive, so the HTTP read timeout alone never fires.
                fut = _CALLS.submit(
                    client.models.generate_content, model=model, contents=user, config=types.GenerateContentConfig(**cfg)
                )
                try:
                    resp = fut.result(timeout=self.s.llm_timeout_s)
                except FutureTimeout:
                    fut.cancel()
                    raise httpx.ReadTimeout(f"no response within {self.s.llm_timeout_s}s") from None
            except errors.ClientError as e:
                detail = json.dumps(e.details) if e.details else str(e)
                if e.code == 429:
                    if "PerDay" in detail:
                        raise QuotaExhausted(f"{model}: free-tier daily quota used up; resume tomorrow") from e
                    delay = re.search(r'"retryDelay":\s*"(\d+)', detail)
                    wait = int(delay.group(1)) + 1 if delay else 20 * (attempt + 1)
                    log.info("%s: rate limited, waiting %ss", model, wait)
                    time.sleep(wait)
                    continue
                if e.code == 400 and use_schema and "schema" in detail.lower():
                    use_schema = False
                    continue
                if e.code == 400 and use_thinking and "thinking" in detail.lower():
                    use_thinking = False  # e.g. a level this model doesn't support: use its default
                    continue
                if e.code in (401, 403) or "API key" in detail:
                    raise LLMError("Gemini rejected the key: check GEMINI_API_KEY") from e
                raise LLMError(f"Gemini {e.code}: {e.message}") from e
            except (errors.ServerError, httpx.TransportError) as e:
                # 503 "high demand" spikes, timeouts and dropped connections are common on the free tier:
                # back off, then try the fallback model.
                what = f"{e.code} {e.message}" if isinstance(e, errors.ServerError) else f"{type(e).__name__}: {e}"
                if attempt >= 1:
                    fb = self.s.gemini_fallback_model
                    if fb and fb != model:
                        log.warning("%s unavailable (%s), falling back to %s", model, what, fb)
                        return self._gemini(fb, system, user, schema, effort, max_tokens)
                    raise LLMError(f"Gemini unavailable: {what}") from e
                log.info("%s: %s, retrying", model, what)
                time.sleep(4 * (attempt + 1))
                continue
            um = resp.usage_metadata
            inp = (um.prompt_token_count or 0) if um else 0
            out = ((um.candidates_token_count or 0) + (um.thoughts_token_count or 0)) if um else 0
            self._record(model, inp, out)
            if not resp.text:
                reason = str(resp.candidates[0].finish_reason) if resp.candidates else "no candidates"
                if "RECITATION" in reason and not recitation_retry:
                    # Google blocks output that repeats source text verbatim; ask again without long quotes.
                    recitation_retry = True
                    system += (
                        "\n\nImportant: do not reproduce passages from the sources verbatim; keep every quote under 12 words."
                    )
                    continue
                fb = self.s.gemini_fallback_model
                if "RECITATION" in reason and fb and fb != model:
                    log.warning("%s blocked the output for recitation, falling back to %s", model, fb)
                    return self._gemini(fb, system, user, schema, effort, max_tokens)
                raise LLMError(f"Gemini returned no text ({reason})")
            try:
                return parse_json(resp.text)
            except json.JSONDecodeError as e:
                # A recitation block can also cut the output off mid-string instead of blanking it.
                reason = str(resp.candidates[0].finish_reason) if resp.candidates else "no candidates"
                if "RECITATION" in reason and not recitation_retry:
                    recitation_retry = True
                    system += (
                        "\n\nImportant: do not reproduce passages from the sources verbatim; keep every quote under 12 words."
                    )
                    continue
                raise LLMError(f"Gemini returned invalid JSON ({reason}): {e}") from e
        raise LLMError(f"{model}: still rate limited after retries")

    # ------------------------------------------------------------------ Ollama (local, unlimited)

    def _ollama(self, model: str, system: str, user: str, schema: dict, effort: Effort, max_tokens: int) -> dict:
        try:
            r = httpx.post(
                f"{self.s.ollama_url}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "format": schema,
                    "stream": False,
                    "options": {"temperature": 0, "num_ctx": self.s.ollama_num_ctx, "num_predict": max_tokens},
                },
                timeout=600,
            )
        except httpx.ConnectError as e:
            raise LLMError(f"Ollama not reachable at {self.s.ollama_url} (start the Ollama app or `ollama serve`)") from e
        if r.status_code == 404:
            raise LLMError(f"Ollama model {model!r} not pulled (run `ollama pull {model}`)")
        r.raise_for_status()
        body = r.json()
        self._record(model, body.get("prompt_eval_count", 0), body.get("eval_count", 0))
        try:
            return parse_json(body["message"]["content"])
        except json.JSONDecodeError as e:
            raise LLMError(f"Ollama returned invalid JSON: {e}") from e

    # ------------------------------------------------------------------ Claude (optional, paid)

    def _anthropic(self, model: str, system: str, user: str, schema: dict, effort: Effort, max_tokens: int) -> dict:
        import anthropic

        client = self._client("anthropic", lambda: anthropic.Anthropic(max_retries=4))
        output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
        if "haiku" not in model:
            output_config["effort"] = effort
        kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )
        self.limiter.wait(model, estimate_tokens(system, user))
        try:
            if model.startswith(("claude-opus-5", "claude-fable")):
                # On a safety-classifier decline the API re-runs the request on a fallback model.
                resp = client.beta.messages.create(**kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            else:
                resp = client.messages.create(**kwargs)
        except anthropic.RateLimitError as e:
            raise LLMError(f"rate limited by the API: {e.message}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e.message} (request {e.request_id})") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"could not reach the Anthropic API: {e}") from e
        except TypeError as e:
            if "authentication" in str(e).lower():
                raise LLMError("no Anthropic credentials: set ANTHROPIC_API_KEY") from e
            raise
        self._record(resp.model or model, resp.usage.input_tokens, resp.usage.output_tokens)
        if resp.stop_reason == "refusal":
            raise LLMError("model declined the request")
        if resp.stop_reason == "max_tokens":
            raise LLMError(f"output truncated at max_tokens={max_tokens}")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise LLMError("no text block in response")
        return parse_json(text)


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = LLM()
    return _llm
