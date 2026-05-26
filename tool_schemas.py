"""JSON schemas describing each tool to Claude."""

TOOL_SCHEMAS = [
    {
        "name": "get_user_payment_profile",
        "description": (
            "Retrieve the Garanti BBVA user's payment profile: their Garanti cards, "
            "available credit limits, points/miles balances, and currently active "
            "merchant promotions tied to those cards. Call this first to understand "
            "what the user can pay with and what Garanti-specific offers apply."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_flights",
        "description": (
            "Search for available flights between two airports on a specific date. "
            "Returns flight options with airline, times, duration, stops, price in USD, "
            "and the airline's miles program."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "IATA airport code, e.g. 'IST'"},
                "destination": {"type": "string", "description": "IATA airport code, e.g. 'DXB'"},
                "date": {"type": "string", "description": "Departure date in YYYY-MM-DD"},
                "time_preference": {
                    "type": "string",
                    "enum": ["morning", "afternoon", "evening"],
                    "description": "Optional departure-time window preference",
                },
                "max_price_usd": {"type": "number"},
            },
            "required": ["origin", "destination", "date"],
        },
    },
    {
        "name": "search_hotels",
        "description": (
            "Search for hotels in a city for a given check-in date and number of nights. "
            "Returns options with star rating, guest score, per-night price, total price, "
            "breakfast/refundable flags, and any Booking.com Genius discount."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "checkin_date": {"type": "string", "description": "YYYY-MM-DD"},
                "nights": {"type": "integer"},
                "max_price_per_night_usd": {"type": "number"},
                "min_star_rating": {"type": "integer"},
            },
            "required": ["city", "checkin_date", "nights"],
        },
    },
    {
        "name": "get_cross_bank_offers",
        "description": (
            "Via the Mastercard Agent Pay infrastructure, retrieve the user's cards "
            "issued by OTHER banks (not Garanti) along with any active promotions on "
            "those cards relevant to the supplied merchants. Use this to find better "
            "deals than what Garanti's own cards offer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "merchants": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Merchant names to check promotions for, e.g. "
                        "['Emirates', 'Turkish Airlines', 'Booking.com']"
                    ),
                }
            },
            "required": ["merchants"],
        },
    },
    {
        "name": "rank_bundles",
        "description": (
            "Run the deterministic bundle scorer. Pass in the flight results, hotel "
            "results, the user's Garanti profile, and the cross-bank offer feed. "
            "Returns the top N flight+hotel+payment-method bundles ranked by total "
            "cost after all promotions, with a cost breakdown and explanatory notes "
            "for each. Call this AFTER you've gathered all four data sources. "
            "You can call it multiple times with different filtered inputs if the "
            "user refines their preferences."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "flights": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "The 'results' array from search_flights",
                },
                "hotels": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "The 'results' array from search_hotels",
                },
                "garanti_profile": {
                    "type": "object",
                    "description": "The full object returned by get_user_payment_profile",
                },
                "cross_bank_feed": {
                    "type": "object",
                    "description": "The full object returned by get_cross_bank_offers",
                },
                "budget_usd": {"type": "number"},
                "top_n": {"type": "integer", "default": 5},
            },
            "required": [
                "flights", "hotels", "garanti_profile", "cross_bank_feed", "budget_usd"
            ],
        },
    },
    {
        "name": "create_agentic_pay_token",
        "description": (
            "FINAL STEP. Once the user has explicitly confirmed a specific bundle, "
            "issue a Mastercard Agentic Pay token to authorize the purchase. "
            "Do NOT call this until the user says yes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "bundle_summary": {
                    "type": "string",
                    "description": "Short human-readable description of what's being booked",
                },
                "card_id": {"type": "string"},
                "total_amount_usd": {"type": "number"},
            },
            "required": ["bundle_summary", "card_id", "total_amount_usd"],
        },
    },
]
