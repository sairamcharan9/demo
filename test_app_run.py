import asyncio
from google.adk.runners import InMemoryRunner
from agent.app import app

async def test_run():
    # Use the app directly with a Runner
    runner = InMemoryRunner(app=app)
    
    print(" === Running Forge via ADKApp === ")
    # run_debug is available in ADK v1.18+
    try:
        async for event in runner.run_async(
            user_id="test-user",
            session_id="test-app-session",
            new_message="Hello Forge! Please just reply with 'Ready' if you can see this."
        ):
            if hasattr(event, "content") and event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        print(f"Agent: {part.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_run())
