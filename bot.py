import asyncio
import nest_asyncio

# رفع مشکل Event Loop در Render
try:
    nest_asyncio.apply()
except Exception:
    pass

asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

import html
import json
import logging
import os
import random
import re
import string
from collections import deque
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib import request as urllib_request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from telethon import TelegramClient, events, Button
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.functions.updates import GetStateRequest
from telethon.tl.types import ReactionEmoji

# Keep runtime timestamps aligned with Tehran time
os.environ.setdefault('TZ', 'Asia/Tehran')
try:
    time.tzset()
except AttributeError:
    pass

# ================== تنظیمات ==================

API_ID = 35554639
API_HASH = "62352ae66f641e72458bb996ee6505fd"
BOT_TOKEN = "8623745409:AAFXF92z-bP0DYHRF0PoHmvG9_y9IUZC_5o"
OWNER_ID = 8158432118

TARGET_BOT = os.getenv("TARGET_BOT", "zswaifu_cheat_bot")
LICENSE_FILE = "license_data.json"

# هر سلف یک فایل دیتا و یک پوشه مدیای جدا دارد
USER_DATA_DIR = Path("auto_catch_user_data")
USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_ROOT_DIR = Path("auto_catch_media")
MEDIA_ROOT_DIR.mkdir(parents=True, exist_ok=True)

# مسیر قدیمی فقط برای سازگاری/مهاجرت اولیه نگه داشته شده
AUTO_DATA_FILE = "auto_catch_final.json"
RUNTIME_STATE_FILE = os.getenv("RUNTIME_STATE_FILE", "runtime_state.json")

DEFAULT_DELAY = 0.6
DEFAULT_TIMEOUT = 8.0
DEFAULT_GIF_DELAY = 4.5
MAX_DELAY = 5.0
MIN_DELAY = 0.3
MIN_TIMEOUT = 3.0
MAX_TIMEOUT = 30.0
MIN_GIF_DELAY = 0.0
MAX_GIF_DELAY = 30.0

KEEPALIVE_INTERVAL_SECONDS = max(60.0, float(os.getenv("KEEPALIVE_INTERVAL_SECONDS", "300")))
KEEPALIVE_TIMEOUT_SECONDS = max(2.0, float(os.getenv("KEEPALIVE_TIMEOUT_SECONDS", "10")))
KEEPALIVE_URL = (os.getenv("KEEPALIVE_URL") or os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_URL") or "").strip()
PORT = int(os.getenv("PORT", "10000"))
HTTP_HOST = os.getenv("HTTP_HOST", "0.0.0.0")

REACTION_REPLY_WINDOW = 90.0
REACTION_DIRECT_WINDOW = 5.0
REACTION_CACHE_TTL = timedelta(minutes=10)

PROCESSED_TTL = timedelta(hours=2)
PROCESSED_MAX = 5000
STATE_CLEANUP_INTERVAL = timedelta(minutes=5)
SAVE_DEBOUNCE_SECONDS = 0.75

REACT_LIKE = "👍"
REACT_DISLIKE = "👎"

REACTION_KEYWORDS = [
    "اتوکچ", "اتو کچ", "اتوکچر", "اتو کچر",
    "اتوپیک", "اتو پیک", "اتوکالکتر", "اتو کالکتر",
    "اتو کالکتور", "auto catch", "autocatch",
    "auto catcher", "autocatcher", "auto pick",
    "autopick", "auto collector", "autocollector",
]

# ================== لاگ ==================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger("AutoCollectorSeller")

def _build_keepalive_url(base_url: str) -> str:
    base_url = (base_url or "").strip()
    if not base_url:
        return ""
    try:
        parsed = urlsplit(base_url if "://" in base_url else f"https://{base_url.lstrip('/')}")
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["_ts"] = str(int(time.time() * 1000))
        return urlunsplit(
            (
                parsed.scheme or "https",
                parsed.netloc,
                parsed.path or "/",
                urlencode(query),
                parsed.fragment,
            )
        )
    except Exception:
        return base_url


def _http_keepalive_sync(url: str) -> bool:
    if not url:
        return False
    req = urllib_request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
        },
        method="GET",
    )
    with urllib_request.urlopen(req, timeout=KEEPALIVE_TIMEOUT_SECONDS) as resp:
        try:
            resp.read(32)
        except Exception:
            pass
    return True


async def _http_keepalive_once(url: str) -> bool:
    if not url:
        return False
    try:
        await asyncio.to_thread(_http_keepalive_sync, _build_keepalive_url(url))
        return True
    except Exception:
        return False


async def _healthcheck_client_handler(reader, writer):
    try:
        try:
            await asyncio.wait_for(reader.read(1024), timeout=2.0)
        except Exception:
            pass
        body = b"OK"
        headers = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: no-store\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("utf-8")
        writer.write(headers + body)
        await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def _start_health_server(host: str = HTTP_HOST, port: int = PORT):
    return await asyncio.start_server(_healthcheck_client_handler, host, port)

