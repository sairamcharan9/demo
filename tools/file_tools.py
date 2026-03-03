"""
File Tools — 8 tools for filesystem operations inside /workspace.

All paths are validated to prevent traversal outside the workspace root.
Each tool takes a tool_context parameter for state management (ADK ToolContext
in production, MockToolContext for testing).

All tools are async for ADK parallelisation.
"""

import os
import shutil
import asyncio
from pathlib import Path

import aiofiles
from google.adk.tools import ToolContext


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/workspace")


def _resolve_safe_path(relative_path: str, workspace: str | None = None) -> str:
    """Resolve *relative_path* against the workspace and ensure it stays inside.

    Raises ValueError if the resolved path escapes the workspace boundary.
    """
    ws = workspace or WORKSPACE_ROOT
    root = Path(ws).resolve()
    target = (root / relative_path).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError(
            f"Path traversal blocked: '{relative_path}' resolves outside workspace"
        )
    return str(target)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


async def list_files(path: str = ".", tool_context: ToolContext = None, workspace: str | None = None) -> dict:
    """List all files and directories under `path` relative to the workspace.
    
    First call in every session — used to orient the agent.

    Args:
        path: The path to list files for. Defaults to ".".
        tool_context: The adk tool context for state management.
        workspace: Optional workspace root directory.

    Returns:
        dict: A dict with `tree` (formatted string) and `files` (flat list).
    """
    root = _resolve_safe_path(path, workspace)
    if not os.path.isdir(root):
        return {"error": f"Directory not found: {path}"}

    def _scan():
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
        return lines, all_files

    lines, all_files = await asyncio.to_thread(_scan)
    return {"tree": "\n".join(lines), "files": all_files}


async def read_file(path: str, tool_context: ToolContext = None, workspace: str | None = None) -> dict:
    """Read the contents of a file.
    
    Called 10-15 times during the setup phase to understand the codebase.

    Args:
        path: The path to the file to read.
        tool_context: The adk tool context for state management.
        workspace: Optional workspace root directory.

    Returns:
        dict: A dict with `content` (raw text), `numbered` (text with line numbers), 
            and `lines` (total line count).
    """
    full = _resolve_safe_path(path, workspace)
    if not os.path.isfile(full):
        return {"error": f"File not found: {path}"}

    try:
        async with aiofiles.open(full, "r", encoding="utf-8", errors="replace") as fh:
            raw = await fh.read()
    except Exception as exc:
        return {"error": str(exc)}

    numbered = "\n".join(
        f"{i + 1:4d} | {line}" for i, line in enumerate(raw.splitlines())
    )
    return {"content": raw, "numbered": numbered, "lines": len(raw.splitlines())}


async def write_file(path: str, content: str, tool_context: ToolContext = None, workspace: str | None = None) -> dict:
    """Create or overwrite a file. Parent directories are created automatically.

    Emits a CUSTOM gitPatch event in production.

    Args:
        path: The target file path.
        content: The text content to write.
        tool_context: The adk tool context for state management.
        workspace: Optional workspace root directory.

    Returns:
        dict: A dict with `status` (ok), `path`, and `bytes` written.
    """
    full = _resolve_safe_path(path, workspace)
    await asyncio.to_thread(os.makedirs, os.path.dirname(full), exist_ok=True)

    try:
        async with aiofiles.open(full, "w", encoding="utf-8", newline="\n") as fh:
            await fh.write(content)
    except Exception as exc:
        return {"error": str(exc)}

    return {"status": "ok", "path": path, "bytes": len(content)}


