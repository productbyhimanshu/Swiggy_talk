"""Phase 6 Orchestrator integration — Personas and Templates."""

import asyncio
import re
from typing import Any

from phases.phase_01.models.intent import UserIntent
from phases.phase_01.models.state import ConversationState
from phases.phase_02.orchestrator import Route
from phases.phase_03.agents.validator import validate_intent
from phases.phase_04.services.swiggy_read import SwiggyReadClient
from phases.phase_04.utils.filters import apply_filters
from phases.phase_05.utils.weights import get_weights
from phases.phase_05.agents.scorer import final_rank

from phases.phase_06.agents.intent_expander import ExpandedIntent, expand_intent, is_vague
from phases.phase_06.agents.persona import format_recommendations
from phases.phase_06.agents.why_picker import annotate_picks_sync
from phases.phase_06.handlers.schedule_handler import handle_schedule, propose_schedule_after_search
from phases.phase_06.utils.templates import (
    get_cart_template,
    get_cancel_template,
    get_greeting_template,
    get_swiggy_down_template,
    get_in_restaurant_template,
)

# Single-word food keywords that trigger dish-level search instead of restaurant
# cards. Heuristic — "momo", "biryani" → user wants dishes; "lunch", "snacks" →
# user is browsing, restaurant cards are still useful.
_DISH_KEYWORDS = {
    "pizza", "momo", "momos", "biryani", "burger", "burgers", "dosa", "idli",
    "vada", "paneer", "chicken", "noodle", "noodles", "sandwich", "pasta",
    "sushi", "cake", "donut", "kebab", "thali", "roll", "rolls", "wrap",
    "wraps", "samosa", "tikka", "shawarma", "falafel", "taco", "tacos",
    "chowmein", "manchurian", "fried rice", "naan", "roti", "paratha",
    "chaap", "bhel", "pani puri", "dahi puri", "ice cream", "shake", "lassi",
    "coffee", "tea", "waffle", "pancake", "salad", "soup",
}


def _is_dish_query(intent: "UserIntent") -> bool:
    """Decide whether the query is dish-specific (fetch menus) or browsy."""
    q = (intent.search_query or "").lower()
    if not q:
        return False
    return any(kw in q for kw in _DISH_KEYWORDS)


