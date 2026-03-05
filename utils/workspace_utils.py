import os
import logging

logger = logging.getLogger(__name__)

def get_workspace(tool_context=None) -> str:
    """Resolve the workspace path for the current session.
    
    Returns the current working directory (os.getcwd()) for local development,
    allowing the agent to operate directly in the project root.
    In PRODUCTION, respects the WORKSPACE_ROOT environment variable.
    """
    # Environment flag to disable local behavior in production
    if os.environ.get("PRODUCTION", "false").lower() == "true":
        return os.environ.get("WORKSPACE_ROOT", "/workspace")

    # Use a standard 'workspace' folder inside the current directory
    ws_path = os.path.join(os.getcwd(), "workspace")
    if not os.path.exists(ws_path):
        os.makedirs(ws_path, exist_ok=True)
    return ws_path
