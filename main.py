from fastapi import FastAPI, Request, HTTPException
import requests
import os
from dotenv import load_dotenv
import logging
from datetime import datetime
import json
from dataclasses import dataclass
from pathlib import Path
import re
import threading
import time
from typing import Any

try:
    import fcntl
except ImportError:
    fcntl = None

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


CSQAQ_API_BASE = os.getenv("CSQAQ_API_BASE", "https://api.csqaq.com/api/v1").rstrip("/")
CSQAQ_API_TOKEN = os.getenv("CSQAQ_API_TOKEN", "").strip()
CSQAQ_INVENTORY_STATE_FILE = os.getenv("CSQAQ_INVENTORY_STATE_FILE", "logs/csqaq_inventory_state.json")
CSQAQ_INVENTORY_SEND_INITIAL = env_flag("CSQAQ_INVENTORY_SEND_INITIAL", False)


def env_int(name: str, default: int, min_value: int | None = None) -> int:
    """读取整数环境变量，异常时回退默认值。"""
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError:
        logger.warning("环境变量 %s=%r 不是整数，使用默认值 %s", name, value, default)
        return default
    if min_value is not None and parsed < min_value:
        logger.warning("环境变量 %s=%r 小于最小值 %s，使用默认值 %s", name, value, min_value, default)
        return default
    return parsed


CSQAQ_INVENTORY_INTERVAL_SECONDS = env_int("CSQAQ_INVENTORY_INTERVAL_SECONDS", 300, 30)
CSQAQ_INVENTORY_PAGE_SIZE = env_int("CSQAQ_INVENTORY_PAGE_SIZE", 50, 1)
CSQAQ_INVENTORY_MAX_PAGES = env_int("CSQAQ_INVENTORY_MAX_PAGES", 1, 1)
CSQAQ_INVENTORY_BATCH_SIZE = env_int("CSQAQ_INVENTORY_BATCH_SIZE", 10, 1)
CSQAQ_INVENTORY_TIMEOUT_SECONDS = env_int("CSQAQ_INVENTORY_TIMEOUT_SECONDS", 15, 1)
CSQAQ_INVENTORY_SEEN_LIMIT = env_int("CSQAQ_INVENTORY_SEEN_LIMIT", 1000, 50)
WECHAT_MARKDOWN_MAX_BYTES = env_int("WECHAT_MARKDOWN_MAX_BYTES", 3800, 500)


def load_inventory_type_labels() -> dict[str, str]:
    custom_labels = os.getenv("CSQAQ_INVENTORY_TYPE_LABELS", "").strip()
    if not custom_labels:
        return {}
    try:
        parsed = json.loads(custom_labels)
    except json.JSONDecodeError:
        logger.warning("CSQAQ_INVENTORY_TYPE_LABELS 不是合法 JSON 对象，使用默认类型展示")
        return {}
    if not isinstance(parsed, dict):
        logger.warning("CSQAQ_INVENTORY_TYPE_LABELS 不是合法 JSON 对象，使用默认类型展示")
        return {}
    return {str(key): str(value) for key, value in parsed.items()}


CSQAQ_INVENTORY_TYPE_LABELS = load_inventory_type_labels()


@dataclass(frozen=True)
class InventoryTaskConfig:
    """库存监控任务配置，字段名对齐 CSQAQ 接口 Body 参数。"""

    task_id: str
    name: str = ""
    search: str = ""
    type: str = "ALL"
    page_size: int = CSQAQ_INVENTORY_PAGE_SIZE
    max_pages: int = CSQAQ_INVENTORY_MAX_PAGES
    interval_seconds: int = CSQAQ_INVENTORY_INTERVAL_SECONDS
    batch_size: int = CSQAQ_INVENTORY_BATCH_SIZE

    @property
    def display_name(self) -> str:
        return self.name or f"任务 {self.task_id}"


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