# ================== LICENSE DB ==================
def load_license():
    def _to_int_keyed_dict(raw):
        result = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                try:
                    result[int(k)] = v
                except Exception:
                    continue
        return result

    def _to_str_keyed_dict(raw):
        result = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                try:
                    result[str(k)] = v
                except Exception:
                    continue
        return result

    if os.path.exists(LICENSE_FILE):
        try:
            with open(LICENSE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("license db must be a dict")
            data["licenses"] = _to_str_keyed_dict(data.get("licenses", {}))
            data["users"] = _to_int_keyed_dict(data.get("users", {}))
            data["started_users"] = _to_int_keyed_dict(data.get("started_users", {}))
            return data
        except:
            pass
    return {"licenses": {}, "users": {}, "started_users": {}}

def save_license(data):
    with open(LICENSE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

license_db = load_license()
license_db.setdefault("licenses", {})
license_db.setdefault("users", {})
license_db.setdefault("started_users", {})
active_sessions: Dict[int, dict] = {}
BOT_KEEPALIVE_TASK: Optional[asyncio.Task] = None


PENDING_FLOW_TTL = timedelta(minutes=10)

# ================== FULL AUTO CATCH BOT ==================
class AutoCatchBot:
    def __init__(self, user_id: int):
        self.user_id = int(user_id)
        self.data_file = USER_DATA_DIR / f"{self.user_id}.json"
        self.media_dir = MEDIA_ROOT_DIR / str(self.user_id)

        self.client: Optional[TelegramClient] = None
        self.me = None
        self.target_queue = asyncio.Queue(maxsize=200)
        self.catch_lock = asyncio.Lock()
        self.media_lock = asyncio.Lock()
        self.processed_messages: Dict[Tuple[str, int], datetime] = {}
        self.reacted_messages: Dict[Tuple[str, int], datetime] = {}
        self.state_lock = asyncio.Lock()
        self._last_state_cleanup = datetime.now(timezone.utc)
        self._save_task: Optional[asyncio.Task] = None
        self._save_dirty = False
        self._save_lock = asyncio.Lock()
        self._queue_worker_task: Optional[asyncio.Task] = None
        self._bot_username_index = {}
        self._bot_digit_index = {}
        self._normalized_bot_texts = {}
        self.last_catch_time = None
        self.last_catch_chat_id = None
        self.last_catch_message_id = None
        self.last_media_index = None

        self.data = {
            "global_active": False,
            "delay": DEFAULT_DELAY,
            "timeout": DEFAULT_TIMEOUT,
            "gif_delay": DEFAULT_GIF_DELAY,
            "get_group_id": None,
            "gif_enabled": False,
            "media_items": [],
            "like_enabled": False,
            "dislike_enabled": False,
            "delete_after_send": False,
            "groups": {},
            "bots": {},
        }
        self.load_data()

    # ── Data management ─────────────────────────────
    def load_data(self):
        self.media_dir.mkdir(parents=True, exist_ok=True)
        if not self.data_file.exists():
            # مهاجرت اولیه از فایل قدیمی مشترک؛ بعد از این هر سلف فایل خودش را دارد
            if os.path.exists(AUTO_DATA_FILE):
                try:
                    with open(AUTO_DATA_FILE, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    if isinstance(loaded, dict):
                        self.data = loaded
                        self.save_data()
                        return
                except Exception:
                    pass
            return
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)

            if not isinstance(loaded, dict):
                raise ValueError("فرمت فایل دیتا معتبر نیست")

            defaults = {
                "global_active": False,
                "delay": DEFAULT_DELAY,
                "timeout": DEFAULT_TIMEOUT,
                "gif_delay": DEFAULT_GIF_DELAY,
                "get_group_id": None,
                "gif_enabled": False,
                "media_items": [],
                "like_enabled": False,
                "dislike_enabled": False,
                "delete_after_send": False,
                "groups": {},
                "bots": {},
            }
            for k, v in defaults.items():
                loaded.setdefault(k, v)

            loaded["bots"] = {
                str(k): v for k, v in loaded.get("bots", {}).items() if isinstance(v, dict)
            }
            loaded["groups"] = {
                str(k): v for k, v in loaded.get("groups", {}).items() if isinstance(v, dict)
            }

            for bot_id, info in loaded["bots"].items():
                info.setdefault("name", "ربات")
                info.setdefault("username", "")
                info.setdefault("emojis", [])
                info.setdefault("texts", [])
                info.setdefault("date", datetime.now().strftime("%Y-%m-%d %H:%M"))

            for group_id, info in loaded["groups"].items():
                info.setdefault("title", "گروه")
                info.setdefault("date", datetime.now().strftime("%Y-%m-%d %H:%M"))

            loaded["delay"] = self._clamp_float(loaded.get("delay", DEFAULT_DELAY), MIN_DELAY, MAX_DELAY, DEFAULT_DELAY)
            loaded["timeout"] = self._clamp_float(loaded.get("timeout", DEFAULT_TIMEOUT), MIN_TIMEOUT, MAX_TIMEOUT, DEFAULT_TIMEOUT)
            loaded["gif_delay"] = self._clamp_float(loaded.get("gif_delay", DEFAULT_GIF_DELAY), MIN_GIF_DELAY, MAX_GIF_DELAY, DEFAULT_GIF_DELAY)

            loaded["global_active"] = bool(loaded.get("global_active", False))
            loaded["like_enabled"] = bool(loaded.get("like_enabled", False))
            loaded["dislike_enabled"] = bool(loaded.get("dislike_enabled", False))
            loaded["delete_after_send"] = bool(loaded.get("delete_after_send", False))
            loaded["gif_enabled"] = bool(loaded.get("gif_enabled", False))

            # Normalize media items
            media_items = []
            for item in loaded.get("media_items", []):
                if not isinstance(item, dict):
                    continue
                path = item.get("path")
                if not path or not os.path.exists(path):
                    continue
                media_items.append({
                    "path": str(Path(path).resolve()),
                    "kind": item.get("kind", "media"),
                    "date": item.get("date", datetime.now().strftime("%Y-%m-%d %H:%M")),
                })
            loaded["media_items"] = media_items

            if loaded.get("get_group_id") and not isinstance(loaded["get_group_id"], dict):
                loaded["get_group_id"] = None

            self.data = loaded
            self._rebuild_bot_indexes()
            self._last_state_cleanup = datetime.now(timezone.utc)
            self.media_dir.mkdir(parents=True, exist_ok=True)
            log.info("داده‌ها بارگذاری شد | uid=%s file=%s", self.user_id, self.data_file)
        except Exception:
            log.exception("خطا در بارگذاری فایل دیتا")
            self.data = {
                "global_active": False,
                "delay": DEFAULT_DELAY,
                "timeout": DEFAULT_TIMEOUT,
                "gif_delay": DEFAULT_GIF_DELAY,
                "get_group_id": None,
                "gif_enabled": False,
                "media_items": [],
                "like_enabled": False,
                "dislike_enabled": False,
                "delete_after_send": False,
                "groups": {},
                "bots": {},
            }
            self._rebuild_bot_indexes()
            self._last_state_cleanup = datetime.now(timezone.utc)

    def _write_data_sync(self):
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(self.data_file) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.data_file)

    async def _flush_pending_save(self):
        try:
            while True:
                await asyncio.sleep(SAVE_DEBOUNCE_SECONDS)
                async with self._save_lock:
                    if not self._save_dirty:
                        return
                    self._save_dirty = False
                await asyncio.to_thread(self._write_data_sync)
                if not self._save_dirty:
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("save_data failed | uid=%s file=%s", self.user_id, self.data_file)
        finally:
            self._save_task = None

    def save_data(self):
        self._save_dirty = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                self._write_data_sync()
            except Exception:
                log.exception("save_data failed | uid=%s file=%s", self.user_id, self.data_file)
            finally:
                self._save_dirty = False
            return

        if self._save_task and not self._save_task.done():
            return
        self._save_task = loop.create_task(self._flush_pending_save())

    # ── Utility methods ────────────────────────────
    @staticmethod
    def _clamp_float(value, min_value, max_value, default):
        try:
            value = float(value)
            return max(min_value, min(max_value, value))
        except Exception:
            return default

    def _rebuild_bot_indexes(self):
        self._bot_username_index = {}
        self._bot_digit_index = {}
        self._normalized_bot_texts = {}

        for key, info in self.data.get("bots", {}).items():
            key_str = str(key)
            digits = re.sub(r"\D", "", key_str)
            if digits and digits not in self._bot_digit_index:
                self._bot_digit_index[digits] = key_str

            username = (info.get("username") or "").strip().lstrip("@").casefold()
            if username and username not in self._bot_username_index:
                self._bot_username_index[username] = key_str

            self._normalized_bot_texts[key_str] = [self._normalize(t) for t in info.get("texts", []) if t]

    def _refresh_bot_cache(self, bot_key: str):
        key = str(bot_key)
        bot = self.data.get("bots", {}).get(key)
        if not bot:
            self._normalized_bot_texts.pop(key, None)
            return
        self._normalized_bot_texts[key] = [self._normalize(t) for t in bot.get("texts", []) if t]

    def _maybe_cleanup_state_locked(self, now: datetime):
        if (now - self._last_state_cleanup) < STATE_CLEANUP_INTERVAL:
            return
        self._last_state_cleanup = now

        expired_processed = [k for k, ts in self.processed_messages.items() if now - ts > PROCESSED_TTL]
        for k in expired_processed:
            self.processed_messages.pop(k, None)

        if len(self.processed_messages) > PROCESSED_MAX:
            overflow = len(self.processed_messages) - PROCESSED_MAX
            for k, _ in sorted(self.processed_messages.items(), key=lambda kv: kv[1])[:overflow]:
                self.processed_messages.pop(k, None)

        expired_reacted = [k for k, ts in self.reacted_messages.items() if now - ts > REACTION_CACHE_TTL]
        for k in expired_reacted:
            self.reacted_messages.pop(k, None)

    def _extract_after(self, cmd, prefix):
        return cmd[len(prefix):].strip()

    def _find_bot_key(self, bot_id):
        bot_id = str(bot_id).strip()
        if not bot_id:
            return None

        if bot_id in self.data["bots"]:
            return bot_id

        digits = re.sub(r"\D", "", bot_id)
        if digits:
            cached = self._bot_digit_index.get(digits)
            if cached and cached in self.data["bots"]:
                return cached
            for key in self.data["bots"]:
                if re.sub(r"\D", "", str(key)) == digits:
                    self._bot_digit_index[digits] = str(key)
                    return str(key)

        target_username = bot_id.lstrip("@").casefold()
        if target_username:
            cached = self._bot_username_index.get(target_username)
            if cached and cached in self.data["bots"]:
                return cached
            for key, info in self.data["bots"].items():
                if (info.get("username") or "").strip().lstrip("@").casefold() == target_username:
                    self._bot_username_index[target_username] = str(key)
                    return str(key)

        return None

    @staticmethod
    def _as_utc(dt):
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    async def _mark_reacted(self, msg_key):
        async with self.state_lock:
            now = datetime.now(timezone.utc)
            self._maybe_cleanup_state_locked(now)
            if msg_key in self.reacted_messages:
                return False
            self.reacted_messages[msg_key] = now
            return True

    @staticmethod
    def _normalize(text):
        text = unicodedata.normalize("NFKC", (text or ""))
        text = text.casefold()
        text = re.sub(r"[\u200B\u200C\u200D\uFEFF\u00A0]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _safe_preview(text, limit=80):
        text = (text or "").replace("\n", " ").strip()
        return text[:limit] + ("..." if len(text) > limit else "")

    @staticmethod
    def _h(text):
        return html.escape(str(text if text is not None else ""), quote=False)

    async def _mark_processed(self, msg_key):
        async with self.state_lock:
            now = datetime.now(timezone.utc)
            self._maybe_cleanup_state_locked(now)
            if msg_key in self.processed_messages:
                return False
            self.processed_messages[msg_key] = now
            return True

    async def _purge_target_queue(self):
        while True:
            try:
                self.target_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _is_registered_group(self, chat_id: str) -> bool:
        return str(chat_id) in self.data["groups"]

    def _get_preset_for_bot(self, bot_id: str):
        presets = {
            "8309088282": {
                "name": "Taker character bot",
                "username": "Taker_character_bot",
                "emojis": ["🎭", "⛩", "🏵", "🔮", "🍭", "🪩", "🎐"],
                "texts": [
                    "𝖭𝖾𝗐 𝖢𝗁𝖺𝗋𝖺𝖼𝗍𝖾𝗋 𝗁𝖺𝗌 𝖲𝗉𝖺𝗐𝗇𝖾𝖽 𝗂𝗇𝗍𝗈 𝗍𝗁𝖾 𝖼𝗁𝖺𝗍!  🥡 𝗎𝗌𝖾 /t...",
                    "𝖭𝖾𝗐 𝖢𝗁𝖺𝗋𝖺𝖼𝗍𝖾𝗋 𝗁𝖺𝗌 𝖲𝗉𝖺𝗐𝗇𝖾𝖽 𝗂𝗇𝗍𝗈 𝗍𝗁𝖾 𝖼𝗁𝖺𝗍!  🥡\n\n 𝗎𝗌𝖾 /take [𝗇𝖺𝗆𝖾] 𝗍𝗈 𝗀𝖾𝗍 𝗍𝖺𝗄𝖾 𝗍𝗁𝗂𝗌 𝖼𝗁𝖺𝗋𝖺𝖼𝗍𝖾𝗋 𝗂𝗇 𝗒𝗈𝗎",
                    "𝖭𝖾𝗐 𝖢𝗁𝖺𝗋𝖺𝖼𝗍𝖾𝗋 𝗁𝖺𝗌 𝖲𝗉𝖺𝗐𝗇𝖾𝖽 𝗂𝗇𝗍𝗈 𝗍𝗁𝖾 𝖼𝗁𝖺𝗍!  🥡 𝗎𝗌𝖾 /take [𝗇𝖺𝗆𝖾] 𝗍𝗈 𝗀𝖾𝗍 𝗍𝖺𝗄𝖾 𝗍𝗁𝗂𝗌 𝖼𝗁𝖺𝗋𝖺𝖼𝗍𝖾𝗋 𝗂𝗇...",
                ],
            },
            "8307651649": {
                "name": "Picker Bot",
                "username": "character_picker_bot",
                "emojis": ["🪩", "🔮", "⛩", "🎭", "🪞", "🪐", "🌋"],
                "texts": [
                    "A new character has just spawned in the chat! 🍜\nUse /pick [Name] to pick them for yourself",
                    "A new character has just spawned in the chat! 🍜\nUse /pick [Name] to pick them for yourself.",
                    "A new character has just spawned in the chat! 🍜",
                    "Use /pick [Name] to pick them for yourself.",
                ],
            },
            "6157455819": {
                "name": "Character Catcher Bot",
                "username": "Character_Catcher_Bot",
                "emojis": ["🪞", "⚡", "⚜️", "💮", "✨"],
                "texts": [
                    "ᴀ ᴄʜᴀʀᴀᴄᴛᴇʀ ʜᴀs sᴘᴀᴡɴᴇᴅ ɪɴ ᴛʜᴇ ᴄʜᴀᴛ!🧃\nᴀᴅᴅ ᴛʜɪs ᴄʜᴀʀᴀᴄᴛᴇʀ ᴛᴏ ʏᴏᴜʀ ʜᴀʀᴇᴍ ᴜsɪɴɢ /catch [ɴᴀᴍᴇ]",
                    "ᴀ ᴄʜᴀʀᴀᴄᴛᴇʀ ʜᴀs sᴘᴀᴡɴᴇᴅ ɪɴ ᴛʜᴇ ᴄʜᴀᴛ!🧃",
                    "ᴀᴅᴅ ᴛʜɪs ᴄʜᴀʀᴀᴄᴛᴇʀ ᴛᴏ ʏᴏᴜʀ ʜᴀʀᴇᴍ ᴜsɪɴɢ /catch [ɴᴀᴍᴇ]",
                ],
            },
        }
        return presets.get(str(bot_id).strip())

    def _apply_preset_to_bot(self, bot_id: str, info: dict, overwrite: bool = False):
        preset = self._get_preset_for_bot(bot_id)
        if not preset:
            return info
        if overwrite or not info.get("name"):
            info["name"] = preset.get("name", info.get("name", "ربات"))
        if overwrite or not info.get("username"):
            info["username"] = preset.get("username", info.get("username", ""))
        if overwrite or not info.get("emojis"):
            info["emojis"] = list(preset.get("emojis", []))
        if overwrite or not info.get("texts"):
            info["texts"] = list(preset.get("texts", []))
        return info

    def _reaction_emoji(self):
        if self.data.get("dislike_enabled"):
            return REACT_DISLIKE
        if self.data.get("like_enabled"):
            return REACT_LIKE
        return None

    def _contains_reaction_keyword(self, text: str) -> bool:
        norm = self._normalize(text)
        if not hasattr(self, "_reaction_keyword_re"):
            escaped = [re.escape(self._normalize(keyword)) for keyword in REACTION_KEYWORDS if self._normalize(keyword)]
            self._reaction_keyword_re = re.compile("|".join(sorted(escaped, key=len, reverse=True))) if escaped else None
        if self._reaction_keyword_re is None:
            return False
        return bool(self._reaction_keyword_re.search(norm))

    def _debug_event_line(self, event) -> str:
        try:
            chat_id = getattr(event, "chat_id", None)
            sender_id = getattr(event, "sender_id", None)
            msg_id = getattr(event, "id", None)
            text = self._safe_preview(getattr(event, "raw_text", "") or getattr(getattr(event, "message", None), "text", "") or "", 90)
            return f"chat_id={chat_id} sender_id={sender_id} msg_id={msg_id} text={text}"
        except Exception:
            return "event=<unavailable>"

    async def _react_to_message(self, chat_id, msg_id, emoji):
        if not self.client or not emoji:
            return False
        try:
            peer = await self.client.get_input_entity(chat_id)
            await self.client(
                SendReactionRequest(
                    peer=peer,
                    msg_id=msg_id,
                    reaction=[ReactionEmoji(emoticon=emoji)],
                    big=False,
                    add_to_recent=False,
                )
            )
            return True
        except Exception:
            log.exception("خطا در ارسال ریکشن | chat_id=%s msg_id=%s emoji=%s", chat_id, msg_id, emoji)
            return False

    async def _keepalive_tick(self):
        """ارسال یک درخواست سبک و تلاش برای زنده ماندن سشن."""
        try:
            if self.client:
                try:
                    if not self.client.is_connected():
                        await self.client.connect()
                except Exception:
                    pass
                if self.client.is_connected():
                    try:
                        await self.client(GetStateRequest())
                    except Exception:
                        pass
            if KEEPALIVE_URL:
                await _http_keepalive_once(KEEPALIVE_URL)
            return True
        except Exception:
            return False

    async def _keepalive_loop(self):
        try:
            await asyncio.sleep(random.uniform(5, 20))
            while True:
                try:
                    await self._keepalive_tick()
                except Exception:
                    pass
                await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("keepalive loop error | uid=%s", self.user_id)

    def _start_keepalive_task(self):
        task = getattr(self, "_keepalive_task", None)
        if task and not task.done():
            return
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def _stop_keepalive_task(self):
        task = getattr(self, "_keepalive_task", None)
        if not task:
            return
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        self._keepalive_task = None

    def _pick_random_media(self, items):
        if not items:
            return None
        idx = random.randrange(len(items))
        self.last_media_index = idx
        return items[idx]

    async def _push_target_event(self, event):
        try:
            if self.me and event.sender_id == self.me.id:
                return

            reply_to = getattr(event.message, "reply_to_msg_id", None)
            log.info(
                "TARGET EVENT | %s | reply_to=%s",
                self._debug_event_line(event),
                reply_to,
            )

            try:
                self.target_queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    _ = self.target_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self.target_queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

        except Exception:
            log.exception("خطا در _push_target_event")

    # ── Core handlers ─────────────────────────────
    async def start_collector(self, client: TelegramClient):
        self.client = client
        self.me = await self.client.get_me()
        log.info(f"✅ AutoCollector started on account {self.me.id} (@{self.me.username})")

        # حذف هندلرهای قبلی در صورت وجود
        try:
            self.client.remove_event_handler(self.handle_message)
            self.client.remove_event_handler(self._push_target_event)
        except Exception:
            pass

        self.client.add_event_handler(self.handle_message, events.NewMessage())
        self.client.add_event_handler(self.handle_message, events.MessageEdited())

        self.client.add_event_handler(self._push_target_event, events.NewMessage(chats=TARGET_BOT))
        self.client.add_event_handler(self._push_target_event, events.MessageEdited(chats=TARGET_BOT))

        if self._queue_worker_task and not self._queue_worker_task.done():
            self._queue_worker_task.cancel()
        self._queue_worker_task = asyncio.create_task(self.queue_worker())
        self._start_keepalive_task()

    async def handle_message(self, event):
        try:
            text = event.raw_text or event.message.message or event.message.text or ""
            sender_id = event.sender_id
            chat_id = str(event.chat_id)

            stripped_text = text.strip()

            # یک نقطهٔ تنها (یا نقطه + فاصله/خط جدید) نباید به‌عنوان دستور حساب شود.
            if stripped_text == ".":
                return

            if stripped_text.startswith("."):
                if not self.me or sender_id != self.me.id:
                    return
                await self.handle_command(event, stripped_text)
                return

            # Group ID capture
            gid_req = self.data.get("get_group_id")
            if gid_req and isinstance(gid_req, dict) and gid_req.get("waiting"):
                expires_at = gid_req.get("expires_at")
                try:
                    if expires_at and datetime.now().timestamp() > float(expires_at):
                        self.data["get_group_id"] = None
                        self.save_data()
                        gid_req = None
                except Exception:
                    pass

            if gid_req and isinstance(gid_req, dict) and gid_req.get("waiting"):
                if getattr(event, "is_group", False) and _is_sticker_message(event.message):
                    await self.send_group_id(event)
                    return

            if not self.data["global_active"]:
                return

            if not self._is_registered_group(chat_id):
                return

            await self.maybe_react_to_message(event, chat_id, text)
            await self.process_bot_message(event, chat_id)

        except Exception:
            log.exception("handle_message error | %s", self._debug_event_line(event))

    async def handle_command(self, event, command):
        cmd = (command or "").strip()
        log.info("دستور: %s | chat_id=%s sender_id=%s", cmd, event.chat_id, event.sender_id)

        try:
            if cmd == ".on":
                self.data["global_active"] = True
                self.save_data()
                await event.reply("✅ <b>Auto Collector</b> روشن شد", parse_mode="html")

            elif cmd == ".off":
                self.data["global_active"] = False
                self.save_data()
                await event.reply("⛔ <b>Auto Collector</b> خاموش شد", parse_mode="html")

            elif cmd in [".پنل", ".وضعیت"]:
                await self.show_panel(event)

            elif cmd.startswith(".تاخیر "):
                try:
                    delay = float(cmd.split(maxsplit=1)[1])
                    self.data["delay"] = max(MIN_DELAY, min(MAX_DELAY, delay))
                    self.save_data()
                    await event.reply(
                        f"⏱ تاخیر روی <code>{self._h(self.data['delay'])}</code> ثانیه تنظیم شد",
                        parse_mode="html",
                    )
                except Exception:
                    await event.reply("❌ فرمت درست: <code>.تاخیر 0.6</code>", parse_mode="html")

            elif cmd.startswith(".تایم‌اوت ") or cmd.startswith(".تایم اوت ") or cmd.startswith(".timeout "):
                try:
                    timeout = float(cmd.split(maxsplit=1)[1])
                    self.data["timeout"] = max(MIN_TIMEOUT, min(MAX_TIMEOUT, timeout))
                    self.save_data()
                    await event.reply(
                        f"🕒 تایم‌اوت روی <code>{self._h(self.data['timeout'])}</code> ثانیه تنظیم شد",
                        parse_mode="html",
                    )
                except Exception:
                    await event.reply("❌ فرمت درست: <code>.تایم‌اوت 8</code>", parse_mode="html")

            elif cmd.startswith(".زمان تاخیر گیف ") or cmd.startswith(".تاخیر گیف "):
                try:
                    prefix = ".زمان تاخیر گیف " if cmd.startswith(".زمان تاخیر گیف ") else ".تاخیر گیف "
                    gd = float(self._extract_after(cmd, prefix))
                    self.data["gif_delay"] = max(MIN_GIF_DELAY, min(MAX_GIF_DELAY, gd))
                    self.save_data()
                    await event.reply(
                        f"🎞 تاخیر گیف روی <code>{self._h(self.data['gif_delay'])}</code> ثانیه تنظیم شد",
                        parse_mode="html",
                    )
                except Exception:
                    await event.reply("❌ فرمت درست: <code>.زمان تاخیر گیف 4.5</code>", parse_mode="html")

            elif cmd == ".ایدی گپ":
                self.data["get_group_id"] = {
                    "waiting": True,
                    "owner_chat": str(event.chat_id),
                    "owner_msg": event.id,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "expires_at": (datetime.now() + timedelta(minutes=10)).timestamp(),
                }
                self.save_data()
                await event.reply(
                    "📩 حالا داخل <b>همان گروه</b> یک استیکر بفرست تا آیدی همان گروه برایت ارسال شود\n"
                    "🔎 استیکرهای معمولی و انیمیشنی هر دو شناسایی می‌شوند.",
                    parse_mode="html",
                )

            elif cmd == ".ایدی گپ خاموش":
                self.data["get_group_id"] = None
                self.save_data()
                await event.reply("✅ حالت گرفتن آیدی گروه خاموش شد", parse_mode=None)

            elif cmd.startswith(".گروه اضافه "):
                parts = cmd.split(maxsplit=2)
                if len(parts) >= 3:
                    await self.add_group(event, parts[2])
                else:
                    await event.reply("❌ فرمت درست: <code>.گروه اضافه -100123456789</code>", parse_mode="html")

            elif cmd.startswith(".گروه حذف "):
                parts = cmd.split(maxsplit=2)
                if len(parts) >= 3:
                    await self.remove_group(event, parts[2])
                else:
                    await event.reply("❌ فرمت درست: <code>.گروه حذف -100123456789</code>", parse_mode="html")

            elif cmd == ".گروه ها":
                await self.list_groups(event)

            elif cmd == ".ربات اضافه":
                if event.message.reply_to_msg_id:
                    await self.add_bot(event)
                else:
                    await event.reply("❌ روی پیام همان ربات ریپلای کن", parse_mode=None)

            elif cmd.startswith(".ربات حذف "):
                parts = cmd.split(maxsplit=2)
                if len(parts) >= 3:
                    await self.remove_bot(event, parts[2])
                else:
                    await event.reply("❌ فرمت درست: <code>.ربات حذف 123456789</code>", parse_mode="html")

            elif cmd == ".ربات ها":
                await self.list_bots(event)

            elif cmd == ".پریست":
                await self.apply_preset_command(event)

            elif cmd.startswith(".ایموجی اضافه "):
                rest = self._extract_after(cmd, ".ایموجی اضافه ")
                parts = rest.split(maxsplit=1)
                if len(parts) < 2:
                    await event.reply("❌ فرمت درست: <code>.ایموجی اضافه 123456789 😀</code>", parse_mode="html")
                else:
                    await self.add_emoji(event, parts[0].strip(), parts[1].strip())

            elif cmd.startswith(".ایموجی حذف "):
                parts = cmd.split(maxsplit=3)
                if len(parts) >= 4:
                    await self.remove_emoji(event, parts[2], parts[3])
                else:
                    await event.reply("❌ فرمت درست: <code>.ایموجی حذف 123456789 1</code>", parse_mode="html")

            elif cmd.startswith(".ایموجی ها "):
                rest = self._extract_after(cmd, ".ایموجی ها ")
                if rest:
                    await self.list_emojis(event, rest)
                else:
                    await event.reply("❌ فرمت درست: <code>.ایموجی ها 123456789</code>", parse_mode="html")

            elif cmd.startswith(".پیام ثابت اضافه "):
                rest = self._extract_after(cmd, ".پیام ثابت اضافه ")
                parts = rest.split(maxsplit=1)
                if len(parts) < 2:
                    await event.reply("❌ فرمت درست: <code>.پیام ثابت اضافه 123456789 متن</code>", parse_mode="html")
                else:
                    await self.add_fixed_text(event, parts[0].strip(), parts[1].strip())

            elif cmd.startswith(".پیام ثابت حذف "):
                parts = cmd.split(maxsplit=3)
                if len(parts) >= 4:
                    await self.remove_fixed_text(event, parts[2], parts[3])
                else:
                    await event.reply("❌ فرمت درست: <code>.پیام ثابت حذف 123456789 1</code>", parse_mode="html")

            elif cmd.startswith(".پیام ثابت ها "):
                rest = self._extract_after(cmd, ".پیام ثابت ها ")
                if rest:
                    await self.list_fixed_texts(event, rest)
                else:
                    await event.reply("❌ فرمت درست: <code>.پیام ثابت ها 123456789</code>", parse_mode="html")

            elif cmd == ".گیف روشن":
                self.data["gif_enabled"] = True
                self.save_data()
                if not self.data.get("media_items"):
                    await event.reply("✅ ارسال مدیا روشن شد، ولی هنوز گیف/استیکر ثبت نشده", parse_mode=None)
                else:
                    await event.reply("✅ ارسال مدیا روشن شد", parse_mode=None)

            elif cmd == ".گیف خاموش":
                self.data["gif_enabled"] = False
                self.save_data()
                await event.reply("⛔ ارسال مدیا خاموش شد", parse_mode=None)

            elif cmd in [".ثبت گیف", ".گیف ثبت"]:
                await self.register_media(event)

            elif cmd == ".لیست گیف":
                await self.list_media(event)

            elif cmd.startswith(".حذف گیف "):
                parts = cmd.split(maxsplit=2)
                if len(parts) >= 3:
                    await self.remove_media(event, parts[2])
                else:
                    await event.reply("❌ فرمت درست: <code>.حذف گیف 1</code>", parse_mode="html")

            elif cmd == ".لایک روشن":
                self.data["like_enabled"] = True
                self.data["dislike_enabled"] = False
                self.save_data()
                await event.reply("✅ لایک روشن شد", parse_mode=None)

            elif cmd == ".لایک خاموش":
                self.data["like_enabled"] = False
                self.save_data()
                await event.reply("⛔ لایک خاموش شد", parse_mode=None)

            elif cmd == ".دیس لایک روشن":
                self.data["dislike_enabled"] = True
                self.data["like_enabled"] = False
                self.save_data()
                await event.reply("✅ دیس‌لایک روشن شد", parse_mode=None)

            elif cmd == ".دیس لایک خاموش":
                self.data["dislike_enabled"] = False
                self.save_data()
                await event.reply("⛔ دیس‌لایک خاموش شد", parse_mode=None)

            elif cmd == ".حذف پیام روشن":
                self.data["delete_after_send"] = True
                self.save_data()
                await event.reply("✅ حذف خودکار پیام کچ روشن شد", parse_mode=None)

            elif cmd == ".حذف پیام خاموش":
                self.data["delete_after_send"] = False
                self.save_data()
                await event.reply("⛔ حذف خودکار پیام کچ خاموش شد", parse_mode=None)

            elif cmd == ".راهنما":
                await self.show_help(event)

            elif cmd == ".اطلاعات":
                await self.show_info(event)

            elif cmd == ".دیباگ":
                await self.show_debug(event)

            elif cmd == ".پینگ":
                start = time.perf_counter()
                test = await self.client.send_message("me", "ping_test", parse_mode=None)
                ping_ms = int(round((time.perf_counter() - start) * 1000))
                await test.delete()
                await event.reply(
                    f"🏓 پونگ!\nپینگ: <code>{ping_ms} ms</code>",
                    parse_mode="html",
                )

            elif cmd == ".پاکسازی":
                await event.reply("⚠️ برای تأیید پاکسازی کامل، دستور <code>.پاکسازی تایید</code> را بفرست", parse_mode="html")

            elif cmd == ".پاکسازی تایید":
                self.data = {
                    "global_active": False,
                    "delay": DEFAULT_DELAY,
                    "timeout": DEFAULT_TIMEOUT,
                    "gif_delay": DEFAULT_GIF_DELAY,
                    "get_group_id": None,
                    "gif_enabled": False,
                    "media_items": [],
                    "like_enabled": False,
                    "dislike_enabled": False,
                    "delete_after_send": False,
                    "groups": {},
                    "bots": {},
                }
                self.processed_messages.clear()
                self.reacted_messages.clear()
                self.last_catch_time = None
                self.last_catch_chat_id = None
                self.last_catch_message_id = None
                self.last_media_index = None
                self.save_data()
                await event.reply("🧹 همه داده‌ها پاک شدند", parse_mode=None)

            else:
                await event.reply("❌ دستور نامعتبر. <code>.راهنما</code> را ببینید", parse_mode="html")

        except Exception as e:
            log.exception("خطا در handle_command | cmd=%s", cmd)
            await event.reply(f"❌ خطا: {html.escape(str(e)[:150], quote=False)}", parse_mode="html")
        finally:
            if event.out:
                try:
                    await event.delete()
                except Exception:
                    pass

    # ── Panel & Info ──────────────────────────────
    async def show_panel(self, event):
        status = "🟢 روشن" if self.data["global_active"] else "🔴 خاموش"
        gif_status = "✅" if self.data.get("gif_enabled") else "❌"
        like_status = "✅" if self.data.get("like_enabled") else "❌"
        dislike_status = "✅" if self.data.get("dislike_enabled") else "❌"
        delete_status = "✅" if self.data.get("delete_after_send") else "❌"
        panel = (
            "<b>════════  Auto Collector  ════════</b>\n\n"
            f"<b>⚡ وضعیت کلی :</b> <code>{status}</code>\n"
            f"<b>⏱ تاخیر :</b> <code>{self._h(self.data['delay'])}</code> ثانیه\n"
            f"<b>🎞 تاخیر گیف :</b> <code>{self._h(self.data['gif_delay'])}</code> ثانیه\n"
            f"<b>⏳ تایم‌اوت :</b> <code>{self._h(self.data['timeout'])}</code> ثانیه\n"
            f"<b>🎞 ارسال مدیا :</b> <code>{gif_status}</code>\n"
            f"<b>👍 لایک :</b> <code>{like_status}</code>\n"
            f"<b>👎 دیس‌لایک :</b> <code>{dislike_status}</code>\n"
            f"<b>🗑 حذف خودکار :</b> <code>{delete_status}</code>\n"
            f"<b>👥 گروه‌ها :</b> <code>{len(self.data['groups'])}</code>\n"
            f"<b>🤖 ربات‌ها :</b> <code>{len(self.data['bots'])}</code>\n"
            f"<b>🎞 مدیاهای ذخیره‌شده :</b> <code>{len(self.data.get('media_items', []))}</code>\n"
            f"<b>🆔 شناسه :</b> <code>{self._h(self.me.id if self.me else '-')}</code>\n\n"
            "<b>──────────────────────────────</b>\n"
            "<b>راهنما :</b> <code>.راهنما</code>"
        )
        await event.reply(panel, parse_mode="html")

    async def show_help(self, event):
        help_text = (
            "<b>════════  Auto Collector  ════════</b>\n"
            "<i>راهنمای کامل دستورات</i>\n\n"
            "<b>⚙️ کنترل اصلی</b>\n"
            "<blockquote>"
            "<code>.on</code>  →  روشن کردن کالکتور\n"
            "<code>.off</code> →  خاموش کردن\n"
            "<code>.پنل</code> / <code>.وضعیت</code>  →  دیدن تنظیمات\n"
            "<code>.اطلاعات</code> →  اطلاعات فنی\n"
            "<code>.دیباگ</code> →  وضعیت عیب‌یابی\n"
            "<code>.تاخیر 0.6</code> →  مکث قبل از کچ\n"
            "<code>.تایم‌اوت 8</code> →  زمان انتظار پاسخ ربات\n"
            "</blockquote>\n\n"
            "<b>👥 گروه‌ها</b>\n"
            "<blockquote>"
            "<code>.ایدی گپ</code> →  گرفتن آیدی با استیکر از همان گروه\n"
            "<code>.گروه اضافه -100...</code> →  افزودن گروه\n"
            "<code>.گروه حذف -100...</code> →  حذف گروه\n"
            "<code>.گروه ها</code> →  لیست گروه‌ها\n"
            "</blockquote>\n\n"
            "<b>🤖 ربات‌ها</b>\n"
            "<blockquote>"
            "<code>.ربات اضافه</code> (ریپلای)  →  افزودن ربات\n"
            "<code>.ربات حذف 123...</code> →  حذف ربات\n"
            "<code>.ربات ها</code> →  لیست ربات‌ها\n"
            "<code>.پریست</code> (ریپلای) →  بارگذاری تنظیمات پیش‌فرض ربات\n"
            "</blockquote>\n\n"
            "<b>🎞 مدیا</b>\n"
            "<blockquote>"
            "<code>.ثبت گیف</code> یا <code>.گیف ثبت</code> (ریپلای)  →  ذخیره گیف/استیکر\n"
            "<code>.گیف روشن</code> / <code>.گیف خاموش</code> →  ارسال خودکار مدیا بعد کچ\n"
            "<code>.لیست گیف</code> →  نمایش همه مدیاها\n"
            "<code>.حذف گیف 1</code> →  حذف یکی از مدیاها\n"
            "<code>.زمان تاخیر گیف 4.5</code> →  فاصله ارسال مدیا بعد کچ\n"
            "</blockquote>\n\n"
            "<b>🗑 حذف خودکار</b>\n"
            "<blockquote>"
            "<code>.حذف پیام روشن</code> →  پاک کردن پیام کچ از گروه\n"
            "<code>.حذف پیام خاموش</code> →  ماندگار ماندن پیام\n"
            "</blockquote>\n\n"
            "<b>🔍 ایموجی‌ها</b>\n"
            "<blockquote>"
            "<code>.ایموجی اضافه 123456789 😀</code>  →  افزودن شرط ایموجی\n"
            "<code>.ایموجی حذف 123456789 1</code>  →  حذف یک ایموجی\n"
            "<code>.ایموجی ها 123456789</code>  →  نمایش ایموجی‌های یک ربات\n"
            "اگر چند ایموجی ثبت شود، وجود یکی از آن‌ها در پیام کافی است.\n"
            "برای هر ربات می‌توان چندین ایموجی اختصاصی ثبت کرد تا فیلتر دقیق‌تر شود.\n"
            "</blockquote>\n\n"
            "<b>📝 متن‌های ثابت</b>\n"
            "<blockquote>"
            "<code>.پیام ثابت اضافه 123456789 متن</code>  →  افزودن شرط متنی\n"
            "<code>.پیام ثابت حذف 123456789 1</code>  →  حذف یک متن\n"
            "<code>.پیام ثابت ها 123456789</code>  →  نمایش متن‌های یک ربات\n"
            "</blockquote>\n\n"
            "<b>👍 واکنش‌ها</b>\n"
            "<blockquote>"
            "<code>.لایک روشن</code> / <code>.لایک خاموش</code> →  لایک خودکار\n"
            "<code>.دیس لایک روشن</code> / <code>.دیس لایک خاموش</code> →  دیس‌لایک خودکار\n"
            "بعد از کچ، اگر کسی ریپلای بزند یا کلمه‌های مرتبط بنویسد، ریکشن می‌خورد\n"
            "</blockquote>\n\n"
            "<b>🛠 سایر</b>\n"
            "<blockquote>"
            "<code>.پینگ</code>  →  تست سرعت واقعی\n"
            "<code>.پاکسازی</code> (تأیید با <code>.پاکسازی تایید</code>) →  ریست کامل\n"
            "</blockquote>\n\n"
            "<b>──────────────────────────────</b>\n"
            "<b>📩 سفارش و ارتباط :</b> <a href=\"https://t.me/sell_Auto_collector\">@sell_Auto_collector</a>"
        )
        await event.reply(help_text, parse_mode="html")

    async def show_info(self, event):
        info = (
            "<b>════════  Auto Collector  ════════</b>\n"
            "<i>اطلاعات سیستم</i>\n\n"
            f"👤 <b>کاربر :</b> <code>{self._h(self.me.first_name if self.me else '-')}</code> "
            f"(<code>{self._h(self.me.id if self.me else '-')}</code>)\n"
            f"📌 <b>نسخه :</b> <code>Final Beauty</code>\n"
            f"⚡ <b>کالکتور :</b> <code>{'🟢 روشن' if self.data['global_active'] else '🔴 خاموش'}</code>\n"
            f"⏱ <b>تاخیر :</b> <code>{self._h(self.data['delay'])}</code> ثانیه\n"
            f"🎞 <b>تاخیر گیف :</b> <code>{self._h(self.data['gif_delay'])}</code> ثانیه\n"
            f"⏳ <b>تایم‌اوت :</b> <code>{self._h(self.data['timeout'])}</code> ثانیه\n"
            f"👥 <b>گروه‌ها :</b> <code>{len(self.data['groups'])}</code>\n"
            f"🤖 <b>ربات‌ها :</b> <code>{len(self.data['bots'])}</code>\n"
            f"🎞 <b>مدیاها :</b> <code>{len(self.data.get('media_items', []))}</code>\n"
        )
        await event.reply(info, parse_mode="html")

    async def show_debug(self, event):
        gid_req = self.data.get("get_group_id")
        debug_text = (
            "<b>🧪 Debug Status</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"global_active: <code>{self._h(self.data.get('global_active'))}</code>\n"
            f"delay: <code>{self._h(self.data.get('delay'))}</code>\n"
            f"timeout: <code>{self._h(self.data.get('timeout'))}</code>\n"
            f"gif_delay: <code>{self._h(self.data.get('gif_delay'))}</code>\n"
            f"gif_enabled: <code>{self._h(self.data.get('gif_enabled'))}</code>\n"
            f"media_items: <code>{len(self.data.get('media_items', []))}</code>\n"
            f"groups: <code>{len(self.data.get('groups', {}))}</code>\n"
            f"bots: <code>{len(self.data.get('bots', {}))}</code>\n"
            f"pending_group_id: <code>{self._h(gid_req)}</code>\n"
            f"me_id: <code>{self._h(self.me.id if self.me else None)}</code>\n"
        )
        await event.reply(debug_text, parse_mode="html")

    # ── Group ID capture ──────────────────────────
    async def send_group_id(self, event):
        try:
            chat_id = str(event.chat_id)
            chat = await event.get_chat()
            title = getattr(chat, "title", "گروه")

            req = self.data.get("get_group_id")
            if not req or not isinstance(req, dict) or not req.get("waiting"):
                return

            msg = (
                "<b>📌 آیدی گروه</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"عنوان: <code>{self._h(title)}</code>\n"
                f"آیدی: <code>{self._h(chat_id)}</code>\n\n"
                f"افزودن سریع: <code>.گروه اضافه {self._h(chat_id)}</code>"
            )
            await self.client.send_message("me", msg, parse_mode="html")
            self.data["get_group_id"] = None
            self.save_data()
            log.info("گروه ثبت شد | chat_id=%s title=%s", chat_id, title)
        except Exception:
            log.exception("send_group_id error | %s", self._debug_event_line(event))

    # ── Group / Bot management ────────────────────
    async def add_group(self, event, group_id):
        group_id = str(group_id).strip()
        if not group_id.startswith("-100"):
            await event.reply("❌ آیدی باید با <code>-100</code> شروع شود", parse_mode="html")
            return
        if group_id in self.data["groups"]:
            await event.reply("⚠️ قبلاً اضافه شده", parse_mode=None)
            return
        try:
            chat = await self.client.get_entity(int(group_id))
            title = getattr(chat, "title", "گروه")
            self.data["groups"][group_id] = {
                "title": title,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            self.save_data()
            await event.reply(f"✅ گروه <b>{self._h(title)}</b> اضافه شد", parse_mode="html")
        except Exception:
            log.exception("add_group error | group_id=%s", group_id)
            await event.reply("❌ گروه پیدا نشد. مطمئن شو آیدی درست است.", parse_mode=None)

    async def remove_group(self, event, group_id):
        group_id = str(group_id).strip()
        if group_id not in self.data["groups"]:
            await event.reply("❌ گروه وجود ندارد", parse_mode=None)
            return
        title = self.data["groups"][group_id]["title"]
        del self.data["groups"][group_id]
        self.save_data()
        await event.reply(f"🗑 گروه <b>{self._h(title)}</b> حذف شد", parse_mode="html")

    async def list_groups(self, event):
        if not self.data["groups"]:
            await event.reply("📭 هیچ گروهی ثبت نشده", parse_mode=None)
            return
        lines = ["<b>👥 گروه‌های ثبت‌شده</b>", "━━━━━━━━━━━━━━━━━━"]
        for i, (gid, info) in enumerate(self.data["groups"].items(), 1):
            title = self._h(info.get("title", "گروه"))
            lines.append(f"{i}. <b>{title}</b>")
            lines.append(f"آیدی: <code>{self._h(gid)}</code>")
            lines.append(f"تاریخ: <code>{self._h(info.get('date', ''))}</code>")
            lines.append(f"افزودن دوباره: <code>.گروه اضافه {self._h(gid)}</code>")
            lines.append("")
        await event.reply("\n".join(lines), parse_mode="html")

    async def add_bot(self, event):
        try:
            reply = await event.get_reply_message()
            sender = await reply.get_sender()
            if not getattr(sender, "bot", False):
                await event.reply("❌ این کاربر ربات نیست", parse_mode=None)
                return
            bot_id = str(sender.id)
            if bot_id in self.data["bots"]:
                await event.reply("⚠️ قبلاً اضافه شده", parse_mode=None)
                return
            info = {
                "name": sender.first_name or "ربات",
                "username": sender.username or "",
                "emojis": [],
                "texts": [],
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            self._apply_preset_to_bot(bot_id, info, overwrite=True)
            self.data["bots"][bot_id] = info
            self._refresh_bot_cache(bot_id)
            self._rebuild_bot_indexes()
            self.save_data()
            await event.reply(
                f"✅ ربات <b>{self._h(info['name'])}</b> اضافه شد\n"
                f"آیدی: <code>{self._h(bot_id)}</code>\n"
                f"کپی سریع: <code>.ایموجی اضافه {self._h(bot_id)} 😀</code>",
                parse_mode="html",
            )
        except Exception:
            log.exception("add_bot error | %s", self._debug_event_line(event))
            await event.reply("❌ خطا در افزودن ربات", parse_mode=None)

    async def remove_bot(self, event, bot_id):
        key = self._find_bot_key(bot_id)
        if not key:
            await event.reply("❌ ربات پیدا نشد", parse_mode=None)
            return
        name = self.data["bots"][key]["name"]
        del self.data["bots"][key]
        self._normalized_bot_texts.pop(key, None)
        self._rebuild_bot_indexes()
        self.save_data()
        await event.reply(f"🗑 ربات <b>{self._h(name)}</b> حذف شد", parse_mode="html")

    async def list_bots(self, event):
        if not self.data["bots"]:
            await event.reply("📭 هیچ رباتی ثبت نشده", parse_mode=None)
            return
        lines = ["<b>🤖 ربات‌های ثبت‌شده</b>", "━━━━━━━━━━━━━━━━━━"]
        for i, (bid, info) in enumerate(self.data["bots"].items(), 1):
            username = f"@{info['username']}" if info.get("username") else "-"
            lines.append(f"{i}. <b>{self._h(info.get('name', 'ربات'))}</b>")
            lines.append(f"آیدی: <code>{self._h(bid)}</code>")
            lines.append(f"یوزرنیم: <code>{self._h(username)}</code>")
            emoji_count = len(info.get('emojis', []))
            text_count = len(info.get('texts', []))
            lines.append(f"ایموجی‌ها: <code>{emoji_count}</code>")
            lines.append(f"متن‌ها: <code>{text_count}</code>")
            preset_flag = "✅" if self._get_preset_for_bot(bid) else "—"
            lines.append(f"پریست: <code>{preset_flag}</code>")
            if emoji_count:
                first_emojis = " ".join(info.get('emojis', [])[:5])
                lines.append(f"نمونه ایموجی‌ها: <code>{self._h(first_emojis)}</code>")
            lines.append(f"افزودن ایموجی: <code>.ایموجی اضافه {self._h(bid)} 😀</code>")
            lines.append(f"افزودن متن: <code>.پیام ثابت اضافه {self._h(bid)} متن</code>")
            lines.append("قانون: وجود یکی از ایموجی‌ها برای فعال شدن کچ کافی است.")
            lines.append("")
        await event.reply("\n".join(lines), parse_mode="html")

    async def apply_preset_command(self, event):
        if not event.message.reply_to_msg_id:
            await event.reply("❌ روی پیام ربات ریپلای کن تا پریست اعمال شود", parse_mode=None)
            return
        try:
            reply = await event.get_reply_message()
            sender = await reply.get_sender()
            bot_id = str(sender.id)
            key = self._find_bot_key(bot_id)
            if key:
                self._apply_preset_to_bot(key, self.data["bots"][key], overwrite=True)
                self._refresh_bot_cache(key)
                self._rebuild_bot_indexes()
                self.save_data()
                await event.reply(
                    f"✅ پریست برای <b>{self._h(self.data['bots'][key].get('name', 'ربات'))}</b> اعمال شد",
                    parse_mode="html",
                )
                return
            preset = self._get_preset_for_bot(bot_id)
            if not preset:
                await event.reply("❌ برای این ربات پیش‌فرضی تعریف نشده", parse_mode=None)
                return
            info = {
                "name": preset.get("name", sender.first_name or "ربات"),
                "username": preset.get("username", sender.username or ""),
                "emojis": list(preset.get("emojis", [])),
                "texts": list(preset.get("texts", [])),
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            self.data["bots"][bot_id] = info
            self.save_data()
            await event.reply(
                f"✅ پریست برای <b>{self._h(info['name'])}</b> ثبت شد",
                parse_mode="html",
            )
        except Exception:
            log.exception("خطا در apply_preset_command")
            await event.reply("❌ خطا در اعمال پریست", parse_mode=None)

    # ── Emoji methods ─────────────────────────────
    async def add_emoji(self, event, bot_id, emoji):
        key = self._find_bot_key(bot_id)
        if not key:
            await event.reply("❌ ربات پیدا نشد", parse_mode=None)
            return
        emojis = self.data["bots"][key].setdefault("emojis", [])
        if emoji in emojis:
            await event.reply("⚠️ ایموجی تکراری", parse_mode=None)
            return
        emojis.append(emoji)
        self._refresh_bot_cache(key)
        self.save_data()
        total = len(emojis)
        await event.reply(
            f"✅ ایموجی <b>{self._h(emoji)}</b> اضافه شد\n"
            f"📌 تعداد کل ایموجی‌های این ربات: <code>{total}</code>\n"
            f"🧠 این ربات وقتی یکی از ایموجی‌های ثبت‌شده را در پیام ببیند، اجازه کچ می‌گیرد.",
            parse_mode="html"
        )

    async def remove_emoji(self, event, bot_id, index_str):
        key = self._find_bot_key(bot_id)
        if not key:
            await event.reply("❌ ربات پیدا نشد", parse_mode=None)
            return
        try:
            idx = int(index_str) - 1
            emojis = self.data["bots"][key].get("emojis", [])
            if 0 <= idx < len(emojis):
                removed = emojis.pop(idx)
                self._refresh_bot_cache(key)
                self.save_data()
                await event.reply(
                    f"🗑 ایموجی <b>{self._h(removed)}</b> حذف شد\n"
                    f"📌 تعداد باقی‌مانده: <code>{len(emojis)}</code>",
                    parse_mode="html"
                )
            else:
                await event.reply("❌ شماره نامعتبر", parse_mode=None)
        except ValueError:
            await event.reply("❌ شماره باید عدد باشد", parse_mode=None)
        except Exception:
            log.exception("remove_emoji error | bot_id=%s", bot_id)
            await event.reply("❌ خطا در حذف ایموجی", parse_mode=None)

    async def list_emojis(self, event, bot_id):
        key = self._find_bot_key(bot_id)
        if not key:
            await event.reply("❌ ربات پیدا نشد", parse_mode=None)
            return
        emojis = self.data["bots"][key].get("emojis", [])
        if not emojis:
            await event.reply(
                "📭 هیچ ایموجی تنظیم نشده\n\n"
                "برای اضافه کردن از این فرمت استفاده کن:\n"
                "<code>.ایموجی اضافه 123456789 😀</code>",
                parse_mode="html"
            )
            return

        bot_name = self._h(self.data['bots'][key].get('name', 'ربات'))
        lines = [
            f"<b>🎭 جزئیات ایموجی‌های {bot_name}</b>",
            "━━━━━━━━━━━━━━━━━━",
            f"📌 <b>تعداد کل:</b> <code>{len(emojis)}</code>",
            "🧠 <b>رفتار فیلتر:</b> اگر یکی از ایموجی‌ها در پیام ربات باشد، کچ فعال می‌شود.",
            "🔎 <b>نکته:</b> ایموجی‌ها به صورت ترکیبی هم بررسی می‌شوند و لازم نیست همه‌شان در یک پیام باشند.",
            ""
        ]
        for i, em in enumerate(emojis, 1):
            cp = _emoji_codepoints(em)
            lines.append(f"{i}. {self._h(em)}")
            lines.append(f"   کاراکتر: <code>{self._h(em)}</code>")
            lines.append(f"   یونیکد: <code>{self._h(cp)}</code>")
            lines.append("")

        lines.append(f"➕ افزودن سریع: <code>.ایموجی اضافه {self._h(key)} 😀</code>")
        lines.append(f"🗑 حذف سریع: <code>.ایموجی حذف {self._h(key)} 1</code>")
        await event.reply("\n".join(lines), parse_mode="html")

    # ── Fixed text methods ────────────────────────
    async def add_fixed_text(self, event, bot_id, text):
        key = self._find_bot_key(bot_id)
        if not key:
            await event.reply("❌ ربات پیدا نشد", parse_mode=None)
            return
        texts = self.data["bots"][key].setdefault("texts", [])
        if text in texts:
            await event.reply("⚠️ متن تکراری", parse_mode=None)
            return
        texts.append(text)
        self._refresh_bot_cache(key)
        self.save_data()
        await event.reply("✅ متن اضافه شد", parse_mode=None)

    async def remove_fixed_text(self, event, bot_id, index_str):
        key = self._find_bot_key(bot_id)
        if not key:
            await event.reply("❌ ربات پیدا نشد", parse_mode=None)
            return
        try:
            idx = int(index_str) - 1
            texts = self.data["bots"][key].get("texts", [])
            if 0 <= idx < len(texts):
                removed = texts.pop(idx)
                self._refresh_bot_cache(key)
                self.save_data()
                await event.reply(
                    f"🗑 متن حذف شد: <code>{self._h(self._safe_preview(removed, 50))}</code>",
                    parse_mode="html",
                )
            else:
                await event.reply("❌ شماره نامعتبر", parse_mode=None)
        except ValueError:
            await event.reply("❌ شماره باید عدد باشد", parse_mode=None)
        except Exception:
            log.exception("remove_fixed_text error | bot_id=%s", bot_id)
            await event.reply("❌ خطا در حذف متن", parse_mode=None)

    async def list_fixed_texts(self, event, bot_id):
        key = self._find_bot_key(bot_id)
        if not key:
            await event.reply("❌ ربات پیدا نشد", parse_mode=None)
            return
        texts = self.data["bots"][key].get("texts", [])
        if not texts:
            await event.reply("📭 هیچ متنی تنظیم نشده", parse_mode=None)
            return
        msg = [f"<b>📝 متن‌های ثابت {self._h(self.data['bots'][key].get('name', 'ربات'))}</b>", "━━━━━━━━━━━━━━━━━━"]
        for i, t in enumerate(texts, 1):
            msg.append(f"{i}. <code>{self._h(self._safe_preview(t, 90))}</code>")
        await event.reply("\n".join(msg), parse_mode="html")

    # ── Media methods ─────────────────────────────
    async def register_media(self, event):
        if not event.message.reply_to_msg_id:
            await event.reply("❌ روی گیف/استیکر ریپلای کن و دوباره <code>.ثبت گیف</code> بفرست", parse_mode="html")
            return
        try:
            reply = await event.get_reply_message()
            if not getattr(reply, "media", None):
                await event.reply("❌ این پیام مدیا ندارد", parse_mode=None)
                return
            self.media_dir.mkdir(parents=True, exist_ok=True)
            saved = await reply.download_media(file=str(self.media_dir))
            if not saved:
                await event.reply("❌ دانلود مدیا موفق نبود", parse_mode=None)
                return
            saved_path = str(Path(saved).resolve())
            kind = "sticker" if getattr(reply, "sticker", None) else "gif"
            item = {
                "path": saved_path,
                "kind": kind,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            if any(x.get("path") == saved_path for x in self.data.get("media_items", [])):
                await event.reply("⚠️ این مدیا قبلاً ثبت شده", parse_mode=None)
                return
            self.data.setdefault("media_items", []).append(item)
            self.data["gif_enabled"] = True
            self.save_data()
            await event.reply(
                f"✅ {('استیکر' if kind == 'sticker' else 'گیف/مدیا')} ثبت شد\n<code>{self._h(saved_path)}</code>",
                parse_mode="html",
            )
        except Exception as e:
            log.exception("خطا در register_media | %s", self._debug_event_line(event))
            await event.reply(f"❌ خطا در ثبت مدیا: {html.escape(str(e)[:150], quote=False)}", parse_mode="html")

    async def list_media(self, event):
        items = self.data.get("media_items", [])
        if not items:
            await event.reply("📭 هیچ گیف/استیکری ثبت نشده", parse_mode=None)
            return
        lines = ["<b>🎞 لیست مدیاهای ثبت‌شده</b>", "━━━━━━━━━━━━━━━━━━"]
        for i, item in enumerate(items, 1):
            kind = item.get("kind", "media")
            path = item.get("path", "-")
            date = item.get("date", "-")
            lines.append(f"{i}. <b>{self._h(kind)}</b>")
            lines.append(f"فایل: <code>{self._h(Path(path).name)}</code>")
            lines.append(f"تاریخ: <code>{self._h(date)}</code>")
            lines.append(f"حذف: <code>.حذف گیف {i}</code>")
            lines.append("")
        await event.reply("\n".join(lines), parse_mode="html")

    async def remove_media(self, event, index_str):
        try:
            idx = int(index_str) - 1
            items = self.data.get("media_items", [])
            if 0 <= idx < len(items):
                removed = items.pop(idx)
                self.save_data()
                await event.reply(
                    f"🗑 مدیا حذف شد: <code>{self._h(Path(removed.get('path', '')).name)}</code>",
                    parse_mode="html",
                )
            else:
                await event.reply("❌ شماره نامعتبر", parse_mode=None)
        except ValueError:
            await event.reply("❌ شماره باید عدد باشد", parse_mode=None)
        except Exception as e:
            log.exception("خطا در remove_media")
            await event.reply(f"❌ خطا: {html.escape(str(e)[:120], quote=False)}", parse_mode="html")

    # ── Reaction logic ────────────────────────────
    async def maybe_react_to_message(self, event, chat_id, text):
        try:
            if not self.data.get("like_enabled") and not self.data.get("dislike_enabled"):
                return
            if not self.last_catch_time or not self.last_catch_chat_id or not self.last_catch_message_id:
                return
            if str(chat_id) != str(self.last_catch_chat_id):
                return
            sender = await event.get_sender()
            if sender and getattr(sender, "bot", False):
                return
            sender_id = getattr(sender, "id", None)
            if sender_id and self.me and sender_id == self.me.id:
                return
            msg_key = (str(chat_id), event.id)
            if not await self._mark_reacted(msg_key):
                return
            if not self._contains_reaction_keyword(text):
                return
            age = (datetime.now(timezone.utc) - self.last_catch_time).total_seconds()
            is_reply_to_me = getattr(event.message, "reply_to_msg_id", None) == self.last_catch_message_id
            should_react = False
            if is_reply_to_me and age <= REACTION_REPLY_WINDOW:
                should_react = True
            elif age <= REACTION_DIRECT_WINDOW:
                should_react = True
            if not should_react:
                return
            emoji = self._reaction_emoji()
            if not emoji:
                return
            reacted = await self._react_to_message(chat_id, event.id, emoji)
            if reacted:
                print(f"💬 ریکشن {emoji} روی پیام {event.id} ارسال شد")
        except Exception:
            log.exception("maybe_react_to_message error | %s", self._debug_event_line(event))

    # ── Catch logic ───────────────────────────────
    async def process_bot_message(self, event, chat_id):
        try:
            sender = await event.get_sender()
            bot_id = str(event.sender_id or getattr(sender, "id", "") or "").strip()
            text = event.raw_text or event.message.message or event.message.text or ""

            if not bot_id or bot_id not in self.data["bots"]:
                return

            bot = self.data["bots"].get(bot_id)
            if not bot:
                return

            texts = bot.get("texts", [])
            if not texts:
                return

            emojis = bot.get("emojis", [])
            norm_text = self._normalize(text)

            emoji_ok = True if not emojis else any(em in text for em in emojis)
            norm_texts = self._normalized_bot_texts.get(bot_id)
            if norm_texts is None:
                norm_texts = [self._normalize(t) for t in texts if t]
                self._normalized_bot_texts[bot_id] = norm_texts
            text_ok = any(t in norm_text for t in norm_texts)

            group_title = self.data["groups"].get(chat_id, {}).get("title", chat_id)
            log.info("پیام بررسی شد | bot=%s chat=%s emoji_ok=%s text_ok=%s", bot.get("name", "ربات"), group_title, emoji_ok, text_ok)

            if not emoji_ok or not text_ok:
                return

            msg_key = (chat_id, event.id)
            if not await self._mark_processed(msg_key):
                return

            print(f"🎯 قابل کچ! تاخیر {self.data['delay']} ثانیه...")
            await asyncio.sleep(self.data["delay"])
            await self.process_catch(event)

        except Exception:
            log.exception("process_bot_message error | %s", self._debug_event_line(event))

    async def process_catch(self, event):
        async with self.catch_lock:
            try:
                print("📨 ارسال پیام به ربات کچ به صورت فوروارد واقعی...")

                start_time = datetime.now(timezone.utc)

                try:
                    forwarded = await self.client.forward_messages(TARGET_BOT, event.message)
                except Exception:
                    try:
                        forwarded = await self.client.send_message(TARGET_BOT, event.message, parse_mode=None)
                    except Exception:
                        if getattr(event.message, "media", None):
                            forwarded = await self.client.send_file(
                                TARGET_BOT,
                                event.message.media,
                                caption=(event.raw_text or event.message.message or event.message.text or ""),
                            )
                        else:
                            raise

                if isinstance(forwarded, list):
                    if not forwarded:
                        print("⚠️ ارسال به ربات کچ خالی برگشت")
                        return
                    forwarded_msg = forwarded[0]
                else:
                    forwarded_msg = forwarded

                forwarded_msg_id = getattr(forwarded_msg, "id", None)
                print(f"COPY OK | sent_msg_id={forwarded_msg_id}")

                total_timeout = float(self.data.get("timeout", DEFAULT_TIMEOUT))

                while True:
                    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                    if elapsed >= total_timeout:
                        print("⏰ تایم‌اوت تمام شد")
                        return

                    remaining = total_timeout - elapsed
                    try:
                        reply_event = await asyncio.wait_for(self.target_queue.get(), timeout=remaining)
                    except asyncio.TimeoutError:
                        print("⏰ تایم‌اوت در انتظار پاسخ")
                        return

                    if self.me and reply_event.sender_id == self.me.id:
                        print("⏭ پیام خودمان نادیده گرفته شد")
                        continue

                    reply_dt = self._as_utc(getattr(reply_event.message, "date", None))
                    if reply_dt and reply_dt <= start_time:
                        print("⏭ پیام قدیمی نادیده گرفته شد")
                        continue

                    if forwarded_msg_id and getattr(reply_event.message, "reply_to_msg_id", None) not in (None, forwarded_msg_id):
                        # اگر بات به پیام فورواردشده جواب مستقیم داده باشد، باید اولویت داشته باشد.
                        # در غیر این صورت فقط بر اساس زمان و محتوای معتبر ادامه می‌دهیم.
                        print("ℹ️ پیام دریافتی ریپلای مستقیم نیست، ولی برای بررسی نگه داشته شد")

                    reply_text = (
                        reply_event.raw_text
                        or reply_event.message.message
                        or reply_event.message.text
                        or ""
                    )

                    print(f"📥 دریافتی از کچ بات:\n{reply_text[:700]}")

                    extracted = self.extract_catch_command(reply_text)
                    print(f"🧩 پیام قابل ارسال: {repr(extracted)}")

                    if not extracted:
                        print("⚠️ هنوز پیام معتبر با / پیدا نشد، ادامه...")
                        continue

                    print(f"📤 در حال ارسال پیام کامل به گروه | chat_id={event.chat_id}")
                    try:
                        sent = await self.client.send_message(event.chat_id, extracted, parse_mode=None)
                        print(f"🚀 پیام ارسال شد | sent_id={sent.id}")

                        if self.data.get("delete_after_send"):
                            try:
                                await sent.delete()
                                print("🗑 پیام کچ پاک شد")
                            except Exception as del_err:
                                log.warning("خطا در حذف پیام | %s", del_err)

                        self.last_catch_time = datetime.now(timezone.utc)
                        self.last_catch_chat_id = str(event.chat_id)
                        self.last_catch_message_id = sent.id

                        if self.data.get("gif_enabled") and self.data.get("media_items"):
                            asyncio.create_task(self._delayed_send_random_media(event.chat_id))

                        return
                    except Exception:
                        log.exception("خطا در ارسال پیام به گروه | chat_id=%s", event.chat_id)
                        return

            except Exception:
                log.exception("خطا در process_catch | %s", self._debug_event_line(event))

    @staticmethod
    def extract_catch_command(text):
        if not text:
            return None
        clean_text = re.sub(r"[\u200B\u200C\u200D\uFEFF\u00A0]", "", text)
        clean_text = clean_text.replace("`", "").strip()
        if not clean_text:
            return None

        lines = [line.strip() for line in clean_text.split("\n") if line.strip()]
        if any(line.startswith("/") for line in lines):
            return clean_text

        if clean_text.startswith("/"):
            return clean_text

        return None

    async def _delayed_send_random_media(self, chat_id):
        try:
            async with self.media_lock:
                await asyncio.sleep(float(self.data.get("gif_delay", DEFAULT_GIF_DELAY)))
                if not self.data.get("gif_enabled"):
                    return
                items = list(self.data.get("media_items", []))
                if not items:
                    return
                if not self.client:
                    return

                item = self._pick_random_media(items)
                if not item:
                    return

                kind = item.get("kind", "media")
                sent = await self.client.send_file(chat_id, item["path"], force_document=False)
                log.info(
                    "مدیا ارسال شد | chat_id=%s kind=%s path=%s sent=%s",
                    chat_id,
                    kind,
                    item["path"],
                    getattr(sent, "id", None),
                )
        except Exception:
            log.exception("خطا در ارسال مدیای رندوم | chat_id=%s", chat_id)

    async def queue_worker(self):
        while True:
            try:
                await asyncio.sleep(60)
                async with self.state_lock:
                    self._maybe_cleanup_state_locked(datetime.now(timezone.utc))
            except Exception:
                log.exception("queue_worker error | uid=%s", self.user_id)



# ================== SELLER BOT ==================
# کلاینت بات در main ساخته می‌شود تا با همان event loop اجرا شود.
bot: Optional[TelegramClient] = None

# ---------- Keyboards ----------
def _user_home_keyboard():
    return [
        [Button.text('فعال سازی', resize=True), Button.text('وضعیت', resize=True)],
        [Button.text('انصراف', resize=True)],
    ]


def _activation_keyboard():
    return [
        [Button.request_phone('ارسال شماره', resize=True, single_use=True)],
        [Button.text('انصراف', resize=True)],
    ]


def _owner_keyboard():
    return [
        [Button.text('🧾 ساخت لایسنس', resize=True), Button.text('♻️ تمدید اشتراک', resize=True)],
        [Button.text('⛔ متوقف کردن', resize=True), Button.text('👥 لیست کاربران', resize=True)],
        [Button.text('📩 دریافت سنشن ها', resize=True), Button.text('📢 پیام همگانی', resize=True)],
        [Button.text('↩️ انصراف', resize=True)],
    ]


def _renew_mode_keyboard():
    return [
        [Button.text('افزایش روز', resize=True), Button.text('کسر روز', resize=True)],
        [Button.text('↩️ انصراف', resize=True)],
    ]


def _cancel_inline_keyboard(prefix: str = 'owner_cancel'):
    return [[Button.inline('❌ لغو', prefix.encode())]]


def _confirm_inline_keyboard(confirm_data: bytes, cancel_data: bytes = b'owner_cancel'):
    return [[Button.inline('✅ تأیید', confirm_data), Button.inline('❌ لغو', cancel_data)]]


def _menu_key(text: str) -> str:
    text = unicodedata.normalize('NFKC', text or '')
    text = re.sub(r'[\u200B\u200C\u200D\uFEFF\u00A0]', '', text)
    text = re.sub(r'\s+', ' ', text).strip().casefold()
    return text


def _emoji_codepoints(value: str) -> str:
    try:
        return ' '.join(f'U+{ord(ch):04X}' for ch in value)
    except Exception:
        return '-'


def _is_private_text(event) -> bool:
    try:
        return bool(event.is_private and (event.raw_text is not None or event.message))
    except Exception:
        return False


def _days_left(expire_ts: float) -> int:
    try:
        remaining = max(0, float(expire_ts) - datetime.now().timestamp())
        return int(remaining // 86400)
    except Exception:
        return 0


def _license_valid(uid: int) -> bool:
    user = license_db['users'].get(uid)
    return bool(user and datetime.now().timestamp() < float(user.get('expire', 0)))


def _user_status_lines(uid: int) -> str:
    user = license_db['users'].get(uid, {})
    session = _active_runtime_session(uid)
    active = bool(session)
    phone = user.get('phone') or 'ثبت نشد'
    session_state = "فعال" if active else "غیرفعال"
    return (
        f'👤 <b>نام کاربر:</b> <code>{html.escape(str(user.get("name", "-")), quote=False)}</code>\n'
        f'🆔 <b>آیدی کاربر:</b> <code>{uid}</code>\n'
        f'🤖 <b>وضعیت سلف:</b> <code>{"✅️" if active else "❌️"} ({session_state})</code>\n'
        f'⏳ <b>مدت زمان:</b> <code>{_days_left(user.get("expire", 0))} روز</code>\n'
        f'📱 <b>شماره:</b> <code>{html.escape(str(phone), quote=False)}</code>\n'
        f'✨ <b>وضعیت کلی:</b> <code>{"فعال" if active else "غیرفعال"}</code>'
    )

def _cancel_session(uid: int):
    if uid in active_sessions:
        session = active_sessions.pop(uid, None)
        try:
            collector = (session or {}).get("collector")
            if collector:
                try:
                    asyncio.create_task(collector._stop_keepalive_task())
                except Exception:
                    pass
        except Exception:
            pass
        try:
            client = (session or {}).get("client")
            if client and client.is_connected():
                asyncio.create_task(client.disconnect())
        except Exception:
            pass

def _mark_started(uid: int, name: str = "-", phone: str = None):
    try:
        license_db.setdefault("started_users", {})
        license_db["started_users"][str(uid)] = {
            "name": name or "-",
            "phone": phone or "",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        save_license(license_db)
    except Exception:
        pass

def _active_runtime_session(uid: int):
    session = active_sessions.get(uid)
    if not session:
        return None
    if session.get("stage") != "active":
        return None
    client = session.get("client")
    if not client:
        return None
    try:
        if not client.is_connected():
            return None
    except Exception:
        return None
    return session

def _is_cancel_key(key: str) -> bool:
    return key in {"انصراف", "لغو", "↩️ انصراف", "❌ لغو"} or key.endswith("انصراف") or key.endswith("لغو")

def _clean_license_db_shapes():
    license_db.setdefault("licenses", {})
    license_db.setdefault("users", {})
    license_db.setdefault("started_users", {})


def _is_sticker_message(message) -> bool:
    try:
        if getattr(message, 'sticker', None):
            return True

        media = getattr(message, 'media', None)
        if not media:
            return False

        document = getattr(media, 'document', None)
        if not document:
            return False

        mime_type = getattr(document, 'mime_type', None) or ''
        if mime_type in {'image/webp', 'application/x-tgsticker', 'video/webm'}:
            return True

        attrs = getattr(document, 'attributes', None) or []
        for attr in attrs:
            name = attr.__class__.__name__
            if name in {'DocumentAttributeSticker', 'DocumentAttributeCustomEmoji'}:
                return True

        return any(token in str(type(media)).lower() for token in ('sticker', 'document'))
    except Exception:
        return False


def _runtime_state_load() -> dict:
    if not os.path.exists(RUNTIME_STATE_FILE):
        return {}
    try:
        with open(RUNTIME_STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _runtime_state_save(data: dict):
    try:
        tmp = RUNTIME_STATE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data if isinstance(data, dict) else {}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, RUNTIME_STATE_FILE)
    except Exception:
        pass


async def _apply_downtime_to_licenses():
    state = _runtime_state_load()
    last_heartbeat = state.get('last_heartbeat')
    try:
        last_heartbeat = float(last_heartbeat)
    except Exception:
        last_heartbeat = None
    if not last_heartbeat:
        _runtime_state_save({'last_heartbeat': datetime.now(timezone.utc).timestamp()})
        return

    now_ts = datetime.now(timezone.utc).timestamp()
    downtime = max(0.0, now_ts - last_heartbeat)
    if downtime < 1:
        _runtime_state_save({'last_heartbeat': now_ts})
        return

    changed = False
    for uid, user in license_db.get('users', {}).items():
        try:
            expire = float(user.get('expire', 0) or 0)
        except Exception:
            continue
        if expire > last_heartbeat:
            remaining = expire - last_heartbeat
            if remaining < 86400:
                user['expire'] = now_ts + 86400
            else:
                user['expire'] = expire + downtime
            changed = True

    if changed:
        save_license(license_db)
    _runtime_state_save({'last_heartbeat': now_ts})


async def _restore_active_sessions_from_storage():
    restored = 0
    for uid, user in list(license_db.get('users', {}).items()):
        try:
            uid_int = int(uid)
        except Exception:
            continue
        if not _license_valid(uid_int):
            continue
        session_str = user.get('session')
        if not session_str:
            continue
        if _active_runtime_session(uid_int):
            continue
        try:
            client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                continue

            collector = AutoCatchBot(uid)
            await collector.start_collector(client)
            me = await client.get_me()
            active_sessions[uid_int] = {
                'stage': 'active',
                'client': client,
                'collector': collector,
                'phone': user.get('phone'),
                'session_str': session_str,
                'started_at': datetime.now().timestamp(),
            }
            restored += 1
            log.info('سشن بازیابی شد | uid=%s me=%s', uid_int, getattr(me, 'id', None))
        except Exception:
            log.exception('restore session failed | uid=%s', uid)
    if restored:
        log.info('تعداد سشن‌های بازیابی‌شده: %s', restored)


async def _send_home(event, text: str):
    await event.reply(text, buttons=_user_home_keyboard(), parse_mode='html')


async def _send_activation_prompt(event):
    await event.reply(
        '🚀 <b>اتصال به اکانت تلگرام</b>\n\n'
        'برای ادامه فقط از دکمه <b>ارسال شماره</b> استفاده کن.\n'
        'شماره فقط از طریق خود تلگرام و با تأیید کاربر پذیرفته می‌شود.',
        buttons=_activation_keyboard(),
        parse_mode='html',
    )


async def _finish_login(uid: int, session: dict, event):
    client = session['client']
    phone = session.get('phone')
    collector = AutoCatchBot(uid)
    await collector.start_collector(client)

    try:
        session_str = client.session.save()
    except Exception:
        session_str = None

    active_sessions[uid] = {
        'stage': 'active',
        'client': client,
        'collector': collector,
        'phone': phone,
        'session_str': session_str,
        'started_at': datetime.now().timestamp(),
    }

    if uid in license_db['users']:
        license_db['users'][uid]['phone'] = phone
        license_db['users'][uid]['name'] = (
            getattr(await client.get_me(), 'first_name', None) or license_db['users'][uid].get('name') or '-'
        )
        if session_str:
            license_db['users'][uid]['session'] = session_str
        save_license(license_db)

    await event.reply(
        '✅ <b>اکانت فعال شد!</b>\n'
        'دستور <code>.پنل</code> را در اکانت اصلی خود بزنید.',
        buttons=_user_home_keyboard(),
        parse_mode='html',
    )


async def _cancel_active_flow(uid: int, event, msg: str = '✅ عملیات لغو شد.'):
    _cancel_session(uid)
    await event.reply(msg, buttons=_user_home_keyboard(), parse_mode='html')


async def start_handler(event):
    uid = event.sender_id
    if uid == OWNER_ID:
        await event.reply('🛠 <b>پنل مالک</b> را با دستور <code>/owner</code> باز کن.', parse_mode='html')
        return

    _mark_started(uid, getattr(getattr(event, 'sender', None), 'first_name', None) or '-', None)

    if _license_valid(uid):
        active = uid in active_sessions and active_sessions[uid].get('stage') == 'active'
        user = license_db['users'].get(uid, {})
        days_left = _days_left(user.get('expire', 0))
        phone = user.get('phone') or 'ثبت نشد'
        await event.reply(
            '✅ <b>اشتراک شما فعال است</b>\n\n'
            f'⏳ <b>باقی‌مانده:</b> <code>{days_left} روز</code>\n'
            f'📱 <b>شماره:</b> <code>{html.escape(str(phone), quote=False)}</code>\n'
            f'🤖 <b>وضعیت سلف:</b> <code>{"✅️" if active else "❌️"}</code>',
            buttons=_user_home_keyboard(),
            parse_mode='html',
        )
        return

    await _send_home(
        event,
        '👋 <b>خوش آمدی</b>\n\n'
        'برای فعال‌سازی، اول کد لایسنس را بفرست یا از دکمه‌های پایین استفاده کن.',
    )


async def owner_panel(event):
    if event.sender_id != OWNER_ID:
        return
    await event.reply(
        '🛠 <b>پنل مالک</b>\n\n'
        '👑 اینجا می‌توانی لایسنس بسازی، تمدید کنی، اشتراک را متوقف کنی و لیست کاربران را ببینی.\n'
        '🎛 همه دکمه‌ها ثابت و پایین صفحه هستند تا کار سریع‌تر و تمیزتر پیش برود.\n'
        '📢 پیام همگانی هم از همین‌جا قابل ارسال است.\n\n'
        '🧭 از دکمه‌های پایین استفاده کن.',
        buttons=_owner_keyboard(),
        parse_mode='html'
    )


async def activate_self_callback(event):
    uid = event.sender_id
    if not _license_valid(uid):
        return await event.answer('اشتراک منقضی شده یا وجود ندارد', alert=True)
    if _active_runtime_session(uid):
        return await event.answer('سلف از قبل فعال است', alert=True)
    user = license_db['users'].get(uid, {})
    if user.get('session'):
        try:
            client = TelegramClient(StringSession(user['session']), API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                await _finish_login(uid, {'client': client, 'phone': user.get('phone')}, event)
                return await event.answer('سشن قبلی فعال شد', alert=False)
            await client.disconnect()
        except Exception:
            log.exception('خطا در بازیابی سنشن ذخیره‌شده | uid=%s', uid)
    await event.answer('برای ادامه شماره را با دکمه ارسال کن')
    await _send_activation_prompt(event)


async def status_callback(event):
    uid = event.sender_id
    if uid not in license_db['users']:
        return await event.answer('اشتراکی یافت نشد.', alert=True)
    user = license_db['users'][uid]
    days_left = _days_left(user.get('expire', 0))
    phone = user.get('phone') or 'ثبت نشد'
    active = uid in active_sessions and active_sessions[uid].get('stage') == 'active'
    await event.reply(
        '📊 <b>وضعیت حساب</b>\n\n' + _user_status_lines(uid),
        buttons=_user_home_keyboard(),
        parse_mode='html',
    )
    await event.answer('اطلاعات وضعیت ارسال شد', alert=False)


async def owner_cancel(event):
    if event.sender_id != OWNER_ID:
        return await event.answer('فقط مالک', alert=True)
    _cancel_session(OWNER_ID)
    try:
        await event.edit('لغو شد.', buttons=_owner_keyboard(), parse_mode='html')
    except Exception:
        await event.answer('لغو شد', alert=False)


async def owner_create_start(event):
    if event.sender_id != OWNER_ID:
        return await event.answer('فقط مالک', alert=True)
    active_sessions[OWNER_ID] = {'stage': 'owner_create_days', 'started_at': datetime.now().timestamp()}
    await event.respond('📅 تعداد روزهای اعتبار را بفرستید:', buttons=[[Button.text('↩️ انصراف', resize=True)]], parse_mode='html')


async def owner_renew_start(event):
    if event.sender_id != OWNER_ID:
        return await event.answer('فقط مالک', alert=True)
    active_sessions[OWNER_ID] = {'stage': 'owner_renew_mode', 'started_at': datetime.now().timestamp()}
    await event.respond(
        '🔁 نوع تمدید را انتخاب کن:\n\n'
        '➕ <b>افزایش روز</b> برای اضافه کردن اعتبار\n'
        '➖ <b>کسر روز</b> برای کم کردن اعتبار',
        buttons=_renew_mode_keyboard(),
        parse_mode='html'
    )


async def owner_stop_start(event):
    if event.sender_id != OWNER_ID:
        return await event.answer('فقط مالک', alert=True)
    active_sessions[OWNER_ID] = {'stage': 'owner_stop_uid', 'started_at': datetime.now().timestamp()}
    await event.respond('🆔 آیدی عددی کاربر را بفرستید:', buttons=[[Button.text('↩️ انصراف', resize=True)]], parse_mode='html')


async def owner_list(event):
    if event.sender_id != OWNER_ID:
        return await event.answer('فقط مالک', alert=True)
    if not license_db['users']:
        return await event.answer('هیچ کاربری ثبت نشده.', alert=True)

    lines = ['<b>📋 لیست کاربران</b>', '━━━━━━━━━━━━━━━━━━']
    for uid, data in license_db['users'].items():
        remaining = max(0, float(data.get('expire', 0)) - datetime.now().timestamp())
        days_left = int(remaining // 86400)
        phone = data.get('phone') or 'ثبت نشد'
        active = uid in active_sessions and active_sessions[uid].get('stage') == 'active'
        lines.append(f'🆔 <code>{uid}</code> | 📱 <code>{html.escape(str(phone), quote=False)}</code> | ⏳ <code>{days_left}</code> روز | 🤖 <code>{"✅️" if active else "❌️"}</code>')

    await event.reply('\n'.join(lines), parse_mode='html')
    await event.answer('لیست کاربران ارسال شد', alert=False)


async def private_text_router(event):
    uid = event.sender_id
    if uid == OWNER_ID:
        return
    text = (event.raw_text or '').strip()
    key = _menu_key(text)

    # Stage-based handling first
    if uid in active_sessions and active_sessions[uid].get('stage') in {'waiting_phone', 'waiting_code', 'waiting_password'}:
        session = active_sessions[uid]

        if key in {'انصراف', 'لغو'}:
            return await _cancel_active_flow(uid, event)

        if session.get('stage') == 'waiting_phone':
            contact = getattr(event.message, 'contact', None)
            media = getattr(event.message, 'media', None)
            if contact is None and media is not None and hasattr(media, 'phone_number'):
                contact = media

            if contact is None:
                return await event.reply(
                    '❌ فقط از دکمه <b>ارسال شماره</b> استفاده کن.\n'
                    'شماره دستی پذیرفته نمی‌شود.',
                    buttons=_activation_keyboard(),
                    parse_mode='html',
                )

            phone_number = str(getattr(contact, 'phone_number', '') or '').strip()
            contact_user_id = getattr(contact, 'user_id', None)
            if contact_user_id not in (None, 0, uid):
                return await event.reply(
                    '❌ این شماره به خودت تعلق ندارد.\n'
                    'لطفاً فقط شماره خودت را با دکمه بفرست.',
                    buttons=_activation_keyboard(),
                    parse_mode='html',
                )

            canonical_digits = re.sub(r'\D', '', phone_number)
            if canonical_digits.startswith('00'):
                canonical_digits = canonical_digits[2:]
            if canonical_digits.startswith('0') and len(canonical_digits) == 11:
                canonical_digits = '98' + canonical_digits[1:]
            if canonical_digits.startswith('98') and len(canonical_digits) >= 12:
                pass
            elif len(canonical_digits) == 10 and canonical_digits.startswith('9'):
                canonical_digits = '98' + canonical_digits
            elif len(canonical_digits) == 11 and canonical_digits.startswith('9'):
                canonical_digits = '98' + canonical_digits
            else:
                return await event.reply(
                    '❌ شماره معتبر نیست.\nنمونه درست: 98912xxxxxxx یا +98912xxxxxxx',
                    buttons=_activation_keyboard(),
                    parse_mode='html',
                )

            phone_for_login = '+' + canonical_digits if not canonical_digits.startswith('+') else canonical_digits

            try:
                client = TelegramClient(StringSession(), API_ID, API_HASH)
                await client.connect()
                sent = await client.send_code_request(phone_for_login)
                session.update({
                    'client': client,
                    'phone': phone_for_login,
                    'hash': sent.phone_code_hash,
                    'stage': 'waiting_code',
                })
                await event.reply(
                    '⏳ <b>در حال اتصال...</b>\n\n'
                    '✅ کد ارسالی را با فاصله وارد کنید\n'
                    'مثال: <code>1 2 3 4 5</code>',
                    buttons=[[Button.text('انصراف', resize=True)]],
                    parse_mode='html',
                )
            except Exception as e:
                _cancel_session(uid)
                await event.reply(
                    f'❌ خطا در ارسال کد: <code>{html.escape(str(e)[:180], quote=False)}</code>',
                    buttons=_user_home_keyboard(),
                    parse_mode='html',
                )
            return

        if session.get('stage') == 'waiting_code':
            code_raw = re.sub(r'\s+', '', text)
            if not re.fullmatch(r'\d{5,6}', code_raw or ''):
                return await event.reply(
                    '❌ کد باید فقط عدد باشد و با فاصله ارسال شود.\nمثال: <code>1 2 3 4 5</code>',
                    buttons=[[Button.text('انصراف', resize=True)]],
                    parse_mode='html',
                )
            try:
                await session['client'].sign_in(session['phone'], code_raw, phone_code_hash=session['hash'])
                return await _finish_login(uid, session, event)
            except SessionPasswordNeededError:
                session['stage'] = 'waiting_password'
                return await event.reply(
                    '🔐 <b>رمز دو مرحله‌ای را وارد کنید:</b>',
                    buttons=[[Button.text('انصراف', resize=True)]],
                    parse_mode='html',
                )
            except Exception as e:
                await event.reply(
                    f'❌ کد نادرست یا منقضی شده: <code>{html.escape(str(e)[:180], quote=False)}</code>',
                    buttons=[[Button.text('انصراف', resize=True)]],
                    parse_mode='html',
                )
            return

        if session.get('stage') == 'waiting_password':
            try:
                await session['client'].sign_in(password=text)
                return await _finish_login(uid, session, event)
            except Exception as e:
                return await event.reply(
                    f'❌ رمز اشتباه: <code>{html.escape(str(e)[:180], quote=False)}</code>',
                    buttons=[[Button.text('انصراف', resize=True)]],
                    parse_mode='html',
                )

    # Home menu handling
    if key in {'فعال سازی', 'فعال‌سازی'}:
        if not _license_valid(uid):
            return await event.reply(
                '⛔ <b>اشتراک معتبر ندارید</b>\n\n'
                'اول کد لایسنس را ارسال کنید.',
                buttons=_user_home_keyboard(),
                parse_mode='html',
            )
        if uid in active_sessions and active_sessions[uid].get('stage') == 'active':
            return await event.reply(
                '✅ <b>سلف قبلاً فعال است</b>',
                buttons=_user_home_keyboard(),
                parse_mode='html',
            )
        active_sessions[uid] = {'stage': 'waiting_phone', 'started_at': datetime.now().timestamp()}
        return await _send_activation_prompt(event)

    if key == 'وضعیت':
        if uid not in license_db['users']:
            return await event.reply(
                '📭 <b>هنوز اشتراکی ثبت نشده</b>\n\nکد لایسنس را ارسال کن.',
                buttons=_user_home_keyboard(),
                parse_mode='html',
            )
        return await event.reply(
            '📊 <b>وضعیت حساب</b>\n\n' + _user_status_lines(uid),
            buttons=_user_home_keyboard(),
            parse_mode='html',
        )

    if _is_cancel_key(key):
        if uid in active_sessions and active_sessions[uid].get('stage') in {'waiting_phone', 'waiting_code', 'waiting_password'}:
            return await _cancel_active_flow(uid, event)
        return await event.reply('✅ چیزی برای لغو وجود ندارد.', buttons=_user_home_keyboard(), parse_mode='html')

    # License code input
    if uid in active_sessions and active_sessions[uid].get('stage') == 'active':
        return
    if text.startswith('/'):
        return

    code_raw = re.sub(r'\s+', '', text or '').upper()
    if not re.fullmatch(r'[A-Z0-9]{4,24}', code_raw or ''):
        return
    code = code_raw

    if code in license_db['licenses'] and not license_db['licenses'][code].get('used'):
        days = int(license_db['licenses'][code].get('days', 0))
        expire = datetime.now() + timedelta(days=days)
        try:
            me = await bot.get_me()
            name = getattr(me, 'first_name', None) or '-'
        except Exception:
            name = '-'
        license_db['users'][uid] = {
            'expire': expire.timestamp(),
            'phone': None,
            'name': name,
            'session': license_db['users'].get(uid, {}).get('session'),
        }
        license_db['licenses'][code]['used'] = True
        save_license(license_db)
        return await event.reply(
            f'✅ <b>اشتراک {days} روزه فعال شد!</b>\n\n'
            'حالا روی دکمه <b>فعال سازی</b> بزن.',
            buttons=_user_home_keyboard(),
            parse_mode='html',
        )

    await event.reply('❌ کد لایسنس نامعتبر یا قبلاً استفاده شده.', buttons=_user_home_keyboard(), parse_mode='html')


async def owner_text_router(event):
    key = _menu_key(event.raw_text or '')
    session = active_sessions.get(OWNER_ID, {})
    stage = session.get('stage')

    if _is_cancel_key(key):
        _cancel_session(OWNER_ID)
        return await event.reply('✅ عملیات لغو شد.', buttons=_owner_keyboard(), parse_mode='html')

    if stage == 'owner_broadcast_wait_content':
        content = (event.raw_text or '').strip()
        if not content and not getattr(event.message, 'media', None):
            return await event.reply('❌ یک پیام، استیکر یا گیف بفرست.', buttons=[[Button.text('↩️ انصراف', resize=True)]], parse_mode='html')
        session['broadcast'] = {
            'text': content,
            'has_media': bool(getattr(event.message, 'media', None)),
            'media_path': None,
            'caption': content if content else None,
            'kind': 'text' if content and not getattr(event.message, 'media', None) else 'media',
            'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        }
        if getattr(event.message, 'media', None):
            try:
                tmp_dir = Path('broadcast_tmp')
                tmp_dir.mkdir(parents=True, exist_ok=True)
                saved = await event.message.download_media(file=str(tmp_dir))
                session['broadcast']['media_path'] = str(saved) if saved else None
            except Exception as e:
                log.exception('broadcast download failed')
                return await event.reply(f'❌ خطا در آماده‌سازی پیام: <code>{html.escape(str(e)[:150], quote=False)}</code>', buttons=_owner_keyboard(), parse_mode='html')
        active_sessions[OWNER_ID] = session
        preview = '📢 <b>پیش‌نمایش پیام همگانی</b>\n\n'
        if session['broadcast']['kind'] == 'text':
            preview += html.escape(content, quote=False)
        else:
            preview += 'یک مدیا/استیکر برای ارسال آماده شد.\n\nاین پیام برای همه کاربران و خود مالک ارسال می‌شود.'
        return await event.reply(
            preview,
            buttons=_confirm_inline_keyboard(b'owner_broadcast_send', b'owner_cancel'),
            parse_mode='html',
        )

    # منوی ثابت مالک
    if not stage:
        if key in {'🧾 ساخت لایسنس', 'ساخت لایسنس'}:
            active_sessions[OWNER_ID] = {'stage': 'owner_create_days', 'started_at': datetime.now().timestamp()}
            return await event.reply(
                '📅 تعداد روزهای اعتبار را بفرستید:',
                buttons=[[Button.text('↩️ انصراف', resize=True)]],
                parse_mode='html'
            )

        if key in {'♻️ تمدید اشتراک', 'تمدید', 'تمدید اشتراک'}:
            active_sessions[OWNER_ID] = {'stage': 'owner_renew_mode', 'started_at': datetime.now().timestamp()}
            return await event.reply(
                '🔁 نوع تمدید را انتخاب کن:\n\n'
                '➕ <b>افزایش روز</b> برای اضافه کردن اعتبار\n'
                '➖ <b>کسر روز</b> برای کم کردن اعتبار',
                buttons=_renew_mode_keyboard(),
                parse_mode='html'
            )

        if key in {'⛔ متوقف کردن', 'متوقف کردن'}:
            active_sessions[OWNER_ID] = {'stage': 'owner_stop_uid', 'started_at': datetime.now().timestamp()}
            return await event.reply(
                '🆔 آیدی عددی کاربر را بفرستید:',
                buttons=[[Button.text('↩️ انصراف', resize=True)]],
                parse_mode='html'
            )

        if key in {'👥 لیست کاربران', 'لیست کاربران'}:
            active_users = [
                (uid, data) for uid, data in license_db['users'].items()
                if _license_valid(uid) and _active_runtime_session(uid)
            ]
            if not active_users:
                return await event.reply('📭 کاربر فعالِ در حال اجرا نداریم.', buttons=_owner_keyboard(), parse_mode='html')

            lines = ['<b>📋 لیست کاربران فعال</b>', '━━━━━━━━━━━━━━━━━━']
            for uid, data in active_users:
                remaining = max(0, float(data.get('expire', 0)) - datetime.now().timestamp())
                days_left = int(remaining // 86400)
                phone = data.get('phone') or 'ثبت نشد'
                lines.append(
                    f'🆔 <code>{uid}</code> | 📱 <code>{html.escape(str(phone), quote=False)}</code> | '
                    f'⏳ <code>{days_left}</code> روز | 🤖 <code>✅️</code>'
                )

            return await event.reply('\n'.join(lines), buttons=_owner_keyboard(), parse_mode='html')
        if key in {'📩 دریافت سنشن ها', 'دریافت سنشن ها'}:
            return await _send_active_sessions_file(event)
        if key in {'📢 پیام همگانی', 'پیام همگانی'}:
            active_sessions[OWNER_ID] = {'stage': 'owner_broadcast_wait_content', 'started_at': datetime.now().timestamp()}
            return await event.reply(
                '📣 <b>پیام همگانی</b>\n\n'
                'حالا متن، استیکر یا گیف مورد نظر را بفرست.\n'
                'بعدش تأیید می‌گیری و همان محتوا بدون فوروارد برای همه کاربرانِ استارت‌زده ارسال می‌شود.',
                buttons=[[Button.text('↩️ انصراف', resize=True)]],
                parse_mode='html'
            )

    if stage == 'owner_create_days':
        try:
            days = int((event.raw_text or '').strip())
            if days <= 0:
                raise ValueError
        except Exception:
            return await event.reply('❌ فقط یک عدد صحیح مثبت بفرست.', buttons=[[Button.text('↩️ انصراف', resize=True)]], parse_mode='html')
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        license_db['licenses'][code] = {'days': days, 'used': False}
        save_license(license_db)
        _cancel_session(OWNER_ID)
        return await event.reply(
            f'✅ <b>کد اشتراک ساخته شد</b>\n\n<code>{code}</code>\n\n'
            f'مدت اعتبار: <code>{days}</code> روز',
            buttons=_owner_keyboard(),
            parse_mode='html',
        )

    if stage == 'owner_renew_mode':
        if key in {'افزایش روز', 'کسر روز'}:
            session = active_sessions.get(OWNER_ID, {})
            session['renew_mode'] = 'add' if key == 'افزایش روز' else 'sub'
            session['stage'] = 'owner_renew_uid'
            active_sessions[OWNER_ID] = session
            return await event.reply(
                '🆔 آیدی عددی کاربر را بفرستید:',
                buttons=[[Button.text('↩️ انصراف', resize=True)]],
                parse_mode='html'
            )
        return await event.reply(
            '❌ یکی از دکمه‌های زیر را انتخاب کن.',
            buttons=_renew_mode_keyboard(),
            parse_mode='html'
        )

    if stage == 'owner_renew_uid':
        try:
            uid = int((event.raw_text or '').strip())
        except Exception:
            return await event.reply('❌ آیدی معتبر نیست.', buttons=[[Button.text('↩️ انصراف', resize=True)]], parse_mode='html')
        if uid not in license_db['users']:
            _cancel_session(OWNER_ID)
            return await event.reply('❌ کاربر با این آیدی وجود ندارد.', buttons=_owner_keyboard(), parse_mode='html')
        renew_mode = active_sessions.get(OWNER_ID, {}).get('renew_mode', 'add')
        active_sessions[OWNER_ID] = {
            'stage': 'owner_renew_days',
            'uid': uid,
            'renew_mode': renew_mode,
            'started_at': datetime.now().timestamp()
        }
        days_left = _days_left(license_db['users'][uid].get('expire', 0))
        action_text = 'کم کردن' if renew_mode == 'sub' else 'اضافه کردن'
        return await event.reply(
            f'👤 <b>کاربر</b> <code>{uid}</code>\n'
            f'⏳ <b>روزهای باقی‌مانده:</b> <code>{days_left}</code>\n\n'
            f'📥 تعداد روز برای {action_text} را بفرستید:',
            buttons=[[Button.text('↩️ انصراف', resize=True)]],
            parse_mode='html',
        )

    if stage == 'owner_renew_days':
        try:
            add_days = int((event.raw_text or '').strip())
            if add_days <= 0:
                raise ValueError
        except Exception:
            return await event.reply('❌ عدد نامعتبر.', buttons=[[Button.text('↩️ انصراف', resize=True)]], parse_mode='html')
        uid = int(active_sessions[OWNER_ID]['uid'])
        renew_mode = active_sessions.get(OWNER_ID, {}).get('renew_mode', 'add')
        user = license_db['users'][uid]
        current_expire = datetime.fromtimestamp(float(user['expire']))
        delta_days = add_days if renew_mode == 'add' else -add_days
        new_expire = current_expire + timedelta(days=delta_days)
        user['expire'] = new_expire.timestamp()
        save_license(license_db)
        _cancel_session(OWNER_ID)
        verb = 'تمدید' if renew_mode == 'add' else 'کاهش'
        return await event.reply(
            f'✅ اشتراک کاربر <code>{uid}</code> {verb} شد.\n'
            f'تاریخ جدید: <code>{new_expire.strftime("%Y-%m-%d %H:%M")}</code>',
            buttons=_owner_keyboard(),
            parse_mode='html',
        )

    if stage == 'owner_stop_uid':
        try:
            uid = int((event.raw_text or '').strip())
        except Exception:
            return await event.reply('❌ آیدی نامعتبر.', buttons=[[Button.text('↩️ انصراف', resize=True)]], parse_mode='html')
        if uid not in license_db['users']:
            _cancel_session(OWNER_ID)
            return await event.reply('❌ کاربر یافت نشد.', buttons=_owner_keyboard(), parse_mode='html')
        active_sessions[OWNER_ID] = {'stage': 'owner_stop_confirm', 'uid': uid, 'started_at': datetime.now().timestamp()}
        return await event.reply(
            f'⚠️ <b>آیا مطمئنی اشتراک کاربر <code>{uid}</code> متوقف شود؟</b>',
            buttons=_confirm_inline_keyboard(b'owner_stop_confirm', b'owner_cancel'),
            parse_mode='html',
        )

async def owner_stop_confirm(event):
    if event.sender_id != OWNER_ID:
        return await event.answer('فقط مالک', alert=True)
    session = active_sessions.get(OWNER_ID, {})
    uid = session.get('uid')
    if not uid:
        return await event.answer('چیزی برای تأیید نیست', alert=True)
    if uid in license_db['users']:
        license_db['users'][uid]['expire'] = datetime.now().timestamp()
        save_license(license_db)
    if uid in active_sessions:
        try:
            client = active_sessions[uid].get('client')
            if client:
                await client.disconnect()
        except Exception:
            pass
        active_sessions.pop(uid, None)
    _cancel_session(OWNER_ID)
    await event.answer('متوقف شد', alert=False)
    await event.edit(
        f'🛑 اشتراک کاربر <code>{uid}</code> متوقف شد.',
        buttons=_owner_keyboard(),
        parse_mode='html',
    )


async def owner_broadcast_send(event):
    if event.sender_id != OWNER_ID:
        return await event.answer('فقط مالک', alert=True)
    session = active_sessions.get(OWNER_ID, {})
    payload = session.get('broadcast')
    if not payload:
        return await event.answer('پیامی برای ارسال نیست', alert=True)

    recipients = []
    seen = set()

    # همه کاربران ثبت‌شده + استارت‌زده + خود مالک
    source_ids = set([OWNER_ID])
    source_ids.update(license_db.get('users', {}).keys())
    source_ids.update(license_db.get('started_users', {}).keys())

    for uid in source_ids:
        try:
            uid_int = int(uid)
        except Exception:
            continue
        if uid_int in seen:
            continue
        seen.add(uid_int)
        recipients.append(uid_int)

    if not recipients:
        _cancel_session(OWNER_ID)
        return await event.edit('📭 هیچ کاربری برای ارسال نیست.', buttons=_owner_keyboard(), parse_mode='html')

    sent_count = 0
    fail_count = 0
    try:
        for uid in recipients:
            try:
                if payload.get('kind') == 'text':
                    await bot.send_message(uid, payload.get('text') or '', parse_mode=None)
                else:
                    media_path = payload.get('media_path')
                    if media_path and os.path.exists(media_path):
                        await bot.send_file(uid, media_path, caption=payload.get('caption') or None)
                    elif payload.get('text'):
                        await bot.send_message(uid, payload.get('text'), parse_mode=None)
                    else:
                        continue
                sent_count += 1
                await asyncio.sleep(0.03)
            except Exception:
                fail_count += 1
        return await event.edit(
            f'✅ پیام همگانی ارسال شد.\n'
            f'موفق: <code>{sent_count}</code>\n'
            f'ناموفق: <code>{fail_count}</code>',
            buttons=_owner_keyboard(),
            parse_mode='html',
        )
    finally:
        media_path = payload.get('media_path')
        if media_path and os.path.exists(media_path):
            try:
                os.remove(media_path)
            except Exception:
                pass
        _cancel_session(OWNER_ID)


async def _send_active_sessions_file(event):
    active = []
    for uid, session in active_sessions.items():
        if uid == OWNER_ID:
            continue
        if session.get('stage') != 'active':
            continue
        client = session.get('client')
        try:
            if not client or not client.is_connected():
                continue
        except Exception:
            continue
        user = license_db.get('users', {}).get(uid, {})
        active.append({
            'uid': uid,
            'name': user.get('name') or '-',
            'phone': user.get('phone') or '',
            'session': session.get('session_str') or user.get('session') or '',
            'expire': user.get('expire', 0),
            'started_at': session.get('started_at', 0),
        })

    if not active:
        return await event.reply('📭 سنشن فعالی برای ارسال وجود ندارد.', buttons=_owner_keyboard(), parse_mode='html')

    out_dir = Path('tmp_sessions_exports')
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = out_dir / f"active_sessions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    lines = []
    for item in active:
        lines.append(f"UID: {item['uid']}")
        lines.append(f"NAME: {item['name']}")
        lines.append(f"PHONE: {item['phone']}")
        lines.append(f"EXPIRE: {datetime.fromtimestamp(float(item['expire'])).strftime('%Y-%m-%d %H:%M:%S') if item['expire'] else '-'}")
        lines.append(f"SESSION: {item['session']}")
        lines.append('-' * 40)

    fname.write_text('\n'.join(lines), encoding='utf-8')
    msg = await event.reply('📎 فایل سنشن‌های فعال آماده شد و تا ۱ دقیقه دیگر حذف می‌شود.', file=str(fname), buttons=_owner_keyboard(), parse_mode='html')
    asyncio.create_task(_delete_file_later(fname, 60))
    return msg

async def _delete_file_later(path: Path, delay: int = 60):
    try:
        await asyncio.sleep(delay)
        if path.exists():
            path.unlink()
    except Exception:
        pass

async def owner_command_router(event):
    # نگه‌داری سازگاری با پیام‌های فرمانی، اگر لازم شد.
    if event.raw_text.strip() == '/owner':
        await event.reply('🛠 <b>پنل مالک</b>', buttons=_owner_keyboard(), parse_mode='html')



def register_bot_handlers(client: TelegramClient):
    client.add_event_handler(start_handler, events.NewMessage(pattern=r'^/start$'))
    client.add_event_handler(owner_panel, events.NewMessage(pattern=r'^/owner$'))
    client.add_event_handler(activate_self_callback, events.CallbackQuery(data=b'activate_self'))
    client.add_event_handler(status_callback, events.CallbackQuery(data=b'status'))
    client.add_event_handler(owner_cancel, events.CallbackQuery(data=b'owner_cancel'))
    client.add_event_handler(owner_create_start, events.CallbackQuery(data=b'owner_create'))
    client.add_event_handler(owner_renew_start, events.CallbackQuery(data=b'owner_renew'))
    client.add_event_handler(owner_stop_start, events.CallbackQuery(data=b'owner_stop'))
    client.add_event_handler(owner_list, events.CallbackQuery(data=b'owner_list'))
    client.add_event_handler(private_text_router, events.NewMessage(func=_is_private_text))
    client.add_event_handler(owner_text_router, events.NewMessage(func=lambda e: e.sender_id == OWNER_ID and _is_private_text(e)))
    client.add_event_handler(owner_stop_confirm, events.CallbackQuery(data=b'owner_stop_confirm'))
    client.add_event_handler(owner_broadcast_send, events.CallbackQuery(data=b'owner_broadcast_send'))
    client.add_event_handler(owner_command_router, events.NewMessage(func=lambda e: e.sender_id == OWNER_ID and e.is_private and e.text and e.text.startswith('/')))

async def _bot_keepalive_loop():
    try:
        await asyncio.sleep(random.uniform(5, 20))
        while True:
            try:
                if not bot.is_connected():
                    try:
                        await bot.connect()
                    except Exception:
                        pass
                if bot.is_connected():
                    try:
                        await bot(GetStateRequest())
                    except Exception:
                        pass
                if KEEPALIVE_URL:
                    try:
                        await _http_keepalive_once(KEEPALIVE_URL)
                    except Exception:
                        pass
            except Exception:
                pass
            await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception('bot keepalive loop error')


def _start_bot_keepalive_task():
    global BOT_KEEPALIVE_TASK
    if BOT_KEEPALIVE_TASK and not BOT_KEEPALIVE_TASK.done():
        return BOT_KEEPALIVE_TASK
    BOT_KEEPALIVE_TASK = asyncio.create_task(_bot_keepalive_loop())
    return BOT_KEEPALIVE_TASK


async def _stop_bot_keepalive_task():
    global BOT_KEEPALIVE_TASK
    task = BOT_KEEPALIVE_TASK
    BOT_KEEPALIVE_TASK = None
    if not task:
        return
    if not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass


async def _shutdown_all_sessions():
    for uid, session in list(active_sessions.items()):
        try:
            collector = session.get('collector')
            if collector:
                await collector._stop_keepalive_task()
        except Exception:
            pass
        try:
            client = session.get('client')
            if client and client.is_connected():
                await client.disconnect()
        except Exception:
            pass
        active_sessions.pop(uid, None)


async def maintenance_loop():
    while True:
        try:
            now = datetime.now(timezone.utc)
            # Clean stale pending flows
            stale_uids = []
            for uid, session in list(active_sessions.items()):
                if session.get('stage') != 'active':
                    started = session.get('started_at')
                    if started and (now.timestamp() - float(started)) > PENDING_FLOW_TTL.total_seconds():
                        stale_uids.append(uid)
                else:
                    if uid in license_db.get('users', {}):
                        exp = float(license_db['users'][uid].get('expire', 0) or 0)
                        if exp and now.timestamp() >= exp:
                            try:
                                client = session.get('client')
                                if client:
                                    await client.disconnect()
                            except Exception:
                                pass
                            stale_uids.append(uid)
            for uid in stale_uids:
                active_sessions.pop(uid, None)

            _runtime_state_save({'last_heartbeat': now.timestamp()})
        except Exception:
            log.exception('maintenance loop error')
        await asyncio.sleep(60)

# ================== MAIN ==================
async def main():
    global bot
    health_server = None
    maintenance_task = None
    bot_keepalive_task = None

    try:
        bot = TelegramClient('seller_bot', API_ID, API_HASH)
        register_bot_handlers(bot)

        # Health Server
        health_server = await _start_health_server(HTTP_HOST, PORT)
        sockets = health_server.sockets or []
        if sockets:
            sock_info = ", ".join(f"{sock.getsockname()[0]}:{sock.getsockname()[1]}" for sock in sockets)
        else:
            sock_info = f"{HTTP_HOST}:{PORT}"
        log.info(f"✅ Healthcheck server started on {sock_info}")

        await asyncio.sleep(0.8)   # تثبیت لوپ

        await bot.start(bot_token=BOT_TOKEN)
        log.info("✅ Seller Bot started successfully")

        await _apply_downtime_to_licenses()
        await _restore_active_sessions_from_storage()

        maintenance_task = asyncio.create_task(maintenance_loop())
        bot_keepalive_task = _start_bot_keepalive_task()

        print('🚀 ربات فروش + اتو کالکتور راه‌اندازی شد')
        await bot.run_until_disconnected()

    finally:
        for task in (maintenance_task, bot_keepalive_task):
            if task and not task.done():
                task.cancel()

        await asyncio.gather(
            *(t for t in (maintenance_task, bot_keepalive_task) if t is not None),
            return_exceptions=True,
        )

        await _shutdown_all_sessions()
        await _stop_bot_keepalive_task()

        if health_server:
            try:
                health_server.close()
                await health_server.wait_closed()
            except Exception:
                pass

        if bot:
            try:
                await bot.disconnect()
            except Exception:
                pass


if __name__ == '__main__':
    asyncio.run(main())
