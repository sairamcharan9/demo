import os
import aiofiles
from google.adk.tools import ToolContext

async def start_live_preview_instructions(tool_context: ToolContext = None) -> dict:
    """Provides instructions for starting a live preview server.
    
    Returns standard instructions dynamically depending on the detected framework.
    """
    return {
        "status": "ok",
        "instructions": (
            "To start a live preview server, use the appropriate command for your framework:\n"
            "- React/Vite: `npm run dev`\n"
            "- Node.js/Express: `node server.js` or `npm start`\n"
            "- Python/Flask: `flask run`\n"
            "- Python/Django: `python manage.py runserver`\n"
            "Run these commands using the `run_in_bash_session` tool to persist the sever."
        )
    }

async def call_hello_world_agent(tool_context: ToolContext = None) -> dict:
    """Calls a test sub-agent and returns its response.
    
    This is a stub tool used for testing sub-agent invocation capabilities.
    """
    return {
        "status": "ok",
        "response": "Hello World from the sub-agent!",
        "agent_name": "hello_world_agent"
    }