def send_wechat_message(msgtype: str, content: str, mentioned_list: list[str] | None = None) -> dict:
    """发送企业微信机器人消息。"""
    wechat_payload = {"msgtype": msgtype}

    if msgtype == "markdown":
        wechat_payload["markdown"] = {"content": content}
    else:
        text_payload = {"content": content}
        if mentioned_list is not None:
            text_payload["mentioned_list"] = mentioned_list
        wechat_payload["text"] = text_payload

    logger.info(
        f"即将发送到企业微信（类型: {msgtype}，长度: {len(content.encode('utf-8'))} 字节）:\n"
        f"{content}\n"
        f"{'-' * 60}"
    )

    resp = requests.post(
        WECHAT_WEBHOOK_URL,
        json=wechat_payload,
        timeout=10
    )
    resp.raise_for_status()

    wechat_resp = resp.json()
    if wechat_resp.get("errcode") != 0:
        logger.error(f"企业微信返回错误: {wechat_resp}")
        raise RuntimeError(f"企业微信发送失败: {wechat_resp}")

    logger.info("成功转发到企业微信群")
    return wechat_resp


def normalize_positive_int(value: Any, default: int, min_value: int = 1) -> int:
    """把任务配置中的数值字段规范成正整数。"""
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= min_value else default


def parse_inventory_tasks() -> list[InventoryTaskConfig]:
    """读取库存监控任务配置，支持 JSON 或逗号分隔 task_id。"""
    default_search = os.getenv("CSQAQ_INVENTORY_SEARCH", "")
    default_type = os.getenv("CSQAQ_INVENTORY_TYPE", "ALL")
    tasks_json = os.getenv("CSQAQ_INVENTORY_TASKS", "").strip()
    task_ids = os.getenv("CSQAQ_INVENTORY_TASK_IDS", "").strip()

    def build_task(raw_task: Any) -> InventoryTaskConfig | None:
        if isinstance(raw_task, (int, str)):
            task_id = str(raw_task).strip()
            if not task_id:
                return None
            return InventoryTaskConfig(
                task_id=task_id,
                search=default_search,
                type=default_type,
            )

        if not isinstance(raw_task, dict):
            logger.warning("忽略不支持的 CSQAQ 库存任务配置: %r", raw_task)
            return None

        task_id = raw_task.get("task_id") or raw_task.get("taskId") or raw_task.get("id")
        task_id = str(task_id).strip() if task_id is not None else ""
        if not task_id:
            logger.warning("忽略缺少 task_id 的 CSQAQ 库存任务配置: %r", raw_task)
            return None

        return InventoryTaskConfig(
            task_id=task_id,
            name=str(raw_task.get("name") or raw_task.get("label") or "").strip(),
            search=str(raw_task.get("search", default_search) or ""),
            type=str(raw_task.get("type", default_type) or "ALL"),
            page_size=normalize_positive_int(
                raw_task.get("page_size", raw_task.get("pageSize")),
                CSQAQ_INVENTORY_PAGE_SIZE,
                1,
            ),
            max_pages=normalize_positive_int(
                raw_task.get("max_pages", raw_task.get("maxPages")),
                CSQAQ_INVENTORY_MAX_PAGES,
                1,
            ),
            interval_seconds=normalize_positive_int(
                raw_task.get("interval_seconds", raw_task.get("intervalSeconds")),
                CSQAQ_INVENTORY_INTERVAL_SECONDS,
                30,
            ),
            batch_size=normalize_positive_int(
                raw_task.get("batch_size", raw_task.get("batchSize")),
                CSQAQ_INVENTORY_BATCH_SIZE,
                1,
            ),
        )

    configured_tasks: list[InventoryTaskConfig] = []
    if tasks_json:
        try:
            raw_tasks = json.loads(tasks_json)
        except json.JSONDecodeError as exc:
            logger.error("CSQAQ_INVENTORY_TASKS 不是合法 JSON: %s", exc)
            raw_tasks = []

        if isinstance(raw_tasks, dict):
            raw_tasks = [raw_tasks]

        if isinstance(raw_tasks, list):
            for raw_task in raw_tasks:
                task = build_task(raw_task)
                if task:
                    configured_tasks.append(task)
        else:
            logger.error("CSQAQ_INVENTORY_TASKS 必须是对象或数组")

    if not configured_tasks and task_ids:
        for raw_task_id in task_ids.split(","):
            task = build_task(raw_task_id)
            if task:
                configured_tasks.append(task)

    return configured_tasks


def task_id_for_payload(task_id: str) -> int | str:
    """task_id 文档示例是数字，允许配置为字符串但尽量按数字发送。"""
    return int(task_id) if task_id.isdigit() else task_id


def inventory_trade_key(trade: dict) -> str:
    """生成库存动态去重键。"""
    key_parts = [
        trade.get("created_at", ""),
        trade.get("good_id", ""),
        trade.get("market_name", ""),
        trade.get("count", ""),
        trade.get("type", ""),
    ]
    return "|".join(str(part) for part in key_parts)


