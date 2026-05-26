"""Conversational agent loop — gpt-oss via Docker Model Runner.

Run with `python run.py`. No API key required; the model runs locally.

The CLI prints:
  - User messages (cyan)
  - Tool calls the model makes (yellow), with arguments
  - Tool results (dim), truncated for readability
  - Model's text replies (green)

Set VERBOSE=1 to also dump the raw assistant message and full tracebacks.
To exit, type 'quit'.
"""

import json
import os
import sys
import traceback as tb
from typing import Any

from openai import OpenAI

import tools.tools as tools
from scorer import rank_bundles
from tool_schemas import TOOL_SCHEMAS

# ANSI colors for the terminal trace.
C_USER   = "\033[96m"   # cyan
C_TOOL   = "\033[93m"   # yellow
C_RESULT = "\033[2m"    # dim
C_AGENT  = "\033[92m"   # green
C_SYSTEM = "\033[95m"   # magenta
C_RESET  = "\033[0m"

# Docker Model Runner: verify the model name with `docker model ls`.
# Common variants: "docker.io/ai/gpt-oss:latest", "gpt-oss:latest", "docker.io/gpt-oss:latest"
MODEL = "docker.io/ai/gpt-oss:latest"

# Safety cap on model↔tool round-trips per user turn.
MAX_TURNS = 10

VERBOSE = os.environ.get("VERBOSE", "").strip() not in ("", "0")

SYSTEM_PROMPT = """You are the Garanti BBVA commerce agent — a conversational shopping \
assistant inside the Garanti BBVA mobile app. Users come to you to book travel \
(flights, hotels) and you find them the best deal by looking across:

  1. Their Garanti cards, miles, available limits, and Garanti-specific promotions
  2. Live flight inventory (via Skyscanner)
  3. Live hotel inventory (via Booking.com)
  4. Their cards from OTHER banks visible through the Mastercard Agent Pay network, \
     including promotions on those cards

Your job is to find combinations a human would miss. A cross-bank promo on one of \
the user's other cards can easily beat their Garanti options — surface that when it \
happens.

Step-by-step workflow — follow this exactly:

  Step 0 — Clarify before searching (do this FIRST):
    Before calling ANY tool, confirm you have all four of:
      • Destination city / airport
      • Departure date (exact date, YYYY-MM-DD)
      • Number of nights
      • Budget in USD (total for flights + hotel combined)
    If ANY is missing, ask for it in ONE short friendly message. Do NOT guess or \
assume. Do NOT call any tools until you have all four.
    Exception: if the user explicitly says cost is not a concern, use budget_usd=9999.

  Step 1. Parse the confirmed trip details (origin, destination, date, nights, budget).

  Step 2. Call ALL FOUR of these tools (you may call them in a single turn):
            - get_user_payment_profile  (no arguments)
            - search_flights            (origin, destination, date, and any preferences)
            - search_hotels             (city, checkin_date, nights)
            - get_cross_bank_offers     (merchants list — include all airlines from \
search results plus "Booking.com")

  Step 3. Call rank_bundles with budget_usd only. The flight, hotel, and payment \
data are supplied automatically from your previous tool calls.

  Step 4. Present ONE primary recommendation in plain prose. Briefly mention 1-2 \
alternatives if any are genuinely close (within ~5% on cost) or trade off \
differently (cheaper but worse rating, etc.).

  Step 5. In the recommendation, explicitly call out which card to pay with and why, \
especially when it's a cross-bank card winning over the Garanti options. This is \
the value the user is here for.

  Step 6. If the user adjusts their preferences, re-call the relevant tools with \
updated parameters and re-run rank_bundles.

  Step 7. When the user confirms, call create_agentic_pay_token and tell them \
the booking is authorized.

Default origin for Turkish users is Istanbul (IST). Be concise — this is a chat \
interface, not a report. No bullet-point walls. Talk like a knowledgeable concierge."""


def _truncate(s: str, n: int = 600) -> str:
    return s if len(s) <= n else s[:n] + f" …[+{len(s) - n} chars]"


# Keys required in the cache before rank_bundles can run.
_CACHE_KEYS = ("garanti_profile", "flights", "hotels", "cross_bank_feed")

# Maps each cache key to the tool that produces it.
_CACHE_KEY_SOURCE = {
    "garanti_profile": "get_user_payment_profile",
    "flights":         "search_flights",
    "hotels":          "search_hotels",
    "cross_bank_feed": "get_cross_bank_offers",
}