async def route_message(
    route: Route,
    intent: UserIntent,
    state: ConversationState,
    swiggy_client: SwiggyReadClient,
    gemini_client
) -> list[dict[str, Any]]:
    """
    Main entrypoint that routes the classified message (Architecture §6).
    Returns the JSON bubble array for the UI.
    """

    # 1. TEMPLATE SHORT-CIRCUITS (Zero LLM calls)
    if route == Route.GREETING:
        return get_greeting_template()

    elif route == Route.CART_ACTION:
        return get_cart_template()

    elif route == Route.CANCEL:
        state.cached_results = []
        state.has_recommendations = False
        state.current_restaurant_id = None
        state.awaiting_clarification = False
        # Kill any pending/confirmed schedule
        if state.scheduled_order:
            job_id = state.scheduled_order.get("job_id")
            if job_id:
                from phases.phase_11.services.scheduler import cancel_job
                cancel_job(job_id)
            state.scheduled_order = None
        return get_cancel_template()

    # SCHEDULE — timing engine proposal/confirm flow (zero LLM)
    elif route == Route.SCHEDULE:
        last_user_msg = ""
        for m in reversed(state.message_history):
            if m.get("role") == "user":
                last_user_msg = m.get("text", "")
                break
        return handle_schedule(last_user_msg, intent, state)

    # 2. FULL SEARCH PIPELINE — validate intent first (Agent 2)
    elif route in (Route.NEW_SEARCH, Route.AMBIGUOUS, Route.CLARIFY_REPLY):
        # Agent 2: validate before searching
        validation = validate_intent(intent)

        # Hard block: budget cap exceeded or no search signal
        if not validation.valid:
            if validation.clarify_question:
                state.awaiting_clarification = True
                state.clarify_field = validation.clarify_field
                state.current_intent = intent
                bubble = {"text": validation.clarify_question, "quick_replies": validation.quick_replies or []}
                return [bubble]
            return get_swiggy_down_template()

        # Soft clarification: veg/non-veg needs answer (valid=True but clarify_field set)
        if validation.clarify_field == "veg_nonveg" and intent.veg_nonveg == "NEEDS_CLARIFICATION":
            state.awaiting_clarification = True
            state.clarify_field = "veg_nonveg"
            state.current_intent = intent
            bubble = {"text": validation.clarify_question, "quick_replies": validation.quick_replies or []}
            return [bubble]

        # Multi-turn clarification ladder (architecture §5 — confidence-driven).
        # The intent parser scored how specific this request is. If confidence
        # is low AND we haven't already drilled in this turn-pair, ask the
        # follow-up the parser suggested. This is what makes "lunch" feel like
        # a real conversation instead of a form.
        # Skip when:
        #   - We just answered a clarification (state.clarify_field was set)
        #   - The user explicitly answered the veg question this turn
        #   - The intent has search_query already (we'd rather show results
        #     and refine via cards than over-question)
        already_drilled = bool(state.clarify_field) or state.has_recommendations
        if (
            intent.confidence is not None
            and intent.confidence < 0.6
            and intent.clarify_probe
            and not already_drilled
            and not intent.search_query
        ):
            state.awaiting_clarification = True
            state.clarify_field = "open_probe"
            state.current_intent = intent
            chips = intent.clarify_options or []
            return [{
                "text": intent.clarify_probe,
                "quick_replies": chips[:3],
            }]

        # Intent is clean — reset clarification state and search
        state.awaiting_clarification = False
        state.clarify_field = None

        # Intent translation layer (architecture: stop being a Swiggy proxy).
        # For concrete queries ("butter chicken under 300") we go direct.
        # For vague queries ("comfort food", "lunch", "snacks") we run an
        # LLM-driven expansion that turns intent + user_facts + clock into
        # 3–5 concrete Swiggy-searchable terms, then run those in parallel.
        base_query = intent.search_query or "food"
        primary = base_query

        expansion: ExpandedIntent | None = None
        search_terms: list[str] = [primary]

        if is_vague(intent):
            try:
                from phases.phase_00.services import memory as user_memory
                user_facts = user_memory.get_user_facts(max_facts=5)
            except Exception:
                user_facts = []
            from datetime import datetime as _dt
            try:
                expansion = await expand_intent(
                    intent, user_facts, _dt.now().hour, gemini_client,
                )
                state.search_relaxation = "expanded"
                # Use terms as-is — veg preference is applied post-search via
                # _gate_diet and scoring. Prefixing "veg " onto Swiggy search
                # terms returns 0 results because Swiggy treats "veg biryani"
                # as a literal string, not a filtered category.
                for term in expansion.search_terms:
                    if term not in search_terms:
                        search_terms.append(term)
            except Exception as exc:
                __import__("logging").getLogger(__name__).warning(
                    "expand_intent_skip: %s", exc,
                )

        weights = get_weights(intent)

        # Parallel multi-search — every expanded term + the original. Merge,
        # dedupe by restaurantId. First non-empty result keeps the user out
        # of dead-ends even on weird queries.
        async def _search_one(q: str) -> list[dict]:
            try:
                return await swiggy_client.search_restaurants(
                    query=q, address_id=state.address_id,
                )
            except Exception:
                return []

        try:
            search_results = await asyncio.gather(
                *(_search_one(q) for q in search_terms)
            )
        except Exception:
            return get_swiggy_down_template()

        # Dedupe across the merged set by restaurantId. Earlier-position
        # results (more relevant query) implicitly outrank later ones.
        seen_ids: set[str] = set()
        raw_restaurants: list[dict] = []
        for batch in search_results:
            for r in batch:
                rid = str(r.get("restaurantId") or r.get("id") or "")
                if rid and rid not in seen_ids:
                    seen_ids.add(rid)
                    raw_restaurants.append(r)

        # Hard gates (architecture §6): OPEN, rating ≥3.5, ETA, diet, budget.
        # If the gates are too aggressive (e.g. all nearby places rated <3.5),
        # relax to rating-sorted raw results rather than show nothing (§14).
        survivors = apply_filters(raw_restaurants, intent)
        if len(survivors) < 3 and raw_restaurants:
            survivors = sorted(
                raw_restaurants,
                key=lambda r: float(r.get("rating") or 0),
                reverse=True,
            )

        # Dish-level search for queries like "momos under 250" — fetch menus
        # for top 3 restaurants (by rating) in parallel, extract matching items,
        # return 6 actual dish cards with images. Architecture §1 promises "6
        # high-accuracy recommendations" and dish cards match the user's
        # mental model. Sort by rating first — Swiggy's raw order leads with
        # ads/low-rated places we don't want at the top of menu fetches.
        if _is_dish_query(intent) and survivors:
            ranked = sorted(
                survivors,
                key=lambda r: float(r.get("rating") or 0),
                reverse=True,
            )
            # Cast a wider net for dish-level search — many top-rated
            # restaurants near a user don't actually serve the dish they're
            # asking for (e.g. searching "momos" includes a dessert place
            # and a biryani spot in the top 3). Pull menus from 6 candidates
            # so we have a real shot at 6 distinct matching dishes after
            # the keyword + diet + budget filters.
            dishes = await _gather_dish_recommendations(
                ranked[:6], intent, swiggy_client, state.address_id,
            )
            if dishes:
                state.has_recommendations = True
                # why-lines are now deterministic (no LLM hop) — annotate
                # locally before the persona call so the prompt sees the
                # same `_match_kind`/badges the cards will display.
                dishes = annotate_picks_sync(intent, dishes)
                bubbles = await format_recommendations(
                    intent, dishes, state.message_history, gemini_client,
                    expansion_reasoning=expansion.reasoning if expansion else None,
                )
                state.cached_results = dishes
                # If the user combined food + time ("momos at 10am"), tack on a
                # schedule proposal so they don't have to ask separately.
                return bubbles + propose_schedule_after_search(intent, state)
            # No matching dishes → fall through to restaurant cards (better than nothing)

        top_6 = await final_rank(survivors, intent, gemini_client)
        state.has_recommendations = True
        top_6 = annotate_picks_sync(intent, top_6)
        bubbles = await format_recommendations(
            intent, top_6, state.message_history, gemini_client,
            expansion_reasoning=expansion.reasoning if expansion else None,
        )
        state.cached_results = top_6
        return bubbles + propose_schedule_after_search(intent, state)

    # 3. REFINE PIPELINE — works on cached results (no network) when possible
    elif route == Route.REFINE:
        if not state.has_recommendations or not state.cached_results:
            return await route_message(Route.NEW_SEARCH, intent, state, swiggy_client, gemini_client)

        # If the cache holds dishes (have itemId / veg as bool), filter dishes
        # by the refined intent directly. If filtering yields too few results,
        # re-trigger a NEW_SEARCH so the user actually sees something.
        cached_is_dishes = bool(state.cached_results) and "itemId" in state.cached_results[0]
        if cached_is_dishes:
            def _ok(it: dict) -> bool:
                if intent.veg_nonveg == "veg" and not it.get("veg", False):
                    return False
                if intent.veg_nonveg == "nonveg" and it.get("veg") is True:
                    return False
                if intent.budget_max and it.get("price", 0) > intent.budget_max:
                    return False
                return True

            filtered = [it for it in state.cached_results if _ok(it)]
            if len(filtered) >= 3:
                state.cached_results = filtered[:6]
                return await format_recommendations(intent, filtered[:6], state.message_history, gemini_client)
            # Too few cached dishes match the refined intent — re-search fresh.
            state.cached_results = []
            state.has_recommendations = False
            return await route_message(Route.NEW_SEARCH, intent, state, swiggy_client, gemini_client)

        # Restaurant-card refinement (original path)
        survivors = apply_filters(state.cached_results, intent)
        if not survivors:
            survivors = state.cached_results
        top_6 = await final_rank(survivors, intent, gemini_client)
        state.cached_results = top_6
        return await format_recommendations(intent, top_6, state.message_history, gemini_client)

    # 4. IN_RESTAURANT — show more dishes from the current/cart restaurant
    elif route == Route.IN_RESTAURANT:
        rest_id = state.current_restaurant_id or state.cart_restaurant_id
        if not rest_id:
            # No restaurant context — also clear stale cards so router doesn't re-emit
            state.has_recommendations = False
            state.cached_results = []
            return [{"text": "Which restaurant did you want more from? Search for something first 🔍", "quick_replies": []}]

        try:
            menu = await swiggy_client.get_restaurant_menu(rest_id, address_id=state.address_id)
            items = menu.get("items") or []
            if not items:
                state.has_recommendations = False
                state.cached_results = []
                return get_in_restaurant_template()

            # Honour veg preference + budget if intent has them
            def _diet_ok(it: dict) -> bool:
                if intent.veg_nonveg == "veg" and not it.get("veg", False):
                    return False
                if intent.veg_nonveg == "nonveg" and it.get("veg") is True:
                    return False
                return True

            def _budget_ok(it: dict) -> bool:
                return not (intent.budget_max and it.get("price", 0) > intent.budget_max)

            # Tier 1: strict — match diet AND budget
            strict = [it for it in items if _diet_ok(it) and _budget_ok(it)]
            # Tier 2: relax budget only (keeps diet honest)
            relax_budget = [it for it in items if _diet_ok(it)]
            # Tier 3: relax diet, keep budget (last resort before showing anything)
            relax_diet = [it for it in items if _budget_ok(it)]

            if strict:
                pool, mode = strict, "match"
            elif relax_budget:
                pool, mode = relax_budget, "over_budget"
            elif relax_diet:
                pool, mode = relax_diet, "wrong_diet"
            else:
                pool, mode = items, "fallback"

            # Bestsellers first, then ascending price — Swiggy-app feel
            pool.sort(key=lambda x: (not x.get("bestseller", False), x.get("price", 999)))
            top = pool[:6]
            # Annotate so persona can be transparent about the relaxation
            state.search_relaxation = mode

            state.has_recommendations = True
            state.cached_results = top
            state.current_restaurant_id = rest_id
            return await format_recommendations(intent, top, state.message_history, gemini_client)
        except Exception as exc:
            log = __import__("logging").getLogger(__name__)
            log.warning("in_restaurant_menu_failed: %s", exc)
            state.has_recommendations = False
            state.cached_results = []
            return get_swiggy_down_template()

    # Fallback
    return [{"text": "I'm still learning how to handle that! 😅", "quick_replies": []}]