def parse_created_at(value: Any) -> datetime:
    """解析 CSQAQ created_at，失败时落到最小时间。"""
    if not value:
        return datetime.min
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.min


def describe_tradable(value: Any) -> str:
    if str(value) == "1":
        return "可交易"
    if str(value) == "0":
        return "不可交易"
    return f"未知({value})"


def describe_trade_type(value: Any) -> str:
    """把 CSQAQ 库存动态 type 转成可读文案。"""
    labels = {
        "ALL": "全部动态",
        "0": "默认库存",
        "4": "取出组件",
        "5": "cd恢复",
        "7": "卖出/存入组件",
    }
    labels.update(CSQAQ_INVENTORY_TYPE_LABELS)
    raw = str(value)
    return labels.get(raw, f"动态类型 {raw}")


def format_inventory_request_params(task: InventoryTaskConfig, page_range: str) -> str:
    search = task.search if task.search else "空"
    request_type = describe_trade_type(task.type)
    return (
        f"page_index={page_range}, page_size={task.page_size}, "
        f"task_id={task.task_id}, search={search}, type={task.type}({request_type})"
    )


def format_inventory_markdown(
    task: InventoryTaskConfig,
    trades: list[dict],
    batch_index: int,
    batch_count: int,
    total_new: int,
) -> str:
    """把库存动态转换成企业微信 markdown。"""
    page_range = "1" if task.max_pages == 1 else f"1-{task.max_pages}"
    header = [
        f"**CSQAQ 库存动态 · {task.display_name}**",
        "",
        f"**任务ID**：{task.task_id}",
        f"**请求参数**：{format_inventory_request_params(task, page_range)}",
        f"**批次**：{batch_index}/{batch_count}，本批 {len(trades)} 条 / 新动态 {total_new} 条",
        "[接口文档](https://docs.csqaq.com/api-358158458)",
        "",
    ]

    lines = []
    for index, trade in enumerate(trades, start=1):
        market_name = clean_markdown_text(str(trade.get("market_name") or "未知饰品")).replace("\n", " ")
        count = trade.get("count", "未知")
        created_at = trade.get("created_at") or "未知时间"
        good_id = trade.get("good_id", "未知")
        trade_type = describe_trade_type(trade.get("type", "未知"))
        tradable = describe_tradable(trade.get("tradable", "未知"))
        lines.append(
            f"> {index}. **{market_name}** x {count}\n"
            f"> 时间：{created_at} | 类型：{trade_type} | {tradable} | good_id：{good_id}"
        )

    content = "\n".join(header + lines)
    return truncate_utf8(content, WECHAT_MARKDOWN_MAX_BYTES)


