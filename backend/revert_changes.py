import json
import os

log_path = r"C:\Users\Anurag Lawaniya\.gemini\antigravity-ide\brain\f0823c21-f72e-43e7-aa9f-4edb6b17b0f2\.system_generated\logs\transcript.jsonl"
file_path = r"d:\Langgraph\backend\chatbot_graph.py"

# Read all edits on chatbot_graph.py in chronological order
edits = []
with open(log_path, "r", encoding="utf-8") as f:
    for line in f:
        try:
            data = json.loads(line)
            # Check tool_calls in model response or system output
            tool_calls = data.get("tool_calls", [])
            for tc in tool_calls:
                name = tc.get("name")
                args = tc.get("args", {})
                target_file = args.get("TargetFile", "")
                if name in ("replace_file_content", "multi_replace_file_content") and "chatbot_graph.py" in target_file:
                    edits.append((name, args))
        except Exception:
            pass

print(f"Found {len(edits)} edits on chatbot_graph.py.")

# We will read the current chatbot_graph.py
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Apply edits in reverse order to undo them
for name, args in reversed(edits):
    print(f"Undoing edit: {args.get('Description') or args.get('Instruction')}")
    if name == "replace_file_content":
        target = args.get("TargetContent")
        replacement = args.get("ReplacementContent")
        # To undo, we replace 'replacement' with 'target'
        if replacement in content:
            content = content.replace(replacement, target, 1)
            print("Successfully reverted single replace.")
        else:
            # Try with clean strings (stripping quotes if any)
            if replacement.startswith('"') and replacement.endswith('"'):
                r_clean = json.loads(replacement)
                t_clean = json.loads(target)
                if r_clean in content:
                    content = content.replace(r_clean, t_clean, 1)
                    print("Successfully reverted single replace (JSON decoded).")
                else:
                    print("WARNING: ReplacementContent not found in file content.")
            else:
                print("WARNING: ReplacementContent not found in file content.")
    elif name == "multi_replace_file_content":
        chunks = args.get("ReplacementChunks")
        if isinstance(chunks, str):
            chunks = json.loads(chunks)
        # Revert chunks in reverse order
        for chunk in reversed(chunks):
            target = chunk.get("TargetContent")
            replacement = chunk.get("ReplacementContent")
            if replacement in content:
                content = content.replace(replacement, target, 1)
                print("Successfully reverted multi-replace chunk.")
            else:
                print("WARNING: Chunk replacement not found in file content.")

# Write reverted content back
with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Rollback complete.")
