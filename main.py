from fastapi import FastAPI, Request, HTTPException
import requests
import os
from dotenv import load_dotenv
import logging
from datetime import datetime
import re

# 日志配置（输出到终端，便于本地测试和调试）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()

app = FastAPI(title="Webhook → 企业微信转发服务")

# 从环境变量读取 webhook 地址（不硬编码）
WECHAT_WEBHOOK_URL = os.getenv("WECHAT_WEBHOOK_URL")
if not WECHAT_WEBHOOK_URL:
    raise ValueError("缺少环境变量 WECHAT_WEBHOOK_URL，请在 .env 文件中设置")


def env_flag(name: str, default: bool = True) -> bool:
    """读取布尔环境变量。"""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SHOW_CSLOG_SUMMARY = env_flag("SHOW_CSLOG_SUMMARY", True)
SHOW_CSLOG_PAGED = env_flag("SHOW_CSLOG_PAGED", True)
SHOW_CSLOG_DETAIL = env_flag("SHOW_CSLOG_DETAIL", True)

def timestamp_to_str(ts: int) -> str:
    """将毫秒或秒时间戳转换为可读格式"""
    if ts > 1e12:  # 毫秒时间戳
        ts //= 1000
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "未知时间"


def clean_markdown_text(text: str) -> str:
    """清理上游 Markdown，尽量保留可读性并兼容企业微信。"""
    if not text:
        return ""

    cleaned_lines = []
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue

        # 去掉标题井号，避免多层 Markdown 在企业微信里显示怪异
        line = re.sub(r"^#{1,6}\s*", "", line)
        # 统一列表符号，减少花样符号导致的视觉噪音
        line = re.sub(r"^[*-]\s+", "• ", line)
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def remove_redundant_heading(text: str, heading: str) -> str:
    """移除内容里与外层模块同名的首行标题，避免重复展示。"""
    cleaned = clean_markdown_text(text)
    if not cleaned:
        return ""

    lines = cleaned.split("\n")
    first_line = lines[0].strip(" :：")
    if first_line == heading.strip(" :："):
        return "\n".join(lines[1:]).strip()
    return cleaned


def indent_multiline(text: str) -> str:
    """为多行内容增加缩进，让企业微信 markdown 更易读。"""
    cleaned = clean_markdown_text(text)
    if not cleaned:
        return "暂无内容"
    return "\n".join(f"> {line}" if line else ">" for line in cleaned.split("\n"))


def truncate_utf8(text: str, max_bytes: int) -> str:
    """按 UTF-8 字节长度截断，避免企业微信 markdown 超限。"""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    truncated = encoded[:max_bytes]
    while True:
        try:
            return truncated.decode("utf-8").rstrip() + "\n> ...内容已截断"
        except UnicodeDecodeError:
            truncated = truncated[:-1]


def resolve_cslog_sections(data: dict) -> dict[str, bool]:
    """根据环境变量和 payload.viewTypes 决定输出哪些模块。"""
    requested_types = {
        str(item).strip().lower()
        for item in (data.get("viewTypes") or [])
        if str(item).strip()
    }

    has_request_filter = bool(requested_types)
    return {
        "summary": SHOW_CSLOG_SUMMARY and (not has_request_filter or "summary" in requested_types),
        "paged": SHOW_CSLOG_PAGED and (not has_request_filter or "paged" in requested_types),
        "detail": SHOW_CSLOG_DETAIL and (not has_request_filter or "detail" in requested_types),
    }


