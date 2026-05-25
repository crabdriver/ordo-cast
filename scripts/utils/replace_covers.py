import os
import glob

script_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.dirname(os.path.dirname(script_dir))

directory = os.path.join(workspace_root, "拆解后文章")
covers_dir = os.path.join(workspace_root, "covers")

if not os.path.exists(directory):
    print(f"Error: Articles directory not found at {directory}")
    exit(1)

files = sorted(glob.glob(os.path.join(directory, "*.md")))

for i, filepath in enumerate(files):
    cover_index = (i % 14) + 1
    cover_name = f"cover_{cover_index:02d}.png"
    # Note: the cover markdown link references ../covers/cover_xx.png relative to the article MD
    cover_markdown = f"![封面图](../covers/{cover_name})\n\n"
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    if content.startswith("!["):
        first_line_end = content.find('\n')
        content = cover_markdown.strip() + content[first_line_end:]
    else:
        content = cover_markdown + content
        
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

print(f"Processed {len(files)} files.")