# ── Dish-level search ────────────────────────────────────────────────────────

async def _gather_dish_recommendations(
    top_restaurants: list[dict],
    intent: UserIntent,
    swiggy_client: SwiggyReadClient,
    address_id: str | None,
) -> list[dict]:
    """
    For a dish-style query ("momos under 250"):
      1. Fetch menus of the top N restaurants in parallel.
      2. Extract items whose name matches the query keyword.
      3. Honour veg + budget intent.
      4. Sort by (bestseller, restaurant rating, ascending price).
      5. Return up to 6 dishes, each enriched with restaurant ETA so the
         card can show delivery time even though menu items don't carry it.

    Falls back to [] when no dishes match — caller may then show restaurants.
    """
    query_lc = (intent.search_query or "").lower().strip()
    # The strict keyword the dish name MUST contain to be kept (a coarse filter
    # — the exact_phrase below is what we use for ranking). "butter chicken
    # under 300" → strict="chicken", exact="butter chicken".
    primary_keyword = next(
        (kw for kw in _DISH_KEYWORDS if kw in query_lc),
        query_lc.split()[0] if query_lc else "",
    )
    # Strip refinement words so "butter chicken under 300" → "butter chicken"
    _STOP = {"under", "below", "less", "than", "rs", "₹", "rupee", "rupees",
             "for", "the", "a", "and", "with", "want", "give", "show", "me",
             "i", "some", "any", "please"}
    exact_phrase = " ".join(
        w for w in re.findall(r"[a-z]+", query_lc)
        if w not in _STOP and not w.isdigit()
    ).strip()

    async def fetch(r):
        try:
            return r, await swiggy_client.get_restaurant_menu(
                str(r.get("restaurantId") or r.get("id", "")),
                address_id=address_id,
            )
        except Exception:
            return r, {"items": []}

    results = await asyncio.gather(*(fetch(r) for r in top_restaurants))

    candidates: list[dict] = []
    for restaurant, menu in results:
        for item in menu.get("items", []):
            name_lc = item.get("name", "").lower()
            if primary_keyword and primary_keyword not in name_lc:
                continue
            # Diet check
            if intent.veg_nonveg == "veg" and not item.get("veg", False):
                continue
            if intent.veg_nonveg == "nonveg" and item.get("veg") is True:
                continue
            # Budget check
            if intent.budget_max and item.get("price", 0) > intent.budget_max:
                continue
            # Enrich with restaurant context the card needs
            item = {
                **item,
                "eta":           restaurant.get("eta") or restaurant.get("deliveryTime"),
                "deliveryTime":  restaurant.get("deliveryTime"),
                "restaurant":    restaurant.get("name") or item.get("restaurant", ""),
                "restaurantId":  str(restaurant.get("restaurantId") or restaurant.get("id", "")),
                # Show the restaurant's rating on the dish card so the user sees
                # which place this dish comes from at a glance.
                "rating":        restaurant.get("rating"),
                # Restaurant-level cuisines line is more readable than category
                "cuisines":      restaurant.get("cuisines") or item.get("cuisines", ""),
                "_restaurant_score": float(restaurant.get("rating") or 0),
            }
            candidates.append(item)

    if not candidates:
        return []

    # Multi-factor scoring matching architecture §6:
    #   rating_score      — restaurant rating, 4.0★ baseline → 100 at 5.0★
    #   eta_score         — faster = higher
    #   price_value       — cheaper within budget = higher
    #   bestseller_bonus  — +20 lift for Swiggy "Bestseller" tag
    # Weights shift by intent (fast → eta matters more; budget → price matters
    # more) using the existing phase_05/weights.py table.
    from phases.phase_04.utils.parse_eta import parse_eta as _parse_eta
    weights = get_weights(intent)
    budget = intent.budget_max or 500

    def _score(d: dict) -> float:
        rating = float(d.get("_restaurant_score") or 0)
        rating_score = max(0.0, min(100.0, (rating - 4.0) * 100.0))
        eta_min = _parse_eta(d.get("deliveryTime", "")) if d.get("deliveryTime") else 45
        eta_score = max(0.0, min(100.0, (60.0 - eta_min) / 60.0 * 100.0))
        price = float(d.get("price") or 0)
        price_value = max(0.0, min(100.0, (budget - price) / budget * 100.0)) if budget else 50.0
        bestseller_bonus = 20.0 if d.get("bestseller") else 0.0
        # KEYWORD-MATCH BOOST — the single most important relevance signal.
        # "butter chicken" must rank above "chicken roll" when the user typed
        # "butter chicken". The boost is bigger than the bestseller bonus
        # because exact match is a stronger signal than menu popularity.
        name_lc = d.get("name", "").lower()
        if exact_phrase and exact_phrase in name_lc:
            keyword_bonus = 60.0          # full phrase match — strongest
            d["_match_kind"] = "exact"
        elif exact_phrase and all(w in name_lc for w in exact_phrase.split()):
            keyword_bonus = 35.0          # all phrase words in any order
            d["_match_kind"] = "all_words"
        else:
            keyword_bonus = 0.0
            d["_match_kind"] = "category"
        return (
            weights.get("rating", 0.2) * rating_score
            + weights.get("eta", 0.2) * eta_score
            + weights.get("price", 0.15) * price_value
            + bestseller_bonus
            + keyword_bonus
        )

    for d in candidates:
        d["_score"] = _score(d)
    candidates.sort(key=lambda d: -d["_score"])

    # Cross-result dedupe by normalised dish name (architecture: avoid
    # showing "Chicken Roll" from 3 different restaurants — same dish, fake
    # variety). Higher-scored copy wins. We still dedupe within a restaurant
    # (same dish across menu categories) for free with this same pass.
    seen_names: set[str] = set()
    deduped: list[dict] = []
    for d in candidates:
        norm_name = re.sub(r"[^a-z0-9]+", " ", d.get("name", "").lower()).strip()
        if norm_name in seen_names:
            continue
        seen_names.add(norm_name)
        deduped.append(d)

    return deduped[:6]
