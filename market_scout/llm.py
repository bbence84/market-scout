"""
LLM integration via OpenRouter for query translation and alternative query suggestions.

Requires an OpenRouter API key in ~/.market-scout/config.toml or
the OPENROUTER_API_KEY environment variable.

OpenRouter is an API gateway that provides access to many models
(Claude, GPT-4, Gemini, Mistral, etc.) through a single OpenAI-compatible endpoint.
"""
from __future__ import annotations

import json
import httpx


class LLMError(Exception):
    pass


def _chat(messages: list[dict], model: str, api_key: str, base_url: str) -> str:
    """Send a chat completion request to OpenRouter and return the reply text."""
    if not api_key:
        raise LLMError(
            "No OpenRouter API key configured.\n"
            "Set it in ~/.market-scout/config.toml under [openrouter] api_key,\n"
            "or export OPENROUTER_API_KEY=<your_key>.\n"
            "Get a key at https://openrouter.ai/keys"
        )

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 512,
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/market-scout",
        "X-Title": "market-scout",
    }

    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise LLMError(f"OpenRouter API error {e.response.status_code}: {e.response.text[:300]}") from e
    except Exception as e:
        raise LLMError(f"OpenRouter request failed: {e}") from e

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise LLMError(f"Unexpected OpenRouter response format: {data}") from e


def translate_query(
    query: str,
    target_language: str,
    model: str,
    api_key: str,
    base_url: str,
) -> str:
    """
    Translate a search query into the target language.
    Returns the translated query, or the original if no translation is needed.
    """
    messages = [
        {
            "role": "system",
            "content": (
                f"You are a translation assistant for a marketplace search tool. "
                f"Translate the user's search query into {target_language}. "
                "Rules: "
                "- Preserve product names, model numbers, brand names, and technical terms exactly. "
                "- If the query is already in the target language or is a proper noun that needs no translation, return it unchanged. "
                "- Return ONLY the translated query, nothing else — no explanation, no quotes."
            ),
        },
        {"role": "user", "content": query},
    ]
    return _chat(messages, model, api_key, base_url)


