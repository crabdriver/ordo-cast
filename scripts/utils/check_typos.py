import os
import glob
import json
import time
from typing import List, Dict

try:
    from openai import OpenAI
except ImportError:
    print("请先安装 openai 库: pip install openai")
    exit(1)

# Resolve workspace root dynamically (parent of scripts/)
script_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.dirname(os.path.dirname(script_dir))

def load_env(env_path: str):
    """Simple parser to load .env file into os.environ without third-party dependencies."""
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    parts = line.split('=', 1)
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = parts[1].strip().strip('"').strip("'")
                        # Only set if not already set in environment
                        if key not in os.environ:
                            os.environ[key] = val

# Load workspace .env if available
load_env(os.path.join(workspace_root, ".env"))

# 配置大模型 API (从环境变量读取，或回退到默认设置)
API_KEY = os.getenv("TYPO_API_KEY") or os.getenv("CONTENT_LLM_API_KEY") or "your_api_key_here"
BASE_URL = os.getenv("TYPO_BASE_URL") or os.getenv("CONTENT_LLM_BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3"
MODEL = os.getenv("TYPO_MODEL") or os.getenv("CONTENT_LLM_MODEL") or "your_model_endpoint"

PROMPT_TEMPLATE = """
你是一个专业的中文文字校对专家。请检查以下 Markdown 文本中的错别字、语病和标点符号错误。
注意：文本中包含大量的“玄学”、“高维认知”、“商业投资”等垂直领域词汇（如：能量黑洞、因果业力、同频共振等），请不要将这些专业词汇误判为错别人。
仅仅挑出真正的拼写错误（例如 “底层罗辑” 应为 “底层逻辑”）。

请以 JSON 格式返回发现的错误，如果没有发现错别字，返回空的 JSON 数组 []。
返回格式要求：
[
    {
        "original": "错误的词或句子",
        "correction": "正确的词或句子",
        "reason": "修改原因"
    }
]

待检查文本：
{text}
"""

def check_text_for_typos(client: OpenAI, text: str) -> List[Dict]:
    if not text.strip():
        return []
    
    # Check if API Key is placeholder
    if API_KEY == "your_api_key_here" or not API_KEY:
        print("警告: 未检测到有效的 API_KEY，请在 .env 中配置 CONTENT_LLM_API_KEY 或 TYPO_API_KEY。")
        return []

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "你是一个严格且精准的文字校对工具，只输出要求的JSON格式。"},
                {"role": "user", "content": PROMPT_TEMPLATE.replace("{text}", text)}
            ],
            temperature=0.1,
            response_format={"type": "json_object"} if "deepseek" in MODEL.lower() else None
        )
        result_str = response.choices[0].message.content
        
        # 尝试解析 JSON
        # 清理可能存在的 markdown 标记
        if result_str.startswith("```json"):
            result_str = result_str[7:-3]
        elif result_str.startswith("```"):
            result_str = result_str[3:-3]
            
        return json.loads(result_str)
    except Exception as e:
        print(f"API 请求或解析失败: {e}")
        return []

def main():
    workspace_dir = os.path.join(workspace_root, "拆解后文章")
    if not os.path.exists(workspace_dir):
        print(f"错误: 拆解后文章的目录不存在于 {workspace_dir}。请先运行拆稿脚本。")
        return
        
    md_files = glob.glob(os.path.join(workspace_dir, "*.md"))
    
    print(f"找到 {len(md_files)} 个 Markdown 文件，开始进行错别字检查...")
    
    if not md_files:
        print("没有找到待校对的 .md 文件。")
        return
        
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    report_lines = ["# 错别字检测报告\n"]
    
    for file_path in md_files:
        filename = os.path.basename(file_path)
        print(f"正在检查: {filename}...")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 简单分段以避免超出 Token 限制（如果文章很长）
        # 这里为了简单，假设文章都在较合理的长度（如2000字以内），直接发送
        typos = check_text_for_typos(client, content)
        
        if typos:
            report_lines.append(f"## {filename}\n")
            for typo in typos:
                report_lines.append(f"- **原文本**：`{typo.get('original', '')}`")
                report_lines.append(f"  **修改为**：`{typo.get('correction', '')}`")
                report_lines.append(f"  **原因**：{typo.get('reason', '')}\n")
            print(f"  -> 发现 {len(typos)} 处错别字！")
        else:
            print("  -> 未发现错别字。")
            
        # 避免 API 频率限制
        time.sleep(1)
        
    report_path = os.path.join(workspace_root, "typos_report.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(report_lines))
        
    print(f"\n检查完成！报告已保存至: {report_path}")

if __name__ == "__main__":
    main()
