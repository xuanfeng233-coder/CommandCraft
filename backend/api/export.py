"""Export API endpoints for .mcfunction and .mcstructure files."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Any

from backend.export.mcfunction import generate_mcfunction, generate_single_command_mcfunction
from backend.export.mcstructure import generate_mcstructure

router = APIRouter(prefix="/api/export", tags=["export"])


class McfunctionExportRequest(BaseModel):
    """Request body for .mcfunction export."""
    project: dict[str, Any] | None = Field(None, description="Project result data")
    command: str | None = Field(None, description="Single command string")
    explanation: str = Field("", description="Command explanation (for single command)")
    filename: str = Field("output", description="Desired filename without extension")


@router.post("/mcfunction")
async def export_mcfunction(request: McfunctionExportRequest):
    """Export project or single command as .mcfunction file."""
    if request.project:
        content = generate_mcfunction(request.project)
    elif request.command:
        content = generate_single_command_mcfunction(
            request.command, request.explanation
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="Must provide either 'project' or 'command'",
        )

    filename = request.filename.replace(" ", "_") + ".mcfunction"

    return Response(
        content=content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


class McstructureExportRequest(BaseModel):
    """Request body for .mcstructure export."""
    project: dict[str, Any] = Field(..., description="Project result data with layout")
    filename: str = Field("output", description="Desired filename without extension")


@router.post("/mcstructure")
async def export_mcstructure(request: McstructureExportRequest):
    """Export project command block layout as .mcstructure (NBT) file."""
    layout = request.project.get("layout", [])
    if not layout:
        raise HTTPException(
            status_code=400,
            detail="Project has no layout data for .mcstructure export",
        )

    try:
        data = generate_mcstructure(request.project)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate .mcstructure: {e}",
        )

    filename = request.filename.replace(" ", "_") + ".mcstructure"

    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
