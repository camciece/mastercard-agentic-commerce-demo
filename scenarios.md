# Scenarios for poking at the agent

Try these one at a time. Edit the fixtures in `data/` between runs to see how
the reasoning shifts.

## 1. The seed scenario (the press release example)
> Work trip on June 15 to Dubai, 3 night stay. $1500 budget, morning flight preferred.

Expected behavior: agent gathers all four data sources, scorer surfaces a bundle
where the **Yapı Kredi Worldcard 15% Emirates promo** plus the **İş Bankası
Maximum 8% Booking discount** combine to beat any Garanti-only pairing. Agent
should explicitly mention "even though this isn't a Garanti card, your linked
Worldcard saves you ~$63 here."

## 2. The user wants miles, not cash savings
> Same trip but I want to maximize my Miles&Smiles miles for a future award flight.

The agent should now prioritize the Turkish Airlines flight paid on the Garanti
Miles&Smiles card (2x miles promo) even though the absolute cost is slightly
higher. Watch how the LLM weighs the user's restated goal against the scorer's
cost-first ranking.

## 3. Mid-conversation refinement
After the initial recommendation:
> Actually I need a 5-star hotel, my client is paying.

Agent should re-call `search_hotels` with `min_star_rating=5` and re-rank. Note
how it doesn't redo the flight search — efficient tool use.

## 4. Knock out the cross-bank winner
Edit `data/agent_pay_feed.json` and either delete the YKB Emirates promo or
change its `valid_until` to a past date (the tools don't validate this, but
you can prune the active_promotions list). Re-run scenario 1. The recommendation
should fall back to a different bundle — most likely Turkish Airlines + a
mid-tier hotel paid via Garanti cards.

## 5. Budget too tight
> Same trip but my budget is $700.

Should force the cheapest combinations: Pegasus or Flydubai + ibis. Watch
whether the agent volunteers that "morning preferred" had to be relaxed if it
gets in the way of the budget.

## 6. Confirm and book
After any recommendation:
> Yes book it.

Agent should call `create_agentic_pay_token` exactly once with the right card
and amount, and confirm the token.
