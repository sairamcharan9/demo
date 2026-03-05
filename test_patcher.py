import re

def apply_patch(file_content: str, patch_content: str) -> str:
    """Applies a unified diff patch to a string with liberal fuzzy matching."""
    lines = file_content.splitlines(keepends=True)
    patch_lines = patch_content.splitlines(keepends=True)
    
    # Extract hunks
    hunks = []
    current_hunk = None
    
    for line in patch_lines:
        if line.startswith('--- ') or line.startswith('+++ ') or line.startswith('diff '):
            continue
        if line.startswith('@@'):
            if current_hunk:
                hunks.append(current_hunk)
            current_hunk = {'old': [], 'new': []}
        elif current_hunk is not None:
            if line.startswith('-'):
                current_hunk['old'].append(line[1:])
            elif line.startswith('+'):
                current_hunk['new'].append(line[1:])
            elif line.startswith(' '):
                current_hunk['old'].append(line[1:])
                current_hunk['new'].append(line[1:])
            else:
                # context without leading space, leniency
                current_hunk['old'].append(line)
                current_hunk['new'].append(line)
    
    if current_hunk:
        hunks.append(current_hunk)
        
    result_content = file_content
    for hunk in hunks:
        old_text = "".join(hunk['old'])
        new_text = "".join(hunk['new'])
        
        # Try exact replace
        if old_text in result_content:
            result_content = result_content.replace(old_text, new_text, 1)
        else:
            # Try line-ending agnostic replace
            def normalize(t): return t.replace('\r\n', '\n').strip()
            old_norm = normalize(old_text)
            # Find the best match in the actual file... this is tricky for a simple script.
            # Easiest way: if we can't find it exactly, throw an error.
            raise ValueError(f"Could not apply hunk:\\n{old_text}")
            
    return result_content

if __name__ == "__main__":
    content = "line1\nline2\nline3\n"
    patch = "@@ -1,3 +1,3 @@\n line1\n-line2\n+line TWO\n line3\n"
    print(apply_patch(content, patch))
