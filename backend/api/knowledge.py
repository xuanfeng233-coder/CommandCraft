"""Knowledge base API — exposes command and ID data for frontend use."""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.knowledge.loader import get_loader
from backend.knowledge.id_registry import get_id_registry

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _get_edition(edition: str) -> str:
    """Normalize and validate edition parameter."""
    return "java" if edition == "java" else "bedrock"


# ── Edition-aware endpoints (new, preferred) ──────────────────────

@router.get("/{edition}/commands")
async def list_commands_edition(edition: str):
    """Return the command index for the given edition."""
    loader = get_loader(_get_edition(edition))
    return {"commands": loader.get_command_index()}


@router.get("/{edition}/commands/all-syntax")
async def get_all_command_syntax_edition(edition: str):
    """Return all commands with syntax and parameters for editor completion."""
    loader = get_loader(_get_edition(edition))
    index = loader.get_command_index()
    result = []
    for cmd_info in index:
        name = cmd_info.get("name", "")
        doc = loader.get_command_doc(name)
        if doc:
            result.append({
                "name": doc.get("name", name),
                "syntax": doc.get("syntax", ""),
                "description": doc.get("description", ""),
                "category": doc.get("category", ""),
                "parameters": doc.get("parameters", []),
            })
        else:
            result.append({
                "name": name,
                "syntax": cmd_info.get("syntax", ""),
                "description": cmd_info.get("description", ""),
                "category": cmd_info.get("category", ""),
                "parameters": [],
            })
    return {"commands": result}


@router.get("/{edition}/commands/{name}")
async def get_command_edition(edition: str, name: str):
    """Return detailed docs for a single command."""
    loader = get_loader(_get_edition(edition))
    docs = loader.get_command_docs([name])
    if not docs:
        return {"error": f"命令 '{name}' 未找到"}
    return {"command": docs[0]}


@router.get("/{edition}/ids")
async def list_id_categories_edition(edition: str):
    """Return available ID categories."""
    registry = get_id_registry(_get_edition(edition))
    return {"categories": registry.get_available_categories()}


@router.get("/{edition}/ids/{category}/full")
async def get_ids_full_edition(edition: str, category: str):
    """Return full ID entries for a category."""
    loader = get_loader(_get_edition(edition))
    entries = loader.get_id_file(category)
    return {"category": category, "entries": entries}


@router.get("/{edition}/ids/{category}")
async def get_ids_edition(edition: str, category: str):
    """Return all IDs for a given category."""
    registry = get_id_registry(_get_edition(edition))
    ids = registry.get_all_ids(category)
    return {"category": category, "ids": sorted(ids)}


@router.get("/{edition}/nbt/{nbt_type}/{name}")
async def get_nbt_schema(edition: str, nbt_type: str, name: str):
    """Return resolved NBT schema for an entity/item/block (Java Edition)."""
    loader = get_loader(_get_edition(edition))
    schema = loader.get_nbt_schema_resolved(nbt_type, name)
    if schema is None:
        return {"error": f"NBT schema '{nbt_type}/{name}' 未找到"}
    return {"schema": schema}


@router.get("/{edition}/nbt/{nbt_type}")
async def list_nbt_schemas(edition: str, nbt_type: str):
    """List available NBT schema names for a type."""
    loader = get_loader(_get_edition(edition))
    names = loader.list_nbt_schemas(nbt_type)
    return {"type": nbt_type, "names": names}


@router.get("/{edition}/data-components")
async def get_data_components(edition: str):
    """Return data component definitions (Java 1.20.5+)."""
    loader = get_loader(_get_edition(edition))
    return loader.get_data_components()


@router.get("/{edition}/text-components")
async def get_text_components(edition: str):
    """Return JSON text component schema."""
    loader = get_loader(_get_edition(edition))
    return loader.get_text_component_schema()


# ── Legacy endpoints (backward compatible, default to bedrock) ────

@router.get("/commands")
async def list_commands():
    """Return the command index (legacy, defaults to bedrock)."""
    loader = get_loader("bedrock")
    return {"commands": loader.get_command_index()}


@router.get("/commands/all-syntax")
async def get_all_command_syntax():
    """Return all commands with syntax (legacy, defaults to bedrock)."""
    loader = get_loader("bedrock")
    index = loader.get_command_index()
    result = []
    for cmd_info in index:
        name = cmd_info.get("name", "")
        doc = loader.get_command_doc(name)
        if doc:
            result.append({
                "name": doc.get("name", name),
                "syntax": doc.get("syntax", ""),
                "description": doc.get("description", ""),
                "category": doc.get("category", ""),
                "parameters": doc.get("parameters", []),
            })
        else:
            result.append({
                "name": name,
                "syntax": cmd_info.get("syntax", ""),
                "description": cmd_info.get("description", ""),
                "category": cmd_info.get("category", ""),
                "parameters": [],
            })
    return {"commands": result}


@router.get("/commands/{name}")
async def get_command(name: str):
    """Return detailed docs for a single command (legacy)."""
    loader = get_loader("bedrock")
    docs = loader.get_command_docs([name])
    if not docs:
        return {"error": f"命令 '{name}' 未找到"}
    return {"command": docs[0]}


@router.get("/ids")
async def list_id_categories():
    """Return available ID categories (legacy)."""
    registry = get_id_registry("bedrock")
    return {"categories": registry.get_available_categories()}


@router.get("/ids/{category}/full")
async def get_ids_full(category: str):
    """Return full ID entries (legacy)."""
    loader = get_loader("bedrock")
    entries = loader.get_id_file(category)
    return {"category": category, "entries": entries}


@router.get("/ids/{category}")
async def get_ids(category: str):
    """Return all IDs for a given category (legacy)."""
    registry = get_id_registry("bedrock")
    ids = registry.get_all_ids(category)
    return {"category": category, "ids": sorted(ids)}


@router.get("/commands/{name}/params")
async def get_command_params(name: str, edition: str = Query("bedrock")):
    """Return parameter definitions for a command (for frontend CommandEditor)."""
    from backend.skills.template_builder import template_builder

    loader = get_loader(_get_edition(edition))
    doc = loader.get_command_doc(name)
    if not doc:
        return {"error": f"命令 '{name}' 未找到", "params": []}

    params = doc.get("parameters", [])
    enriched = []
    for p in params:
        entry = {
            "name": p.get("name", ""),
            "type": p.get("type", "string"),
            "required": p.get("required", False),
            "description": p.get("description", ""),
        }
        if p.get("default") is not None:
            entry["default"] = str(p["default"])
        if p.get("range"):
            entry["range"] = p["range"]

        options = template_builder.get_param_options(name, p.get("name", ""))
        if options:
            entry["options"] = options

        enriched.append(entry)

    return {"command": name, "params": enriched}
