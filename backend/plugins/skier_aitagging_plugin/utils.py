
import logging
from collections import defaultdict
from typing import Any, Mapping, Sequence

from stash_ai_server.actions.models import ContextInput
from stash_ai_server.utils.stash_api import stash_api

from .stash_handler import resolve_ai_tag_reference


_log = logging.getLogger(__name__)

def extract_tags_from_response(response: Mapping[str, Any] | Any | None) -> dict[str | None, list[str]]:
    """Extract image-tag labels grouped by category from a service response."""

    categorized: dict[str | None, list[str]] = defaultdict(list)
    for key, value in response.items():
        if key == "error":
            continue
        categorized[key] = value

    return categorized

def get_selected_items(ctx: ContextInput) -> list[str]:
    """Collect target IDs based on scope."""

    if ctx.is_detail_view:
        return [ctx.entity_id]
    elif ctx.selected_ids:
        return ctx.selected_ids
    elif ctx.visible_ids:
        return ctx.visible_ids
    else:
        # TODO
        return []

def resolve_image_tag_id_from_label(label: str, config) -> int | None:
    """Resolve a configured image tag label to a concrete Stash tag id."""

    normalized = (label or "").strip()
    if not normalized:
        _log.warning("Failed to resolve image tag label '%s': empty or invalid", label)
        return None
    settings = config.resolve(normalized)
    if not settings.image_enabled:
        return None
    stash_name = settings.stash_name or normalized
    if not stash_name:
        _log.warning("Failed to resolve image tag label '%s': no stash name found", label)
        return None
    return resolve_ai_tag_reference(stash_name)


def filter_enabled_tag_ids(tag_ids: Sequence[int], config) -> list[int]:
    """Normalize cached tag ids to match current configuration constraints."""

    filtered: list[int] = []
    applied: set[int] = set()
    for tag_id in tag_ids:
        tag_name = stash_api.get_stash_tag_name(tag_id)
        if not tag_name:
            continue
        settings = config.resolve(tag_name)
        if not settings.image_enabled:
            continue
        stash_name = settings.stash_name or tag_name
        candidate = resolve_ai_tag_reference(stash_name) if stash_name else None
        if candidate is None:
            continue
        if candidate in applied:
            continue
        applied.add(candidate)
        filtered.append(candidate)
    return filtered