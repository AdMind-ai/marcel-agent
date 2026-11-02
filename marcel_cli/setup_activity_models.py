"""Activity eligibility and small, metadata-based Router recommendations.

Tier scales and activity tags are deliberately data, not hard-coded model IDs.
Missing tiers do not imply a quality/cost claim or a benchmark result.
"""

from marcel_cli.setup_model_labels import capabilities, chat_models, metadata, model_label

TIER_SCORES = {
    "quality_tier": {"low": 1, "medium": 2, "high": 3},
    "cost_tier": {"low": 1, "medium": 2, "high": 3},
    "speed_tier": {"low": 1, "medium": 2, "high": 3, "slow": 1, "balanced": 2, "fast": 3},
}
ACTIVITY_TAGS = {
    "search": {"search", "research", "web-search"},
    "coding": {"coding", "code"},
    "documents": {"documents", "document", "writing"},
    "vision": {"vision", "image-analysis"},
    "video_analysis": {"video-analysis", "video_analysis", "video"},
    "image_generation": {"image-generation", "image_generation"},
    "image": {"image-generation", "image_generation"},
    "video": {"video-generation", "video_generation"},
}


def compatible_models(catalog: list, activity: str = "") -> list[dict]:
    """Every worker needs chat/tools; perception needs explicit input support."""
    entries = chat_models(catalog)
    required = {"vision": "vision", "video_analysis": "video_analysis"}.get(activity)
    if required:
        entries = [entry for entry in entries if capabilities(entry).get(required) is True]
    if activity == "coding":
        entries = [entry for entry in entries if capabilities(entry).get("coding") is not False]
    return entries


def _score(entry: dict, field: str) -> int | None:
    value = metadata(entry).get(field)
    return TIER_SCORES.get(field, {}).get(value) if isinstance(value, str) else None


def _recommended(entry: dict, activity: str) -> bool:
    tags = metadata(entry).get("recommended_for")
    return isinstance(tags, list) and any(
        isinstance(tag, str) and tag in ACTIVITY_TAGS.get(activity, {activity})
        for tag in tags
    )


def recommendations(entries: list[dict], activity: str) -> list[tuple[str, dict]]:
    """At most three distinct models with explainable, declared tier criteria."""
    result = []
    used = set()
    for label, fields, rank in (
        ("Quality", ("quality_tier",),
         lambda e: (_score(e, "quality_tier") or 0, -(_score(e, "cost_tier") or 4))),
        ("Quality/cost balance", ("quality_tier", "cost_tier"),
         lambda e: ((_score(e, "quality_tier") or 0) - (_score(e, "cost_tier") or 0),
                    _score(e, "quality_tier") or 0)),
        ("Speed/economy", ("cost_tier",),
         lambda e: (-(_score(e, "cost_tier") or 0), _score(e, "speed_tier") or 0)),
    ):
        pool = [entry for entry in entries if entry["id"] not in used
                and all(_score(entry, field) is not None for field in fields)]
        if not pool:
            continue
        # Activity recommendations are Router declarations, not inferred from IDs.
        preferred = [entry for entry in pool if _recommended(entry, activity)]
        chosen = max(preferred or pool, key=rank)
        meta = metadata(chosen)
        tiers = ", ".join(f"{field.removesuffix('_tier')}={meta[field]}"
                          for field in ("quality_tier", "cost_tier", "speed_tier")
                          if _score(chosen, field) is not None)
        reason = f"declared {tiers}"
        if _recommended(chosen, activity):
            reason += f"; Router recommended_for={activity}"
        result.append((f"{label} — {model_label(chosen)} | {reason}", chosen))
        used.add(chosen["id"])
    return result


def choose_activity_model(setup, label: str, entries: list[dict],
                          activity: str, current: str = "") -> str:
    if not entries:
        setup.print_error(f"No available chat/tool model explicitly supports {activity}.")
        return ""
    setup._info(
        f"Models for {activity}: {len(entries)} compatible.",
        "Compatibility is not a quality ranking. Recommendations use declared Router tiers only.",
        "Quality: highest quality tier; balance: quality minus cost tier; "
        "economy: lowest cost, then highest speed. Activity recommendations take priority.",
        None,
    )
    curated = recommendations(entries, activity)
    if not curated:
        setup._info("No tier-based ranking available; these are compatible models, not recommendations.", None)
        if len(entries) <= 3:
            curated = [(model_label(entry), entry) for entry in entries]
    current_entry = next((entry for entry in entries if entry["id"] == current), None)
    if current_entry and all(entry["id"] != current for _, entry in curated):
        curated.append((f"Keep current — {model_label(current_entry)}", current_entry))
    choices = [title for title, _ in curated]
    choices.append(f"Show all compatible models ({len(entries)})")
    default = next((i for i, (_, entry) in enumerate(curated) if entry["id"] == current), 0)
    selected = setup.prompt_choice(label, choices, default)
    if selected < len(curated):
        return curated[selected][1]["id"]
    selected = setup.prompt_choice(
        f"{label} — all compatible", [model_label(entry) for entry in entries],
        next((i for i, entry in enumerate(entries) if entry["id"] == current), 0),
    )
    return entries[selected]["id"]
