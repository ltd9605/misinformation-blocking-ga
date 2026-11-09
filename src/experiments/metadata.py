"""Read-only software/hardware/Git provenance for experiment artifacts."""

from importlib import metadata
import os
import platform
import subprocess
from typing import Any

from src.data.loader import sha256_file
from src.data.specs import PROJECT_ROOT


def _command(arguments: list[str]) -> str | None:
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, check=False, timeout=3)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def environment_metadata() -> dict[str, Any]:
    """Capture measured/available values; unavailable hardware fields stay null."""
    memory = None
    try:
        memory = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        pass
    model, processor = None, platform.processor() or None
    if platform.system() == "Darwin":
        model = _command(["sysctl", "-n", "hw.model"])
        processor = _command(["sysctl", "-n", "machdep.cpu.brand_string"]) or processor
        value = _command(["sysctl", "-n", "hw.memsize"])
        if value and value.isdigit():
            memory = int(value)
    status = _command(["git", "-C", str(PROJECT_ROOT), "status", "--porcelain"])
    return {
        "python": platform.python_version(), "python_implementation": platform.python_implementation(),
        "platform": platform.platform(), "os": platform.system(), "os_release": platform.release(),
        "machine": platform.machine(), "processor": processor, "hardware_model": model,
        "logical_cpu_count": os.cpu_count(), "physical_memory_bytes": memory,
        "libraries": dict(sorted((dist.metadata["Name"], dist.version) for dist in metadata.distributions())),
        "git_commit": _command(["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"]),
        "git_dirty": bool(status) if status is not None else None,
        "git_status_porcelain": status,
        "source_sha256": {p.relative_to(PROJECT_ROOT).as_posix(): sha256_file(p)
                          for p in sorted((PROJECT_ROOT / "src").rglob("*.py"))},
    }
