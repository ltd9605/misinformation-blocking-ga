"""Document locations and Markdown output for experiment reports."""

import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from src.data.specs import PROJECT_ROOT


# Legacy paths remain in historical manifests; resolve them without rewriting evidence.
DOCUMENT_PATHS = {
    "HUONG_DAN_CHAY_THU_CONG.md": "docs/guides/HUONG_DAN_CHAY_THU_CONG.md",
    "THESIS_VERSION.md": "docs/reference/THESIS_VERSION.md",
    "PROJECT_CONTEXT.md": "docs/planning/PROJECT_CONTEXT.md",
    "EXPERIMENT_PLAN.md": "docs/planning/EXPERIMENT_PLAN.md",
    "EXPERIMENT_PROTOCOL_V1.md": "docs/protocols/EXPERIMENT_PROTOCOL_V1.md",
    "MAIN_EXPERIMENTS_PROTOCOL.md": "docs/protocols/MAIN_EXPERIMENTS_PROTOCOL.md",
    "MAIN_EXPERIMENTS_PROTOCOL_V2.md": "docs/protocols/MAIN_EXPERIMENTS_PROTOCOL_V2.md",
    "CROSS_SCENARIO_GA_CONFIRMATION.md": "docs/reports/CROSS_SCENARIO_GA_CONFIRMATION.md",
    "MAIN_EXPERIMENTS_RESULTS.md": "docs/reports/MAIN_EXPERIMENTS_RESULTS.md",
    "MILESTONE_7_REDUCED_SCREEN.md": "docs/reports/MILESTONE_7_REDUCED_SCREEN.md",
    "MILESTONE_7_REDUCED_SCREEN_V2.md": "docs/reports/MILESTONE_7_REDUCED_SCREEN_V2.md",
    "PILOT_2_CALIBRATION.md": "docs/reports/PILOT_2_CALIBRATION.md",
    "PILOT_PROTOCOL_VALIDATION.md": "docs/reports/PILOT_PROTOCOL_VALIDATION.md",
    **{
        f"docs/{name}.md": f"docs/reports/{name}.md"
        for name in ("MILESTONE_4A_PILOT", "MILESTONE_4B_PILOT", "MILESTONE_5_PILOT", "MILESTONE_6_SMOKE")
    },
}

_MARKDOWN_LINK = re.compile(r"(!?\[[^\]\n]*\]\()([^\s)]+)(\))")


def project_document(path: str | Path) -> Path:
    """Resolve a project-relative document path, including its legacy location."""
    return PROJECT_ROOT / DOCUMENT_PATHS.get(str(path), str(path))


def write_project_report(target: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write a report whose template links are relative to the repository root.

    Rebase local Markdown links to the output directory, including custom output
    directories outside the repository. Shell commands and provenance text stay
    relative to the repository, where experiment commands must be run.
    """
    target = target.resolve()

    def rebase(match: re.Match[str]) -> str:
        parts = urlsplit(match[2])
        if parts.scheme or parts.netloc or match[2].startswith(("#", "/")):
            return match[0]
        path = os.path.relpath(project_document(parts.path), target.parent)
        link = Path(path).as_posix()
        if parts.query:
            link += "?" + parts.query
        if parts.fragment:
            link += "#" + parts.fragment
        return match[1] + link + match[3]

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_MARKDOWN_LINK.sub(rebase, content), encoding=encoding)
