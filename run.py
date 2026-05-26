"""Conversational agent loop — gpt-oss via Docker Model Runner.

Run with `python run.py`. No API key required; the model runs locally.

The CLI prints:
  - User messages (cyan)
  - Tool calls the model makes (yellow), with arguments
  - Tool results (dim), truncated for readability
  - Model's text replies (green)

Set VERBOSE=1 to also dump the raw assistant message each turn.
To exit, type 'quit'.
"""

import json
import os
import sys
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
  Step 1. Parse the user's trip intent (origin, destination, dates, budget, preferences).
  Step 2. Call ALL FOUR of these tools (you may call them in a single turn):
            - get_user_payment_profile  (no arguments)
            - search_flights            (origin, destination, date, and any preferences)
            - search_hotels             (city, checkin_date, nights)
            - get_cross_bank_offers     (merchants list, e.g. ["Emirates", "Turkish Airlines", \
"Pegasus", "Booking.com"])
  Step 3. Call rank_bundles with the results from all four tools above.
  Step 4. Present ONE primary recommendation in plain prose. Briefly mention 1-2 \
alternatives if any are genuinely close (within ~5% on cost) or trade off \
differently (cheaper but worse rating, etc.).
  Step 5. In the recommendation, explicitly call out which card to pay with and why, \
especially when it's a cross-bank card winning over the Garanti options.
  Step 6. If the user adjusts their preferences, re-call the relevant tools with \
updated parameters and re-run rank_bundles.
  Step 7. When the user confirms, call create_agentic_pay_token and tell them \
the booking is authorized.

IMPORTANT: Always call get_user_payment_profile, search_flights, search_hotels, \
and get_cross_bank_offers before calling rank_bundles. You may call them all \
in the same turn (parallel calls). Do not skip any of them.

Default origin for Turkish users is Istanbul (IST). Be concise — this is a chat \
interface, not a report. No bullet-point walls. Talk like a knowledgeable concierge."""


def _truncate(s: str, n: int = 600) -> str:
    return s if len(s) <= n else s[:n] + f" …[+{len(s) - n} chars]"


def dispatch_tool(name: str, args: dict[str, Any]) -> Any:
    """Route a tool call to the right Python function."""
    if name == "get_user_payment_profile":
        return tools.get_user_payment_profile()
    if name == "search_flights":
        return tools.search_flights(**args)
    if name == "search_hotels":
        return tools.search_hotels(**args)
    if name == "get_cross_bank_offers":
        return tools.get_cross_bank_offers(**args)
    if name == "rank_bundles":
        return rank_bundles(**args)
    if name == "create_agentic_pay_token":
        return tools.create_agentic_pay_token(**args)
    raise ValueError(f"Unknown tool: {name}")


def run_turn(client: OpenAI, messages: list[dict]) -> list[dict]:
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
                result = dispatch_tool(tc.function.name, args)
                result_str = json.dumps(result, default=str)
                print(f"{C_RESULT}  ← {_truncate(result_str, 400)}{C_RESET}")
            except json.JSONDecodeError as e:
                result_str = f"Error: could not parse tool arguments — {e}"
                print(f"{C_RESULT}  ← {result_str}{C_RESET}")
            except Exception as e:
                result_str = f"Error: {e}"
                print(f"{C_RESULT}  ← {result_str}{C_RESET}")

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
        run_turn(client, messages)
        print()


if __name__ == "__main__":
    main()
