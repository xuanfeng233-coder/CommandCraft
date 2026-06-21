"""ID Registry — validates entity/item/block/effect IDs against knowledge base."""

from __future__ import annotations

from backend.knowledge.loader import KnowledgeLoader, bedrock_loader, java_loader


class IDRegistry:
    """Loads ID files and provides lookup/validation."""

    def __init__(self, loader: KnowledgeLoader):
        self._loader = loader
        self._cache: dict[str, set[str]] = {}

    def _load_category(self, category: str) -> set[str]:
        if category not in self._cache:
            entries = self._loader.get_id_file(category)
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
        return self._loader.get_id_categories()

    def reload(self) -> None:
        self._cache.clear()


# Edition-specific singletons
bedrock_id_registry = IDRegistry(loader=bedrock_loader)
java_id_registry = IDRegistry(loader=java_loader)

# Default (backward compatible)
id_registry = bedrock_id_registry


def get_id_registry(edition: str = "bedrock") -> IDRegistry:
    """Get the IDRegistry for the given edition."""
    return java_id_registry if edition == "java" else bedrock_id_registry
