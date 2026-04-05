# ═══════════════════════════════════════════════════════════════════════════
#  CDP v3.4.2  –  Nuitka-patched edition
#  Changes vs original:
#    • get_app_dir()        replaces Path(__file__).resolve().parent
#    • get_bundled_tool()   resolves ffmpeg/ffprobe next to the .exe first
#    • Entry-point guard    adds freeze_support + WindowsSelectorEventLoop
#
#  Build command (run once, inside the project folder):
#    pip install nuitka ordered-set zstandard
#    python -m nuitka --onefile --standalone ^
#           --enable-plugin=anti-bloat ^
#           --include-package=aiohttp ^
#           --include-package=aiohttp.http_websocket ^
#           --include-package=yarl ^
#           --include-package=multidict ^
#           --include-package=frozenlist ^
#           --include-package=aiosignal ^
#           --windows-console-mode=attach ^
#           --output-filename=CDP-v3.4.2.exe ^
#           CDP-v3.4.2-nuitka.py
#
#  After build: place ffmpeg.exe and ffprobe.exe in the same folder as
#  CDP-v3.4.2.exe — they will be found automatically via get_bundled_tool().
# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════
#  LAUNCHER GUARD  —  يجب تشغيله عبر Launcher.exe فقط
# ═══════════════════════════════════════════════════════════════════════
import hmac as _hmac, time as _time, hashlib as _hashlib, os as _os
import sys as _sys

