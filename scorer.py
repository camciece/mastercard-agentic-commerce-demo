"""Deterministic ranking over flight × hotel × payment-method bundles.

The LLM hands us the raw tool outputs and asks for the top N bundles.
We enumerate combinations, apply each candidate payment method's promotions,
filter by budget and other hard constraints, and rank.

The output is rich: each bundle includes a cost breakdown and a list of
'notes' explaining why each promo applied, so the LLM has clean material
to narrate the recommendation.
"""

from typing import Any
from itertools import product


def _flight_promo_for(card: dict, flight: dict, promotions: list[dict]) -> dict | None:
    """Find a promotion on `card` that applies to `flight`'s airline."""
    airline = flight["airline"]
    for p in promotions:
        if p.get("card_id") == card["card_id"] and p.get("merchant", "").lower() == airline.lower():
            return p
    return None


def _hotel_promo_for(card: dict, promotions: list[dict]) -> dict | None:
    """Find a Booking.com promotion on `card`."""
    for p in promotions:
        if p.get("card_id") == card["card_id"] and p["merchant"].lower() == "booking.com":
            return p
    return None


def _apply_percentage_promo(base_usd: float, promo: dict) -> tuple[float, str]:
    """Returns (discount_usd, human_readable_note)."""
    if promo.get("discount_type") not in ("percentage",):
        return 0.0, ""
    raw = base_usd * promo.get("discount_value", 0.0)
    cap = promo.get("max_discount_usd")
    discount = min(raw, cap) if cap is not None else raw
    note = f"{promo.get('description', 'discount')} → −${discount:.2f}"
    return discount, note


def rank_bundles(
    flights: list[dict],
    hotels: list[dict],
    garanti_profile: dict,
    cross_bank_feed: dict,
    budget_usd: float,
    top_n: int = 5,
) -> list[dict]:
    """Return the top N bundles ranked by total cost after promos."""

    # Build a unified pool of cards and promotions across Garanti + cross-bank.
    all_cards = list(garanti_profile["cards"]) + list(cross_bank_feed["linked_cards"])
    all_promos = (
        list(garanti_profile.get("active_promotions", []))
        + list(cross_bank_feed.get("matched_promotions", []))
    )

    bundles: list[dict] = []

    for flight, hotel in product(flights, hotels):
        # Try each card as the payment method for this flight+hotel pair.
        # The recommendation may suggest splitting (one card for flight,
        # another for hotel), so we consider that combinatorially.
        for flight_card, hotel_card in product(all_cards, all_cards):
            flight_price = flight["price_usd"]
            hotel_price = hotel["total_usd"]
            notes: list[str] = []

            # Booking.com Genius discount is intrinsic to the listing (not card-tied).
            genius = hotel.get("booking_genius_discount", 0.0)
            if genius:
                genius_discount = hotel_price * genius
                hotel_price -= genius_discount
                notes.append(f"Booking Genius {int(genius*100)}% → −${genius_discount:.2f}")

            # Apply card-tied promotions.
            f_promo = _flight_promo_for(flight_card, flight, all_promos)
            if f_promo:
                d, note = _apply_percentage_promo(flight["price_usd"], f_promo)
                flight_price -= d
                if note:
                    notes.append(f"[{flight_card['name']}] {note}")

            h_promo = _hotel_promo_for(hotel_card, all_promos)
            if h_promo:
                d, note = _apply_percentage_promo(hotel["total_usd"], h_promo)
                hotel_price -= d
                if note:
                    notes.append(f"[{hotel_card['name']}] {note}")

            total = flight_price + hotel_price
            if total > budget_usd:
                continue

            # Miles earned (informational, used as tiebreaker, not for cost).
            miles_note = ""
            if (
                flight.get("miles_eligible_program") == "Miles&Smiles"
                and flight_card.get("rewards_program") == "Turkish Airlines Miles"
            ):
                # Check for Garanti 2x miles promo.
                for p in all_promos:
                    if (
                        p.get("card_id") == flight_card["card_id"]
                        and p["merchant"].lower() == "turkish airlines"
                        and p.get("discount_type") == "miles_multiplier"
                    ):
                        bonus = flight["base_miles_earned"] * (p["discount_value"] - 1)
                        miles_note = (
                            f"+{int(flight['base_miles_earned'] + bonus)} Miles&Smiles "
                            f"(2x promo)"
                        )
                        notes.append(miles_note)
                        break
                else:
                    miles_note = f"+{flight['base_miles_earned']} Miles&Smiles"

            bundles.append({
                "flight": {
                    "id": flight["flight_id"],
                    "airline": flight["airline"],
                    "depart": flight["depart_time"],
                    "duration_min": flight["duration_minutes"],
                    "stops": flight["stops"],
                    "base_price_usd": flight["price_usd"],
                    "final_price_usd": round(flight_price, 2),
                },
                "hotel": {
                    "id": hotel["hotel_id"],
                    "name": hotel["name"],
                    "stars": hotel["star_rating"],
                    "guest_score": hotel["guest_score"],
                    "base_total_usd": hotel["total_usd"]
                        + hotel["total_usd"] * hotel.get("booking_genius_discount", 0.0),
                    "final_total_usd": round(hotel_price, 2),
                },
                "payment": {
                    "flight_card": flight_card["name"],
                    "flight_card_id": flight_card["card_id"],
                    "hotel_card": hotel_card["name"],
                    "hotel_card_id": hotel_card["card_id"],
                },
                "total_usd": round(total, 2),
                "savings_vs_base": round(
                    flight["price_usd"]
                    + hotel["total_usd"]
                    + hotel["total_usd"] * hotel.get("booking_genius_discount", 0.0)
                    - total, 2
                ),
                "notes": notes,
            })

    # Sort by total cost ascending, tiebreak by guest_score then star rating.
    bundles.sort(key=lambda b: (
        b["total_usd"],
        -b["hotel"]["guest_score"],
        -b["hotel"]["stars"],
    ))

    # Diversify the shortlist: for each FLIGHT, keep only the cheapest hotel
    # + payment-card combination. This way the top N shows distinct flight
    # options (Turkish vs Emirates vs Pegasus, etc.) rather than the same
    # cheap flight paired with several near-identical cheap hotels.
    #
    # Each flight's "best" pairing has already maximized hotel/promo savings
    # within budget, so the LLM gets a clean menu of trade-offs:
    #   "cheapest overall" vs "best airline with cross-bank promo" vs ...
    seen_flights: set[str] = set()
    by_flight: list[dict] = []
    for b in bundles:
        if b["flight"]["id"] in seen_flights:
            continue
        seen_flights.add(b["flight"]["id"])
        by_flight.append(b)

    return by_flight[:top_n]
