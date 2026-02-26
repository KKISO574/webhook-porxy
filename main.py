from fastapi import FastAPI, Request, HTTPException
import requests
import os
from dotenv import load_dotenv
import logging
from datetime import datetime

# 日志配置（输出到终端，便于本地测试）
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

def timestamp_to_str(ts: int) -> str:
    """将毫秒或秒时间戳转换为可读格式"""
    if ts > 1e12:  # 毫秒时间戳
        ts //= 1000
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "未知时间"

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
        ts = payload.get("timestamp", 0)
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
            # CS2 更新公告
            summary_text = data.get("summary", {}).get("text", "").strip()
            detail_text = data.get("detail", {}).get("text", "").strip()[:800]  # 限制长度

            paged_info = ""
            paged = data.get("paged", {})
            if paged.get("pages"):
                first_page = paged["pages"][0]
                page_title = first_page.get("moduleTitle", "模块")
                page_text = first_page.get("text", "").strip()
                paged_info = (
                    f"**第一页 - {page_title}**\n"
                    f"{page_text.replace('\n', '\n  ')}"  # 强制缩进
                )

            # 规范 Markdown 语法
            content = (
                f"**{title}**\n\n"
                f"**时间**：{time_str}\n\n"
                f"**总结**\n"
                f"{summary_text.replace('\n', '\n  ')}\n\n"  # 列表缩进
                f"{paged_info}\n\n"
                f"**详情预览**\n"
                f"{detail_text.replace('\n', '\n  ')}...\n\n"
                f"[查看完整公告]({url})"
            )

            # 如果内容太长，降级为纯文本
            if len(content.encode('utf-8')) > 3800:
                msgtype = "text"
                content = (
                    f"{title}\n"
                    f"时间：{time_str}\n\n"
                    f"{summary_text[:1000]}...\n\n"
                    f"[查看详情]({url})"
                )

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

        # 调试：打印最终发送的内容
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