def build_cslog_content(title: str, url: str, time_str: str, data: dict) -> tuple[str, str]:
    """构造更适合企业微信阅读的 CSLog 消息。"""
    summary_text = remove_redundant_heading(data.get("summary", {}).get("text", "").strip(), "总结")
    detail_text = remove_redundant_heading(data.get("detail", {}).get("text", "").strip(), "详情")
    enabled_sections = resolve_cslog_sections(data)

    paged = data.get("paged", {})
    pages = paged.get("pages", []) or []
    page_blocks = []
    for page in pages:
        page_index = page.get("pageIndex", "?")
        page_count = page.get("pageCount") or paged.get("pageCount") or len(pages) or "?"
        module_title = page.get("moduleTitle", "未命名模块")
        module_text = indent_multiline(remove_redundant_heading(page.get("text", ""), module_title))
        page_blocks.append(
            f"**模块 {page_index}/{page_count} · {module_title}**\n"
            f"{module_text}"
        )

    paged_text = "\n\n".join(page_blocks) if page_blocks else "暂无模块内容"

    markdown_sections = [
        f"**{title}**\n\n"
        f"**时间**：{time_str}\n"
        f"**来源**：FKBUFF CSLog"
    ]
    text_sections = [
        f"{title}\n"
        f"时间：{time_str}\n"
        f"来源：FKBUFF CSLog"
    ]

    if enabled_sections["summary"]:
        markdown_sections.append(f"**总结**\n{indent_multiline(summary_text)}")
        text_sections.append(f"【总结】\n{clean_markdown_text(summary_text) or '暂无内容'}")

    if enabled_sections["paged"]:
        markdown_sections.append(f"**详细模块**\n{paged_text}")
        text_sections.append(f"【详细模块】\n{clean_markdown_text(chr(10).join(page_blocks)) or '暂无内容'}")

    if enabled_sections["detail"]:
        markdown_sections.append(f"**详细**\n{indent_multiline(detail_text)}")
        text_sections.append(f"【详细】\n{clean_markdown_text(detail_text) or '暂无内容'}")

    if not any(enabled_sections.values()):
        markdown_sections.append("> 当前未启用任何 cslog 模块")
        text_sections.append("【提示】\n当前未启用任何 cslog 模块")

    markdown_sections.append(f"[查看原文]({url})")
    text_sections.append(f"查看原文：{url}")

    markdown_content = "\n\n".join(markdown_sections)

    if len(markdown_content.encode("utf-8")) <= 3800:
        return "markdown", markdown_content

    text_content = "\n\n".join(text_sections)
    return "text", truncate_utf8(text_content, 3800)

@app.post("/webhook/incoming")
async def receive_and_forward(request: Request):
    try:
        payload = await request.json()
        logger.info(f"收到上游 webhook 数据: {payload}")

        msg_type = payload.get("type")
        title = payload.get("title", "无标题")
        text = payload.get("text", "").strip()
        url = payload.get("url", "")
        data = payload.get("data", {})
        ts = payload.get("timestamp") or data.get("publishedAt", 0)
        time_str = timestamp_to_str(ts)

        content = ""
        msgtype = "markdown"  # 优先使用 markdown

        if msg_type == "message":
            # 饰品消息通知
            goods = data.get("goodsInfo", {})
            goods_name = goods.get("goodsName", "未知饰品")
            content = (
                f"**{title}**\n\n"
                f"**饰品**：{goods_name}\n"
                f"**消息**：{text}\n\n"
                f"**时间**：{time_str}\n"
                f"[查看详情]({url})"
            )

        elif msg_type == "cslog":
            # CS2 更新公告：完整输出总结、模块详情、全文详情
            msgtype, content = build_cslog_content(title, url, time_str, data)

        else:
            # 未知类型
            msgtype = "text"
            content = (
                f"收到未知类型消息：{msg_type}\n"
                f"标题：{title}\n"
                f"内容：{text[:1500]}...\n"
                f"链接：{url}"
            )

        # 构建企业微信 payload
        wechat_payload = {"msgtype": msgtype}

        if msgtype == "markdown":
            wechat_payload["markdown"] = {"content": content}
        else:
            wechat_payload["text"] = {
                "content": content,
                "mentioned_list": ["@all"]  # 可改为 [] 或具体用户名
                # "mentioned_mobile_list": ["138xxxxxxxx"]
            }

        # 调试：打印最终发送的内容（方便排查格式问题）
        logger.info(
            f"即将发送到企业微信（类型: {msgtype}，长度: {len(content.encode('utf-8'))} 字节）:\n"
            f"{content}\n"
            f"{'-' * 60}"
        )

        # 发送请求
        resp = requests.post(
            WECHAT_WEBHOOK_URL,
            json=wechat_payload,
            timeout=10
        )
        resp.raise_for_status()

        wechat_resp = resp.json()
        if wechat_resp.get("errcode") != 0:
            logger.error(f"企业微信返回错误: {wechat_resp}")
            raise HTTPException(status_code=500, detail=f"企业微信发送失败: {wechat_resp}")

        logger.info("成功转发到企业微信群")
        return {"status": "success", "detail": "已推送"}

    except Exception as e:
        logger.error(f"处理过程中发生错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/health")
def health():
    return {"status": "ok", "message": "服务正常运行"}
