"""Knowledge base API — exposes command and ID data for frontend use."""

from __future__ import annotations

from fastapi import APIRouter

from backend.knowledge.loader import knowledge_loader
from backend.knowledge.id_registry import id_registry

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/commands")
async def list_commands():
    """Return the command index for frontend display."""
    index = knowledge_loader.get_command_index()
    return {"commands": index}


@router.get("/commands/all-syntax")
async def get_all_command_syntax():
    """Return all commands with their name, syntax, category, and parameters array.

    Used by the frontend editor for completion and validation.
    """
    index = knowledge_loader.get_command_index()
    result = []
    for cmd_info in index:
        name = cmd_info.get("name", "")
        doc = knowledge_loader.get_command_doc(name)
        if doc:
            result.append({
                "name": doc.get("name", name),
                "syntax": doc.get("syntax", ""),
                "description": doc.get("description", ""),
                "category": doc.get("category", ""),
                "parameters": doc.get("parameters", []),
            })
        else:
            # Fallback: include index info without parameters
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
    """Return detailed docs for a single command."""
    docs = knowledge_loader.get_command_docs([name])
    if not docs:
        return {"error": f"命令 '{name}' 未找到"}
    return {"command": docs[0]}


@router.get("/ids")
async def list_id_categories():
    """Return available ID categories."""
    categories = id_registry.get_available_categories()
    return {"categories": categories}


@router.get("/ids/{category}/full")
async def get_ids_full(category: str):
    """Return full ID entries for a category (id + name + category)."""
    entries = knowledge_loader.get_id_file(category)
    return {"category": category, "entries": entries}


@router.get("/ids/{category}")
async def get_ids(category: str):
    """Return all IDs for a given category (items, entities, effects, etc.)."""
    ids = id_registry.get_all_ids(category)
    return {"category": category, "ids": sorted(ids)}


@router.get("/commands/{name}/params")
async def get_command_params(name: str):
    """Return parameter definitions for a command (for frontend CommandEditor)."""
    from backend.skills.template_builder import template_builder

    doc = knowledge_loader.get_command_doc(name)
    if not doc:
        return {"error": f"命令 '{name}' 未找到", "params": []}

    params = doc.get("parameters", [])
    # Enrich with knowledge base options
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
