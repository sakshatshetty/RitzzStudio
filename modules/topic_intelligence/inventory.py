"""Persistent inventory of RITZZ topics and covered concepts."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field


class ContentInventoryEntry(BaseModel):
    topic: str
    normalized_topic: str
    keywords: list[str] = Field(default_factory=list)
    project_id: str | None = None
    status: str = "planned"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    published_at: str | None = None
    title: str | None = None
    url: str | None = None
    covered_concepts: list[str] = Field(default_factory=list)
    related_topics: list[str] = Field(default_factory=list)


class ContentInventory(BaseModel):
    entries: list[ContentInventoryEntry] = Field(default_factory=list)


class ContentInventoryManager:
    """Read and update the single-channel RITZZ content inventory."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> ContentInventory:
        if not self.path.exists():
            return ContentInventory()
        return ContentInventory.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, inventory: ContentInventory) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(inventory.model_dump_json(indent=2), encoding="utf-8")

    def add(self, entry: ContentInventoryEntry) -> ContentInventory:
        inventory = self.load()
        existing = next((item for item in inventory.entries if item.project_id == entry.project_id), None)
        if existing is None:
            inventory.entries.append(entry)
        else:
            inventory.entries[inventory.entries.index(existing)] = entry
        self.save(inventory)
        return inventory

    def find_overlap(self, topic: str, threshold: float = 0.6) -> list[ContentInventoryEntry]:
        query_key = normalize_topic(topic)
        query_tokens = set(query_key.split())
        if not query_tokens:
            return []
        matches = []
        for entry in self.load().entries:
            if entry.normalized_topic == query_key:
                matches.append(entry)
                continue
            entry_tokens = set(entry.normalized_topic.split())
            union = query_tokens | entry_tokens
            overlap = len(query_tokens & entry_tokens) / len(union) if union else 0
            if overlap >= threshold:
                matches.append(entry)
        return matches


def normalize_topic(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", value.casefold())
    return " ".join(word for word in words if word not in {"a", "an", "the"})


def inventory_path(root: str | Path) -> Path:
    return Path(root) / "content_inventory.json"
