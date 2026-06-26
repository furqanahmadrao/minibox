"""Template API endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from src.core.templates import Template, get_template, list_templates, register_template
from src.models.sandbox import TemplateRegisterRequest, TemplateResponse

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("", response_model=list[TemplateResponse])
async def list_templates_endpoint() -> list[TemplateResponse]:
    """List all available templates."""
    templates = list_templates()
    return [
        TemplateResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            packages=t.packages,
            is_custom=t.is_custom,
        )
        for t in templates
    ]


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template_endpoint(template_id: str) -> TemplateResponse:
    """Get a specific template."""
    template = get_template(template_id)
    if template is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    return TemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        packages=template.packages,
        is_custom=template.is_custom,
    )


@router.post("", response_model=TemplateResponse)
async def register_template_endpoint(req: TemplateRegisterRequest) -> TemplateResponse:
    """Register a custom template."""
    template = Template(
        id=req.id,
        name=req.name,
        description=req.description,
        packages=req.packages,
        env=req.env,
        is_custom=True,
    )
    register_template(template)
    return TemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        packages=template.packages,
        is_custom=True,
    )


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template_endpoint(template_id: str, req: TemplateRegisterRequest) -> TemplateResponse:
    """Update a custom template."""
    from fastapi import HTTPException
    from src.core.templates import get_template, _custom_templates, _save_custom_templates
    
    template = get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    if not template.is_custom:
        raise HTTPException(status_code=400, detail="Cannot edit built-in templates")
        
    template.name = req.name
    template.description = req.description
    template.packages = req.packages
    template.env = req.env
    
    _custom_templates[template.id] = template
    _save_custom_templates()
    
    return TemplateResponse(
        id=template.id,
        name=template.name,
        description=template.description,
        packages=template.packages,
        is_custom=True,
    )


@router.delete("/{template_id}")
async def delete_template_endpoint(template_id: str) -> dict:
    """Delete a custom template."""
    from fastapi import HTTPException
    from src.core.templates import get_template, _custom_templates, _save_custom_templates
    
    template = get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    if not template.is_custom:
        raise HTTPException(status_code=400, detail="Cannot delete built-in templates")
        
    if template_id in _custom_templates:
        del _custom_templates[template_id]
        _save_custom_templates()
        return {"deleted": True, "id": template_id}
    
    raise HTTPException(status_code=500, detail="Failed to delete template")
