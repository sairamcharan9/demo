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
import subprocess
from pathlib import Path

import aiofiles
from google.adk.tools import ToolContext
from utils.workspace_utils import get_workspace


# Path safety
# ---------------------------------------------------------------------------



def _resolve_safe_path(relative_path: str, tool_context: ToolContext = None, workspace: str | None = None) -> str:
    """Resolve *relative_path* against the workspace and ensure it stays inside.

    Raises ValueError if the resolved path escapes the workspace boundary.
    """
    ws = workspace or get_workspace(tool_context)
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
    root = _resolve_safe_path(path, tool_context, workspace)
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
    full = _resolve_safe_path(path, tool_context, workspace)
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
    full = _resolve_safe_path(path, tool_context, workspace)
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
    full = _resolve_safe_path(path, tool_context, workspace)
    if not os.path.isfile(full):
        return {"error": f"File not found: {path}"}

    ws = workspace or get_workspace(tool_context)
    
    # Pre-process diff to ensure it uses Unix line endings, which git apply prefers
    diff = diff.replace("\r\n", "\n")
    
    # Auto-fix missing headers which git apply requires
    if not diff.startswith("diff --git"):
        header = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        lines = diff.split("\n")
        start_idx = 0
        for i, line in enumerate(lines[:5]):
            if line.startswith("@@"):
                start_idx = i
                break
        diff = header + "\n".join(lines[start_idx:])
    
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            ["git", "apply", "--recount", "--unidiff-zero", "--ignore-whitespace", "--ignore-space-change", "--whitespace=nowarn", "-"],
            input=diff.encode(),
            capture_output=True,
            cwd=ws,
            timeout=30,
        )
        if proc.returncode != 0:
            # Fallback 1: try with patch command
            try:
                proc2 = await asyncio.to_thread(
                    subprocess.run,
                    ["patch", "-p1", "--no-backup-if-mismatch"],
                    input=diff.encode(),
                    capture_output=True,
                    cwd=ws,
                    timeout=30,
                )
                if proc2.returncode == 0:
                    return {"status": "ok", "path": path}
            except Exception:
                pass
            
            # Fallback 2: Pure Python fuzzy patcher (very forgiving of LLM diffs)
            try:
                with open(full, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Split content and hunks using universal newlines
                hunks = diff.split("@@ -")
                if len(hunks) < 2:
                    raise ValueError("No valid hunks found in diff")
                
                patched_content = content
                for hunk_str in hunks[1:]:
                    hunk_lines = ("@@ -" + hunk_str).splitlines()
                    old_lines = []
                    new_lines = []
                    
                    for line in hunk_lines[1:]:
                        if line.startswith("-"):
                            old_lines.append(line[1:])
                        elif line.startswith("+"):
                            new_lines.append(line[1:])
                        elif line.startswith(" "):
                            old_lines.append(line[1:])
                            new_lines.append(line[1:])
                        elif line == "":
                            old_lines.append("")
                            new_lines.append("")
                            
                    old_text = "\n".join(old_lines)
                    new_text = "\n".join(new_lines)
                    
                    # Try exact block replace first
                    if old_text in patched_content:
                        patched_content = patched_content.replace(old_text, new_text, 1)
                    else:
                        # Try ignoring all whitespace
                        import re
                        def strip_ws(t): return re.sub(r'\\s+', '', t)
                        old_ws_stripped = strip_ws(old_text)
                        
                        # Find matching substring in patched_content matching the stripped old_text
                        curr_ws_stripped = ""
                        char_map = []
                        for i, char in enumerate(patched_content):
                            if not char.isspace():
                                curr_ws_stripped += char
                                char_map.append(i)
                                
                        idx = curr_ws_stripped.find(old_ws_stripped)
                        if idx != -1:
                            start_pos = char_map[idx]
                            end_pos = char_map[idx + len(old_ws_stripped) - 1] + 1
                            patched_content = patched_content[:start_pos] + new_text + patched_content[end_pos:]
                        else:
                            return {
                                "error": f"git apply failed and Python fallback could not locate hunk:\\n{old_text}",
                            }
                
                with open(full, "w", encoding="utf-8", newline="\n") as f:
                    f.write(patched_content)
                return {"status": "ok", "path": path, "note": "Applied via Python fallback"}
            except Exception as e:
                return {
                    "error": f"git apply failed and Python fallback crashed: {str(e)}\\nGit error: {proc.stderr.decode().strip()}",
                }
    except FileNotFoundError:
        return {"error": "'git' command not found on system"}
    except subprocess.TimeoutExpired:
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
    full = _resolve_safe_path(path, tool_context, workspace)
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
    src = _resolve_safe_path(source, tool_context, workspace)
    dst = _resolve_safe_path(destination, tool_context, workspace)

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
    _resolve_safe_path(path, tool_context, workspace)  # validate path stays inside workspace
    ws = workspace or get_workspace(tool_context)

    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            ["git", "checkout", "--", path],
            capture_output=True,
            cwd=ws,
            timeout=30,
        )
        if proc.returncode != 0:
            return {"error": f"git checkout failed: {proc.stderr.decode().strip()}"}
    except FileNotFoundError:
        return {"error": "git not found on system"}
    except subprocess.TimeoutExpired:
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
    ws = workspace or get_workspace(tool_context)

    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            ["git", "reset", "--hard", "HEAD"],
            capture_output=True,
            cwd=ws,
            timeout=30,
        )
        if proc.returncode != 0:
            return {"error": f"git reset failed: {proc.stderr.decode().strip()}"}
    except FileNotFoundError:
        return {"error": "git not found on system"}
    except subprocess.TimeoutExpired:
        return {"error": "git reset timed out"}

    return {"status": "ok", "message": "Workspace reset to HEAD"}