def dispatch_tool(name: str, args: dict[str, Any], tool_cache: dict) -> Any:
    """Route a tool call to the right Python function.

    Data tools populate `tool_cache` on success so that rank_bundles can
    retrieve the full, unmodified Python objects without the model needing
    to echo large JSON blobs back as arguments.
    """
    if name == "get_user_payment_profile":
        result = tools.get_user_payment_profile()
        tool_cache["garanti_profile"] = result
        return result

    if name == "search_flights":
        result = tools.search_flights(**args)
        tool_cache["flights"] = result.get("results", [])
        return result

    if name == "search_hotels":
        result = tools.search_hotels(**args)
        tool_cache["hotels"] = result.get("results", [])
        return result

    if name == "get_cross_bank_offers":
        result = tools.get_cross_bank_offers(**args)
        tool_cache["cross_bank_feed"] = result
        return result

    if name == "rank_bundles":
        missing = [k for k in _CACHE_KEYS if k not in tool_cache]
        if missing:
            needed_tools = [_CACHE_KEY_SOURCE[k] for k in missing]
            return {
                "error": (
                    f"Cannot rank yet — missing data from: {needed_tools}. "
                    "Please call those tools first, then retry rank_bundles."
                )
            }
        return rank_bundles(
            flights=tool_cache["flights"],
            hotels=tool_cache["hotels"],
            garanti_profile=tool_cache["garanti_profile"],
            cross_bank_feed=tool_cache["cross_bank_feed"],
            budget_usd=args["budget_usd"],
            top_n=args.get("top_n", 5),
        )

    if name == "create_agentic_pay_token":
        return tools.create_agentic_pay_token(**args)

    raise ValueError(f"Unknown tool: {name}")


def run_turn(client: OpenAI, messages: list[dict], tool_cache: dict) -> list[dict]:
    """Run one user turn through to the model's final text response.

    Mutates and returns `messages` with all assistant turns and tool
    result turns appended.
    """
    turns = 0
    while turns < MAX_TURNS:
        turns += 1

        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )

        msg = response.choices[0].message

        if VERBOSE:
            print(f"\n{C_SYSTEM}[VERBOSE raw message]{C_RESET}")
            print(json.dumps({
                "role": msg.role,
                "content": msg.content,
                "tool_calls": [
                    {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
                    for tc in (msg.tool_calls or [])
                ],
            }, indent=2))

        # Append assistant turn to history (serialised to plain dict).
        assistant_dict: dict[str, Any] = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            assistant_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_dict)

        # Print any text the model produced this turn.
        if msg.content and msg.content.strip():
            print(f"\n{C_AGENT}Agent:{C_RESET} {msg.content}")

        # No tool calls → model is done for this user turn.
        if not msg.tool_calls:
            return messages

        # Execute each tool call and collect results.
        for tc in msg.tool_calls:
            arg_str = tc.function.arguments or "{}"
            print(
                f"\n{C_TOOL}→ tool_call:{C_RESET} {tc.function.name}"
                f"({_truncate(arg_str, 200)})"
            )
            try:
                args = json.loads(arg_str)
                result = dispatch_tool(tc.function.name, args, tool_cache)
                result_str = json.dumps(result, default=str)
                print(f"{C_RESULT}  ← {_truncate(result_str, 400)}{C_RESET}")
            except json.JSONDecodeError as e:
                result_str = f"Error (JSONDecodeError): could not parse tool arguments — {e}"
                print(f"{C_RESULT}  ← {result_str}{C_RESET}")
            except Exception as e:
                result_str = f"Error ({type(e).__name__}): {e}"
                print(f"{C_RESULT}  ← {result_str}{C_RESET}")
                if VERBOSE:
                    print(tb.format_exc(), file=sys.stderr)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str,
            })

        # Loop: send tool results back to the model.

    print(f"\n{C_SYSTEM}[MAX_TURNS={MAX_TURNS} reached — stopping]{C_RESET}")
    return messages


def main():
    # Docker Model Runner needs no real key; the SDK still requires a non-empty string.
    client = OpenAI(
        base_url="http://localhost:12434/engines/v1",
        api_key="docker-model-runner",
    )
    messages: list[dict] = []
    # Stores the last successful result from each data tool so rank_bundles
    # can use clean Python objects without the model echoing large blobs back.
    tool_cache: dict = {}

    print(f"{C_SYSTEM}Garanti BBVA Commerce Agent (gpt-oss via Docker Model Runner){C_RESET}")
    print(f"{C_SYSTEM}Model: {MODEL}  |  Set VERBOSE=1 for raw message dumps{C_RESET}")
    print(f"{C_SYSTEM}Try: \"Work trip on June 15 to Dubai, 3 night stay. "
          f"$1500 budget, morning flight preferred\"{C_RESET}\n")

    while True:
        try:
            user_input = input(f"{C_USER}You:{C_RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit"}:
            break

        messages.append({"role": "user", "content": user_input})
        run_turn(client, messages, tool_cache)
        print()


if __name__ == "__main__":
    main()