async def replace_with_git_merge_diff(
    path: str, diff: str, tool_context: ToolContext = None, workspace: str | None = None
) -> dict:
    """Apply a unified diff to an existing file using `git apply` or `patch`.

    Preferred over write_file for surgical edits. Emits a CUSTOM gitPatch event.

    Args:
        path: The path to the file being patched.
        diff: The unified diff content.
        tool_context: The adk tool context for state management.
        workspace: Optional workspace root directory.

    Returns:
        dict: A dict with `status` (ok) and `path`, or `error` if both git and patch fail.
    """
    full = _resolve_safe_path(path, workspace)
    if not os.path.isfile(full):
        return {"error": f"File not found: {path}"}

    ws = workspace or WORKSPACE_ROOT
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "apply", "--whitespace=nowarn", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ws,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(input=diff.encode()), timeout=30)
        if proc.returncode != 0:
            # Fallback: try with patch command
            proc2 = await asyncio.create_subprocess_exec(
                "patch", "-p1", "--no-backup-if-mismatch",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=ws,
            )
            stdout2, stderr2 = await asyncio.wait_for(proc2.communicate(input=diff.encode()), timeout=30)
            if proc2.returncode != 0:
                return {
                    "error": f"Patch failed: {stderr2.decode().strip()}",
                    "stdout": stdout2.decode().strip(),
                }
    except FileNotFoundError:
        return {"error": "Neither 'git' nor 'patch' command found on system"}
    except asyncio.TimeoutError:
        return {"error": "Patch command timed out after 30s"}

    return {"status": "ok", "path": path}


async def delete_file(path: str, tool_context: ToolContext = None, workspace: str | None = None) -> dict:
    """Delete a file or directory from the workspace entirely.

    Emits a CUSTOM gitPatch event in production.

    Args:
        path: The path to the file or directory to delete.
        tool_context: The adk tool context for state management.
        workspace: Optional workspace root directory.

    Returns:
        dict: A dict with `status` (ok) and `path`.
    """
    full = _resolve_safe_path(path, workspace)
    if not os.path.exists(full):
        return {"error": f"File not found: {path}"}

    try:
        if os.path.isdir(full):
            await asyncio.to_thread(shutil.rmtree, full)
        else:
            await asyncio.to_thread(os.remove, full)
    except Exception as exc:
        return {"error": str(exc)}

    return {"status": "ok", "path": path}


async def rename_file(
    source: str, destination: str, tool_context: ToolContext = None, workspace: str | None = None
) -> dict:
    """Move or rename a file within the workspace boundaries.

    Args:
        source: The original file path.
        destination: The target file path.
        tool_context: The adk tool context for state management.
        workspace: Optional workspace root directory.

    Returns:
        dict: A dict with `status` (ok), `source`, and `destination`.
    """
    src = _resolve_safe_path(source, workspace)
    dst = _resolve_safe_path(destination, workspace)

    if not os.path.exists(src):
        return {"error": f"Source not found: {source}"}

    await asyncio.to_thread(os.makedirs, os.path.dirname(dst), exist_ok=True)

    try:
        await asyncio.to_thread(shutil.move, src, dst)
    except Exception as exc:
        return {"error": str(exc)}

    return {"status": "ok", "source": source, "destination": destination}


async def restore_file(path: str, tool_context: ToolContext = None, workspace: str | None = None) -> dict:
    """Revert a single file to its last git committed state.

    Equivalent to `git checkout -- <path>`.

    Args:
        path: The path to the file to revert.
        tool_context: The adk tool context for state management.
        workspace: Optional workspace root directory.

    Returns:
        dict: A dict with `status` (ok) and `path`.
    """
    _resolve_safe_path(path, workspace)  # validate path stays inside workspace
    ws = workspace or WORKSPACE_ROOT

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "checkout", "--", path,   # relative path — not absolute
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ws,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            return {"error": f"git checkout failed: {stderr.decode().strip()}"}
    except FileNotFoundError:
        return {"error": "git not found on system"}
    except asyncio.TimeoutError:
        return {"error": "git checkout timed out"}

    return {"status": "ok", "path": path}


async def reset_all(tool_context: ToolContext = None, workspace: str | None = None) -> dict:
    """Hard reset the entire workspace to the HEAD commit.

    Equivalent to `git reset --hard HEAD`. Emergency use only.

    Args:
        tool_context: The adk tool context for state management.
        workspace: Optional workspace root directory.

    Returns:
        dict: A dict with `status` (ok) and `message`.
    """
    ws = workspace or WORKSPACE_ROOT

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "reset", "--hard", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=ws,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            return {"error": f"git reset failed: {stderr.decode().strip()}"}
    except FileNotFoundError:
        return {"error": "git not found on system"}
    except asyncio.TimeoutError:
        return {"error": "git reset timed out"}

    return {"status": "ok", "message": "Workspace reset to HEAD"}
