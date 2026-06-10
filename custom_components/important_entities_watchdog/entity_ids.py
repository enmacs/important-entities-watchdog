"""Deterministic entity_id construction for the integration's own entities.

HA derives an entity_id from the entity's *name* (slugified) unless the entity
sets ``self.entity_id`` explicitly. Relying on the name makes ids unstable —
they change whenever a display name changes. To keep ids predictable (and to
match the ids documented in the README), every entity this integration creates
sets ``self.entity_id`` to one of the helpers below, and a one-time registry
migration (see ``__init__.py``) renames any pre-existing entities to match.

Keep these in sync with the documented ids in README.md.
"""

from __future__ import annotations

from homeassistant.util import slugify

from .const import DOMAIN


def binary_sensor_entity_id(label_id: str, source_entity_id: str, period: str) -> str:
    """Per-source availability binary sensor id."""
    return f"binary_sensor.{DOMAIN}_{slugify(label_id)}_{slugify(source_entity_id)}_{period}"


def summary_sensor_entity_id(label_id: str, period: str) -> str:
    """Silent-count summary sensor id."""
    return f"sensor.{DOMAIN}_silent_{slugify(label_id)}_{period}"


def clean_orphans_entity_id(label_id: str, period: str) -> str:
    """Clean-orphans button id."""
    return f"button.{DOMAIN}_clean_orphans_{slugify(label_id)}_{period}"


def create_dashboard_entity_id(label_id: str, period: str) -> str:
    """Create-dashboard button id."""
    return f"button.{DOMAIN}_create_dashboard_{slugify(label_id)}_{period}"
