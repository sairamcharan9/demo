import os
import logging

logger = logging.getLogger(__name__)

def get_workspace(tool_context=None) -> str:
    """Resolve the workspace path for the current session.
    
    In PRODUCTION, respects the WORKSPACE_ROOT environment variable.
    In local development, returns a unique sub-directory per session under 'workspaces/'
    relative to the current working directory.
    """
    # Environment flag to disable local behavior in production
    if os.environ.get("PRODUCTION", "false").lower() == "true":
        return os.environ.get("WORKSPACE_ROOT", "/workspace")

    # Attempt to get session_id from tool_context
    session_id = None
    if tool_context:
        session_id = getattr(tool_context, "session_id", None)
        if not session_id and hasattr(tool_context, "state"):
            session_id = tool_context.state.get("session_id")

    if not session_id:
        # Fallback to a plain 'workspace' folder if no session context provided
        ws_path = os.path.join(os.getcwd(), "workspace")
    else:
        # Calculate isolated path under 'workspaces/' directory relative to project root
        ws_path = os.path.join(os.getcwd(), "workspaces", f"session_{session_id}")
    
    # Ensure it exists
    if not os.path.exists(ws_path):
        os.makedirs(ws_path, exist_ok=True)
        
    return ws_path

def get_project_id(repo_url: str | None) -> str:
    """Generate a safe project identifier from a repo URL."""
    if not repo_url:
        return "default"
    
    # Strip protocol and .git
    clean = repo_url.replace("https://", "").replace("http://", "").replace(".git", "")
    # Keep only alphanumeric and common separators, then replace with -
    import re
    safe = re.sub(r'[^a-zA-Z0-9]', '-', clean)
    # Remove duplicates and trailing dashes
    safe = re.sub(r'-+', '-', safe).strip("-")
    
    return safe
