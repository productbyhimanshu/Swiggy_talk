"""Phase 6 Orchestrator integration — Personas and Templates."""

import asyncio
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

from phases.phase_00.services.swiggy_auth import ReauthRequired, SwiggyAuthError
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

        # Dish-level search via Swiggy's search_menu (one call per term,
        # Swiggy-ranked across all nearby restaurants). Dish queries search the
        # cleaned phrase ("butter chicken"); vague requests search each
        # expanded term ("dal makhani", "khichdi", …). Started now so it runs
        # concurrently with the restaurant searches below.
        dish_terms: list[str] = []
        if state.address_id:
            if _is_dish_query(intent):
                phrase = _exact_phrase(intent.search_query or "")
                dish_terms = [phrase] if phrase else []
            elif expansion is not None and expansion.search_terms:
                dish_terms = list(expansion.search_terms)
        dish_task = (
            asyncio.create_task(
                _search_dishes(swiggy_client, dish_terms, intent, state.address_id)
            )
            if dish_terms else None
        )

        # Parallel multi-search — every expanded term + the original. Merge,
        # dedupe by restaurantId. Feeds restaurant-card fallback and gives
        # dish cards their restaurant ETA / rating.
        async def _search_one(q: str) -> list[dict]:
            try:
                return await swiggy_client.search_restaurants(
                    query=q, address_id=state.address_id,
                )
            except _AUTH_ERRORS:
                raise
            except Exception:
                return []

        try:
            search_results = await asyncio.gather(
                *(_search_one(q) for q in search_terms)
            )
        except _AUTH_ERRORS:
            if dish_task:
                dish_task.cancel()
            raise
        except Exception:
            if dish_task:
                dish_task.cancel()
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

        _log = __import__("logging").getLogger(__name__)
        _log.info(
            "multi_search_result terms=%d results_per_term=%s raw=%d",
            len(search_terms),
            [len(b) for b in search_results],
            len(raw_restaurants),
        )

        # Hard gates (architecture §6): OPEN, rating ≥3.5, ETA, diet, budget.
        # If the gates are too aggressive (e.g. all nearby places rated <3.5),
        # relax to rating-sorted raw results rather than show nothing (§14).
        survivors = apply_filters(raw_restaurants, intent)
        if len(survivors) < 3 and raw_restaurants:
            _log.info(
                "survivors_relaxed strict=%d raw=%d — using raw sorted by rating",
                len(survivors), len(raw_restaurants),
            )
            survivors = sorted(
                raw_restaurants,
                key=lambda r: float(r.get("rating") or 0),
                reverse=True,
            )
        if not survivors:
            _log.warning(
                "search_empty query=%r terms=%s — all 6 Swiggy searches returned []",
                primary, search_terms,
            )

        # Dish cards (architecture §1: "6 high-accuracy recommendations").
        if dish_task is not None:
            hits = await dish_task
            rest_by_id = {
                str(r.get("restaurantId") or r.get("id") or ""): r for r in raw_restaurants
            }
            dishes = _rank_dishes(hits, intent, rest_by_id, variety=len(dish_terms) > 1)
            _log.info("dish_search terms=%s hits=%d picked=%d", dish_terms, len(hits), len(dishes))
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


# ── Dish-level search (Swiggy search_menu) ───────────────────────────────────

# Auth failures must reach the API layer (→ 401 reauth_required), never be
# swallowed as "no results".
_AUTH_ERRORS = (ReauthRequired, SwiggyAuthError)

# Refinement words stripped from a dish query: "butter chicken under 300" → "butter chicken"
_QUERY_STOP = {
    "under", "below", "less", "than", "rs", "rupee", "rupees", "for", "the", "a",
    "and", "with", "want", "give", "show", "me", "i", "some", "any", "please",
}

# Words too generic to identify a dish on their own when matching names.
_GENERIC_DISH_WORDS = {
    "veg", "non", "nonveg", "food", "special", "combo", "meal", "meals",
    "with", "and", "the", "of", "style", "full", "half", "fresh", "plate",
}

_MAX_PER_RESTAURANT = 2
_MAX_DISH_PAGES = 4


def _exact_phrase(query: str) -> str:
    return " ".join(
        w for w in re.findall(r"[a-z]+", query.lower())
        if w not in _QUERY_STOP
    ).strip()