class InventoryMonitor:
    """按配置轮询 CSQAQ 库存动态并分批推送到企业微信。"""

    def __init__(self, tasks: list[InventoryTaskConfig], token: str, state_file: str):
        self.tasks = tasks
        self.token = token
        self.state_path = Path(state_file)
        self.lock_path = self.state_path.with_suffix(f"{self.state_path.suffix}.lock")
        self.lock_file = None
        self.lock_acquired = False
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.run_lock = threading.Lock()
        self.next_run_at = {task.task_id: 0.0 for task in tasks}
        self.state = self.load_state()

    def load_state(self) -> dict:
        if not self.state_path.exists():
            return {"tasks": {}}
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("读取 CSQAQ 库存监控状态失败，将重新初始化: %s", exc)
            return {"tasks": {}}
        if not isinstance(state, dict):
            return {"tasks": {}}
        state.setdefault("tasks", {})
        return state

    def save_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.state_path.with_name(f"{self.state_path.name}.tmp")
            tmp_path.write_text(
                json.dumps(self.state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(self.state_path)
        except OSError as exc:
            logger.error("保存 CSQAQ 库存监控状态失败: %s", exc)

    def acquire_process_lock(self) -> bool:
        if fcntl is None:
            logger.warning("当前系统不支持 fcntl，CSQAQ 库存监控无法做多进程锁保护")
            return True

        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self.lock_file = self.lock_path.open("w", encoding="utf-8")
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.lock_file.write(str(os.getpid()))
            self.lock_file.flush()
            self.lock_acquired = True
            return True
        except BlockingIOError:
            logger.info("其他 worker 已启动 CSQAQ 库存监控，本 worker 不重复启动")
            return False
        except OSError as exc:
            logger.error("获取 CSQAQ 库存监控进程锁失败: %s", exc)
            return False

    def release_process_lock(self) -> None:
        if fcntl is None or not self.lock_file:
            return
        try:
            fcntl.flock(self.lock_file.fileno(), fcntl.LOCK_UN)
            self.lock_file.close()
        except OSError as exc:
            logger.warning("释放 CSQAQ 库存监控进程锁失败: %s", exc)
        finally:
            self.lock_file = None
            self.lock_acquired = False

    def task_state(self, task: InventoryTaskConfig) -> dict:
        tasks_state = self.state.setdefault("tasks", {})
        task_state = tasks_state.setdefault(task.task_id, {})
        task_state.setdefault("seen", [])
        return task_state

    def mark_seen(self, task: InventoryTaskConfig, keys: list[str]) -> None:
        task_state = self.task_state(task)
        seen = task_state.setdefault("seen", [])
        seen_set = set(seen)
        for key in keys:
            if key not in seen_set:
                seen.append(key)
                seen_set.add(key)
        if len(seen) > CSQAQ_INVENTORY_SEEN_LIMIT:
            task_state["seen"] = seen[-CSQAQ_INVENTORY_SEEN_LIMIT:]
        task_state["last_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def request_task_business(self, task: InventoryTaskConfig) -> list[dict]:
        all_trades: list[dict] = []
        headers = {
            "ApiToken": self.token,
            "Content-Type": "application/json",
        }

        for page_index in range(1, task.max_pages + 1):
            payload = {
                "page_index": page_index,
                "page_size": task.page_size,
                "task_id": task_id_for_payload(task.task_id),
                "search": task.search,
                "type": task.type,
            }
            resp = requests.post(
                f"{CSQAQ_API_BASE}/task/get_task_business",
                headers=headers,
                json=payload,
                timeout=CSQAQ_INVENTORY_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            body = resp.json()
            if str(body.get("code")) != "200":
                raise RuntimeError(f"CSQAQ 接口返回异常: {body}")

            data = body.get("data") or {}
            trades = data.get("trades") or []
            if not isinstance(trades, list):
                raise RuntimeError(f"CSQAQ 返回 trades 格式异常: {body}")

            all_trades.extend(trades)
            total = normalize_positive_int(data.get("total"), len(all_trades), 0)
            if not trades or len(all_trades) >= total:
                break

        return all_trades

    def check_task(self, task: InventoryTaskConfig) -> dict:
        trades = self.request_task_business(task)
        task_state = self.task_state(task)
        existing_seen = set(task_state.get("seen") or [])

        new_items: list[tuple[dict, str]] = []
        scanned_seen = set(existing_seen)
        for trade in trades:
            key = inventory_trade_key(trade)
            if key in scanned_seen:
                continue
            scanned_seen.add(key)
            new_items.append((trade, key))

        if not existing_seen and not CSQAQ_INVENTORY_SEND_INITIAL:
            self.mark_seen(task, [inventory_trade_key(trade) for trade in trades])
            self.save_state()
            logger.info(
                "CSQAQ 库存任务 %s 首次运行，已记录 %s 条基线动态，未推送历史内容",
                task.task_id,
                len(trades),
            )
            return {
                "task_id": task.task_id,
                "fetched": len(trades),
                "new": 0,
                "sent": 0,
                "baseline": True,
            }

        new_items.sort(key=lambda item: parse_created_at(item[0].get("created_at")))
        if not new_items:
            self.mark_seen(task, [])
            self.save_state()
            logger.info("CSQAQ 库存任务 %s 暂无新动态", task.task_id)
            return {
                "task_id": task.task_id,
                "fetched": len(trades),
                "new": 0,
                "sent": 0,
                "baseline": False,
            }

        total_new = len(new_items)
        sent_count = 0
        batch_count = (total_new + task.batch_size - 1) // task.batch_size
        for batch_index in range(batch_count):
            batch_items = new_items[
                batch_index * task.batch_size:(batch_index + 1) * task.batch_size
            ]
            batch_trades = [item[0] for item in batch_items]
            batch_keys = [item[1] for item in batch_items]
            content = format_inventory_markdown(
                task=task,
                trades=batch_trades,
                batch_index=batch_index + 1,
                batch_count=batch_count,
                total_new=total_new,
            )
            send_wechat_message("markdown", content)
            self.mark_seen(task, batch_keys)
            self.save_state()
            sent_count += len(batch_items)

        logger.info("CSQAQ 库存任务 %s 已推送 %s 条新动态", task.task_id, sent_count)
        return {
            "task_id": task.task_id,
            "fetched": len(trades),
            "new": total_new,
            "sent": sent_count,
            "baseline": False,
        }

    def run_once(self) -> list[dict]:
        results = []
        with self.run_lock:
            for task in self.tasks:
                try:
                    results.append(self.check_task(task))
                except Exception as exc:
                    logger.exception("CSQAQ 库存任务 %s 执行失败", task.task_id)
                    results.append({"task_id": task.task_id, "error": str(exc)})
        return results

    def run_loop(self) -> None:
        logger.info("CSQAQ 库存监控已启动，共 %s 个任务", len(self.tasks))
        while not self.stop_event.is_set():
            now = time.monotonic()
            for task in self.tasks:
                if self.stop_event.is_set():
                    break
                if now < self.next_run_at.get(task.task_id, 0):
                    continue

                if not self.run_lock.acquire(blocking=False):
                    logger.info("CSQAQ 库存监控正在执行，跳过本轮任务 %s", task.task_id)
                    continue
                try:
                    self.check_task(task)
                except Exception:
                    logger.exception("CSQAQ 库存任务 %s 执行失败", task.task_id)
                finally:
                    self.next_run_at[task.task_id] = time.monotonic() + task.interval_seconds
                    self.run_lock.release()

            self.stop_event.wait(1)

        logger.info("CSQAQ 库存监控已停止")

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        if not self.acquire_process_lock():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run_loop, name="csqaq-inventory-monitor", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        self.release_process_lock()

    def status(self) -> dict:
        tasks = []
        for task in self.tasks:
            task_state = self.task_state(task)
            tasks.append({
                "task_id": task.task_id,
                "name": task.name,
                "search": task.search,
                "type": task.type,
                "page_size": task.page_size,
                "max_pages": task.max_pages,
                "interval_seconds": task.interval_seconds,
                "batch_size": task.batch_size,
                "seen_count": len(task_state.get("seen") or []),
                "last_checked_at": task_state.get("last_checked_at"),
            })

        return {
            "enabled": True,
            "running": bool(self.thread and self.thread.is_alive()),
            "lock_acquired": self.lock_acquired,
            "tasks": tasks,
        }


def build_inventory_monitor() -> InventoryMonitor | None:
    tasks = parse_inventory_tasks()
    if not tasks:
        logger.info("未配置 CSQAQ 库存监控任务，后台轮询不启动")
        return None
    if not CSQAQ_API_TOKEN:
        logger.warning("已配置 CSQAQ 库存监控任务，但缺少 CSQAQ_API_TOKEN，后台轮询不启动")
        return None
    return InventoryMonitor(tasks=tasks, token=CSQAQ_API_TOKEN, state_file=CSQAQ_INVENTORY_STATE_FILE)


inventory_monitor = build_inventory_monitor()


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


@app.on_event("startup")
def start_inventory_monitor():
    if inventory_monitor:
        inventory_monitor.start()


@app.on_event("shutdown")
def stop_inventory_monitor():
    if inventory_monitor:
        inventory_monitor.stop()


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

        mentioned_list = ["@all"] if msgtype == "text" else None
        send_wechat_message(msgtype, content, mentioned_list=mentioned_list)
        return {"status": "success", "detail": "已推送"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"处理过程中发生错误: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/csqaq/inventory/status")
def csqaq_inventory_status():
    if not inventory_monitor:
        return {"enabled": False, "running": False, "tasks": []}
    return inventory_monitor.status()


@app.post("/csqaq/inventory/run")
def run_csqaq_inventory_once():
    if not inventory_monitor:
        raise HTTPException(status_code=400, detail="未启用 CSQAQ 库存监控，请配置 CSQAQ_API_TOKEN 和 CSQAQ_INVENTORY_TASKS")
    return {"status": "success", "results": inventory_monitor.run_once()}


@app.get("/health")
def health():
    inventory_status = inventory_monitor.status() if inventory_monitor else {"enabled": False, "running": False}
    return {"status": "ok", "message": "服务正常运行", "csqaq_inventory": inventory_status}
