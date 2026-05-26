# mastercard-agentic-commerce-demo

A personal PoC of the Garanti BBVA / Mastercard Agent Pay conversational
commerce demo. Type a trip in natural language; the agent calls four mock
tools, ranks bundles with a deterministic scorer, and recommends the best
flight + hotel + payment-method combination — often pulling in a non-Garanti
card via Mastercard Agent Pay when its promotions win.

## Setup

**Requires Docker Desktop with Docker Model Runner and the gpt-oss model loaded.**

```bash
# 1. Verify the model is loaded and the runner is up
docker model ls
# You should see something like:  docker.io/ai/gpt-oss:latest  (or gpt-oss:latest)

# 2. If not yet loaded, pull it
docker model pull docker.io/gpt-oss:latest

# 3. Confirm the OpenAI-compatible endpoint responds
curl http://localhost:12434/engines/v1/models

# 4. Install Python deps (no API key needed)
pip install -r requirements.txt

# 5. Run
python run.py
```

**Model string note:** `run.py` defaults to `MODEL = "docker.io/ai/gpt-oss:latest"`.
If the `curl` above shows a different name for your model, update that constant.
Common variants: `"gpt-oss:latest"`, `"docker.io/gpt-oss:latest"`.

**Debug flag:** `VERBOSE=1 python run.py` prints the raw assistant message
(including tool_calls) each turn — useful when the model misbehaves.

## What you'll see

Each turn prints, in order:

  - `→ tool_call: ...` — every tool the model invokes, with arguments
  - `← {result}` — the tool's response (truncated)
  - `Agent: ...` — the model's natural-language reply

## Files

| File | What it is |
| --- | --- |
| `run.py` | CLI entrypoint and OpenAI tool-use loop |
| `tools/tools.py` | The four mock data tools + the Mastercard Agent Pay token tool |
| `scorer.py` | Deterministic bundle scorer: flight × hotel × payment → top 3 |
| `tool_schemas.py` | Tool descriptions in OpenAI function-calling format |
| `data/garanti_user.json` | The user's Garanti cards, miles, limits, promos |
| `data/flights.json` | Mock Skyscanner inventory (IST/SAW → DXB on 2026-06-15) |
| `data/hotels.json` | Mock Booking.com inventory (Dubai, 3 nights) |
| `data/agent_pay_feed.json` | User's non-Garanti cards + their promotions |
| `scenarios.md` | Suggested prompts and tweaks for experiments |

## Quirks and Improvements?

Currently the data is mocked and the model generally halucinates if there's close enough responses from the tool call. e.g. Exact flight match except for date; pretend there's the same flight today as well (not unreasonable)

The logic can be adjusted to be more strict. Or not. It's a low effort PoC, treat it like one.

See `scenarios.md` for specific things to try.

## "Architecture"

The agent is gpt-oss (20B, GGUF Q4) running locally via Docker Model Runner,
accessed through its OpenAI-compatible endpoint. Tools are local Python functions
that read JSON fixtures. The recommendation isn't pure-LLM: a deterministic scorer
enumerates every flight × hotel × payment-card combination, applies promotions,
filters by budget, dedupes, and returns the top 3. The model reads the scored
bundles and writes the natural-language recommendation. This split keeps the demo
reliable (the cross-bank insight always surfaces when it should) while keeping
the conversational layer flexible (refinements, explanations, follow-up).
