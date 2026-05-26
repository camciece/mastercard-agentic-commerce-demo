"""Tool schemas in OpenAI function-calling format.

Each entry follows the OpenAI spec:
  { "type": "function", "function": { "name", "description", "parameters" } }

The JSON Schema bodies inside "parameters" are identical to the original
Anthropic input_schema objects — only the outer wrapper changed.
"""

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_user_payment_profile",
            "description": (
                "Retrieve the Garanti BBVA user's payment profile: their Garanti cards, "
                "available credit limits, points/miles balances, and currently active "
                "merchant promotions tied to those cards. Call this first to understand "
                "what the user can pay with and what Garanti-specific offers apply."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_flights",
            "description": (
                "Search for available flights between two airports on a specific date. "
                "Returns flight options with airline, times, duration, stops, price in USD, "
                "and the airline's miles program."
            ),
            "parameters": {
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
    },
    {
        "type": "function",
        "function": {
            "name": "search_hotels",
            "description": (
                "Search for hotels in a city for a given check-in date and number of nights. "
                "Returns options with star rating, guest score, per-night price, total price, "
                "breakfast/refundable flags, and any Booking.com Genius discount."
            ),
            "parameters": {
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
    },
    {
        "type": "function",
        "function": {
            "name": "get_cross_bank_offers",
            "description": (
                "Via the Mastercard Agent Pay infrastructure, retrieve the user's cards "
                "issued by OTHER banks (not Garanti) along with any active promotions on "
                "those cards relevant to the supplied merchants. Use this to find better "
                "deals than what Garanti's own cards offer."
            ),
            "parameters": {
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
    },
    {
        "type": "function",
        "function": {
            "name": "rank_bundles",
            "description": (
                "Run the deterministic bundle scorer. Returns the top N "
                "flight+hotel+payment-method bundles ranked by total cost after all "
                "promotions, with a cost breakdown and explanatory notes for each. "
                "Call this AFTER get_user_payment_profile, search_flights, "
                "search_hotels, and get_cross_bank_offers have all been called. "
                "Flight, hotel, and payment data are sourced automatically from those "
                "previous calls — do NOT pass them here. Only supply budget_usd."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "budget_usd": {
                        "type": "number",
                        "description": "Total trip budget in USD (flights + hotels combined)",
                    },
                    "top_n": {
                        "type": "integer",
                        "default": 5,
                        "description": "Maximum number of bundles to return",
                    },
                },
                "required": ["budget_usd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_agentic_pay_token",
            "description": (
                "FINAL STEP. Once the user has explicitly confirmed a specific bundle, "
                "issue a Mastercard Agentic Pay token to authorize the purchase. "
                "Do NOT call this until the user says yes."
            ),
            "parameters": {
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
    },
]
