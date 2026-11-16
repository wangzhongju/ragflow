"""The engine's single sandbox and filter registry."""

from jinja2 import StrictUndefined, meta
from jinja2.sandbox import SandboxedEnvironment


def render_parts(parts: list) -> str:
    return "\n".join((part if isinstance(part, dict) else part.model_dump()).get("text") or "" for part in parts)


def sandbox() -> SandboxedEnvironment:
    env = SandboxedEnvironment(undefined=StrictUndefined)
    env.filters["render_parts"] = render_parts
    return env


def template_roots(template: str) -> set[str]:
    return set(meta.find_undeclared_variables(sandbox().parse(template)))
