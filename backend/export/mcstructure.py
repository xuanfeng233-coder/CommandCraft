"""Export project data as Bedrock Edition .mcstructure binary file.

The .mcstructure format is little-endian NBT containing:
- Block palette (command block types + air)
- Block indices (3D grid mapping to palette)
- Block entity data (commands for each command block)
"""

from __future__ import annotations

from typing import Any

from backend.export.nbt import NBTWriter, NBTByte, NBTFloat

# Facing direction values for Bedrock Edition
DIRECTION_MAP: dict[str, int] = {
    "down": 0,
    "up": 1,
    "north": 2,
    "south": 3,
    "west": 4,
    "east": 5,
}

# Block version for ~1.21.x
BLOCK_VERSION = 18153472


def _make_block_state(
    block_type: str,
    facing_direction: int,
    conditional: bool,
) -> dict[str, Any]:
    """Create a block palette entry."""
    return {
        "name": f"minecraft:{block_type}",
        "states": {
            "facing_direction": facing_direction,
            "conditional_bit": NBTByte(1 if conditional else 0),
        },
        "version": BLOCK_VERSION,
    }


def _make_block_entity(
    command: str,
    custom_name: str,
    auto: bool,
    x: int,
    y: int,
    z: int,
    lp_command_mode: int = 2,
    conditional: bool = False,
) -> dict[str, Any]:
    """Create block_entity_data for a command block.

    lp_command_mode: 0=impulse, 1=repeat, 2=chain
    """
    return {
        "id": "CommandBlock",
        "Command": command,
        "CustomName": custom_name,
        "auto": NBTByte(1 if auto else 0),
        "TrackOutput": NBTByte(1),
        "conditionMet": NBTByte(0),
        "powered": NBTByte(0),
        "LPCommandMode": lp_command_mode,
        "LPConditionalMode": NBTByte(1 if conditional else 0),
        "LPRedstoneMode": NBTByte(1 if auto else 0),
        "SuccessCount": 0,
        "LastOutput": "",
        "isMovable": NBTByte(1),
        "x": x,
        "y": y,
        "z": z,
    }


# Map block_type to LPCommandMode
_COMMAND_MODE_MAP = {
    "command_block": 0,
    "repeating_command_block": 1,
    "chain_command_block": 2,
}


def generate_mcstructure(project: dict[str, Any]) -> bytes:
    """Generate a .mcstructure binary from project layout data.

    Args:
        project: Dict with 'layout', 'dimensions', etc. matching ProjectResult.

    Returns:
        The raw .mcstructure file bytes.
    """
    layout = project.get("layout", [])
    dims = project.get("dimensions", {})

    width = max(dims.get("width", 1), 1)
    height = max(dims.get("height", 1), 1)
    depth = max(dims.get("depth", 1), 1)

    # Build palette: index 0 = air, then unique block states
    palette: list[dict[str, Any]] = [
        {"name": "minecraft:air", "states": {}, "version": BLOCK_VERSION}
    ]
    palette_key_to_idx: dict[str, int] = {}

    # Build 3D grid (ZYX order): default to 0 (air)
    total_blocks = width * height * depth
    indices = [0] * total_blocks

    # Block entity data keyed by block index
    block_entity_map: dict[str, dict[str, Any]] = {}

    for block in layout:
        pos = block.get("position", {})
        x = pos.get("x", 0)
        y = pos.get("y", 0)
        z = pos.get("z", 0)

        if x < 0 or x >= width or y < 0 or y >= height or z < 0 or z >= depth:
            continue

        block_type = block.get("block_type", "chain_command_block")
        direction = block.get("direction", "east")
        conditional = block.get("conditional", False)
        facing = DIRECTION_MAP.get(direction, 5)

        # Unique palette key
        pkey = f"{block_type}|{facing}|{conditional}"
        if pkey not in palette_key_to_idx:
            palette_key_to_idx[pkey] = len(palette)
            palette.append(_make_block_state(block_type, facing, conditional))

        # ZYX index = SZ*SY*X + SZ*Y + Z
        idx = depth * height * x + depth * y + z
        indices[idx] = palette_key_to_idx[pkey]

        # Block entity data
        command = block.get("command", "")
        custom_name = block.get("custom_name", "")
        auto = block.get("auto", True)
        lp_mode = _COMMAND_MODE_MAP.get(block_type, 2)

        block_entity_map[str(idx)] = {
            "block_entity_data": _make_block_entity(
                command=command,
                custom_name=custom_name,
                auto=auto,
                x=x,
                y=y,
                z=z,
                lp_command_mode=lp_mode,
                conditional=conditional,
            )
        }

    # Secondary layer (all -1 = no waterlogging)
    secondary = [-1] * total_blocks

    # Build NBT structure
    nbt_data: dict[str, Any] = {
        "format_version": 1,
        "size": [width, height, depth],
        "structure": {
            "block_indices": [indices, secondary],
            "entities": [],
            "palette": {
                "default": {
                    "block_palette": palette,
                    "block_position_data": block_entity_map,
                }
            },
        },
        "structure_world_origin": [0, 0, 0],
    }

    writer = NBTWriter()
    return writer.write_root_compound("", nbt_data)
