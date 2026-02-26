"""
File Tools — 8 tools for filesystem operations inside /workspace.

All paths are validated to prevent traversal outside the workspace root.
Each tool takes a tool_context parameter for state management (ADK ToolContext
in production, dict with 'state' key for testing).
"""

import os
import shutil
import subprocess
from pathlib import Path


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/workspace")


def _resolve_safe_path(relative_path: str, workspace: str | None = None) -> str:
    """Resolve *relative_path* against the workspace and ensure it stays inside.

    Raises ValueError if the resolved path escapes the workspace boundary.
    """
    root = Path(workspace or WORKSPACE_ROOT).resolve()
    target = (root / relative_path).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError(
            f"Path traversal blocked: '{relative_path}' resolves outside workspace"
        )
    return str(target)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def list_files(path: str = ".", tool_context=None, workspace: str | None = None) -> dict:
    """List all files and directories under *path* relative to the workspace.

    Returns a dict with ``tree`` (formatted string) and ``files`` (flat list).
    First call in every session — used to orient the agent.
    """
    root = _resolve_safe_path(path, workspace)
    if not os.path.isdir(root):
        return {"error": f"Directory not found: {path}"}

    lines: list[str] = []
    all_files: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden directories like .git
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        level = len(Path(dirpath).relative_to(root).parts)
        indent = "  " * level
        basename = os.path.basename(dirpath)
        if level == 0:
            lines.append(f"{path}/")
        else:
            lines.append(f"{indent}{basename}/")
        for fname in sorted(filenames):
            if fname.startswith("."):
                continue
            lines.append(f"{indent}  {fname}")
            rel = os.path.relpath(os.path.join(dirpath, fname), root)
            all_files.append(rel.replace("\\", "/"))

    return {"tree": "\n".join(lines), "files": all_files}


def read_file(path: str, tool_context=None, workspace: str | None = None) -> dict:
    """Read the contents of a file. Returns content with line numbers.

    Called 10-15 times during the setup phase to understand the codebase.
    """
    full = _resolve_safe_path(path, workspace)
    if not os.path.isfile(full):
        return {"error": f"File not found: {path}"}

    try:
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except Exception as exc:
        return {"error": str(exc)}

    numbered = "\n".join(
        f"{i + 1:4d} | {line}" for i, line in enumerate(raw.splitlines())
    )
    return {"content": raw, "numbered": numbered, "lines": len(raw.splitlines())}


def write_file(path: str, content: str, tool_context=None, workspace: str | None = None) -> dict:
    """Create or overwrite a file. Parent directories are created automatically.

    Emits a CUSTOM gitPatch event in production (via tool_context).
    """
    full = _resolve_safe_path(path, workspace)
    os.makedirs(os.path.dirname(full), exist_ok=True)

    try:
        with open(full, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
    except Exception as exc:
        return {"error": str(exc)}

    return {"status": "ok", "path": path, "bytes": len(content)}


def replace_with_git_merge_diff(
    path: str, diff: str, tool_context=None, workspace: str | None = None
) -> dict:
    """Apply a unified diff to an existing file using ``patch``.

    Preferred over write_file for surgical edits.
    Emits a CUSTOM gitPatch event in production.
    """
    full = _resolve_safe_path(path, workspace)
    if not os.path.isfile(full):
        return {"error": f"File not found: {path}"}

    ws = workspace or WORKSPACE_ROOT
    try:
        result = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            input=diff,
            capture_output=True,
            text=True,
            cwd=ws,
            timeout=30,
        )
        if result.returncode != 0:
            # Fallback: try with patch command
            result = subprocess.run(
                ["patch", "-p1", "--no-backup-if-mismatch"],
                input=diff,
                capture_output=True,
                text=True,
                cwd=ws,
                timeout=30,
            )
            if result.returncode != 0:
                return {
                    "error": f"Patch failed: {result.stderr.strip()}",
                    "stdout": result.stdout.strip(),
                }
    except FileNotFoundError:
        return {"error": "Neither 'git' nor 'patch' command found on system"}
    except subprocess.TimeoutExpired:
        return {"error": "Patch command timed out after 30s"}

    return {"status": "ok", "path": path}


def delete_file(path: str, tool_context=None, workspace: str | None = None) -> dict:
    """Delete a file from the workspace.

    Emits a CUSTOM gitPatch event in production.
    """
    full = _resolve_safe_path(path, workspace)
    if not os.path.exists(full):
        return {"error": f"File not found: {path}"}

    try:
        if os.path.isdir(full):
            shutil.rmtree(full)
        else:
            os.remove(full)
    except Exception as exc:
        return {"error": str(exc)}

    return {"status": "ok", "path": path}


def rename_file(
    source: str, destination: str, tool_context=None, workspace: str | None = None
) -> dict:
    """Move or rename a file within the workspace."""
    src = _resolve_safe_path(source, workspace)
    dst = _resolve_safe_path(destination, workspace)

    if not os.path.exists(src):
        return {"error": f"Source not found: {source}"}

    os.makedirs(os.path.dirname(dst), exist_ok=True)

    try:
        shutil.move(src, dst)
    except Exception as exc:
        return {"error": str(exc)}

    return {"status": "ok", "source": source, "destination": destination}


def restore_file(path: str, tool_context=None, workspace: str | None = None) -> dict:
    """Revert a single file to its last git committed state.

    Equivalent to ``git checkout -- <path>``.
    """
    full = _resolve_safe_path(path, workspace)
    ws = workspace or WORKSPACE_ROOT

    try:
        result = subprocess.run(
            ["git", "checkout", "--", full],
            capture_output=True,
            text=True,
            cwd=ws,
            timeout=30,
        )
        if result.returncode != 0:
            return {"error": f"git checkout failed: {result.stderr.strip()}"}
    except FileNotFoundError:
        return {"error": "git not found on system"}
    except subprocess.TimeoutExpired:
        return {"error": "git checkout timed out"}

    return {"status": "ok", "path": path}


def reset_all(tool_context=None, workspace: str | None = None) -> dict:
    """Hard reset the entire workspace to HEAD.

    Equivalent to ``git reset --hard HEAD``. Emergency use only.
    """
    ws = workspace or WORKSPACE_ROOT

    try:
        result = subprocess.run(
            ["git", "reset", "--hard", "HEAD"],
            capture_output=True,
            text=True,
            cwd=ws,
            timeout=30,
        )
        if result.returncode != 0:
            return {"error": f"git reset failed: {result.stderr.strip()}"}
    except FileNotFoundError:
        return {"error": "git not found on system"}
    except subprocess.TimeoutExpired:
        return {"error": "git reset timed out"}

    return {"status": "ok", "message": "Workspace reset to HEAD"}
