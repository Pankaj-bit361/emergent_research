"""Skill discovery and loading from standard SKILL.md locations.

Skills are markdown files with YAML frontmatter (name + description) that teach
the agent HOW to do domain-specific tasks. They follow the Anthropic/Codex
SKILL.md convention and are discovered from a priority-ordered hierarchy.

Hierarchy (lowest → highest precedence):
  1. Project skills  — inside workspace (.agents/skills/, skills/)
  2. Agent skills    — agent-specific (.wingman/, .claude/, .codex/)
  3. User skills     — user home, persisted across workspaces

Symlinks are followed — users can symlink skill dirs from repos or packages.
"""

import logging
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

logger = logging.getLogger(__name__)

# Skill directories searched in priority order (lowest → highest precedence).
# Higher-precedence dirs override skills with the same name from lower ones.
# /root is the persisted home on envcore pods; work_space lives inside it.
_SKILL_ROOTS = [
    # Project-level (inside workspace repo)
    "/root/workspace/.agents/skills",       # .agents/skills/ (Codex convention)
    "/root/workspace/skills",               # bare skills/ dir
    # Agent-specific (inside work_space)
    "/root/workspace/.wingman/skills",
    "/root/workspace/.claude/skills",
    "/root/workspace/.codex/skills",
    # User-level (persisted home — survives workspace changes)
    "/root/.agents/skills",                  # ~/.agents/skills/ (Codex convention)
    "/root/.wingman/skills",
    "/root/.claude/skills",
    "/root/.codex/skills",
]


def _discover_skills() -> list[dict]:
    """Scan all skill roots and return deduplicated metadata.

    Returns list of {name, description, path, source} dicts.
    Later roots override earlier ones (higher precedence wins).
    Symlinks are followed for both directories and SKILL.md files.
    """
    seen: dict[str, dict] = {}
    for root in _SKILL_ROOTS:
        root_path = Path(root)
        if not root_path.is_dir():
            continue
        source = root_path.parent.name  # e.g. ".wingman", ".claude", "work_space"
        for entry in sorted(root_path.iterdir()):
            # Follow symlinks — entry.is_dir() follows by default
            if not entry.is_dir():
                continue
            skill_file = entry / "SKILL.md"
            if not skill_file.is_file():
                continue
            name, desc = _parse_skill_frontmatter(skill_file)
            if not name:
                name = entry.name
            seen[name] = {
                "name": name,
                "description": desc,
                "path": str(skill_file.resolve()),  # resolve symlinks
                "source": source,
            }
    return list(seen.values())


def _parse_skill_frontmatter(path: Path) -> tuple[str, str]:
    """Extract name and description from SKILL.md YAML frontmatter."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return "", ""
    if not text.startswith("---"):
        return "", ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", ""
    name = ""
    desc = ""
    for line in parts[1].splitlines():
        line = line.strip()
        if line.startswith("name:"):
            name = line[len("name:"):].strip().strip("'\"")
        elif line.startswith("description:"):
            desc = line[len("description:"):].strip().strip("'\"")
    return name, desc


def _find_skill(name: str, skills: list[dict]) -> dict | None:
    """Find a skill by name or directory name (case-insensitive)."""
    name_lower = name.strip().lower()
    for s in skills:
        if s["name"].lower() == name_lower:
            return s
        dir_name = Path(s["path"]).parent.name.lower()
        if dir_name == name_lower:
            return s
    return None


# ── Tool registration ─────────────────────────────────────────────


def register_skill_tools(mcp: FastMCP):
    """Register list_skills and load_skill on the provided FastMCP instance."""

    @mcp.tool()
    def list_skills() -> str:
        """List all available skills in the environment.

        Scans standard skill locations for SKILL.md files and returns each
        skill's name and description. Use load_skill to read full instructions.

        Skill directories searched (highest precedence last):
        - Project: work_space/.agents/skills/, work_space/skills/
        - Agent:   work_space/.wingman/skills/, .claude/skills/, .codex/skills/
        - User:    ~/.wingman/skills/, ~/.claude/skills/, ~/.codex/skills/
        Symlinks are followed.
        """
        skills = _discover_skills()
        if not skills:
            return "No skills found."
        lines = []
        for s in skills:
            lines.append(f"- {s['name']}: {s['description']}")
        return "\n".join(lines)

    @mcp.tool()
    def load_skill(
        name: Annotated[str, Field(description="Name of the skill to load")],
    ) -> str:
        """Load a skill's full SKILL.md instructions by name.

        Returns the complete SKILL.md content including frontmatter and body.
        Use list_skills first to see available skills.
        """
        skills = _discover_skills()
        match = _find_skill(name, skills)

        if not match:
            available = ", ".join(s["name"] for s in skills) if skills else "none"
            return f"Skill '{name}' not found. Available: {available}"

        try:
            return Path(match["path"]).read_text(errors="replace")
        except OSError as e:
            return f"Error reading skill: {e}"

    return list_skills, load_skill
