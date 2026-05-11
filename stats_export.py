"""
Stats export with 7-day reminder and one-click email.
"""

import logging
import os
import sys
import time
import webbrowser
import urllib.parse

logger = logging.getLogger(__name__)

if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.join(sys._MEIPASS, "data")
else:
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

EXPORT_LOG = os.path.join(DATA_DIR, "last_export.txt")
RECIPIENT_EMAIL = "y3493627922@outlook.com"
REMINDER_DAYS = 7


def _get_export_dir() -> str:
    """Get a user-accessible directory for exported files (Desktop)."""
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if os.path.isdir(desktop):
        return desktop
    return os.path.expanduser("~")


def get_days_since_last_export() -> int | None:
    """Return days since last export, or None if never exported."""
    if not os.path.exists(EXPORT_LOG):
        return None
    try:
        with open(EXPORT_LOG, "r") as f:
            last = float(f.read().strip())
        return int((time.time() - last) / 86400)
    except (ValueError, OSError):
        return None


def needs_reminder() -> bool:
    """Check if enough time has passed since last export."""
    days = get_days_since_last_export()
    if days is None:
        return True
    return days >= REMINDER_DAYS


def _save_export_time():
    """Record current time as last export."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(EXPORT_LOG, "w") as f:
        f.write(str(time.time()))


def export_and_email() -> bool:
    """Export stats JSON and open mail client with pre-filled recipient.

    Returns True on success.
    """
    from match_collector import get_db_stats
    from stats_engine import export_stats

    try:
        db_stats = get_db_stats()
        total_games = db_stats.get("total_games", 0)

        # Export JSON to Desktop
        export_dir = _get_export_dir()
        output_path = os.path.join(
            export_dir,
            f"lol_bp_stats_{time.strftime('%Y%m%d_%H%M%S')}.json"
        )
        export_stats(output_path, min_games=2)

        # Build mailto URI
        subject = "LoL BP 数据导出"
        body = (
            f"附件为统计导出数据。\n\n"
            f"对局数：{total_games} 局\n"
            f"导出时间：{time.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"请将生成的 JSON 文件拖入邮件附件后发送。\n"
            f"文件位置：{output_path}"
        )
        mailto = (
            f"mailto:{RECIPIENT_EMAIL}"
            f"?subject={urllib.parse.quote(subject)}"
            f"&body={urllib.parse.quote(body)}"
        )
        webbrowser.open(mailto)

        _save_export_time()
        logger.info("Stats exported to %s (email client opened)", output_path)
        return True
    except Exception:
        logger.exception("Export failed")
        return False


def get_reminder_message() -> str | None:
    """Get the reminder message text if reminder is needed, or None."""
    if not needs_reminder():
        return None

    from match_collector import get_db_stats

    db_stats = get_db_stats()
    total_games = db_stats.get("total_games", 0)
    days = get_days_since_last_export()

    if days is None:
        days_str = "（首次导出）"
    else:
        days_str = f"（上次导出：{days} 天前）"

    return (
        f"你的对局数据已经积累了 {total_games} 局 {days_str}，"
        f"请导出并发送给 Benedict。\n\n"
        f"步骤：\n"
        f"1. 点击「导出并发送」按钮\n"
        f"2. 邮件客户端会自动打开\n"
        f"3. 将生成的 JSON 文件拖入邮件附件\n"
        f"4. 点击发送\n\n"
        f"接收邮箱：{RECIPIENT_EMAIL}"
    )