def suggest_queries(
    query: str,
    model: str,
    api_key: str,
    base_url: str,
) -> list[str]:
    """
    Suggest alternative search terms for a marketplace query.
    Returns a list of variants including the original.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are a marketplace search expert. "
                "Given a search query for a second-hand item, suggest up to 5 alternative search terms "
                "that sellers commonly use when listing this item — including abbreviations, common misspellings, "
                "regional names, and related model names. "
                "Rules: "
                "- Always include the original query as the first item. "
                "- Return a JSON array of strings only — no explanation, no markdown. "
                "- Example input: 'Commodore 64' "
                '- Example output: ["Commodore 64", "C64", "C-64", "Commodore64", "CBM 64"]'
            ),
        },
        {"role": "user", "content": query},
    ]
    raw = _chat(messages, model, api_key, base_url)

    # Parse JSON array from response
    try:
        # Handle cases where the model wraps in markdown code blocks
        if "```" in raw:
            raw = raw.split("```")[1].strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        result = json.loads(raw)
        if isinstance(result, list) and all(isinstance(s, str) for s in result):
            # Ensure original is present and first
            if query not in result:
                result.insert(0, query)
            return result[:6]  # cap at 6
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: return just the original
    return [query]


_BATCH_SIZE = 30  # max items per LLM call to avoid token limit truncation


def _translate_batch(items: list[str], target_language: str,
                     model: str, api_key: str, base_url: str) -> list[str]:
    """Translate a single batch of up to _BATCH_SIZE items."""
    if not items:
        return []
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(items))
    messages = [
        {
            "role": "system",
            "content": (
                f"Translate these marketplace listing strings into {target_language}. "
                "Rules: "
                "- Preserve product names, model numbers, brand names, prices, and technical specs exactly. "
                "- If a string is already in {target_language} or is a proper noun, return it unchanged. "
                "- Return ONLY a numbered list in the same format as the input (1. ... 2. ... etc.). "
                "- One translation per line, same numbering. No extra commentary, no blank lines."
            ),
        },
        {"role": "user", "content": numbered},
    ]
    raw = _chat(messages, model, api_key, base_url)

    translated = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip leading "N. " for any number of digits
        import re as _re
        m = _re.match(r'^\d+\.\s+', line)
        if m:
            line = line[m.end():]
        translated.append(line)

    if len(translated) >= len(items):
        return translated[: len(items)]
    return translated + items[len(translated):]


def translate_listings(
    titles: list[str],
    target_language: str,
    model: str,
    api_key: str,
    base_url: str,
) -> list[str]:
    """
    Translate a batch of listing titles into target_language.
    Splits into chunks of _BATCH_SIZE to avoid LLM token limit truncation.
    Returns a list of translated titles in the same order.
    """
    if not titles:
        return []

    result = []
    for i in range(0, len(titles), _BATCH_SIZE):
        chunk = titles[i: i + _BATCH_SIZE]
        result.extend(_translate_batch(chunk, target_language, model, api_key, base_url))
    return result


def analyse_listing(
    description: str,
    question: str,
    model: str,
    api_key: str,
    base_url: str,
    search_query: str = "",
    title: str = "",
    user_lang: str = "en",
) -> str:
    """
    Evaluate whether a listing matches the user's question.
    Uses the listing title and description together with the original search query.
    Returns a string starting with "YES", "MAYBE", or "NO" followed by " — <reason>".
    The reason sentence is written in user_lang.
    """
    # Build context from whatever is available
    context_parts = []
    if search_query:
        context_parts.append(f"Search query (what the user was looking for): {search_query}")
    context_parts.append(f"Buyer's question: {question}")
    if title:
        context_parts.append(f"\nListing title: {title}")
    if description.strip():
        context_parts.append(f"Listing description:\n{description[:1500]}")
    else:
        context_parts.append("Listing description: (not available)")

    messages = [
        {
            "role": "system",
            "content": (
                "You are evaluating a marketplace listing to determine whether it matches "
                "a buyer's intent. "
                "You are given the original search query, the buyer's specific question, "
                "the listing title, and the listing description. "
                f"Write your reasoning sentence in {user_lang}. "
                "Reply with EXACTLY one of: YES, MAYBE, or NO — then a space-dash-space ' — ' "
                "and ONE concise sentence explaining your reasoning. "
                "Rules:\n"
                "- Use BOTH the title and description to judge.\n"
                "- If the title or description is too vague, too short, or does not provide "
                "enough information to answer the question confidently, answer MAYBE.\n"
                "- If the title clearly matches but the description adds nothing relevant, "
                "that is still MAYBE — not YES.\n"
                "- Only answer YES if the combined evidence makes it highly likely the listing "
                "matches the buyer's question.\n"
                "- Only answer NO if the listing clearly does not match.\n"
                "Examples (verdicts are always English, reason in the requested language):\n"
                "YES — title and description both confirm it is an Amiga 500 in working condition\n"
                "MAYBE — title says Amiga 500 but description gives no details about condition\n"
                "MAYBE — description is too short to judge\n"
                "NO — this is a Fiat 500 car, not a computer"
            ),
        },
        {
            "role": "user",
            "content": "\n".join(context_parts),
        },
    ]
    try:
        raw = _chat(messages, model, api_key, base_url).strip()
        # Normalise: ensure it starts with one of the three verdicts
        upper = raw.upper()
        for verdict in ("YES", "MAYBE", "NO"):
            if upper.startswith(verdict):
                return raw
        # If model returned something unexpected, classify as MAYBE
        return f"MAYBE — {raw[:120]}"
    except Exception as exc:
        return f"MAYBE — analysis failed: {str(exc)[:80]}"


def analyse_listings(
    listings_with_desc: list[tuple[int, str]],  # (index, description)
    question: str,
    model: str,
    api_key: str,
    base_url: str,
    search_query: str = "",
) -> dict[int, str]:
    """
    Analyse multiple listings sequentially. Returns {index: result_string}.
    Only processes listings that have a non-empty description.
    """
    results: dict[int, str] = {}
    for idx, desc in listings_with_desc:
        results[idx] = analyse_listing(desc, question, model, api_key, base_url, search_query)
    return results
