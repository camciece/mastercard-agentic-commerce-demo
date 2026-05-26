"""Conversational agent loop.

Run with `python run.py`. Requires ANTHROPIC_API_KEY in the environment.

The CLI prints:
  - User messages (cyan)
  - Tool calls Claude makes (yellow), with arguments
  - Tool results (dim), truncated for readability
  - Claude's text replies (green)

Refine your message, see how the reasoning changes. To exit, type 'quit'.
"""

import json
import os
import sys
from typing import Any

import anthropic

import tools.tools as tools
from scorer import rank_bundles
from tool_schemas import TOOL_SCHEMAS

# ANSI colors for the terminal trace.
C_USER = "\033[96m"      # cyan
C_TOOL = "\033[93m"      # yellow
C_RESULT = "\033[2m"     # dim
C_AGENT = "\033[92m"     # green
C_SYSTEM = "\033[95m"    # magenta
C_RESET = "\033[0m"

MODEL = "claude-opus-4-7"

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

Workflow:
  - Parse the user's trip intent (origin, destination, dates, budget, preferences).
  - In parallel, call: get_user_payment_profile, search_flights, search_hotels, \
    and get_cross_bank_offers (with the airlines and Booking.com as merchants).
  - Then call rank_bundles with all four results to get the top 3 bundles.
  - Present ONE primary recommendation in plain prose. Briefly mention 1-2 \
    alternatives if any are genuinely close (within ~5% on cost) or trade off \
    differently (cheaper but worse rating, etc.).
  - In the recommendation, explicitly call out which card to pay with and why, \
    especially when it's a cross-bank card winning over the Garanti options. This \
    is the value the user is here for.
  - If the user adjusts their preferences (different airline, higher rating, etc.), \
    re-call the relevant tools with updated parameters and re-rank.
  - When the user confirms, call create_agentic_pay_token and tell them the booking \
    is authorized.

Default origin for Turkish users is Istanbul (IST). Be concise — this is a chat \
interface, not a report. No bullet-point walls. Talk like a knowledgeable concierge."""


def _truncate(s: str, n: int = 600) -> str:
    return s if len(s) <= n else s[:n] + f" …[+{len(s) - n} chars]"


def dispatch_tool(name: str, args: dict[str, Any]) -> Any:
    """Route a tool call from Claude to the right Python function."""
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


def run_turn(client, messages: list[dict]) -> list[dict]:
    """Run one user turn through to Claude's final text response.

    Mutates and returns the `messages` list with all assistant turns and
    tool_result turns appended.
    """
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        # Record Claude's full turn (text + tool_use blocks) in history.
        messages.append({"role": "assistant", "content": response.content})

        # Render any text blocks first.
        for block in response.content:
            if block.type == "text" and block.text.strip():
                print(f"\n{C_AGENT}Agent:{C_RESET} {block.text}")

        # Collect tool_use blocks; if none, we're done.
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            return messages

        tool_results = []
        for tu in tool_uses:
            arg_preview = json.dumps(tu.input, default=str)
            print(
                f"\n{C_TOOL}→ tool_call:{C_RESET} {tu.name}"
                f"({_truncate(arg_preview, 200)})"
            )
            try:
                result = dispatch_tool(tu.name, tu.input)
                result_str = json.dumps(result, default=str)
                print(f"{C_RESULT}  ← {_truncate(result_str, 400)}{C_RESET}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result_str,
                })
            except Exception as e:
                print(f"{C_RESULT}  ← ERROR: {e}{C_RESET}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": f"Error: {e}",
                    "is_error": True,
                })

        messages.append({"role": "user", "content": tool_results})
        # Loop again so Claude can react to the tool results.


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            f"{C_SYSTEM}Set ANTHROPIC_API_KEY in your environment.{C_RESET}",
            file=sys.stderr,
        )
        sys.exit(1)

    client = anthropic.Anthropic()
    messages: list[dict] = []

    print(f"{C_SYSTEM}Garanti BBVA Commerce Agent — type 'quit' to exit.{C_RESET}")
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