def _verify_launcher() -> bool:
    _S = [0x43, 0x44, 0x50, 0x5F, 0x4C, 0x41, 0x55,
          0x4E, 0x43, 0x48, 0x5F, 0x4B, 0x45, 0x59,
          0x5F, 0x76, 0x33, 0x34, 0x32, 0x5F, 0x53,
          0x45, 0x43, 0x52, 0x45, 0x54, 0x5F, 0x58]
    _SECRET = bytes(_S)
    _ENV_TOKEN = 'CDP_LAUNCH_TOKEN'
    token = _os.environ.get(_ENV_TOKEN, '')
    if not token:
        return False
    # نافذة ±1  →  مهلة 90 ثانية بين Launcher و AppCore
    for delta in (0, -1, 1):
        slot = str(int(_time.time()) // 30 + delta).encode()
        expected = _hmac.new(_SECRET, slot, _hashlib.sha256).hexdigest()
        if _hmac.compare_digest(token, expected):
            return True
    return False

if not _verify_launcher():
    print()
    print("  ╔══════════════════════════════════════════════════╗")
    print("  ║  ✘  Direct launch is not allowed.               ║")
    print("  ║     Please run  Launcher.exe  instead.          ║")
    print("  ╚══════════════════════════════════════════════════╝")
    print()
    try:
        input("  Press Enter to exit...")
    except Exception:
        pass
    _sys.exit(1)

# نظّف المتغيرات المؤقتة
del _verify_launcher, _hmac, _time, _hashlib
_os.environ.pop('CDP_LAUNCH_TOKEN', None)   # امسح الـ token فوراً
_os.environ.pop('CDP_ROOT_DIR',    None)     # نظّف Root path أيضاً بعد قراءته
# ═══════════════════════════════════════════════════════════════════════


import re
import os
import sys
import json
import time
import base64
import asyncio
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path
from urllib.parse import quote, urlparse, parse_qs
from urllib.request import urlopen, Request
import aiohttp

# ┌─────────────────────────────────────────────────────────────────────────┐
# │  NUITKA COMPATIBILITY HELPERS                                           │
# │  get_app_dir()       → always returns the EXE's own directory          │
# │  get_bundled_tool()  → finds ffmpeg/ffprobe next to the EXE first      │
# └─────────────────────────────────────────────────────────────────────────┘

def get_app_dir() -> Path:
    """Return the ROOT working directory for all user-visible data.

    Priority:
      1. CDP_ROOT_DIR env var  — set by Launcher.exe to its own folder
         This means tools/ output/ logs/ temp/ all live next to Launcher.exe
         regardless of where AppCore/CDP-v3.4.2.exe is located.
      2. Compiled exe parent   — fallback when running AppCore standalone
         (goes up one level if exe lives inside an 'AppCore' subfolder)
      3. Script directory      — fallback for plain CPython runs
    """
    # 1. Launcher provided the root path → use it
    root_from_env = os.environ.get('CDP_ROOT_DIR', '').strip()
    if root_from_env:
        p = Path(root_from_env).resolve()
        if p.is_dir():
            return p

    # 2. Compiled exe
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent

    exe = Path(sys.executable).resolve()
    _py_stems = {
        'python', 'python3', 'pythonw', 'pythonw3',
        'python37', 'python38', 'python39',
        'python310', 'python311', 'python312',
    }
    if exe.stem.lower() not in _py_stems:
        exe_dir = exe.parent
        # If inside an 'AppCore' subfolder, go up to Root
        if exe_dir.name.lower() == 'appcore':
            return exe_dir.parent
        return exe_dir

    # 3. Plain CPython
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path.cwd()

def get_bundled_tool(name: str) -> str:
    """
    Resolve the path of an external binary (ffmpeg / ffprobe).

    Search order:
      1. Same directory as the running executable  (bundled alongside .exe)
      2. PATH  (system-wide install)

    Returns the resolved absolute path string, or just `name` as fallback
    so the original error message from subprocess is preserved.
    """
    exe_name = (name + '.exe') if os.name == 'nt' else name
    # 1. tools/ subfolder next to the exe  (preferred — keeps root clean)
    candidate = get_app_dir() / 'tools' / exe_name
    if candidate.is_file():
        return str(candidate)
    # 2. Same directory as the running exe  (legacy / flat layout)
    candidate = get_app_dir() / exe_name
    if candidate.is_file():
        return str(candidate)
    # 3. Anywhere on PATH
    found = shutil.which(name)
    if found:
        return found
    # 3. Fallback – let subprocess raise its own FileNotFoundError
    return name



def _safe_input(prompt: str = '') -> str:
    """input() that survives EOF / closed stdin in Nuitka standalone builds."""
    try:
        return input(prompt)
    except EOFError:
        if os.name == 'nt':
            try:
                sys.stdin = open('CONIN$', 'r')
                sys.stdout = open('CONOUT$', 'w')
                sys.stderr = open('CONOUT$', 'w')
                return input(prompt)
            except Exception:
                pass
        return ''
    except Exception:
        return ''
class C:
    RESET  = "\033[0m";  BOLD   = "\033[1m";  DIM    = "\033[2m"
    RED    = "\033[91m"; GREEN  = "\033[92m"; YELLOW = "\033[93m"
    BLUE   = "\033[94m"; CYAN   = "\033[96m"; WHITE  = "\033[97m"
    GRAY   = "\033[90m"

DEBUG_HOST = "127.0.0.1"
DEBUG_PORT = 9222
DEBUG_BASE = f"http://{DEBUG_HOST}:{DEBUG_PORT}"
CHROME_START_TIMEOUT = 25
MONITOR_TIMEOUT = 60
QUALITY_WAIT_SECONDS = 10
DEFAULT_SHOW_EVENT_LOGS = False
DEFAULT_SHOW_CAPTURE_LOGS = True
ATTACH_INIT_RETRIES = 3
ATTACH_INIT_DELAY = 0.25
LOGS_DIR_NAME = 'logs'
APP_VERSION = 'CDP v3.4.2'
APP_TAGLINE = '     Download - Merge Streams · By DEVTE'
QUALITY_PROMPT_OPTIONS = ['240p', '360p', '480p', '720p', '1080p', '1440p', '2160p', '4320p']
QUALITY_CAPTURE_TIMEOUT = 8.0
QUALITY_APPLY_ATTEMPTS = 3
QUALITY_MENU_OPEN_TIMEOUT = 2.5
PLAY_RETRY_ATTEMPTS = 5
PLAY_RETRY_STREAM_TIMEOUT = 2.5
PLAY_RETRY_DELAY = 0.0
PLAY_STATE_TIMEOUT = 1.4
MIN_PLAYER_READY_WAIT = 4.0
PLAYER_READY_STABLE_HITS = 6
UI_MODE_COMPACT = True
LOG_TO_FILE = True
SHOW_CONSOLE_DETAILS = False

OUTPUT_STATE = {
    'log_file_path': None,
'network_log_file_path': None,
    'last_ui_message': None,
    'run_started_at': None,
    'version_label': APP_VERSION,
    'stage_group': None,
    'stage_step': None,
    'stage_total': None,
    'stage_detail': None,
    'note': None,
    'warning': None,
    'progress': None,
    'rendered_lines': 0,
}

CHROME_STAGE_MAP = {
    'Chrome Profile Clone Mode': ('Preparing Chrome', 1, 7, 'Close Chrome'),
    'Cloning Profile': ('Preparing Chrome', 2, 7, 'Cloning profile'),
    'Remote Debugging': ('Preparing Chrome', 3, 7, 'Remote debugging'),
    'Target Preparation': ('Preparing Chrome', 4, 7, 'Preparing target'),
    'Connecting to Browser': ('Preparing Chrome', 5, 7, 'Connecting to browser'),
    'Monitoring Primed': ('Preparing Chrome', 6, 7, 'Priming monitor'),
    'Navigating': ('Preparing Chrome', 7, 7, 'Opening page'),
}

VIDEO_STAGE_MAP = {
    'Waiting for Player UI': ('Processing Video', 1, 10, 'Waiting for player UI'),
    'Auto Prime Playback': ('Processing Video', 2, 10, 'Auto play/pause'),
    'Monitoring Network': ('Processing Video', 3, 10, 'Monitoring network'),
    'Extracting Video Title': ('Processing Video', 4, 10, 'Extracting title'),
    'Quality Selection Window': ('Processing Video', 5, 10, 'Quality selection'),
    'Finalizing Captured URLs': ('Processing Video', 6, 10, 'Finalizing URLs'),
    'Selected Streams': ('Processing Video', 7, 10, 'Selecting streams'),
    'Merging Video & Audio': ('Processing Video', 10, 10, 'Merging output'),
}
# Chrome profile clone lives inside the exe's own temp/ folder
# (auto-created at runtime via get_app_dir() / "temp" / "chrome_clone")
CLONE_USER_DATA_DIR = None  # resolved at runtime in clone_profile_to_workdir()
REUSE_EXISTING_CLONE = True

BATCH_URL_LIST_FILENAME   = 'list-url.txt'
BATCH_DONE_LIST_FILENAME  = 'list-done.txt'
BATCH_ERROR_LIST_FILENAME = 'list-error.txt'
BATCH_OUTPUT_SUBDIR       = 'output'


ITAG_VIDEO_RANK = {
    "133": 1,  "134": 2,  "135": 3,  "136": 4,
    "137": 5,  "248": 6,  "264": 7,  "271": 8,
    "313": 9,  "315": 10, "272": 11,
}
ITAG_QUALITY_NAME = {
    "133": "240p",        "134": "360p",        "135": "480p",
    "136": "720p",        "137": "1080p",       "248": "1080p_WebM",
    "264": "1440p",       "271": "1440p_WebM",  "313": "2160p",
    "315": "2160p_60fps", "272": "4320p",
}

def normalize_quality_label(label):
    raw = str(label or '').strip()
    m = re.search(r'(\d+)p', raw.lower())
    if m:
        return f"{m.group(1)}p"
    if raw.lower() == 'auto':
        return 'auto'
    return raw


def quality_numeric_value(label):
    m = re.search(r'(\d+)p', normalize_quality_label(label).lower())
    return int(m.group(1)) if m else -1


def describe_quality_preference(preferred_quality):
    if not preferred_quality or preferred_quality.get('mode') == 'max':
        return 'Highest available quality'
    return preferred_quality.get('label', 'Highest available quality')


def prompt_user_quality_preference():
    print(f"\n  {C.CYAN}{C.BOLD}Choose preferred quality{C.RESET}")
    for idx, label in enumerate(QUALITY_PROMPT_OPTIONS, 1):
        end = '\n' if idx % 4 == 0 else '\t'
        print(f"  {idx}- {label}", end=end)
    if len(QUALITY_PROMPT_OPTIONS) % 4:
        print()
    print('  99- Highest available quality')
    while True:
        choice = _safe_input(f"\n  {C.CYAN}{C.BOLD}Choose quality number ›{C.RESET}  ").strip()
        if choice == '99':
            return {'mode': 'max', 'label': None}
        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(QUALITY_PROMPT_OPTIONS):
                return {'mode': 'exact', 'label': QUALITY_PROMPT_OPTIONS[idx - 1]}
        print(f"  {C.YELLOW}Invalid choice. Pick one of the listed numbers.{C.RESET}")


def get_last_captured_video_quality(state):
    if not state.get('video_urls'):
        return None, None
    last_itag = next(reversed(state['video_urls']))
    last_label = normalize_quality_label(ITAG_QUALITY_NAME.get(last_itag, f'itag_{last_itag}'))
    return last_itag, last_label


def select_preferred_quality_label_from_available(available_labels, preferred_quality):
    cleaned = []
    seen = set()
    for label in available_labels:
        norm = normalize_quality_label(label)
        if not norm or norm == 'auto' or norm in seen:
            continue
        cleaned.append(norm)
        seen.add(norm)
    cleaned.sort(key=quality_numeric_value)
    if not cleaned:
        return None, 'no-qualities'
    if not preferred_quality or preferred_quality.get('mode') == 'max':
        return cleaned[-1], 'highest-available'
    desired = normalize_quality_label(preferred_quality.get('label'))
    if desired in cleaned:
        return desired, 'exact-match'
    desired_value = quality_numeric_value(desired)
    lower_or_equal = [label for label in cleaned if quality_numeric_value(label) <= desired_value]
    if lower_or_equal:
        return lower_or_equal[-1], 'nearest-lower'
    return cleaned[0], 'lowest-above-fallback'


def pick_preferred_video_itag(video_urls, preferred_quality):
    if not video_urls:
        return None
    grouped = {}
    for itag in video_urls:
        label = normalize_quality_label(ITAG_QUALITY_NAME.get(itag, f'itag_{itag}'))
        grouped.setdefault(label, []).append(itag)
    available_labels = list(grouped.keys())
    target_label, _ = select_preferred_quality_label_from_available(available_labels, preferred_quality)
    if target_label and target_label in grouped:
        return max(grouped[target_label], key=lambda t: ITAG_VIDEO_RANK.get(t, 0))
    return max(video_urls, key=lambda t: ITAG_VIDEO_RANK.get(t, 0))


EXACT_SKIP = {
    'SingletonCookie', 'SingletonLock', 'SingletonSocket', 'lockfile',
    'DevToolsActivePort', 'Last Browser', 'Last Version', 'BrowserMetrics',
    'Crashpad', 'Crash Reports', 'lock', 'LOCK', 'Network Persistent State',
}
DIR_SKIP = {
    'Cache', 'Code Cache', 'GPUCache', 'GrShaderCache', 'ShaderCache',
    'DawnCache', 'component_crx_cache', 'Safe Browsing', 'OptimizationHints',
    'BrowserMetrics', 'Crashpad', 'Crash Reports', 'Service Worker\\CacheStorage',
}
CONTAINS_SKIP = {
    'Cookies', 'Cookies-journal', 'LOCK', 'lock', 'QuotaManager',
    'Affiliation Database', 'Account Web Data', 'Login Data', 'Login Data For Account',
    'Web Data', 'Top Sites', 'History', 'History-journal', 'Favicons',
    'Network Action Predictor', 'Network\\Trust Tokens', 'Network\\Reporting and NEL',
    'Device Bound Sessions', 'Safe Browsing Cookies', 'Shortcuts',
}
INTERESTING_TOKENS = [
    'mime=video', 'mime=audio', 'googlevideo', 'videoplayback', 'itag=',
    'range=', 'docid=', 'get_video_info', 'keepalive=yes', 'preview',
]

JS_FETCH_CHUNK_TEMPLATE = r"""
(async () => {
    const baseUrl = __BASE_URL__;
    const start = __START__;
    const end = __END__;
    const chunkN = __CHUNKN__;
    try {
        const url = baseUrl + '&alr=yes&range=' + start + '-' + end + '&rn=' + chunkN + '&rbuf=0';
        const resp = await fetch(url, {
            method: 'GET',
            credentials: 'include',
            headers: {
                'Accept': '*/*',
                'Accept-Encoding': 'identity',
                'Sec-Fetch-Dest': 'video',
                'Sec-Fetch-Mode': 'no-cors',
                'Sec-Fetch-Site': 'cross-site',
            }
        });
        if (resp.status === 416) return { eof: true, size: 0, totalSize: 0 };
        if (!resp.ok) return { error: resp.status + ' ' + resp.statusText };
        let totalSize = 0;
        const cr = resp.headers.get('content-range') || '';
        const m = cr.match(/\/([0-9]+)$/);
        if (m) totalSize = parseInt(m[1], 10);
        const buf = await resp.arrayBuffer();
        const u8 = new Uint8Array(buf);
        if (u8.length === 0) return { eof: true, size: 0, totalSize };
        let bin = '';
        const cs = 8192;
        for (let i = 0; i < u8.length; i += cs) {
            bin += String.fromCharCode(...u8.slice(i, i + cs));
        }
        return { ok: true, data: btoa(bin), size: u8.length, totalSize };
    } catch (e) {
        return { error: String(e) };
    }
})()
"""

class CDPClient:
    def __init__(self, websocket_url):
        self.websocket_url = websocket_url
        self.session = None
        self.ws = None
        self._next_id = 0
        self._pending = {}
        self._all_events = asyncio.Queue()
        self._receiver_task = None
        self._closed = False

    async def connect(self):
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(self.websocket_url, autoping=True, heartbeat=20)
        self._receiver_task = asyncio.create_task(self._receiver())

    async def close(self):
        self._closed = True
        if self._receiver_task:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()

    async def _receiver(self):
        try:
            async for msg in self.ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                payload = json.loads(msg.data)
                if 'id' in payload:
                    fut = self._pending.pop(payload['id'], None)
                    if fut and not fut.done():
                        fut.set_result(payload)
                else:
                    self._all_events.put_nowait(payload)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(e)
            self._pending.clear()
            if not self._closed:
                raise

    async def send(self, method, params=None, session_id=None):
        self._next_id += 1
        msg_id = self._next_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        payload = {"id": msg_id, "method": method, "params": params or {}}
        if session_id:
            payload['sessionId'] = session_id
        await self.ws.send_str(json.dumps(payload))
        result = await fut
        if 'error' in result:
            raise RuntimeError(f"CDP error in {method}: {result['error']}")
        return result.get('result', {})

    async def next_event(self, timeout=None):
        return await asyncio.wait_for(self._all_events.get(), timeout=timeout)


def strip_ansi(text_value):
    return re.sub(r'\x1b\[[0-9;]*m', '', str(text_value))

def init_log_file(script_dir):
    logs_dir = Path(script_dir) / LOGS_DIR_NAME
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime('%Y-%m-%d_%H-%M-%S')
    log_path = logs_dir / f'nve_{ts}.log'
    network_log_path = logs_dir / f'nve_network_{ts}.log'
    OUTPUT_STATE['log_file_path'] = log_path
    OUTPUT_STATE['network_log_file_path'] = network_log_path
    OUTPUT_STATE['run_started_at'] = time.time()
    log_path.write_text('', encoding='utf-8')
    network_log_path.write_text('', encoding='utf-8')
    write_log_line('SESSION', f"Started {OUTPUT_STATE['version_label']}")
    write_network_log_line('SESSION', f"Started {OUTPUT_STATE['version_label']}")
    return log_path

def write_log_line(level, message):
    if not LOG_TO_FILE:
        return
    log_path = OUTPUT_STATE.get('log_file_path')
    if not log_path:
        return
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    clean = strip_ansi(message)
    with open(log_path, 'a', encoding='utf-8') as fh:
        fh.write(f'[{ts}] [{level}] {clean}\n')

def write_network_log_line(level, message):
    if not LOG_TO_FILE:
        return
    log_path = OUTPUT_STATE.get('network_log_file_path')
    if not log_path:
        return
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    clean = strip_ansi(message)
    with open(log_path, 'a', encoding='utf-8') as fh:
        fh.write(f'[{ts}] [{level}] {clean}\n')

def log_exception(context, exc):
    write_log_line('ERROR', f'{context}: {exc}')
    write_log_line('TRACE', traceback.format_exc().rstrip())

def resolve_stage(title):
    if title in CHROME_STAGE_MAP:
        return CHROME_STAGE_MAP[title]
    if title in VIDEO_STAGE_MAP:
        return VIDEO_STAGE_MAP[title]
    if title.startswith('Downloading  Video'):
        return ('Processing Video', 8, 10, 'Downloading video')
    if title.startswith('Downloading  Audio'):
        return ('Processing Video', 9, 10, 'Downloading audio')
    return None

def ui_render():
    if not UI_MODE_COMPACT:
        return
    lines_out = []
    group = OUTPUT_STATE.get('stage_group')
    step = OUTPUT_STATE.get('stage_step')
    total = OUTPUT_STATE.get('stage_total')
    detail = OUTPUT_STATE.get('stage_detail')
    if group and step and total:
        msg = f'{group} ... {step}/{total}'
        if detail:
            msg += f'  {C.DIM}({detail}){C.RESET}'
        lines_out.append(f"  {C.BLUE}{C.BOLD}{msg}{C.RESET}")
        OUTPUT_STATE['last_ui_message'] = strip_ansi(msg)
    warning = OUTPUT_STATE.get('warning')
    note = OUTPUT_STATE.get('note')
    progress = OUTPUT_STATE.get('progress')
    if warning:
        lines_out.append(f"  {C.YELLOW}⚠   {warning}{C.RESET}")
    elif note:
        lines_out.append(f"  {C.CYAN}➜  {note}{C.RESET}")
    if progress:
        lines_out.append(progress)
    prev = OUTPUT_STATE.get('rendered_lines', 0)
    if prev:
        sys.stdout.write('\r')
        for idx in range(prev):
            sys.stdout.write('\x1b[2K')
            if idx < prev - 1:
                sys.stdout.write('\x1b[1A')
        sys.stdout.write('\r')
    else:
        sys.stdout.write('\n')
    if lines_out:
        sys.stdout.write('\n'.join(lines_out))
    sys.stdout.flush()
    OUTPUT_STATE['rendered_lines'] = len(lines_out)

def ui_clear_render(blank_line=True):
    prev = OUTPUT_STATE.get('rendered_lines', 0)
    if prev:
        sys.stdout.write('\r')
        for idx in range(prev):
            sys.stdout.write('\x1b[2K')
            if idx < prev - 1:
                sys.stdout.write('\x1b[1A')
        if blank_line:
            sys.stdout.write('\n')
        sys.stdout.flush()
    OUTPUT_STATE['rendered_lines'] = 0
    OUTPUT_STATE['note'] = None
    OUTPUT_STATE['warning'] = None
    OUTPUT_STATE['progress'] = None

def ui_stage(group, step, total, detail=None):
    OUTPUT_STATE['stage_group'] = group
    OUTPUT_STATE['stage_step'] = step
    OUTPUT_STATE['stage_total'] = total
    OUTPUT_STATE['stage_detail'] = detail
    OUTPUT_STATE['note'] = None
    OUTPUT_STATE['warning'] = None
    OUTPUT_STATE['progress'] = None
    ui_render()

def ui_note(message):
    OUTPUT_STATE['note'] = message
    OUTPUT_STATE['warning'] = None
    ui_render()

def ui_warn(message):
    OUTPUT_STATE['warning'] = message
    ui_render()

def ui_progress(message):
    OUTPUT_STATE['progress'] = message
    ui_render()

def ui_success(message):
    ui_clear_render()
    print(f"  {C.GREEN}{C.BOLD}✔  {message}{C.RESET}")

def ui_error(message):
    ui_clear_render()
    print(f"  {C.RED}{C.BOLD}✘  {message}{C.RESET}")
    if OUTPUT_STATE.get('log_file_path'):
        print(f"  {C.DIM}Details saved to: {OUTPUT_STATE['log_file_path']}{C.RESET}")


# ┌─────────────────────────────────────────────────────────────────────────┐
# │  UI UTILITIES  –  ANSI-safe width helpers + dynamic box/separator draw  │
# └─────────────────────────────────────────────────────────────────────────┘

def _ui_width():
    """
    Usable terminal column count for UI elements.
    Leaves a small left-indent margin; capped at 100 to stay readable on wide terminals.
    """
    return min(shutil.get_terminal_size((100, 24)).columns - 4, 100)


def _ui_vlen(s):
    """
    Visible terminal width of *s*:
      • strips ANSI escape codes (colour, bold, dim …)
      • counts wide Unicode characters (emoji, CJK, …) as 2 columns
    This is the single source of truth for all box-drawing width maths.
    """
    plain = strip_ansi(s)
    w = 0
    for ch in plain:
        cp = ord(ch)
        wide = (
            0x1100 <= cp <= 0x115F or   # Hangul Jamo
            0x2E80 <= cp <= 0x303E or   # CJK Radicals
            0x3040 <= cp <= 0xA4CF or   # CJK + Kana unified
            0xAC00 <= cp <= 0xD7AF or   # Hangul Syllables
            0xF900 <= cp <= 0xFAFF or   # CJK Compat
            0xFE10 <= cp <= 0xFE1F or   # Vertical Forms
            0xFE30 <= cp <= 0xFE6F or   # CJK Compat Forms
            0xFF00 <= cp <= 0xFF60 or   # Fullwidth Latin / Kana
            0xFFE0 <= cp <= 0xFFE6 or   # Fullwidth Signs
            0x1F004 <= cp <= 0x1FFFF or # Emoji (Misc Symbols & Pictographs+)
            cp in (                     # Misc Technical wide chars used in UI
                0x23F3, 0x23F0,         # ⏳⏰
                0x231A, 0x231B,         # ⌚⌛
                0x1F3AC,                # 🎬  (U+1F3AC CLAPPER BOARD)
                0x25FE, 0x2614, 0x2615,
                0x2648, 0x26CE, 0x26F5,
                0x2705, 0x270A, 0x270B,
                0x2728, 0x274C, 0x274E,
                0x2753, 0x2757, 0x2795,
                0x27B0, 0x27BF, 0x2B1B,
                0x2B1C, 0x2B50, 0x2B55,
            )
        )
        w += 2 if wide else 1
    return w


def _ui_sep(w=None):
    """Print one ───── separator line.  Width defaults to terminal width."""
    w = w or _ui_width()
    print(f"  {C.CYAN}{C.BOLD}{'─' * w}{C.RESET}")


def _ui_box_row(content, W):
    """
    Print one ║-bounded row inside a box of inner visible width W.
    *content* may contain ANSI codes; padding is computed from _ui_vlen.
    """
    pad = ' ' * max(0, W - _ui_vlen(content))
    print(f"  {C.CYAN}║{C.RESET}{content}{pad}{C.CYAN}║{C.RESET}")

def banner():
    """
    Print the main banner with a fully dynamic box width.
    Uses _ui_vlen() so the 🎬 emoji (wide: 2 cols) is counted correctly,
    and every ║ border aligns perfectly regardless of terminal font.
    """
    os.system('cls' if os.name == 'nt' else 'clear')

    # Build the two content strings (no colour codes → clean width calc)
    row1_plain = f"  🎬  Google Drive Video Extractor  {APP_VERSION}"
    row2_plain = f"  {APP_TAGLINE}"

    # Dynamic inner width: widest visible row + 2 breathing cols
    W = max(_ui_vlen(row1_plain), _ui_vlen(row2_plain)) + 2

    print()
    print(f"  {C.CYAN}{C.BOLD}╔{'═' * W}╗{C.RESET}")
    _ui_box_row(f"  {C.BOLD}🎬  Google Drive Video Extractor  {C.CYAN}{APP_VERSION}{C.RESET}", W)
    _ui_box_row(f"  {C.DIM}{APP_TAGLINE}{C.RESET}", W)
    print(f"  {C.CYAN}{C.BOLD}╚{'═' * W}╝{C.RESET}")
    print()

def log(icon, label, msg, color=C.WHITE):
    ts = time.strftime('%H:%M:%S')
    line = f'[{ts}] {label} {msg}'
    write_log_line('EVENT', line)
    if not UI_MODE_COMPACT or SHOW_CONSOLE_DETAILS:
        print(f"  {C.GRAY}[{ts}]{C.RESET} {icon}  {color}{C.BOLD}{label}{C.RESET}  {C.DIM}{msg}{C.RESET}")

def section(title):
    write_log_line('SECTION', title)
    stage = resolve_stage(title)
    if UI_MODE_COMPACT and stage:
        group, step, total, detail = stage
        ui_stage(group, step, total, detail)
    else:
        print(f"\n{C.BLUE}{C.BOLD}  ── {title} {'─' * max(0, _ui_width() - 6 - len(title))}{C.RESET}")

def success(msg):
    write_log_line('SUCCESS', msg)
    if not UI_MODE_COMPACT:
        print(f"\n  {C.GREEN}{C.BOLD}✔  {msg}{C.RESET}")
        return
    keep = ('Video only  →', 'All done!')
    if any(token in strip_ansi(msg) for token in keep):
        ui_success(msg)

def error(msg):
    write_log_line('ERROR', msg)
    ui_error(msg)

def info(msg):
    write_log_line('INFO', msg)
    if not UI_MODE_COMPACT or SHOW_CONSOLE_DETAILS:
        print(f"  {C.CYAN}➜  {msg}{C.RESET}")
def get_chrome_user_data_dir():
    if os.name == 'nt':
        local = os.environ.get('LOCALAPPDATA', '')
        return os.path.join(local, 'Google', 'Chrome', 'User Data') if local else ''
    if sys.platform == 'darwin':
        return os.path.expanduser('~/Library/Application Support/Google/Chrome')
    return os.path.expanduser('~/.config/google-chrome')

def detect_primary_profile(user_data_dir):
    if not user_data_dir or not os.path.isdir(user_data_dir):
        return None
    if os.path.isdir(os.path.join(user_data_dir, 'Default')):
        return 'Default'
    for name in sorted(os.listdir(user_data_dir)):
        if re.fullmatch(r'Profile\s+\d+', name) and os.path.isdir(os.path.join(user_data_dir, name)):
            return name
    return None

def get_chrome_executable():
    if os.name == 'nt':
        candidates = [
            os.path.join(os.environ.get('PROGRAMFILES', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Google', 'Chrome', 'Application', 'chrome.exe'),
        ]
        for p in candidates:
            if p and os.path.isfile(p):
                return p
        return 'chrome.exe'
    if sys.platform == 'darwin':
        return '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    for name in ['google-chrome', 'google-chrome-stable', 'chromium-browser', 'chromium']:
        path = shutil.which(name)
        if path:
            return path
    return 'google-chrome'

def prompt_close_original_chrome():
    OUTPUT_STATE['warning'] = 'Make sure original Chrome is fully closed before continuing.'
    ui_render()
    ui_clear_render(blank_line=False)
    _safe_input(f"  {C.CYAN}{C.BOLD}Close original Chrome, then press Enter to continue ›{C.RESET}  ")
    info('Continuing with profile clone launch ...')

def http_json(path, method='GET'):
    req = Request(DEBUG_BASE + path, headers={'Cache-Control': 'no-cache'}, method=method)
    with urlopen(req, timeout=3) as r:
        return json.loads(r.read().decode('utf-8', errors='replace'))

def wait_for_debug_endpoint(timeout=CHROME_START_TIMEOUT):
    end = time.time() + timeout
    last_err = None
    while time.time() < end:
        try:
            return http_json('/json/version')
        except Exception as e:
            last_err = e
            time.sleep(0.25)
    raise TimeoutError(f'Remote debugging endpoint not ready after {timeout}s: {last_err}')

def list_targets():
    return http_json('/json/list')

def close_target(target_id):
    try:
        http_json(f'/json/close/{target_id}')
        return True
    except Exception:
        return False

def activate_target(target_id):
    try:
        http_json(f'/json/activate/{target_id}')
        return True
    except Exception:
        return False

def new_target(url):
    encoded = quote(url, safe=':/?&=%#')
    return http_json(f'/json/new?{encoded}', method='PUT')

def filter_page_targets(targets):
    return [t for t in targets if t.get('type') == 'page']

def normalize_url(url):
    return url.strip()

def get_itag(url):
    return parse_qs(urlparse(url).query).get('itag', ['0'])[0]

def prepare_base_url(url):
    for param in ['range', 'rn', 'rbuf', 'ump', 'srfvp', 'alr']:
        url = re.sub(rf'[&?]{param}=[^&]*', '', url)
    return url

def safe_trunc(url, n=150):
    return url if len(url) <= n else url[:n] + '...'

def safe_filename(name):
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:120] if name else 'output'

def ensure_temp_dir(base_dir):
    temp_dir = Path(base_dir) / 'temp'
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir

def cleanup_temp_dir(temp_dir):
    temp_dir = Path(temp_dir)
    if temp_dir.exists():
        for item in temp_dir.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
            except Exception:
                pass
    temp_dir.mkdir(parents=True, exist_ok=True)


def progress_bar(done, total, width=40):
    if total > 0:
        pct = min(done / total, 1.0)
        filled = int(width * pct)
        bar = '█' * filled + '░' * (width - filled)
        size_str = f'{done/1024/1024:.1f} / {total/1024/1024:.1f} MB'
    else:
        pos = (done // (1024*1024)) % width
        bar = ('░' * pos + '▓▓▓' + '░' * (width - pos - 3))[:width]
        size_str = f'{done/1024/1024:.1f} MB (size unknown)'
        pct = 0
    return f'  {C.CYAN}[{bar}]{C.RESET} {C.BOLD}{pct*100:5.1f}%{C.RESET}  {size_str}'

def get_duration(filepath):
    r = subprocess.run([
        get_bundled_tool('ffprobe'), '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', filepath
    ], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0

def fmt_dur(s):
    return f'{int(s//3600):02d}:{int((s%3600)//60):02d}:{int(s%60):02d}'

def merge_video_audio(video_file, audio_file, output_file):
    video_file = Path(video_file)
    audio_file = Path(audio_file)
    output_file = Path(output_file)
    section('Merging Video & Audio')
    info(f'Video  →  {video_file}')
    info(f'Audio  →  {audio_file}')
    info(f'Output →  {C.WHITE}{C.BOLD}{output_file}{C.RESET}')
    v_dur = get_duration(str(video_file))
    a_dur = get_duration(str(audio_file))
    info(f'Video duration  →  {fmt_dur(v_dur)}')
    info(f'Audio duration  →  {fmt_dur(a_dur)}')
    diff = abs(v_dur - a_dur)
    if diff > 5:
        ui_warn(f'Duration mismatch detected: {diff:.1f}s difference.')
        error('Duration verification failed before merge.')
        return False
    else:
        write_log_line('INFO', 'Durations match before merge')
    total_dur = v_dur
    proc = subprocess.Popen([
        get_bundled_tool('ffmpeg'), '-y', '-i', str(video_file), '-i', str(audio_file),
        '-c:v', 'copy', '-c:a', 'copy', '-progress', 'pipe:1', '-nostats', str(output_file)
    ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
    width = 40
    current = {}
    start_t = time.time()
    for line in proc.stdout:
        line = line.strip()
        if '=' in line:
            k, _, v = line.partition('=')
            current[k.strip()] = v.strip()
        if 'out_time_us' in current:
            try:
                done_s = int(current['out_time_us']) / 1_000_000
                wall = max(time.time() - start_t, 0.001)
                speed = done_s / wall
                pct = min(done_s / total_dur, 1.0) if total_dur > 0 else 0
                filled = int(width * pct)
                bar = '█' * filled + '░' * (width - filled)
                size_kb = current.get('total_size', '0')
                size_mb = int(size_kb) / 1024 / 1024 if size_kb.isdigit() else 0
                ui_progress(f"  {C.CYAN}[{bar}]{C.RESET} {C.BOLD}{pct*100:5.1f}%{C.RESET}  {fmt_dur(done_s)} / {fmt_dur(total_dur)}  {C.YELLOW}{speed:.1f}x{C.RESET}  {C.DIM}{size_mb:.1f} MB{C.RESET}")
            except Exception:
                pass
        if current.get('progress') == 'end':
            break
    proc.wait()
    if proc.returncode == 0:
        out_dur = get_duration(str(output_file))
        success(f'Merge complete  →  {output_file}')
        info(f'Output duration  →  {fmt_dur(out_dur)}')
        if abs(out_dur - v_dur) > 5:
            ui_warn(f'Output duration differs from video by {abs(out_dur-v_dur):.1f}s')
            error('Output duration verification failed after merge.')
            if output_file.exists():
                output_file.unlink(missing_ok=True)
            return False
        else:
            write_log_line('INFO', 'Output duration verified')
        return True
    error('ffmpeg merge failed.')
    if output_file.exists():
        output_file.unlink(missing_ok=True)
    return False


def should_skip_name(name):
    if name in EXACT_SKIP:
        return True
    return any(token in name for token in CONTAINS_SKIP)

def resilient_copy_file(src, dst):
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)

def resilient_copy_tree(src_root, dst_root):
    copied = 0
    skipped = 0
    failed = []
    src_root = Path(src_root)
    dst_root = Path(dst_root)
    for root, dirs, files in os.walk(src_root):
        root_path = Path(root)
        rel_root = root_path.relative_to(src_root)
        dst_dir = dst_root / rel_root
        dst_dir.mkdir(parents=True, exist_ok=True)
        kept_dirs = []
        for d in dirs:
            if d in DIR_SKIP or should_skip_name(d):
                skipped += 1
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs
        for f in files:
            if should_skip_name(f):
                skipped += 1
                continue
            src_file = root_path / f
            dst_file = dst_dir / f
            try:
                resilient_copy_file(src_file, dst_file)
                copied += 1
            except Exception as e:
                failed.append((str(src_file), str(e)))
    return copied, skipped, failed

def clone_profile_to_workdir(force_rebuild=False):
    source_user_data = Path(get_chrome_user_data_dir())
    profile_name = detect_primary_profile(str(source_user_data))
    if not source_user_data.is_dir():
        raise RuntimeError('Chrome user data directory not found.')
    if not profile_name:
        raise RuntimeError('Primary Chrome profile not found.')
    source_profile = source_user_data / profile_name
    # Resolve clone directory at runtime: temp/ subfolder next to the exe
    clone_root = get_app_dir() / 'temp' / 'chrome_clone'
    clone_profile = clone_root / profile_name
    if REUSE_EXISTING_CLONE and not force_rebuild and clone_profile.exists():
        return {
            'source_user_data': str(source_user_data), 'profile_name': profile_name,
            'clone_user_data_dir': str(clone_root), 'copied_files': 0,
            'skipped_items': 0, 'failed_files': [], 'reused_existing_clone': True,
        }
    if clone_root.exists():
        shutil.rmtree(clone_root, ignore_errors=True)
    clone_root.mkdir(parents=True, exist_ok=True)
    copied_meta = 0
    for name in ['Local State', 'First Run']:
        src = source_user_data / name
        dst = clone_root / name
        if src.exists():
            try:
                resilient_copy_file(src, dst)
                copied_meta += 1
            except Exception:
                pass
    copied, skipped, failed = resilient_copy_tree(source_profile, clone_profile)
    return {
        'source_user_data': str(source_user_data), 'profile_name': profile_name,
        'clone_user_data_dir': str(clone_root), 'copied_files': copied + copied_meta,
        'skipped_items': skipped, 'failed_files': failed, 'reused_existing_clone': False,
    }

def launch_chrome_with_cloned_profile(clone_user_data_dir, profile_dir):
    chrome = get_chrome_executable()
    cmd = [
        chrome, f'--remote-debugging-port={DEBUG_PORT}',
        f'--user-data-dir={clone_user_data_dir}', f'--profile-directory={profile_dir}',
        '--new-window', '--no-first-run', '--no-default-browser-check', 'about:blank',
    ]
    creationflags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) if os.name == 'nt' else 0
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)


def close_launched_chrome(proc, wait_seconds=3.0):
    pid = getattr(proc, 'pid', None) if proc else None
    result = {
        'ok': False,
        'pid': pid,
        'initial_poll': (proc.poll() if proc else None),
        'method': 'not-run',
    }
    try:
        if not proc:
            result.update({'ok': True, 'method': 'no-proc'})
            return result
        if os.name == 'nt' and pid:
            force = subprocess.run(
                ['taskkill', '/PID', str(pid), '/T', '/F'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(int(wait_seconds), 1),
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
            time.sleep(0.8)
            result.update({
                'ok': force.returncode == 0 or proc.poll() is not None,
                'method': 'taskkill-tree-force',
                'force_rc': force.returncode,
                'final_poll': proc.poll(),
            })
            return result
        try:
            proc.terminate()
        except Exception:
            pass
        time.sleep(min(wait_seconds, 1.0))
        if proc.poll() is None:
            proc.kill()
            time.sleep(0.3)
        result.update({
            'ok': proc.poll() is not None,
            'method': 'terminate-kill',
            'final_poll': proc.poll(),
        })
        return result
    except Exception as e:
        result.update({'ok': False, 'method': 'exception', 'error': str(e), 'final_poll': (proc.poll() if proc else None)})
        return result

def choose_or_create_root_target(target_url):
    pages = filter_page_targets(list_targets())
    if not pages:
        return new_target(target_url)
    target = pages[0]
    for extra in pages[1:]:
        tid = extra.get('id')
        if tid:
            close_target(tid)
    activate_target(target.get('id'))
    return target


def maybe_mark_readiness(url, state, source=''):
    try:
        if not url:
            return False
        url_s = str(url)
        if 'play.google.com/log?format=json&hasfast=true&authuser=0' in url_s:
            write_network_log_line('TRACE', f'READINESS_MATCH source={source or "unknown"} url={url_s}')
            state['readiness_seen'] = True
            state['readiness_url'] = url_s
            state['readiness_source'] = source or 'unknown'
            if state.get('readiness_first_seen_ts') is None:
                state['readiness_first_seen_ts'] = time.time()
            readiness_event = state.get('readiness_event')
            if readiness_event and not readiness_event.is_set():
                readiness_event.set()
            return True
        return False
    except Exception as e:
        write_network_log_line('TRACE', f'READINESS_ERROR source={source or "unknown"} err={e!r}')
        raise

def build_monitor_state(root_target_id=None):
    return {
        'root_target_id': root_target_id,
        'root_session_id': None,
        'sessions': {},
        'video_urls': {},
        'audio_urls': {},
        'video_found': False,
        'request_urls': {},
        'request_event_count': 0,
        'response_event_count': 0,
        'interesting_request_count': 0,
        'interesting_response_count': 0,
        'last_interesting_request': None,
        'last_interesting_response': None,
        'last_registered_video': None,
        'last_registered_audio': None,
        'readiness_seen': False,
        'readiness_url': '',
        'readiness_source': '',
        'readiness_event': asyncio.Event(),
        'readiness_first_seen_ts': None,
        'raw_printed': set(),
        'candidate_printed': set(),
        'initialized_sessions': set(),
        'log_limit': 160,
        'log_count': 0,
        'debug_network': False,
        'show_event_logs': DEFAULT_SHOW_EVENT_LOGS,
        'show_capture_logs': DEFAULT_SHOW_CAPTURE_LOGS,
    }

def session_key(session_id, request_id):
    return f'{session_id}:{request_id}'

def is_interesting_url(url):
    u = url.lower()
    return any(token in u for token in INTERESTING_TOKENS)

def register_video(url, state, session_id, reason='url-match', headers=None):
    itag = get_itag(url)
    quality = ITAG_QUALITY_NAME.get(itag, f'itag {itag}')
    if itag not in state['video_urls']:
        color = C.GREEN if ITAG_VIDEO_RANK.get(itag, 0) >= 5 else C.YELLOW
        if state.get('show_capture_logs'):
            log('🎬', 'VIDEO', f'{quality}  (itag={itag})  ← {reason}', color)
    state['video_urls'][itag] = {'url': url, 'session_id': session_id, 'headers': headers or {}}
    state['last_registered_video'] = {
        'itag': itag,
        'quality': normalize_quality_label(quality),
        'url': url,
        'session_id': session_id,
        'reason': reason,
        'ts': round(time.time(), 3),
    }
    state['video_found'] = True

def register_audio(url, state, session_id, reason='url-match', headers=None):
    itag = get_itag(url)
    if itag not in state['audio_urls']:
        if state.get('show_capture_logs'):
            log('🔊', 'AUDIO', f'itag={itag}  ← {reason}', C.BLUE)
    state['audio_urls'][itag] = {'url': url, 'session_id': session_id, 'headers': headers or {}}
    state['last_registered_audio'] = {
        'itag': itag,
        'url': url,
        'session_id': session_id,
        'reason': reason,
        'ts': round(time.time(), 3),
    }

def maybe_log_raw(url, state, session_id, resource_type='', source='REQ'):
    if not state.get('debug_network'):
        return
    if state['log_count'] >= state['log_limit']:
        return
    if not is_interesting_url(url) and resource_type not in ('Media', 'XHR', 'Fetch', 'Other', 'Ping', 'Preflight'):
        return
    key = (source, session_id, url)
    if key in state['raw_printed']:
        return
    state['raw_printed'].add(key)
    state['log_count'] += 1
    target_type = state['sessions'].get(session_id, {}).get('type', 'unknown')
    log('🌐', 'RAW', f'{source} {target_type}/{resource_type or "-"}  {safe_trunc(url)}', C.GRAY)

def maybe_log_candidate(url, state, session_id, reason):
    if not state.get('debug_network'):
        return
    key = (session_id, url, reason)
    if key in state['candidate_printed']:
        return
    state['candidate_printed'].add(key)
    target_type = state['sessions'].get(session_id, {}).get('type', 'unknown')
    log('🧩', 'CAND', f'{target_type}  {reason}  {safe_trunc(url)}', C.CYAN)

def handle_request_event(event, state):
    session_id = event.get('sessionId')
    params = event.get('params', {})
    request = params.get('request', {})
    url = request.get('url', '')
    request_id = params.get('requestId', '')
    resource_type = params.get('type', '')
    headers = request.get('headers', {}) or {}
    if not url:
        return
    state['request_event_count'] = state.get('request_event_count', 0) + 1
    if request_id:
        state['request_urls'][session_key(session_id, request_id)] = url
    maybe_mark_readiness(url, state, 'request')
    maybe_log_raw(url, state, session_id, resource_type, 'REQ')
    if 'mime=video' in url:
        state['interesting_request_count'] = state.get('interesting_request_count', 0) + 1
        state['last_interesting_request'] = {
            'url': url,
            'session_id': session_id,
            'request_id': request_id,
            'resource_type': resource_type,
            'reason': 'request mime=video',
            'ts': round(time.time(), 3),
        }
        register_video(url, state, session_id, 'request mime=video', headers=headers)
        return
    if 'mime=audio' in url:
        state['interesting_request_count'] = state.get('interesting_request_count', 0) + 1
        state['last_interesting_request'] = {
            'url': url,
            'session_id': session_id,
            'request_id': request_id,
            'resource_type': resource_type,
            'reason': 'request mime=audio',
            'ts': round(time.time(), 3),
        }
        register_audio(url, state, session_id, 'request mime=audio', headers=headers)
        return
    if is_interesting_url(url):
        state['interesting_request_count'] = state.get('interesting_request_count', 0) + 1
        state['last_interesting_request'] = {
            'url': url,
            'session_id': session_id,
            'request_id': request_id,
            'resource_type': resource_type,
            'reason': 'interesting url',
            'ts': round(time.time(), 3),
        }
        maybe_log_candidate(url, state, session_id, 'interesting url')

def handle_response_event(event, state):
    session_id = event.get('sessionId')
    params = event.get('params', {})
    request_id = params.get('requestId', '')
    response = params.get('response', {})
    mime_type = (response.get('mimeType') or '').lower()
    url = response.get('url') or state['request_urls'].get(session_key(session_id, request_id), '')
    resource_type = params.get('type', '')
    if not url:
        return
    state['response_event_count'] = state.get('response_event_count', 0) + 1
    maybe_mark_readiness(url, state, 'response')
    maybe_log_raw(url, state, session_id, resource_type, 'RES')
    if mime_type.startswith('video/'):
        state['interesting_response_count'] = state.get('interesting_response_count', 0) + 1
        state['last_interesting_response'] = {
            'url': url,
            'session_id': session_id,
            'request_id': request_id,
            'resource_type': resource_type,
            'mime_type': mime_type,
            'reason': f'mimeType={mime_type}',
            'ts': round(time.time(), 3),
        }
        maybe_log_candidate(url, state, session_id, f'mimeType={mime_type}')
        register_video(url, state, session_id, f'response {mime_type}')
    elif mime_type.startswith('audio/'):
        state['interesting_response_count'] = state.get('interesting_response_count', 0) + 1
        state['last_interesting_response'] = {
            'url': url,
            'session_id': session_id,
            'request_id': request_id,
            'resource_type': resource_type,
            'mime_type': mime_type,
            'reason': f'mimeType={mime_type}',
            'ts': round(time.time(), 3),
        }
        maybe_log_candidate(url, state, session_id, f'mimeType={mime_type}')
        register_audio(url, state, session_id, f'response {mime_type}')
    elif is_interesting_url(url):
        state['interesting_response_count'] = state.get('interesting_response_count', 0) + 1
        state['last_interesting_response'] = {
            'url': url,
            'session_id': session_id,
            'request_id': request_id,
            'resource_type': resource_type,
            'mime_type': mime_type,
            'reason': 'interesting url',
            'ts': round(time.time(), 3),
        }

def handle_target_created(event, state=None):
    if state is not None and not state.get('show_event_logs'):
        return
    info_t = event.get('params', {}).get('targetInfo', {})
    if info_t.get('targetId'):
        log('🪟', 'TARGET', f"created  {info_t.get('type', 'unknown')}  {safe_trunc(info_t.get('url', ''), 110)}", C.WHITE)

async def init_attached_session(client, state, session_id, target_info):
    if not session_id or session_id in state['initialized_sessions']:
        return
    state['initialized_sessions'].add(session_id)
    state['sessions'][session_id] = {
        'targetId': target_info.get('targetId'),
        'type': target_info.get('type', 'unknown'),
        'url': target_info.get('url', ''),
        'title': target_info.get('title', ''),
    }
    if state.get('show_event_logs'):
        log('🔗', 'ATTACH', f"{target_info.get('type', 'unknown')}  {safe_trunc(target_info.get('url', ''), 110)}", C.WHITE)
    await asyncio.sleep(ATTACH_INIT_DELAY)

    async def send_with_retry(method, params=None, warn_label=None):
        last_exc = None
        for attempt in range(1, ATTACH_INIT_RETRIES + 1):
            try:
                await client.send(method, params or {}, session_id=session_id)
                return True
            except Exception as e:
                last_exc = e
                if attempt < ATTACH_INIT_RETRIES:
                    await asyncio.sleep(ATTACH_INIT_DELAY)
        if state.get('show_event_logs') and warn_label and last_exc is not None:
            log('⚠', 'WARN', f"{warn_label} failed for {target_info.get('type', 'unknown')}: {last_exc}", C.YELLOW)
        return False

    await send_with_retry('Network.enable', {}, 'Network.enable')
    await send_with_retry('Page.enable', {}, 'Page.enable')

async def attach_root_session(client, target_id, state):
    result = await client.send('Target.attachToTarget', {'targetId': target_id, 'flatten': True})
    session_id = result.get('sessionId')
    state['root_session_id'] = session_id
    pages = {t.get('id'): t for t in filter_page_targets(list_targets())}
    target_info = pages.get(target_id, {'id': target_id, 'type': 'page', 'url': ''})
    await init_attached_session(client, state, session_id, {
        'targetId': target_id,
        'type': target_info.get('type', 'page'),
        'url': target_info.get('url', ''),
        'title': target_info.get('title', ''),
    })
    return session_id

async def configure_browser_targeting(client, root_target_id):
    await client.send('Target.setDiscoverTargets', {'discover': True})
    try:
        await client.send('Target.setAutoAttach', {
            'autoAttach': True,
            'waitForDebuggerOnStart': False,
            'flatten': True,
            'filter': [
                {'type': 'page', 'exclude': False},
                {'type': 'iframe', 'exclude': False},
                {'type': 'worker', 'exclude': False},
                {'type': 'shared_worker', 'exclude': False},
                {'type': 'service_worker', 'exclude': False},
            ],
        })
    except Exception:
        await client.send('Target.setAutoAttach', {
            'autoAttach': True,
            'waitForDebuggerOnStart': False,
            'flatten': True,
        })
    try:
        await client.send('Target.autoAttachRelated', {
            'targetId': root_target_id,
            'waitForDebuggerOnStart': False,
        })
    except Exception:
        pass

async def process_event_loop(client, state):
    while True:
        try:
            event = await client.next_event(timeout=0.5)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            raise
        try:
            method = event.get('method')
            if method == 'Target.targetCreated':
                handle_target_created(event, state)
            elif method == 'Target.attachedToTarget':
                params = event.get('params', {})
                await init_attached_session(client, state, params.get('sessionId'), params.get('targetInfo', {}))
            elif method == 'Target.detachedFromTarget':
                session_id = event.get('params', {}).get('sessionId')
                info_s = state['sessions'].pop(session_id, None)
                if session_id in state['initialized_sessions']:
                    state['initialized_sessions'].remove(session_id)
                if info_s:
                    if state.get('show_event_logs'):
                        log('🔌', 'DETACH', f"{info_s.get('type', 'unknown')}  {safe_trunc(info_s.get('url', ''), 90)}", C.DIM)
            elif method == 'Network.requestWillBeSent':
                handle_request_event(event, state)
            elif method == 'Network.responseReceived':
                handle_response_event(event, state)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log('⚠', 'WARN', f'Event processing error: {e}', C.YELLOW)

async def wait_for_readiness_request(state, timeout=60.0):
    write_network_log_line('TRACE', f'READINESS_WAIT_START timeout={timeout} event_exists={bool(state.get("readiness_event"))} event_set={bool(state.get("readiness_event").is_set()) if state.get("readiness_event") else False}')
    started_at = time.time()
    readiness_event = state.get('readiness_event')
    while (time.time() - started_at) < timeout:
        if state.get('readiness_seen'):
            result = {
                'ok': True,
                'waited': round(time.time() - started_at, 1),
                'url': str(state.get('readiness_url', '')),
                'source': state.get('readiness_source', 'unknown'),
            }
            write_network_log_line('TRACE', f'READINESS_WAIT_END result={result}')
            return result
        if readiness_event and readiness_event.is_set():
            result = {
                'ok': True,
                'waited': round(time.time() - started_at, 1),
                'url': str(state.get('readiness_url', '')),
                'source': state.get('readiness_source', 'unknown'),
            }
            write_network_log_line('TRACE', f'READINESS_WAIT_END result={result}')
            return result
        await asyncio.sleep(0.4)
    result = {
        'ok': False,
        'waited': round(time.time() - started_at, 1),
        'reason': 'timeout',
        'url': str(state.get('readiness_url', '')),
        'source': state.get('readiness_source', 'unknown'),
    }
    write_network_log_line('TRACE', f'READINESS_WAIT_TIMEOUT result={result}')
    return result


async def wait_for_stable_player_ui(client, state, timeout=30.0, poll=0.4, stable_hits=PLAYER_READY_STABLE_HITS):
    session_id = state.get('root_session_id')
    if not session_id:
        return {'ok': False, 'reason': 'missing-root-session', 'waited': 0.0}
    expr = r"""
(() => {
const directBtn = Array.from(document.querySelectorAll('[data-tooltip-label-on]'))
  .find(el => (el.getAttribute('data-tooltip-label-on') || '').includes('(k)'));
const jsBtn = document.querySelector('[jsname="IGlMSc"]');
const btn = directBtn || jsBtn;
const settingsBtn = document.querySelector('[jsname="dq27Te"]');
const ariaPressed = btn ? btn.getAttribute('aria-pressed') : null;
const rect = btn ? btn.getBoundingClientRect() : {width: 0, height: 0};
return {
ready: !!btn,
settingsReady: !!settingsBtn,
iframeCount: document.getElementsByTagName('iframe').length,
readyState: document.readyState || '',
title: document.title || '',
ariaPressed,
buttonVisible: !!btn && rect.width > 0 && rect.height > 0,
};
})()
"""
    waited = 0.0
    stable = 0
    last = {'ok': False, 'reason': 'not-run', 'waited': 0.0}
    while waited < timeout:
        try:
            value = await cdp_evaluate(client, session_id, expr)
            if isinstance(value, dict):
                last = dict(value)
                ready_now = bool(
                    value.get('ready') and
                    value.get('settingsReady') and
                    value.get('buttonVisible') and
                    value.get('iframeCount', 0) >= 3 and
                    value.get('readyState') in ('interactive', 'complete') and
                    value.get('ariaPressed') in ('false', None)
                )
                if ready_now:
                    stable += 1
                    if stable >= stable_hits and waited >= MIN_PLAYER_READY_WAIT:
                        last['ok'] = True
                        last['waited'] = round(waited, 1)
                        last['stable_hits'] = stable
                        last['min_wait'] = MIN_PLAYER_READY_WAIT
                        return last
                else:
                    stable = 0
        except Exception as e:
            last = {'ok': False, 'reason': str(e), 'waited': round(waited, 1)}
            stable = 0
        await asyncio.sleep(poll)
        waited += poll
    last['ok'] = False
    last['reason'] = 'play-button-not-stable'
    last['waited'] = round(waited, 1)
    last['min_wait'] = MIN_PLAYER_READY_WAIT
    return last


async def click_play_pause_once(client, state, attempts=3):
    session_id = state.get('root_session_id')
    if not session_id:
        return {'ok': False, 'found': False, 'clicked': False, 'reason': 'missing-root-session'}
    last = {'ok': False, 'found': False, 'clicked': False, 'reason': 'not-run'}
    expr = r"""
(async () => {
    const events = ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
    const iframeWindow = document.getElementsByTagName('iframe')[1]?.contentWindow || window;
    const triggerEvents = (target) => {
        if (!target) return false;
        events.forEach(type => {
            const ev = new MouseEvent(type, {
                view: iframeWindow,
                bubbles: true,
                cancelable: true,
                buttons: 1
            });
            target.dispatchEvent(ev);
        });
        return true;
    };
    const playPauseBtn = document.querySelector('[jsname="IGlMSc"]');
    if (!playPauseBtn) {
        return {ok: false, found: false, clicked: false, reason: 'jsname-not-found'};
    }
    const clicked = triggerEvents(playPauseBtn);
    return {ok: !!clicked, found: true, clicked, method: 'direct-jsname-single-click'};
})()
"""
    for attempt in range(1, attempts + 1):
        try:
            value = await cdp_evaluate(client, session_id, expr)
            if isinstance(value, dict):
                value['attempt'] = attempt
                last = value
                if value.get('ok'):
                    return value
        except Exception as e:
            last = {'ok': False, 'found': False, 'clicked': False, 'reason': str(e), 'attempt': attempt}
        await asyncio.sleep(0.5)
    return last


async def wait_for_play_button_pressed(client, state, target_pressed=True, timeout=PLAY_STATE_TIMEOUT, poll=0.2, stable_hits=2):
    session_id = state.get('root_session_id')
    if not session_id:
        return {'ok': False, 'found': False, 'pressed': None, 'reason': 'missing-root-session', 'waited': 0.0}
    expr = r"""
(() => {
    const btn = document.querySelector('[jsname="IGlMSc"]');
    if (!btn) {
        return {found: false, pressed: null, ariaPressed: null};
    }
    const ariaPressed = btn.getAttribute('aria-pressed');
    return {
        found: true,
        pressed: ariaPressed === 'true',
        ariaPressed,
        className: btn.className ? String(btn.className).slice(0, 120) : null,
    };
})()
"""
    waited = 0.0
    stable = 0
    last = {'ok': False, 'found': False, 'pressed': None, 'reason': 'not-run', 'waited': 0.0}
    while waited < timeout:
        try:
            value = await cdp_evaluate(client, session_id, expr)
            if isinstance(value, dict):
                last = dict(value)
                pressed = value.get('pressed')
                if value.get('found') and pressed is target_pressed:
                    stable += 1
                    if stable >= stable_hits:
                        last['ok'] = True
                        last['targetPressed'] = target_pressed
                        last['stable_hits'] = stable
                        last['waited'] = round(waited, 1)
                        return last
                else:
                    stable = 0
        except Exception as e:
            last = {'ok': False, 'found': False, 'pressed': None, 'reason': str(e), 'waited': round(waited, 1)}
            stable = 0
        await asyncio.sleep(poll)
        waited += poll
    last['ok'] = False
    last['targetPressed'] = target_pressed
    last['stable_hits'] = stable
    last['waited'] = round(waited, 1)
    last['reason'] = last.get('reason') or 'pressed-state-timeout'
    return last


async def wait_for_first_stream_after_play(state, baseline_video_count, baseline_audio_count, baseline_request_count=None, baseline_response_count=None, baseline_interesting_request_count=None, baseline_interesting_response_count=None, timeout=PLAY_RETRY_STREAM_TIMEOUT):
    started = time.time()
    baseline_request_count = state.get('request_event_count', 0) if baseline_request_count is None else baseline_request_count
    baseline_response_count = state.get('response_event_count', 0) if baseline_response_count is None else baseline_response_count
    baseline_interesting_request_count = state.get('interesting_request_count', 0) if baseline_interesting_request_count is None else baseline_interesting_request_count
    baseline_interesting_response_count = state.get('interesting_response_count', 0) if baseline_interesting_response_count is None else baseline_interesting_response_count
    while time.time() - started < timeout:
        video_count = len(state['video_urls'])
        audio_count = len(state['audio_urls'])
        request_count = state.get('request_event_count', 0)
        response_count = state.get('response_event_count', 0)
        interesting_request_count = state.get('interesting_request_count', 0)
        interesting_response_count = state.get('interesting_response_count', 0)
        if video_count > baseline_video_count or audio_count > baseline_audio_count or state.get('video_found'):
            return {
                'ok': True,
                'waited': round(time.time() - started, 1),
                'video_count': video_count,
                'audio_count': audio_count,
                'request_count': request_count,
                'response_count': response_count,
                'interesting_request_count': interesting_request_count,
                'interesting_response_count': interesting_response_count,
                'request_count_delta': request_count - baseline_request_count,
                'response_count_delta': response_count - baseline_response_count,
                'interesting_request_delta': interesting_request_count - baseline_interesting_request_count,
                'interesting_response_delta': interesting_response_count - baseline_interesting_response_count,
                'last_interesting_request': state.get('last_interesting_request'),
                'last_interesting_response': state.get('last_interesting_response'),
                'last_registered_video': state.get('last_registered_video'),
                'last_registered_audio': state.get('last_registered_audio'),
            }
        await asyncio.sleep(0.25)
    video_count = len(state['video_urls'])
    audio_count = len(state['audio_urls'])
    request_count = state.get('request_event_count', 0)
    response_count = state.get('response_event_count', 0)
    interesting_request_count = state.get('interesting_request_count', 0)
    interesting_response_count = state.get('interesting_response_count', 0)
    return {
        'ok': False,
        'waited': round(time.time() - started, 1),
        'video_count': video_count,
        'audio_count': audio_count,
        'request_count': request_count,
        'response_count': response_count,
        'interesting_request_count': interesting_request_count,
        'interesting_response_count': interesting_response_count,
        'request_count_delta': request_count - baseline_request_count,
        'response_count_delta': response_count - baseline_response_count,
        'interesting_request_delta': interesting_request_count - baseline_interesting_request_count,
        'interesting_response_delta': interesting_response_count - baseline_interesting_response_count,
        'last_interesting_request': state.get('last_interesting_request'),
        'last_interesting_response': state.get('last_interesting_response'),
        'last_registered_video': state.get('last_registered_video'),
        'last_registered_audio': state.get('last_registered_audio'),
        'reason': 'stream-timeout',
    }


async def auto_prime_playback(client, state, attempts=PLAY_RETRY_ATTEMPTS):
    readiness = await wait_for_readiness_request(state, timeout=60.0)
    if not readiness.get('ok'):
        return {
            'ok': False,
            'found': False,
            'clicked': False,
            'reason': 'readiness-timeout',
            'readiness': readiness,
            'attempts_used': 0,
        }

    state['pending_auto_pause'] = False
    last = {
        'ok': False,
        'found': False,
        'clicked': False,
        'reason': 'not-run',
        'readiness': readiness,
        'attempts_used': 0,
    }
    for attempt in range(1, attempts + 1):
        pre_ready = await wait_for_stable_player_ui(client, state, timeout=8.0, poll=0.4, stable_hits=3)
        baseline_video_count = len(state['video_urls'])
        baseline_audio_count = len(state['audio_urls'])
        baseline_request_count = state.get('request_event_count', 0)
        baseline_response_count = state.get('response_event_count', 0)
        baseline_interesting_request_count = state.get('interesting_request_count', 0)
        baseline_interesting_response_count = state.get('interesting_response_count', 0)
        click_result = await click_play_pause_once(client, state, attempts=1)
        click_result['attempt'] = attempt
        play_state = await wait_for_play_button_pressed(client, state, target_pressed=True)
        stream_result = await wait_for_first_stream_after_play(
            state,
            baseline_video_count,
            baseline_audio_count,
            baseline_request_count,
            baseline_response_count,
            baseline_interesting_request_count,
            baseline_interesting_response_count,
        )
        if stream_result.get('ok'):
            pause_result = await click_play_pause_once(client, state, attempts=2)
            pause_state = await wait_for_play_button_pressed(client, state, target_pressed=False, timeout=1.0, poll=0.2, stable_hits=1)
            state['pending_auto_pause'] = False
            return {
                'ok': True,
                'found': click_result.get('found'),
                'clicked': click_result.get('clicked'),
                'reason': 'stream-detected',
                'attempts_used': attempt,
                'readiness': readiness,
                'pre_ready': pre_ready,
                'click_result': click_result,
                'play_state': play_state,
                'stream_result': stream_result,
                'pause_result': pause_result,
                'pause_state': pause_state,
            }
        post_ready = await wait_for_stable_player_ui(client, state, timeout=4.0, poll=0.4, stable_hits=2)
        last = {
            'ok': False,
            'found': click_result.get('found'),
            'clicked': click_result.get('clicked'),
            'reason': 'stream-not-detected-after-click',
            'attempts_used': attempt,
            'readiness': readiness,
            'pre_ready': pre_ready,
            'click_result': click_result,
            'play_state': play_state,
            'stream_result': stream_result,
            'post_ready': post_ready,
        }
        write_log_line('INFO', f'Auto-prime retry #{attempt}: {last}')
        if PLAY_RETRY_DELAY > 0:
            await asyncio.sleep(PLAY_RETRY_DELAY)
    return last


async def monitor_until_video_found(client, state, processor_task):
    pending_auto_pause = bool(state.get('pending_auto_pause'))
    if state.get('video_found'):
        if pending_auto_pause:
            pause_result = await click_play_pause_once(client, state, attempts=2)
            pause_state = await wait_for_play_button_pressed(client, state, target_pressed=False, timeout=1.0, poll=0.2, stable_hits=1)
            state['pending_auto_pause'] = False
            write_log_line('INFO', f'Delayed auto-pause result: {pause_result}')
            write_log_line('INFO', f'Delayed auto-pause button state: {pause_state}')
            if pause_result.get('ok'):
                ui_note('First stream detected after delayed monitoring. Playback paused automatically.')
            else:
                ui_warn(f"First stream detected, but delayed auto-pause failed: {pause_result.get('reason', 'unknown')}")
        else:
            ui_note('First stream already detected during auto-prime. Continuing monitoring briefly ...')
        await asyncio.sleep(1.0)
        return state
    ui_note('Monitoring network for first video/audio stream request ...')
    write_log_line('INFO', 'Monitoring network for first video/audio stream request')
    elapsed = 0.0
    warned15 = warned30 = warned60 = False
    while not state['video_found']:
        await asyncio.sleep(0.5)
        elapsed += 0.5
        if elapsed >= 15 and not warned15:
            ui_warn('Still waiting for first stream request ...')
            warned15 = True
        if elapsed >= 30 and not warned30:
            ui_warn('Slow connection. Monitoring continues ...')
            warned30 = True
        if elapsed >= 60 and not warned60:
            ui_warn('60s elapsed. Monitoring continues ...')
            warned60 = True
        if elapsed >= MONITOR_TIMEOUT:
            break
        if processor_task.done():
            try:
                exc = processor_task.exception()
            except asyncio.CancelledError:
                break
            if exc:
                write_log_line('WARN', f'Event loop stopped: {exc}')
                break
    if state.get('video_found') and state.get('pending_auto_pause'):
        pause_result = await click_play_pause_once(client, state, attempts=2)
        pause_state = await wait_for_play_button_pressed(client, state, target_pressed=False, timeout=1.0, poll=0.2, stable_hits=1)
        state['pending_auto_pause'] = False
        write_log_line('INFO', f'Delayed auto-pause result: {pause_result}')
        write_log_line('INFO', f'Delayed auto-pause button state: {pause_state}')
        if pause_result.get('ok'):
            ui_note('First stream detected. Playback paused automatically after monitoring.')
        else:
            ui_warn(f"First stream detected, but delayed auto-pause failed: {pause_result.get('reason', 'unknown')}")
    return state


async def ensure_quality_menu_open(client, state, timeout=QUALITY_MENU_OPEN_TIMEOUT, attempts=2):
    session_id = state.get('root_session_id')
    if not session_id:
        return {'ok': False, 'reason': 'missing-root-session', 'qualities': [], 'qualityRows': []}
    expr = r"""
(async () => {
    const timeoutMs = __TIMEOUT_MS__;
    const events = ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
    const iframe = document.getElementsByTagName("iframe")[1];
    const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));
    const normalizeQuality = (text) => {
        const raw = String(text || '').trim();
        const m = raw.match(/(\d+)p/i);
        if (m) return `${m[1]}p`;
        if (raw.toLowerCase() === 'auto') return 'auto';
        return raw.toLowerCase();
    };
    const simulateClick = (target) => {
        if (!target) return false;
        events.forEach(type => {
            const ev = new MouseEvent(type, {
                view: iframe?.contentWindow || window,
                bubbles: true,
                cancelable: true,
                buttons: 1
            });
            target.dispatchEvent(ev);
        });
        return true;
    };
    const collectRows = () => Array.from(document.querySelectorAll('span[jsname="K4r5Ff"]')).map((el, index) => {
        const raw = (el.textContent || '').trim();
        const normalized = normalizeQuality(raw);
        const radio = el.closest('[role="menuitemradio"]');
        const menuItem = el.closest('[role="menuitem"]');
        const button = el.closest('[role="button"], button');
        const parent = el.parentElement;
        const clickTarget = radio || menuItem || button || parent || el;
        return {
            index,
            raw,
            normalized,
            tag: el.tagName,
            clickTag: clickTarget?.tagName || null,
            clickRole: clickTarget?.getAttribute?.('role') || null,
            clickClass: clickTarget?.className ? String(clickTarget.className).slice(0, 120) : null,
            ariaChecked: clickTarget?.getAttribute?.('aria-checked') || radio?.getAttribute?.('aria-checked') || null,
        };
    }).filter(item => /^\d+p$/i.test(item.normalized) || item.normalized === 'auto');
    const waitForRows = async () => {
        const started = Date.now();
        while ((Date.now() - started) < timeoutMs) {
            const rows = collectRows();
            if (rows.length > 0) {
                return {ok: true, waitedMs: Date.now() - started, qualities: Array.from(new Set(rows.map(r => r.normalized))), qualityRows: rows};
            }
            await wait(120);
        }
        const rows = collectRows();
        return {ok: rows.length > 0, waitedMs: Date.now() - started, qualities: Array.from(new Set(rows.map(r => r.normalized))), qualityRows: rows};
    };

    let existing = await waitForRows();
    if (existing.ok) {
        return {ok: true, settingsClicked: false, qualityClicked: false, source: 'already-open', ...existing};
    }

    const settingsBtn = document.querySelector('[jsname="dq27Te"]');
    const settingsClicked = simulateClick(settingsBtn);
    if (settingsClicked) await wait(450);
    let afterSettings = await waitForRows();
    if (afterSettings.ok) {
        return {ok: true, settingsClicked, qualityClicked: false, source: 'settings-opened-menu', ...afterSettings};
    }

    const qualityMenuBtn = document.querySelector('[jsname="NuIc0d"]');
    const qualityClicked = simulateClick(qualityMenuBtn);
    if (qualityClicked) await wait(550);
    const afterQuality = await waitForRows();
    return {ok: afterQuality.ok, settingsClicked, qualityClicked, source: 'quality-menu-click', ...afterQuality};
})()
""".replace('__TIMEOUT_MS__', str(int(timeout * 1000)))
    last = {'ok': False, 'reason': 'not-run', 'qualities': [], 'qualityRows': []}
    for attempt_no in range(1, attempts + 1):
        value = await cdp_evaluate(client, session_id, expr)
        if isinstance(value, dict):
            value['attempt'] = attempt_no
            last = value
            if value.get('ok'):
                return value
        await asyncio.sleep(0.25)
    last['reason'] = last.get('reason') or 'quality-menu-not-open'
    return last


async def extract_available_qualities(client, state):
    return await ensure_quality_menu_open(client, state)


async def apply_quality_choice(client, state, target_quality):
    session_id = state.get('root_session_id')
    if not session_id:
        return {'ok': False, 'reason': 'missing-root-session', 'target': target_quality}
    menu_result = await ensure_quality_menu_open(client, state)
    if not menu_result.get('ok'):
        return {
            'ok': False,
            'reason': 'quality-menu-not-open',
            'target': target_quality,
            'normalizedTarget': normalize_quality_label(target_quality),
            'menuResult': menu_result,
            'found': False,
            'available': menu_result.get('qualities', []),
            'qualityRows': menu_result.get('qualityRows', []),
            'targetRow': None,
            'attemptResults': [],
            'selectedAfterClick': [],
            'finalVerification': {'ok': False, 'selected': [], 'targetChecked': False, 'targetRow': None, 'rows': []},
        }
    expr = r"""
(async () => {
    const targetQuality = __TARGET__;
    const events = ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
    const iframe = document.getElementsByTagName("iframe")[1];
    const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));
    const normalizeQuality = (text) => {
        const raw = String(text || '').trim();
        const m = raw.match(/(\d+)p/i);
        if (m) return `${m[1]}p`;
        if (raw.toLowerCase() === 'auto') return 'auto';
        return raw.toLowerCase();
    };
    const simulateClick = (target) => {
        if (!target) return false;
        events.forEach(type => {
            const ev = new MouseEvent(type, {
                view: iframe?.contentWindow || window,
                bubbles: true,
                cancelable: true,
                buttons: 1
            });
            target.dispatchEvent(ev);
        });
        return true;
    };
    const buildRows = () => Array.from(document.querySelectorAll('span[jsname="K4r5Ff"]')).map((el, index) => {
        const raw = (el.textContent || '').trim();
        const normalized = normalizeQuality(raw);
        const radio = el.closest('[role="menuitemradio"]');
        const menuItem = el.closest('[role="menuitem"]');
        const button = el.closest('[role="button"], button');
        const parent = el.parentElement;
        const grandParent = parent?.parentElement || null;
        const candidates = [radio, menuItem, button, parent, grandParent, el].filter(Boolean);
        const summaries = candidates.map(node => ({
            tag: node.tagName,
            role: node.getAttribute?.('role') || null,
            ariaChecked: node.getAttribute?.('aria-checked') || null,
            className: node.className ? String(node.className).slice(0, 120) : null,
        }));
        const ariaValues = summaries.map(item => item.ariaChecked).filter(v => v !== null && v !== undefined);
        const checked = ariaValues.includes('true');
        return {
            index,
            raw,
            normalized,
            candidates,
            summary: summaries,
            checked,
            checkedValues: ariaValues,
        };
    }).filter(item => /^\d+p$/i.test(item.normalized) || item.normalized === 'auto');
    const verifySelection = (wanted) => {
        const rows = buildRows();
        const targetRow = rows.find(row => row.normalized === wanted) || null;
        const selected = rows.filter(row => row.checked).map(row => row.normalized);
        return {
            ok: !!(targetRow && targetRow.checked),
            selected,
            targetChecked: !!(targetRow && targetRow.checked),
            targetRow: targetRow ? {
                index: targetRow.index,
                raw: targetRow.raw,
                normalized: targetRow.normalized,
                checked: targetRow.checked,
                checkedValues: targetRow.checkedValues,
                summary: targetRow.summary,
            } : null,
            rows: rows.map(row => ({
                index: row.index,
                raw: row.raw,
                normalized: row.normalized,
                checked: row.checked,
                checkedValues: row.checkedValues,
                summary: row.summary,
            })),
        };
    };
    const wanted = normalizeQuality(String(targetQuality));
    const initialRows = buildRows();
    const targetRow = initialRows.find(row => row.normalized === wanted) || null;
    const attemptResults = [];
    let success = false;
    let selected = [];
    let finalVerification = verifySelection(wanted);
    if (finalVerification.ok) {
        success = true;
        selected = finalVerification.selected;
    } else if (targetRow) {
        for (let i = 0; i < targetRow.candidates.length; i += 1) {
            const candidate = targetRow.candidates[i];
            const clicked = simulateClick(candidate);
            await wait(250);
            const verify = verifySelection(wanted);
            finalVerification = verify;
            selected = verify.selected;
            attemptResults.push({
                candidateIndex: i,
                clicked,
                tag: candidate?.tagName || null,
                role: candidate?.getAttribute?.('role') || null,
                ariaChecked: candidate?.getAttribute?.('aria-checked') || null,
                className: candidate?.className ? String(candidate.className).slice(0, 120) : null,
                verifyOk: verify.ok,
                targetChecked: verify.targetChecked,
                selected: verify.selected,
                rowsVisibleAfterClick: (Array.isArray(verify.rows) ? verify.rows.length : 0),
            });
            if (clicked && verify.ok) {
                success = true;
                break;
            }
            if (clicked && (!verify.rows || verify.rows.length === 0)) {
                break;
            }
        }
    }
    return {
        ok: success,
        applied: success,
        target: targetQuality,
        normalizedTarget: wanted,
        found: !!targetRow,
        available: initialRows.map(row => row.normalized),
        qualityRows: initialRows.map(row => ({index: row.index, raw: row.raw, normalized: row.normalized, checked: row.checked, checkedValues: row.checkedValues, summary: row.summary})),
        targetRow: targetRow ? {index: targetRow.index, raw: targetRow.raw, normalized: targetRow.normalized, checked: targetRow.checked, checkedValues: targetRow.checkedValues, summary: targetRow.summary} : null,
        attemptResults,
        selectedAfterClick: selected,
        finalVerification,
    };
})()
""".replace('__TARGET__', json.dumps(target_quality))
    value = await cdp_evaluate(client, session_id, expr)
    if not isinstance(value, dict):
        value = {'ok': False, 'reason': 'empty-result', 'target': target_quality}
    value['menuResult'] = menu_result
    return value


async def apply_quality_choice_with_retry(client, state, target_quality, attempts=QUALITY_APPLY_ATTEMPTS):
    history = []
    for attempt in range(1, attempts + 1):
        result = await apply_quality_choice(client, state, target_quality)
        result['attempt'] = attempt
        history.append(result)
        write_log_line('INFO', f'Quality apply attempt #{attempt}: {result}')
        if result.get('ok'):
            result['history'] = history
            return result
        quick_wait = await wait_for_quality_capture(state, target_quality, timeout=1.6)
        write_log_line('INFO', f'Quality quick capture check #{attempt}: {quick_wait}')
        if quick_wait.get('ok'):
            result['ok'] = True
            result['applied'] = True
            result['reason'] = 'stream-detected-after-click'
            result['quick_wait'] = quick_wait
            result['history'] = history
            return result
        await asyncio.sleep(0.25)
    final = history[-1] if history else {'ok': False, 'reason': 'no-attempts', 'target': target_quality}
    final['history'] = history
    return final


async def wait_for_quality_capture(state, target_quality, timeout=QUALITY_CAPTURE_TIMEOUT):
    started = time.time()
    initial_keys = set(state['video_urls'].keys())
    target_quality = normalize_quality_label(target_quality)
    while time.time() - started < timeout:
        labels = sorted({normalize_quality_label(ITAG_QUALITY_NAME.get(itag, f'itag_{itag}')) for itag in state['video_urls']})
        if target_quality in labels and set(state['video_urls'].keys()) != initial_keys:
            return {'ok': True, 'waited': round(time.time() - started, 1), 'target': target_quality, 'labels': labels, 'newVideoCount': len(state['video_urls'])}
        await asyncio.sleep(0.5)
    labels = sorted({normalize_quality_label(ITAG_QUALITY_NAME.get(itag, f'itag_{itag}')) for itag in state['video_urls']})
    if target_quality in labels:
        return {'ok': True, 'waited': round(time.time() - started, 1), 'target': target_quality, 'labels': labels, 'reason': 'quality-already-present', 'newVideoCount': len(state['video_urls'])}
    return {'ok': False, 'waited': round(time.time() - started, 1), 'target': target_quality, 'labels': labels, 'newVideoCount': len(state['video_urls'])}


async def quality_selection_window(client, state, preferred_quality):
    if not state['video_urls']:
        return
    section('Quality Selection Window')
    write_log_line('INFO', f"Preferred quality: {describe_quality_preference(preferred_quality)}")
    last_itag, last_label = get_last_captured_video_quality(state)
    if last_itag:
        write_log_line('INFO', f'Last captured video itag={last_itag} quality={last_label}')
    desired_label = normalize_quality_label((preferred_quality or {}).get('label')) if preferred_quality else None
    if preferred_quality and preferred_quality.get('mode') == 'exact' and last_label == desired_label:
        ui_note(f'Preferred quality already captured: {last_label}')
        write_log_line('INFO', f'Quality selection skipped because last captured quality already matches: {last_label}')
        return

    extract_result = await extract_available_qualities(client, state)
    write_log_line('INFO', f'Quality menu extraction result: {extract_result}')
    available = [normalize_quality_label(q) for q in extract_result.get('qualities', []) if normalize_quality_label(q) != 'auto']
    target_label, reason = select_preferred_quality_label_from_available(available, preferred_quality)
    write_log_line('INFO', f'Quality target decision: desired={desired_label} available={available} chosen={target_label} reason={reason}')
    if not target_label:
        ui_warn('Could not extract usable qualities. Continuing with captured streams.')
        return

    if reason == 'exact-match':
        ui_note(f'Applying preferred quality automatically: {target_label}')
    elif reason == 'highest-available':
        ui_note(f'Applying highest available quality automatically: {target_label}')
    elif reason == 'nearest-lower':
        ui_warn(f'Preferred quality not found. Applying nearest lower quality: {target_label}')
    else:
        ui_warn(f'Preferred quality not found. Applying lowest available fallback: {target_label}')

    apply_result = await apply_quality_choice_with_retry(client, state, target_label)
    write_log_line('INFO', f'Quality apply final result: {apply_result}')
    if not apply_result.get('ok'):
        ui_warn(f'Automatic quality apply failed for {target_label}. Continuing with captured streams.')
        return

    wait_result = await wait_for_quality_capture(state, target_label)
    write_log_line('INFO', f'Quality capture wait result: {wait_result}')
    if wait_result.get('ok'):
        ui_note(f'Quality ready for selection logic: {target_label}')
    else:
        ui_warn(f'No new stream for {target_label} was observed in time. Continuing with best captured match.')


async def cdp_evaluate(client, session_id, expression, return_by_value=True):
    result = await client.send('Runtime.evaluate', {
        'expression': expression,
        'awaitPromise': True,
        'returnByValue': return_by_value,
    }, session_id=session_id)
    return result.get('result', {}).get('value')

async def extract_title(client, state):
    session_id = state.get('root_session_id')
    if not session_id:
        return None
    expressions = [
        "(() => { const el = document.querySelector('[aria-describedby=\\\"HADQ6c\\\"]'); return el ? el.textContent.trim() : null; })()",
        "(() => document.title || null)()",
    ]
    for expr in expressions:
        try:
            value = await cdp_evaluate(client, session_id, expr)
            if value:
                title = str(value).strip()
                if title:
                    return title
        except Exception:
            pass
    return None

async def fetch_chunk_via_session(client, session_id, base_url, start, end, chunk_n):
    expr = JS_FETCH_CHUNK_TEMPLATE
    expr = expr.replace('__BASE_URL__', json.dumps(base_url))
    expr = expr.replace('__START__', str(start))
    expr = expr.replace('__END__', str(end))
    expr = expr.replace('__CHUNKN__', str(chunk_n))
    value = await cdp_evaluate(client, session_id, expr)
    return value or {}

async def download_chunked(client, session_id, url, filename, label, chunk_mb=5):
    base_url = prepare_base_url(url)
    clen_param = parse_qs(urlparse(url).query).get('clen', [0])[0]
    total_size = int(clen_param) if str(clen_param).isdigit() else 0
    chunk_size = chunk_mb * 1024 * 1024
    section(f'Downloading  {label}')
    write_log_line('INFO', f'Base URL: {base_url}')
    info(f'File     →  {C.WHITE}{C.BOLD}{filename}{C.RESET}')
    info(f'clen     →  {total_size/1024/1024:.1f} MB  {C.DIM}(server hint — may be partial){C.RESET}')
    info(f'Method   →  GET chunks {chunk_mb} MB each — real size from Content-Range or EOF')
    written = 0
    chunk_n = 1
    start_t = time.time()
    errors = 0
    size_known = False
    empty_streak = 0
    with open(filename, 'wb') as f:
        while True:
            if size_known and written >= total_size:
                break
            end = min(written + chunk_size - 1, total_size - 1) if size_known and total_size > 0 else written + chunk_size - 1
            result = await fetch_chunk_via_session(client, session_id, base_url, written, end, chunk_n)
            if result.get('eof'):
                if result.get('size', 0) == 0:
                    empty_streak += 1
                    if empty_streak >= 3:
                        write_log_line('INFO', f'EOF (empty x3) at {written/1024/1024:.1f} MB')
                        break
                    await asyncio.sleep(1)
                    continue
                write_log_line('INFO', f'EOF (HTTP 416) at {written/1024/1024:.1f} MB')
                break
            if 'error' in result:
                err_msg = str(result['error'])
                if any(code in err_msg for code in ['400', '403', '416']):
                    write_log_line('INFO', f'EOF ({err_msg}) at {written/1024/1024:.1f} MB')
                    break
                errors += 1
                write_log_line('WARN', f'Chunk #{chunk_n}: {err_msg} — retry {errors}/5')
                if errors >= 5:
                    error(f'Too many errors. Aborted at {written/1024/1024:.1f} MB')
                    return False
                await asyncio.sleep(2)
                continue
            if not size_known and result.get('totalSize', 0) > 0:
                real = int(result['totalSize'])
                if real != total_size:
                    write_log_line('INFO', f'Real size: {real/1024/1024:.1f} MB (clen was {total_size/1024/1024:.1f} MB)')
                total_size = real
                size_known = True
            data = result.get('data')
            actual_size = int(result.get('size', 0))
            if not data or actual_size == 0:
                empty_streak += 1
                if empty_streak >= 3:
                    print(f"\n  {C.DIM}  EOF (empty data x3) at {written/1024/1024:.1f} MB{C.RESET}")
                    break
                await asyncio.sleep(1)
                continue
            empty_streak = 0
            f.write(base64.b64decode(data))
            written += actual_size
            chunk_n += 1
            errors = 0
            elapsed = max(time.time() - start_t, 0.001)
            speed = written / elapsed / 1024 / 1024
            ui_progress(f"{progress_bar(written, total_size if size_known else 0)}  {C.YELLOW}{speed:.1f} MB/s{C.RESET}  #{chunk_n-1}")
    actual_mb = os.path.getsize(filename) / 1024 / 1024 if os.path.exists(filename) else 0
    success(f'Saved  →  {filename}  ({actual_mb:.1f} MB)')
    return True


async def get_browser_cookies(client, urls):
    try:
        result = await client.send('Network.getCookies', {'urls': [u for u in urls if u]})
        return result.get('cookies', [])
    except Exception:
        return []

async def download_http_range(url, filename, label, referer=None, user_agent=None, cookies=None, extra_headers=None, chunk_mb=5):
    base_url = prepare_base_url(url)
    hinted = parse_qs(urlparse(url).query).get('clen', [0])[0]
    total_size = int(hinted) if str(hinted).isdigit() else 0
    chunk_size = chunk_mb * 1024 * 1024

    section(f'Downloading  {label}')
    write_log_line('INFO', f'Base URL: {base_url}')
    info(f'File     →  {C.WHITE}{C.BOLD}{filename}{C.RESET}')
    info(f'clen     →  {total_size/1024/1024:.1f} MB  {C.DIM}(URL hint — may be partial){C.RESET}')
    info(f'Method   →  HTTP range chunks {chunk_mb} MB each')

    headers = {
        'Accept': '*/*',
        'Accept-Encoding': 'identity',
        'User-Agent': user_agent or 'Mozilla/5.0',
    }
    if referer:
        headers['Referer'] = referer
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            headers['Origin'] = f'{parsed.scheme}://{parsed.netloc}'
    if extra_headers:
        for k, v in extra_headers.items():
            if not v:
                continue
            lk = k.lower()
            if lk in {'host', 'content-length', 'cookie', 'range'}:
                continue
            headers[k] = v

    jar = aiohttp.CookieJar(unsafe=True)
    if cookies:
        for ck in cookies:
            try:
                domain = (ck.get('domain') or urlparse(url).hostname or '').lstrip('.')
                jar.update_cookies({ck.get('name'): ck.get('value')}, response_url=f'https://{domain}{ck.get("path") or "/"}')
            except Exception:
                pass

    timeout = aiohttp.ClientTimeout(total=None, connect=20, sock_read=60)
    written = 0
    chunk_n = 1
    errors = 0
    empty_streak = 0
    size_known = False
    start_t = time.time()

    with open(filename, 'wb') as f:
        async with aiohttp.ClientSession(cookie_jar=jar, timeout=timeout, trust_env=True) as session:
            while True:
                if size_known and total_size > 0 and written >= total_size:
                    break

                end = min(written + chunk_size - 1, total_size - 1) if size_known and total_size > 0 else written + chunk_size - 1
                sep = '&' if '?' in base_url else '?'
                chunk_url = f'{base_url}{sep}alr=yes&range={written}-{end}&rn={chunk_n}&rbuf=0'

                try:
                    async with session.get(chunk_url, headers=headers, allow_redirects=True) as resp:
                        if resp.status == 416:
                            write_log_line('INFO', f'EOF (HTTP 416) at {written/1024/1024:.1f} MB')
                            break
                        if resp.status >= 400:
                            errors += 1
                            err_msg = f'{resp.status} {resp.reason}'
                            if any(code in err_msg for code in ['400', '403', '416']):
                                write_log_line('INFO', f'EOF ({err_msg}) at {written/1024/1024:.1f} MB')
                                break
                            write_log_line('WARN', f'Chunk #{chunk_n}: {err_msg} — retry {errors}/5')
                            if errors >= 5:
                                error(f'Too many errors. Aborted at {written/1024/1024:.1f} MB')
                                return False
                            await asyncio.sleep(2)
                            continue

                        cr = resp.headers.get('Content-Range', '') or resp.headers.get('content-range', '')
                        m = re.search(r'/([0-9]+)$', cr)
                        if m:
                            real = int(m.group(1))
                            if not size_known or real != total_size:
                                if total_size and real != total_size:
                                    write_log_line('INFO', f'Real size: {real/1024/1024:.1f} MB (clen was {total_size/1024/1024:.1f} MB)')
                                total_size = real
                                size_known = True
                        elif total_size > 0:
                            size_known = True

                        chunk_written = 0
                        async for chunk in resp.content.iter_chunked(512 * 1024):
                            if not chunk:
                                continue
                            f.write(chunk)
                            chunk_written += len(chunk)
                            written += len(chunk)
                            elapsed = max(time.time() - start_t, 0.001)
                            speed = written / elapsed / 1024 / 1024
                            ui_progress(f"{progress_bar(written, total_size if size_known else 0)}  {C.YELLOW}{speed:.1f} MB/s{C.RESET}  #{chunk_n}")

                        if chunk_written == 0:
                            empty_streak += 1
                            if empty_streak >= 3:
                                write_log_line('INFO', f'EOF (empty x3) at {written/1024/1024:.1f} MB')
                                break
                            await asyncio.sleep(1)
                            continue

                        if chunk_written < chunk_size and (not size_known or written >= total_size):
                            break

                        empty_streak = 0
                        errors = 0
                        chunk_n += 1

                except Exception as e:
                    errors += 1
                    write_log_line('WARN', f'Chunk #{chunk_n}: {e} — retry {errors}/5')
                    if errors >= 5:
                        error(f'Too many errors. Aborted at {written/1024/1024:.1f} MB')
                        return False
                    await asyncio.sleep(2)
                    continue

    actual_mb = Path(filename).stat().st_size / 1024 / 1024 if Path(filename).exists() else 0
    if actual_mb <= 0:
        error(f'No data saved to {filename}')
        return False
    success(f'Saved  →  {filename}  ({actual_mb:.1f} MB)')
    return True


async def run(target_url, preferred_quality, output_dir=None, skip_chrome_prompt=False):
    close_browser_on_exit = True
    run_succeeded = False
    target_url = normalize_url(target_url)
    script_dir = get_app_dir()
    init_log_file(script_dir)
    write_log_line('INPUT', f'URL: {target_url}')
    write_log_line('INPUT', f"Preferred quality: {describe_quality_preference(preferred_quality)}")
    section('Chrome Profile Clone Mode')
    if not skip_chrome_prompt:
        prompt_close_original_chrome()

    section('Cloning Profile')
    info('Preparing non-default debug profile copy ...')
    clone_info = clone_profile_to_workdir()
    if clone_info.get('reused_existing_clone'):
        success('Existing cloned profile was reused.')
    else:
        success('Profile clone created successfully.')
    info(f"Source user data  →  {clone_info['source_user_data']}")
    info(f"Profile           →  {clone_info['profile_name']}")
    info(f"Clone user data   →  {clone_info['clone_user_data_dir']}")
    info('Launching Chrome with cloned profile ...')
    proc = launch_chrome_with_cloned_profile(clone_info['clone_user_data_dir'], clone_info['profile_name'])

    client = None
    processor = None
    try:
        section('Remote Debugging')
        version = wait_for_debug_endpoint()
        success('Debug endpoint is ready.')
        info(f"Browser  →  {version.get('Browser', 'Unknown')}")

        section('Target Preparation')
        target = choose_or_create_root_target(target_url)
        target_id = target.get('id') or target.get('targetId')
        info(f"Target ID  →  {target_id or 'unknown'}")
        info(f"Target URL →  {target.get('url', 'about:blank')}")

        section('Connecting to Browser')
        browser_ws = version.get('webSocketDebuggerUrl')
        if not browser_ws:
            raise RuntimeError('Browser WebSocket debugger URL not found in /json/version.')
        client = CDPClient(browser_ws)
        await client.connect()
        success('Connected to browser WebSocket.')

        state = build_monitor_state(root_target_id=target_id)
        await configure_browser_targeting(client, target_id)
        root_session = await attach_root_session(client, target_id, state)
        success(f'Root session attached  →  {root_session}')

        section('Monitoring Primed')
        processor = asyncio.create_task(process_event_loop(client, state))
        await asyncio.sleep(0.75)
        info('Event monitoring started before navigation.')

        section('Navigating')
        await client.send('Page.navigate', {'url': target_url}, session_id=root_session)
        success(f'Page navigate sent  →  {target_url[:65]}...')

        section('Waiting for Player UI')
        player_ready = await wait_for_stable_player_ui(client, state)
        write_log_line('INFO', f'Player ready result: {player_ready}')
        if player_ready.get('ok'):
            success(f"Player UI stable after {player_ready.get('waited', 0):.1f}s.")
        else:
            ui_warn(f"Player UI was not stable in time: {player_ready.get('reason', 'timeout')}")

        section('Auto Prime Playback')
        prime_result = await auto_prime_playback(client, state)
        write_log_line('INFO', f'Prime playback result: {prime_result}')
        if prime_result.get('ok'):
            ui_note(f"Playback started after {prime_result.get('attempts_used')} attempt(s), then paused after first stream detection.")
            write_log_line('INFO', f'Auto-prime success details: {prime_result}')
        else:
            write_log_line('WARN', f'Auto-prime failed: {prime_result}')
            error(f"Auto-prime failed after {prime_result.get('attempts_used', 0)} attempt(s): {prime_result.get('reason', 'unknown')}")
            return {'ok': False, 'reason': 'auto-prime-failed'}

        section('Monitoring Network')
        state = await monitor_until_video_found(client, state, processor)

        section('Extracting Video Title')
        title = await extract_title(client, state)
        if title:
            write_log_line('INFO', f'Title: {title}')
            ui_note(f'Title detected: {title}')
        else:
            ui_warn('Title not found — quality label will be used.')

        await quality_selection_window(client, state, preferred_quality)

        section('Finalizing Captured URLs')
        info(f"Sessions attached :  {C.BOLD}{len(state['sessions'])}{C.RESET}")
        info(f"Video streams     :  {C.BOLD}{len(state['video_urls'])}{C.RESET}")
        info(f"Audio streams     :  {C.BOLD}{len(state['audio_urls'])}{C.RESET}")
        if not state['video_urls']:
            error('No video URLs captured in this stage.')
            return {'ok': False, 'reason': 'no-video-urls'}

        best_video_itag = pick_preferred_video_itag(state['video_urls'], preferred_quality)
        best_video = state['video_urls'][best_video_itag]
        quality_label = ITAG_QUALITY_NAME.get(best_video_itag, f'itag_{best_video_itag}')
        best_audio = None
        best_audio_itag = None
        if state['audio_urls']:
            best_audio_itag = max(state['audio_urls'], key=lambda t: int(t) if str(t).isdigit() else 0)
            best_audio = state['audio_urls'][best_audio_itag]

        section('Selected Streams')
        write_log_line('INFO', f'Selected video itag={best_video_itag} quality={quality_label}')
        if best_audio:
            write_log_line('INFO', f'Selected audio itag={best_audio_itag}')
            ui_note(f'Selected quality: {quality_label} + audio')
        else:
            ui_warn(f'Selected quality: {quality_label} (video only fallback if needed)')

        _run_output_dir = output_dir if output_dir is not None else script_dir
        temp_dir = ensure_temp_dir(_run_output_dir)
        cleanup_temp_dir(temp_dir)

        base_name = safe_filename(title) if title else quality_label
        _final_output_path = None
        output_file = safe_unique_filename(_run_output_dir, f'{base_name} [{quality_label}].mp4')
        video_file = temp_dir / f'_tmp_video_{quality_label}.mp4'
        audio_file = temp_dir / f'_tmp_audio_{quality_label}.m4a'
        info(f"Output  →  {C.WHITE}{C.BOLD}{output_file}{C.RESET}")
        info(f"Temp dir →  {C.WHITE}{temp_dir}{C.RESET}")

        if processor and not processor.done():
            info('Stopping network monitor before download ...')
            processor.cancel()
            try:
                await asyncio.wait_for(processor, timeout=1.5)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                info('Monitor stop timed out; continuing with download.')
            except Exception:
                pass
            processor = None

        browser_cookies = await get_browser_cookies(client, [target_url, best_video['url'], best_audio['url'] if best_audio else None])
        browser_ua = version.get('User-Agent') or 'Mozilla/5.0'

        video_ok = await download_http_range(
            best_video['url'], video_file, f'Video ({quality_label})',
            referer=target_url, user_agent=browser_ua, cookies=browser_cookies,
            extra_headers=best_video.get('headers'),
        )
        audio_ok = False
        if video_ok and best_audio:
            audio_ok = await download_http_range(
                best_audio['url'], audio_file, 'Audio',
                referer=target_url, user_agent=browser_ua, cookies=browser_cookies,
                extra_headers=best_audio.get('headers'),
            )

        if video_ok and audio_ok:
            merge_ok = merge_video_audio(video_file, audio_file, output_file)
            if merge_ok:
                ui_clear_render()
                cleanup_temp_dir(temp_dir)
                info('Temp directory cleaned.')
                ui_success(f'All done!  →  {output_file}')
                run_succeeded = True
                _final_output_path = output_file
            else:
                cleanup_temp_dir(temp_dir)
                info('Temp directory cleaned.')
                error('Merge or duration verification failed.')
                return {'ok': False, 'reason': 'merge-failed'}
        elif video_ok:
            ui_clear_render()
            suffix = '(audio missing)' if best_audio else '(no audio)'
            final = safe_unique_filename(_run_output_dir, f'{base_name} [{quality_label}] {suffix}.mp4')
            os.replace(video_file, final)
            cleanup_temp_dir(temp_dir)
            info('Temp directory cleaned.')
            ui_warn(f'Video only  →  {final}')
            run_succeeded = True
            _final_output_path = final
        else:
            ui_clear_render()
            cleanup_temp_dir(temp_dir)
            info('Temp directory cleaned.')
            error('Download failed. Please run the script again.')
            return {'ok': False, 'reason': 'download-failed'}
        return {'ok': True, 'output': _final_output_path}
    finally:
        if processor:
            processor.cancel()
            try:
                await asyncio.wait_for(processor, timeout=1.0)
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                pass
            except Exception:
                pass
        browser_close_result = None
        if close_browser_on_exit and client:
            try:
                browser_close_result = await client.send('Browser.close')
                write_log_line('INFO', f'Browser.close sent successfully: {browser_close_result}')
                await asyncio.sleep(1.0)
            except Exception as e:
                browser_close_result = {'ok': False, 'method': 'Browser.close', 'error': str(e)}
                write_log_line('WARN', f'Browser.close failed: {browser_close_result}')
        if client:
            await client.close()
        if close_browser_on_exit:
            close_result = close_launched_chrome(proc)
            if close_result.get('ok'):
                reason = 'successful completion' if run_succeeded else 'failed/early-stopped run'
                write_log_line('INFO', f'Chrome clone closed automatically after {reason}: {close_result}')
            else:
                write_log_line('WARN', f'Automatic Chrome close fallback failed: {close_result}')
                ui_note('Chrome window may still be open. Close it manually if needed.')


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH MODE  — URL list management, validation, orchestration
# ═══════════════════════════════════════════════════════════════════════════════

def normalize_url_entry(raw_line):
    """Strip whitespace; return cleaned URL string or None for blanks/comments."""
    line = raw_line.strip()
    if not line or line.startswith('#'):
        return None
    return line


def validate_and_load_urls(file_path):
    """
    Parse list-url.txt and return:
      ok          : True if file has at least one valid URL and zero errors
      urls        : list of validated URL strings
      errors      : list of (line_number, raw_line, reason)
      total_lines : raw line count
      reason      : 'empty' | 'file-not-found' | None
    """
    file_path = Path(file_path)
    if not file_path.exists():
        return {'ok': False, 'urls': [], 'errors': [], 'total_lines': 0, 'reason': 'file-not-found'}

    raw_lines = file_path.read_text(encoding='utf-8').splitlines()
    urls, errors = [], []

    for lineno, raw in enumerate(raw_lines, 1):
        entry = normalize_url_entry(raw)
        if entry is None:
            continue
        parsed = urlparse(entry)
        if parsed.scheme not in ('http', 'https'):
            errors.append((lineno, raw, f"Must start with http:// or https:// (got: '{parsed.scheme or entry[:20]}...')"))
            continue
        if not parsed.netloc:
            errors.append((lineno, raw, 'URL has no domain/host'))
            continue
        urls.append(entry)

    if not urls and not errors:
        return {'ok': False, 'urls': [], 'errors': [], 'total_lines': len(raw_lines), 'reason': 'empty'}

    return {
        'ok': len(errors) == 0,
        'urls': urls,
        'errors': errors,
        'total_lines': len(raw_lines),
        'reason': None,
    }


def ensure_url_list_file(script_dir):
    """Create list-url.txt in script_dir if it does not exist. Return Path."""
    p = Path(script_dir) / BATCH_URL_LIST_FILENAME
    if not p.exists():
        p.write_text('', encoding='utf-8')
    return p


def show_url_list_instructions(file_path):
    """Print setup instructions and a filled example for list-url.txt."""
    print()
    _ui_sep()
    print(f"  {C.WHITE}{C.BOLD}  Open and fill:  {file_path}{C.RESET}")
    _ui_sep()
    print(f"  {C.DIM}  Rules:{C.RESET}")
    print(f"  {C.DIM}    - One URL per line{C.RESET}")
    print(f"  {C.DIM}    - Lines starting with # are treated as comments{C.RESET}")
    print(f"  {C.DIM}    - Blank lines are ignored{C.RESET}")
    print()
    print(f"  {C.YELLOW}  Example content:{C.RESET}")
    print(f"  {C.DIM}    https://www.youtube.com/watch?v=XXXXXXXXXX{C.RESET}")
    print(f"  {C.DIM}    https://www.youtube.com/watch?v=YYYYYYYYYY{C.RESET}")
    print(f"  {C.DIM}    # This is a comment and will be skipped{C.RESET}")
    print(f"  {C.DIM}    https://www.youtube.com/watch?v=ZZZZZZZZZZ{C.RESET}")
    print()


def show_validation_errors(result, file_path):
    """Print validation error details so the user knows what to fix."""
    print()
    print(f"  {C.RED}{C.BOLD}  Validation failed  →  {file_path}{C.RESET}")
    print(f"  {C.YELLOW}  {len(result['errors'])} error(s) found:{C.RESET}")
    for lineno, raw, reason in result['errors'][:10]:
        print(f"    {C.DIM}Line {lineno:>3}:{C.RESET}  {C.RED}{reason}{C.RESET}")
        print(f"           {C.DIM}{raw[:90]}{C.RESET}")
    if len(result['errors']) > 10:
        print(f"  {C.DIM}  ... and {len(result['errors']) - 10} more error(s).{C.RESET}")
    print()


def create_batch_output_dir(script_dir):
    """
    Create  output/<YYYY-MM-DD_HH-MM-SS>/  inside script_dir.
    Appends  _2, _3 ...  if the timestamp dir already exists (collision guard).
    Returns the resolved Path.
    """
    base_ts   = time.strftime('%Y-%m-%d_%H-%M-%S')
    base      = Path(script_dir) / BATCH_OUTPUT_SUBDIR / base_ts
    candidate = base
    suffix    = 2
    while candidate.exists():
        candidate = Path(str(base) + f'_{suffix}')
        suffix   += 1
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def safe_unique_filename(output_dir, base_name):
    """
    Return a Path that does not collide with any existing file in output_dir.
    Example: 'title [720p].mp4' exists  →  'title [720p] (2).mp4'  →  ...
    """
    output_dir = Path(output_dir)
    stem, ext  = os.path.splitext(base_name)
    candidate  = output_dir / base_name
    counter    = 2
    while candidate.exists():
        candidate = output_dir / f'{stem} ({counter}){ext}'
        counter  += 1
    return candidate


def _atomic_write_lines(file_path, lines):
    """Write lines to file_path via a temp file → os.replace (atomic on POSIX & NTFS)."""
    file_path = Path(file_path)
    tmp       = file_path.with_suffix('.tmp')
    content   = '\n'.join(lines) + ('\n' if lines else '')
    tmp.write_text(content, encoding='utf-8')
    os.replace(tmp, file_path)


def remove_url_from_list(url, list_path):
    """Remove the first matching URL from list-url.txt atomically."""
    list_path = Path(list_path)
    if not list_path.exists():
        return
    lines     = list_path.read_text(encoding='utf-8').splitlines()
    removed   = False
    new_lines = []
    for l in lines:
        if not removed and normalize_url_entry(l) == url:
            removed = True
            continue
        new_lines.append(l)
    _atomic_write_lines(list_path, new_lines)


def append_done_entry(url, filename, list_path, done_path):
    """
    Append a success record to list-done.txt and
    remove the URL from list-url.txt atomically.
    Format: [YYYY-MM-DD HH:MM:SS] DONE  <url>  =>  <filename>
    """
    ts    = time.strftime('%Y-%m-%d %H:%M:%S')
    fname = Path(filename).name if filename else 'unknown'
    with open(done_path, 'a', encoding='utf-8') as fh:
        fh.write(f'[{ts}] DONE   {url}  =>  {fname}\n')
    remove_url_from_list(url, list_path)


def append_error_entry(url, error_msg, list_path, error_path):
    """
    Append a failure record to list-error.txt and
    remove the URL from list-url.txt atomically.
    Format: [YYYY-MM-DD HH:MM:SS] ERROR  <url>  =>  <reason>
    """
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    with open(error_path, 'a', encoding='utf-8') as fh:
        fh.write(f'[{ts}] ERROR  {url}  =>  {error_msg[:200]}\n')
    remove_url_from_list(url, list_path)



def _batch_print_header(total, done_count, error_count,
                        quality_label, output_dir,
                        is_complete=False,
                        done_path=None, error_path=None):
    """
    Clear the terminal and redraw the Batch dashboard.
    Box width is fully dynamic: computed from the widest VISIBLE content line.
    ANSI colour codes are stripped before any width calculation so the right
    border ║ always stays perfectly aligned regardless of color sequences.
    """
    os.system('cls' if os.name == 'nt' else 'clear')

    # Determine usable path length from terminal width via shared _ui_width()
    MAX_PATH = max(30, _ui_width() - 22)   # 22 = indent + borders + label + margins

    # _vlen() → now delegates to module-level _ui_vlen()

    def _trunc(p):
        s = str(p)
        return ('...' + s[-(MAX_PATH - 3):]) if len(s) > MAX_PATH else s

    # ── Build all content rows (with colour codes, no padding yet) ────────────
    left       = max(0, total - done_count - error_count)
    done_str   = f"{C.GREEN}✔ {done_count} done{C.RESET}"
    failed_str = f"{C.RED}✘ {error_count} failed{C.RESET}"

    if is_complete:
        sc         = C.GREEN if error_count == 0 else C.YELLOW
        title_line = f"  {sc}{C.BOLD}✔  Batch Complete  ─  {total} URL(s){C.RESET}"
    else:
        title_line = f"  {C.BLUE}{C.BOLD}⏳  Batch Mode  ─  {total} URL(s){C.RESET}"

    top_lines = [
        title_line,
        f"  {C.DIM}Quality  : {quality_label}{C.RESET}",
        f"  {C.DIM}Output   : {_trunc(output_dir)}{C.RESET}",
    ]

    if is_complete:
        bot_lines = [f"  Result   :  {done_str}   {failed_str}"]
        if done_count and done_path:
            bot_lines.append(f"  {C.DIM}Done log : {_trunc(done_path)}{C.RESET}")
        if error_count and error_path:
            bot_lines.append(f"  {C.DIM}Err log  : {_trunc(error_path)}{C.RESET}")
    else:
        left_str  = f"{C.CYAN}⏳ {left} left{C.RESET}"
        bot_lines = [f"  Progress :  {done_str}   {failed_str}   {left_str}"]

    all_lines = top_lines + bot_lines

    # ── Compute box inner width from VISIBLE content (ANSI-safe) ─────────────
    W  = max(_ui_vlen(l) for l in all_lines) + 2   # +2 right breathing room
    BW = W + 2                                   # banner width = ╔═…═╗ span

    # row() → delegates to module-level _ui_box_row(content, W)
    def row(content):
        _ui_box_row(content, W)

    # ── Mini banner — width anchored to box (BW = W+2) ─────────────────────
    print()
    print(f"  {C.CYAN}{C.BOLD}  {'─' * BW}{C.RESET}")
    print(f"  {C.CYAN}{C.BOLD}  {'Google Drive Video Extractor':^{BW}}{C.RESET}")
    print(f"  {C.DIM}  {APP_VERSION:^{BW}}{C.RESET}")
    print(f"  {C.CYAN}{C.BOLD}  {'─' * BW}{C.RESET}")
    print()

    # ── Box ───────────────────────────────────────────────────────────────────
    print(f"  {C.CYAN}╔{'═' * W}╗{C.RESET}")
    for line in top_lines:
        row(line)
    print(f"  {C.CYAN}╠{'═' * W}╣{C.RESET}")
    for line in bot_lines:
        row(line)
    print(f"  {C.CYAN}╚{'═' * W}╝{C.RESET}\n")


async def run_batch_mode(script_dir, preferred_quality):
    """
    Batch (Auto) Mode orchestrator.
    ─ Reads  list-url.txt  (creates if missing)
    ─ Validates format with user-friendly error reporting
    ─ Asks user to close original Chrome once
    ─ Processes each URL sequentially (Chrome reused per session, isolated per URL)
    ─ Clears screen before each URL → shows live stats header
    ─ Moves URLs to list-done.txt / list-error.txt atomically
    ─ Returns 'back' | 'done'
    """
    list_path     = Path(script_dir) / BATCH_URL_LIST_FILENAME
    done_path     = Path(script_dir) / BATCH_DONE_LIST_FILENAME
    error_path    = Path(script_dir) / BATCH_ERROR_LIST_FILENAME
    quality_label = describe_quality_preference(preferred_quality)

    ensure_url_list_file(script_dir)

    # ── Validation loop ──────────────────────────────────────────────────────
    # Enter or '0' → go back   |   'R' / 'r' → re-check
    while True:
        vr = validate_and_load_urls(list_path)

        # ① File empty
        if not vr.get('urls') and not vr.get('errors'):
            show_url_list_instructions(list_path)
            print(f"  {C.YELLOW}  The file is empty. Add your URLs, then come back.{C.RESET}")
            cmd = _safe_input(
                f"\n  {C.CYAN}{C.BOLD}  Press Enter to go back  ─  or R to re-check  ›  {C.RESET}"
            ).strip().upper()
            if cmd != 'R':
                return 'back'
            continue

        # ② File not found
        if vr.get('reason') == 'file-not-found':
            print(f"\n  {C.RED}  File not found: {list_path}{C.RESET}")
            cmd = _safe_input(
                f"  {C.CYAN}  Press Enter to go back  ─  or R to retry  ›  {C.RESET}"
            ).strip().upper()
            if cmd != 'R':
                return 'back'
            continue

        # ③ Validation errors
        if not vr['ok'] and vr.get('errors'):
            show_validation_errors(vr, list_path)
            cmd = _safe_input(
                f"  {C.CYAN}{C.BOLD}  Press Enter to go back  ─  or R to re-validate  ›  {C.RESET}"
            ).strip().upper()
            if cmd != 'R':
                return 'back'
            continue

        break  # ✔ valid

    urls       = vr['urls']
    total      = len(urls)
    output_dir = create_batch_output_dir(script_dir)
    done_count  = 0
    error_count = 0

    # ── Initial dashboard + Chrome close prompt ──────────────────────────────
    _batch_print_header(total, 0, 0, quality_label, output_dir)
    prompt_close_original_chrome()

    init_log_file(script_dir)
    write_log_line('BATCH', f'Start: {total} URL(s), quality={quality_label}, output={output_dir}')

    # ── URL processing loop ──────────────────────────────────────────────────
    interrupted = False
    for idx, url in enumerate(urls, 1):

        # Refresh header with current stats before each URL
        _batch_print_header(total, done_count, error_count, quality_label, output_dir)

        url_display = url if len(url) <= 86 else url[:83] + '...'
        print(f"  {C.BLUE}{C.BOLD}  [{idx}/{total}]  Processing ...{C.RESET}")
        print(f"  {C.DIM}  {url_display}{C.RESET}\n")
        write_log_line('BATCH', f'[{idx}/{total}] Starting: {url}')

        try:
            ri = await run(
                url, preferred_quality,
                output_dir=output_dir,
                skip_chrome_prompt=True,
            )

            if isinstance(ri, dict) and ri.get('ok'):
                out_file = ri.get('output')
                append_done_entry(url, str(out_file or ''), list_path, done_path)
                done_count += 1
                write_log_line('BATCH', f'[{idx}/{total}] SUCCESS => {out_file}')
            else:
                reason = ri.get('reason', 'unknown') if isinstance(ri, dict) else 'run-returned-false'
                append_error_entry(url, reason, list_path, error_path)
                error_count += 1
                write_log_line('BATCH', f'[{idx}/{total}] FAILED ({reason}): {url}')

        except KeyboardInterrupt:
            write_log_line('BATCH', 'Interrupted by user.')
            interrupted = True
            break

        except Exception as e:
            log_exception(f'Batch [{idx}/{total}]', e)
            append_error_entry(url, str(e)[:200], list_path, error_path)
            error_count += 1
            write_log_line('BATCH', f'[{idx}/{total}] EXCEPTION {e!r}: {url}')

    # ── Final dashboard (complete state) ─────────────────────────────────────
    _batch_print_header(
        total, done_count, error_count, quality_label, output_dir,
        is_complete=True,
        done_path=done_path  if done_count  else None,
        error_path=error_path if error_count else None,
    )
    if interrupted:
        print(f"  {C.YELLOW}  ⚠  Batch was interrupted. Remaining URLs are still in {BATCH_URL_LIST_FILENAME}.{C.RESET}\n")

    write_log_line('BATCH', f'Complete: {done_count} done, {error_count} failed')
    return 'done'


def prompt_url_mode():
    """
    Ask user to choose mode. Returns '1', '2', or '3' (exit).
    Pressing Enter with no input is treated as '3' (exit).
    """
    print(f"\n  {C.CYAN}{C.BOLD}  Select Mode{C.RESET}")
    print(f"  {C.WHITE}    1{C.RESET}  ─  Single URL")
    print(f"  {C.WHITE}    2{C.RESET}  ─  Batch / Auto  (uses {BATCH_URL_LIST_FILENAME})")
    print(f"  {C.WHITE}    3{C.RESET}  ─  {C.DIM}Exit{C.RESET}")
    while True:
        choice = _safe_input(f"\n  {C.CYAN}{C.BOLD}  Mode  ›  {C.RESET}").strip()
        if choice == '':
            continue            # bare Enter → ignore, re-ask
        if choice in ('1', '2', '3'):
            return choice
        print(f"  {C.YELLOW}  Enter 1, 2, or 3.{C.RESET}")

def main():
    script_dir = get_app_dir()
    while True:
        banner()
        mode = prompt_url_mode()

        # ── Exit ─────────────────────────────────────────────────────────────
        if mode == '3':
            print(f"\n  {C.DIM}  Goodbye.{C.RESET}\n")
            break

        # ── Single URL Mode ──────────────────────────────────────────────────
        elif mode == '1':
            target_url = _safe_input(f"\n  {C.CYAN}{C.BOLD}  Enter URL  ›  {C.RESET}").strip()
            if not target_url:
                print(f"  {C.YELLOW}  No URL entered. Returning to menu.{C.RESET}")
                _safe_input(f"  {C.DIM}  Press Enter ...{C.RESET}")
                continue
            preferred_quality = prompt_user_quality_preference()
            try:
                # Create a timestamped output dir (same structure as batch mode)
                _single_out = create_batch_output_dir(script_dir)
                asyncio.run(run(target_url, preferred_quality, output_dir=_single_out))
            except KeyboardInterrupt:
                error('Interrupted by user.')
            except Exception as e:
                log_exception('Fatal error', e)
                error(f'Unexpected error: {e}')
            _safe_input(f"\n  {C.DIM}  Press Enter to return to menu ...{C.RESET}")

        # ── Batch / Auto Mode ────────────────────────────────────────────────
        elif mode == '2':
            preferred_quality = prompt_user_quality_preference()
            try:
                batch_result = asyncio.run(run_batch_mode(script_dir, preferred_quality))
                if batch_result != 'back':
                    _safe_input(f"\n  {C.DIM}  Press Enter to return to menu ...{C.RESET}")
            except KeyboardInterrupt:
                error('Interrupted by user.')
            except Exception as e:
                log_exception('Fatal error in batch mode', e)
                error(f'Unexpected error: {e}')
                _safe_input(f"\n  {C.DIM}  Press Enter to return to menu ...{C.RESET}")



if __name__ == '__main__':
    import multiprocessing
    import traceback as _tb

    multiprocessing.freeze_support()

    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # ── Flush stdin buffer ─────────────────────────────────────────────
    # Prevents the Enter key used to launch the .exe from being consumed
    # by the first _safe_input() call, which would immediately exit the program.
    try:
        import time as _time
        _time.sleep(0.15)   # let the OS drain any pending key events
        if os.name == 'nt':
            import msvcrt as _msvcrt
            while _msvcrt.kbhit():
                _msvcrt.getch()
        else:
            import termios as _termios
            import sys as _sys
            try:
                _termios.tcflush(_sys.stdin, _termios.TCIFLUSH)
            except Exception:
                pass
    except Exception:
        pass

    _crash_log = get_app_dir() / 'crash_log.txt'
    try:
        main()
    except KeyboardInterrupt:
        pass
    except SystemExit:
        pass
    except Exception as _exc:
        _msg = _tb.format_exc()
        try:
            with open(_crash_log, 'w', encoding='utf-8') as _f:
                _f.write('CDP v3.4.2 - Crash Report\n')
                _f.write('=' * 60 + '\n')
                _f.write(_msg)
            print('\n' + '=' * 60)
            print('  CRASH - Error saved to: ' + str(_crash_log))
            print('=' * 60)
            print(_msg)
        except Exception:
            print(_msg)
        input('\nPress Enter to close...')
