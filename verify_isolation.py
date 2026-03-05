import asyncio
import os
import shutil
from types import SimpleNamespace
from tools.file_tools import write_file, list_files
from utils.workspace_utils import get_workspace

async def verify_isolation():
    print("=== Verifying Workspace Isolation ===")
    
    # 1. Setup mock contexts for two different sessions
    ctx1 = SimpleNamespace(session_id="test_session_1", state={})
    ctx2 = SimpleNamespace(session_id="test_session_2", state={})
    
    # 2. Resolve workspaces
    ws1 = get_workspace(ctx1)
    ws2 = get_workspace(ctx2)
    
    print(f"Session 1 Workspace: {ws1}")
    print(f"Session 2 Workspace: {ws2}")
    
    if ws1 == ws2:
        print("FAILED: Workspaces are not isolated!")
        return
    
    if "session_test_session_1" not in ws1:
        print(f"FAILED: Workspace path {ws1} does not contain session ID")
        return

    # 3. Write files safely to each isolated workspace
    await write_file("test.txt", "Content for session 1", tool_context=ctx1)
    await write_file("test.txt", "Content for session 2", tool_context=ctx2)
    
    # 4. Verify cross-isolation
    print("\nVerifying file isolation...")
    
    # Session 1 should only see its own version
    res1 = await list_files(".", tool_context=ctx1)
    print(f"Session 1 files: {res1.get('files')}")
    
    with open(os.path.join(ws1, "test.txt"), "r") as f:
        c1 = f.read()
    with open(os.path.join(ws2, "test.txt"), "r") as f:
        c2 = f.read()
        
    print(f"Session 1 File Content: '{c1}'")
    print(f"Session 2 File Content: '{c2}'")
    
    if c1 != "Content for session 1" or c2 != "Content for session 2":
        print("FAILED: File contents are mixed or incorrect!")
    else:
        print("\nSUCCESS: Workspaces are isolated and independent.")

    # Cleanup
    # shutil.rmtree(os.path.dirname(ws1)) # Cleanup the 'workspaces' dir if desired

if __name__ == "__main__":
    asyncio.run(verify_isolation())
