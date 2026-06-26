"""Built-in and custom sandbox templates."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Template:
    id: str
    name: str
    description: str
    base_image: str = ""
    packages: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    command: str = "/bin/bash"
    is_custom: bool = False


BUILTIN_TEMPLATES: dict[str, Template] = {
    "python-dev": Template(
        id="python-dev",
        name="Python Development",
        description="Python 3.12 with pip, venv, common data science packages",
        packages=["python3", "python3-pip", "python3-venv"],
        env={"VIRTUAL_ENV": "/workspace/.venv"},
    ),
    "node-dev": Template(
        id="node-dev",
        name="Node.js Development",
        description="Node.js 20 with npm, yarn, pnpm",
        packages=["nodejs", "npm"],
    ),
    "rust-dev": Template(
        id="rust-dev",
        name="Rust Development",
        description="Rust toolchain with cargo",
        packages=["rustc", "cargo", "libssl-dev"],
    ),
    "research": Template(
        id="research",
        name="Research",
        description="Minimal environment for experimentation",
        packages=["python3", "curl", "wget", "git"],
    ),
    "data-science": Template(
        id="data-science",
        name="Data Science",
        description="Python with numpy, pandas, jupyter",
        packages=["python3", "python3-pip"],
        env={"NUMEXPR_DISABLE": "1"},
    ),
    "minimal": Template(
        id="minimal",
        name="Minimal",
        description="Bare minimum — just bash and coreutils",
        packages=["bash", "coreutils"],
    ),
}


_custom_templates: dict[str, Template] = {}


def _get_templates_db_path():
    from pathlib import Path
    from src.config import get_config
    config = get_config()
    return config.sandbox.workspace_root.parent / "templates.json"


def _load_custom_templates() -> None:
    import json
    try:
        db_path = _get_templates_db_path()
        if db_path.exists():
            data = json.loads(db_path.read_text(encoding="utf-8"))
            for key, val in data.items():
                _custom_templates[key] = Template(
                    id=val["id"],
                    name=val["name"],
                    description=val["description"],
                    base_image=val.get("base_image", ""),
                    packages=val.get("packages", []),
                    env=val.get("env", {}),
                    command=val.get("command", "/bin/bash"),
                    is_custom=True,
                )
    except Exception:
        pass


def _save_custom_templates() -> None:
    import json
    try:
        db_path = _get_templates_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            k: {
                "id": v.id,
                "name": v.name,
                "description": v.description,
                "base_image": v.base_image,
                "packages": v.packages,
                "env": v.env,
                "command": v.command,
            }
            for k, v in _custom_templates.items()
        }
        db_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_template(template_id: str) -> Template | None:
    """Get a template by ID."""
    return BUILTIN_TEMPLATES.get(template_id) or _custom_templates.get(template_id)


def list_templates() -> list[Template]:
    """List all available templates."""
    return list(BUILTIN_TEMPLATES.values()) + list(_custom_templates.values())


def register_template(template: Template) -> None:
    """Register a custom template."""
    template.is_custom = True
    _custom_templates[template.id] = template
    _save_custom_templates()


# Load custom templates on startup
_load_custom_templates()
