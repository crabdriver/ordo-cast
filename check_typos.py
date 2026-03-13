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

# 配置你的大模型 API (建议使用 DeepSeek 或 火山引擎的通义/豆包等，成本低且准确)
API_KEY = "your_api_key_here"  # 替换为你的火山引擎或 DeepSeek API Key
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"  # 替换为你的 Base URL (例如火山引擎)
MODEL = "your_model_endpoint"  # 替换为你的模型名 (例如 ep-xxx)

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

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

def check_text_for_typos(text: str) -> List[Dict]:
    if not text.strip():
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
    workspace_dir = r"d:\tiandiworkspace\拆解后文章"
    md_files = glob.glob(os.path.join(workspace_dir, "*.md"))
    
    print(f"找到 {len(md_files)} 个 Markdown 文件，开始进行错别字检查...")
    
    report_lines = ["# 错别字检测报告\n"]
    
    for file_path in md_files:
        filename = os.path.basename(file_path)
        print(f"正在检查: {filename}...")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 简单分段以避免超出 Token 限制（如果文章很长）
        # 这里为了简单，假设文章都在较合理的长度（如2000字以内），直接发送
        typos = check_text_for_typos(content)
        
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
        
    report_path = os.path.join(r"d:\tiandiworkspace", "typos_report.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(report_lines))
        
    print(f"\n检查完成！报告已保存至: {report_path}")

if __name__ == "__main__":
    main()
