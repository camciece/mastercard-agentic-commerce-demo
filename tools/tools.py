"""Mock implementations of the four data tools plus the Mastercard Agentic Pay token tool.

Each function reads its JSON fixture and returns a Python dict. Filtering parameters
are honored where they make sense; the data is small enough that this is just a
demonstration of shape, not a real search.
"""

import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent.parent / "data"


def _load(name: str) -> dict[str, Any]:
    with open(DATA_DIR / name) as f:
        return json.load(f)


# ----- Tool 1: Garanti Core Banking ------------------------------------------------

def get_user_payment_profile() -> dict[str, Any]:
    """Returns the user's Garanti cards, points/miles balances, available limits,
    and currently active Garanti merchant promotions."""
    return _load("garanti_user.json")


# ----- Tool 2: Skyscanner ----------------------------------------------------------

def search_flights(
    origin: str,
    destination: str,
    date: str,
    time_preference: str | None = None,
    max_price_usd: float | None = None,
) -> dict[str, Any]:
    """Search flights. time_preference is one of 'morning', 'afternoon', 'evening', None."""
    data = _load("flights.json")
    results = data["results"]

    if time_preference:
        def in_window(iso: str) -> bool:
            hour = datetime.fromisoformat(iso).hour
            if time_preference == "morning":
                return 5 <= hour < 12
            if time_preference == "afternoon":
                return 12 <= hour < 17
            if time_preference == "evening":
                return 17 <= hour <= 23
            return True
        results = [r for r in results if in_window(r["depart_time"])]

    if max_price_usd is not None:
        results = [r for r in results if r["price_usd"] <= max_price_usd]

    return {**data, "results": results, "filter_applied": {
        "origin": origin, "destination": destination, "date": date,
        "time_preference": time_preference, "max_price_usd": max_price_usd
    }}


# ----- Tool 3: Booking.com ---------------------------------------------------------

def search_hotels(
    city: str,
    checkin_date: str,
    nights: int,
    max_price_per_night_usd: float | None = None,
    min_star_rating: int | None = None,
) -> dict[str, Any]:
    data = _load("hotels.json")
    results = data["results"]

    if max_price_per_night_usd is not None:
        results = [r for r in results if r["price_per_night_usd"] <= max_price_per_night_usd]
    if min_star_rating is not None:
        results = [r for r in results if r["star_rating"] >= min_star_rating]

    # Recompute totals for the requested nights (fixture is 3-night totals; rescale).
    for r in results:
        r["total_usd"] = round(r["price_per_night_usd"] * nights, 2)

    return {**data, "results": results, "filter_applied": {
        "city": city, "checkin_date": checkin_date, "nights": nights,
        "max_price_per_night_usd": max_price_per_night_usd,
        "min_star_rating": min_star_rating
    }}


# ----- Tool 4: Agent Pay cross-bank feed ------------------------------------------

def get_cross_bank_offers(merchants: list[str]) -> dict[str, Any]:
    """Returns the user's non-Garanti cards (via Mastercard Agent Pay) and any
    active promotions matching the requested merchant list."""
    data = _load("agent_pay_feed.json")
    merchants_lower = {m.lower() for m in merchants}
    matched = [
        p for p in data["active_promotions"]
        if p["merchant"].lower() in merchants_lower
    ]
    return {
        "user_id": data["user_id"],
        "linked_cards": data["linked_cards"],
        "matched_promotions": matched,
        "filter_applied": {"merchants": merchants},
    }


# ----- Mastercard Agentic Pay -----------------------------------------------------

def create_agentic_pay_token(
    bundle_summary: str,
    card_id: str,
    total_amount_usd: float,
) -> dict[str, Any]:
    """Issues a Mastercard Agent Pay token authorizing this specific purchase
    on the named card. In the real system this is a scoped, single-use token
    issued by Mastercard after the user's in-app confirmation."""
    token = "mc_apay_" + secrets.token_hex(8)
    return {
        "status": "AUTHORIZED",
        "token": token,
        "card_id": card_id,
        "amount_usd": total_amount_usd,
        "bundle_summary": bundle_summary,
        "issued_at": datetime.utcnow().isoformat() + "Z",
        "expires_in_seconds": 300,
    }
