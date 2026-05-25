import os
import re

# Resolve workspace root dynamically (parent of scripts/)
script_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.dirname(os.path.dirname(script_dir))

inp = os.path.join(workspace_root, "all_articles_concat.txt")
out_dir = os.path.join(workspace_root, "拆解后文章")

if not os.path.exists(out_dir):
    os.makedirs(out_dir)

current_file = None
current_content = []

if not os.path.exists(inp):
    print(f"Error: Input file not found at {inp}")
    exit(1)

with open(inp, "r", encoding="utf-8") as f:
    for line in f:
        # Check for new file header
        m = re.match(r"^===\s*FILE:\s*(.+?)\s*===$", line.strip())
        if m:
            # Save previous file if exists
            if current_file:
                with open(os.path.join(out_dir, current_file), "w", encoding="utf-8") as out_f:
                    out_f.write("\n".join(current_content))
            
            current_file = m.group(1).strip()
            current_content = []
            continue
        
        if current_file:
            # Remove [number] prefix
            # Example: "[1] # 满级..." -> "# 满级..."
            # "[123]   " -> ""
            clean_line = re.sub(r"^\[\d+\]\s?", "", line.rstrip("\n"))
            current_content.append(clean_line)

# Save the last file
if current_file:
    with open(os.path.join(out_dir, current_file), "w", encoding="utf-8") as out_f:
        out_f.write("\n".join(current_content))

print(f"Extraction complete! Files saved to {out_dir}/")
