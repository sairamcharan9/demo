from google.adk.apps import App, ResumabilityConfig
from agent.agent import create_agent

# Create the root agent
# This uses the same configuration as our worker
root_agent = create_agent()

# Wrap it in an App
# This allows 'adk web' to find it and simplifies state management
app = App(
    name="forge",
    root_agent=root_agent,
    resumability_config=ResumabilityConfig(is_resumable=True),
)