def _has_word(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def _keyword_match(name_lc: str, terms: list[str]) -> tuple[int, str | None]:
    """Best match of a dish name against search terms.

    3 = full phrase, 2 = all significant words, 1 = any significant word, 0 = none.
    """
    best, best_term = 0, None
    for term in terms:
        if _has_word(name_lc, term):
            return 3, term
        words = [w for w in term.split() if w not in _GENERIC_DISH_WORDS and len(w) >= 3]
        if not words:
            continue
        if all(_has_word(name_lc, w) for w in words):
            level = 2
        elif any(len(w) >= 4 and _has_word(name_lc, w) for w in words):
            level = 1
        else:
            continue
        if level > best:
            best, best_term = level, term
    return best, best_term


def _resembles(name_lc: str, term: str, threshold: float = 0.8) -> bool:
    """True if any significant word of `term` is a near-spelling of a word in the name."""
    name_words = re.findall(r"[a-z]+", name_lc)
    for w in term.lower().split():
        if w in _GENERIC_DISH_WORDS or len(w) < 3:
            continue
        if any(SequenceMatcher(None, w, nw).ratio() >= threshold for nw in name_words):
            return True
    return False


async def _search_dishes(
    swiggy_client: SwiggyReadClient,
    terms: list[str],
    intent: UserIntent,
    address_id: str,
) -> list[tuple[str, dict]]:
    """Run search_menu for every term in parallel → [(term, dish), ...].

    A single-term (dish) query keeps paging until enough dishes survive the
    budget/diet filters (a tight budget can push matches to later pages);
    multi-term (vague) queries take one page each.
    """
    veg_only = intent.veg_nonveg == "veg"

    def _passes(d: dict) -> bool:
        # Swiggy's vegFilter doesn't actually filter, so check diet here too.
        if intent.veg_nonveg == "veg" and not d.get("veg"):
            return False
        if intent.veg_nonveg == "nonveg" and d.get("veg") is True:
            return False
        return not (intent.budget_max and d.get("price", 0) > intent.budget_max)

    async def one(term: str) -> list[tuple[str, dict]]:
        try:
            page = await swiggy_client.search_menu(term, address_id, veg_only=veg_only)
            items = list(page["items"])
            pages = 1
            while (
                len(terms) == 1
                and pages < _MAX_DISH_PAGES
                and sum(_passes(d) for d in items) < 6
                and page["has_more"]
                and page["next_offset"]
            ):
                page = await swiggy_client.search_menu(
                    term, address_id, veg_only=veg_only, offset=page["next_offset"],
                )
                items.extend(page["items"])
                pages += 1
            return [(term, d) for d in items]
        except _AUTH_ERRORS:
            raise
        except Exception:
            return []

    batches = await asyncio.gather(*(one(t) for t in terms))
    return [hit for batch in batches for hit in batch]


def _rank_dishes(
    hits: list[tuple[str, dict]],
    intent: UserIntent,
    rest_by_id: dict[str, dict],
    variety: bool,
) -> list[dict]:
    """Filter, enrich, score and pick up to 6 dish cards.

    variety=True (vague request, several terms): one dish per term first,
    and the same dish name is shown once across restaurants.
    variety=False (dish query): the same dish from different restaurants is
    the point, so only exact duplicates within a restaurant are collapsed.
    """
    from phases.phase_04.utils.parse_eta import parse_eta as _parse_eta

    candidates: list[dict] = []
    for term, dish in hits:
        if intent.veg_nonveg == "veg" and not dish.get("veg"):
            continue
        if intent.veg_nonveg == "nonveg" and dish.get("veg") is True:
            continue
        if intent.budget_max and dish.get("price", 0) > intent.budget_max:
            continue
        rest = rest_by_id.get(dish.get("restaurantId", ""))
        if rest is not None and rest.get("availabilityStatus", "OPEN") != "OPEN":
            continue

        # Swiggy's search_menu returns *something* even for nonsense ("xqzzvplk"
        # → milks), so a hit must resemble the term. Spelling variants
        # ("Daal Makhni" for "dal makhani") still pass as loose matches.
        name_lc = dish.get("name", "").lower()
        level = _keyword_match(name_lc, [term])[0]
        if level == 0 and _resembles(name_lc, term):
            level = 1
        if level == 0:
            continue
        rest_rating = rest.get("rating") if rest else None
        candidates.append({
            **dish,
            "eta":          rest.get("eta") if rest else None,
            "deliveryTime": rest.get("deliveryTime") if rest else None,
            "rating":       rest_rating if rest_rating is not None else dish.get("dishRating"),
            "cuisines":     rest.get("cuisines", "") if rest else "",
            "category":     "",
            "placeholder":  "🍽️",
            "_restaurant_score": float(rest_rating or dish.get("dishRating") or 0),
            "_kw_level":    level,
            "_matched_term": term,
            "_match_kind":  {3: "exact", 2: "all_words"}.get(level, "category"),
        })

    # Loose matches only fill in when strong ones can't make a card row.
    strong = [c for c in candidates if c["_kw_level"] >= 2]
    if len(strong) >= 3:
        candidates = strong
    if not candidates:
        return []

    weights = get_weights(intent)
    budget = intent.budget_max or 500

    def _score(d: dict) -> float:
        rating_score = max(0.0, min(100.0, (d["_restaurant_score"] - 4.0) * 100.0))
        eta_min = _parse_eta(d["deliveryTime"]) if d.get("deliveryTime") else 45
        eta_score = max(0.0, min(100.0, (60.0 - eta_min) / 60.0 * 100.0))
        price = float(d.get("price") or 0)
        price_value = max(0.0, min(100.0, (budget - price) / budget * 100.0))
        dish_rating = d.get("dishRating") or 0
        dish_bonus = 10.0 if dish_rating >= 4.5 else 5.0 if dish_rating >= 4.0 else 0.0
        keyword_bonus = {3: 60.0, 2: 35.0, 1: 15.0}[d["_kw_level"]]
        return (
            weights.get("rating", 0.2) * rating_score
            + weights.get("eta", 0.2) * eta_score
            + weights.get("price", 0.15) * price_value
            + dish_bonus
            + keyword_bonus
        )

    for d in candidates:
        d["_score"] = _score(d)
    candidates.sort(key=lambda d: -d["_score"])

    seen: set = set()
    deduped: list[dict] = []
    for d in candidates:
        norm = re.sub(r"[^a-z0-9]+", " ", d.get("name", "").lower()).strip()
        key = norm if variety else (norm, d.get("restaurantId"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(d)

    per_rest: Counter = Counter()
    picked: list[dict] = []
    covered_terms: set[str] = set()
    for require_new_term in ((True, False) if variety else (False,)):
        for d in deduped:
            if len(picked) >= 6:
                break
            if any(p is d for p in picked) or per_rest[d["restaurantId"]] >= _MAX_PER_RESTAURANT:
                continue
            if require_new_term and d["_matched_term"] in covered_terms:
                continue
            picked.append(d)
            per_rest[d["restaurantId"]] += 1
            covered_terms.add(d["_matched_term"])
    return picked

