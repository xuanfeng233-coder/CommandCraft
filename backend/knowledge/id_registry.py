"""ID Registry — validates entity/item/block/effect IDs against knowledge base."""

from __future__ import annotations

from backend.knowledge.loader import knowledge_loader


class IDRegistry:
    """Loads ID files and provides lookup/validation."""

    def __init__(self):
        self._cache: dict[str, set[str]] = {}

    def _load_category(self, category: str) -> set[str]:
        if category not in self._cache:
            entries = knowledge_loader.get_id_file(category)
            self._cache[category] = {e.get("id", "") for e in entries if e.get("id")}
        return self._cache[category]

    def is_valid_item(self, item_id: str) -> bool:
        return item_id in self._load_category("items")

    def is_valid_entity(self, entity_id: str) -> bool:
        return entity_id in self._load_category("entities")

    def is_valid_effect(self, effect_id: str) -> bool:
        return effect_id in self._load_category("effects")

    def is_valid_enchantment(self, enchant_id: str) -> bool:
        return enchant_id in self._load_category("enchantments")

    def is_valid_block(self, block_id: str) -> bool:
        blocks = self._load_category("blocks")
        if not blocks:
            return True  # If blocks.json not yet loaded, skip validation
        return block_id in blocks

    def is_valid_id(self, id_value: str, category: str) -> bool:
        """Generic ID validation against a category."""
        ids = self._load_category(category)
        if not ids:
            return True  # Skip validation if category not available
        return id_value in ids

    def get_all_ids(self, category: str) -> set[str]:
        return self._load_category(category)

    def get_available_categories(self) -> list[str]:
        return knowledge_loader.get_id_categories()

    def reload(self) -> None:
        self._cache.clear()


id_registry = IDRegistry()
