import os
import logging

logger = logging.getLogger(__name__)

# Default root for local development fallbacks
DEFAULT_WORKSPACE_BASE = os.getcwd()

def get_workspace(tool_context=None) -> str:
    """Resolve the workspace path for the current session.
    
    In PRODUCTION, always returns the standard /workspace.
    In local development, returns a unique sub-directory per session under 'workspaces/'.
    """
    # Environment flag to disable isolation (e.g., in Docker/VM production)
    if os.environ.get("PRODUCTION", "false").lower() == "true":
        return os.environ.get("WORKSPACE_ROOT", "/workspace")

    # Attempt to get session_id from tool_context
    session_id = None
    if tool_context:
        session_id = getattr(tool_context, "session_id", None)
        if not session_id and hasattr(tool_context, "state"):
            session_id = tool_context.state.get("session_id")

    if not session_id:
        # Fallback to local 'workspace' folder if no session context provided
        return os.path.join(DEFAULT_WORKSPACE_BASE, "workspace")

    # Calculate isolated path under 'workspaces/' directory
    base_dir = os.path.join(DEFAULT_WORKSPACE_BASE, "workspaces")
    isolated_path = os.path.join(base_dir, f"session_{session_id}")
    
    # Ensure it exists
    if not os.path.exists(isolated_path):
        os.makedirs(isolated_path, exist_ok=True)
        
    return isolated_path
