"""
Kuber Android (no-root, Termux). Runs on your phone; brain runs on Cloudflare Workers AI.

Install (phone):
  1. Install Termux + Termux:API from F-Droid (not Play Store).
  2. Copy this folder to the phone, then in Termux:  bash termux-setup.sh
  3. Set Cloudflare vars (same values as your PC cf-setup):
       export CF_ACCOUNT_ID="..."  CF_API_TOKEN="..."
     (or edit ~/.bashrc to keep them)
  4. Run:  python my_agent_android.py --cloudflare
  5. Grant permissions when Android asks: SMS, Contacts, Storage, Location.

Examples:
  what is my battery and storage
  set brightness to 80 and volume music to 5
  open wifi settings
  text mom that I will call in 10 minutes
  find 5 phone chargers under Rs 1000 and save to chargers.md

Everything the agent saves goes into the 'workspace' folder next to this file.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from openai import OpenAI

HERE = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.join(HERE, "workspace")
os.makedirs(WORKSPACE, exist_ok=True)
MAX_STEPS = 25
MAX_DOWNLOAD_MB = 500
HEADERS = {"User-Agent": "Mozilla/5.0 (kuber-android)"}

# ---------------- choose the brain (same as PC agent) ----------------
import argparse

ap = argparse.ArgumentParser(description="Kuber Android agent")
ap.add_argument("--claude", action="store_true", help="use Claude API (needs ANTHROPIC_API_KEY)")
ap.add_argument("--cloudflare", action="store_true",
                help="use Cloudflare Workers AI (recommended on phone; always on)")
ap.add_argument("--gemini", action="store_true",
                help="use Google Gemini (needs GEMINI_API_KEY)")
ap.add_argument("--model", help="model name")
ap.add_argument("--base-url", help="any OpenAI-compatible API base URL")
ap.add_argument("--api-key-env", default="AGENT_API_KEY", help="env var holding that API's key")
ap.add_argument("--fast", action="store_true", help="Kaggle only: disable thinking")
ap.add_argument("task", nargs="*", help="optional one-shot task (for Termux:Widget)")
ap.add_argument("--stay", action="store_true", help="keep chat open after one-shot task")
opts = ap.parse_args()

if opts.claude:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit('Set ANTHROPIC_API_KEY first:  export ANTHROPIC_API_KEY="sk-ant-..."')
    client = OpenAI(base_url="https://api.anthropic.com/v1/", api_key=key)
    MODEL = opts.model or "claude-sonnet-5-5"
    BRAIN = f"{MODEL} (Claude API)"
elif opts.cloudflare:
    acct, tok = os.environ.get("CF_ACCOUNT_ID"), os.environ.get("CF_API_TOKEN")
    if not (acct and tok):
        sys.exit("Cloudflare not set. Run:  export CF_ACCOUNT_ID=... CF_API_TOKEN=...\n"
                 "(use the same values as cf-setup on your PC)")
    client = OpenAI(base_url=f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/v1",
                    api_key=tok, timeout=600, max_retries=2)
    MODEL = opts.model or os.environ.get("CF_AGENT_MODEL", "@cf/qwen/qwen3-30b-a3b-fp8")
    BRAIN = f"{MODEL.split('/')[-1]} on Cloudflare"
elif opts.gemini:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit('Set GEMINI_API_KEY first:  export GEMINI_API_KEY="..."')
    client = OpenAI(base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    api_key=key, timeout=600, max_retries=2)
    MODEL = opts.model or os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    BRAIN = f"{MODEL} (Google)"
elif opts.base_url:
    key = os.environ.get(opts.api_key_env)
    if not key:
        sys.exit(f"Set {opts.api_key_env} first.")
    if not opts.model:
        sys.exit("Also pass --model with --base-url.")
    client = OpenAI(base_url=opts.base_url, api_key=key)
    MODEL = opts.model
    BRAIN = f"{MODEL} ({opts.base_url})"
else:
    # Fallback: Kaggle tunnel (needs start-llm on PC). Works, but Cloudflare is better on phone.
    base = os.environ.get("KAGGLE_LLM_URL")
    if not base:
        sys.exit("No brain selected. On phone use:  python my_agent_android.py --cloudflare")
    client = OpenAI(base_url=f"{base}/v1", api_key="kaggle", timeout=900, max_retries=1,
                    default_headers={"ngrok-skip-browser-warning": "1"})
    MODEL = opts.model or os.environ.get("KAGGLE_LLM_MODEL", "qwen3.6:27b")
    BRAIN = f"{MODEL} on Kaggle"

KAGGLE = not (opts.claude or opts.base_url or opts.cloudflare or opts.gemini)
EXTRA = {"reasoning_effort": "none", "chat_template_kwargs": {"enable_thinking": False}} \
    if (opts.fast and KAGGLE) else {}
SAMPLING = {}
if KAGGLE:
    SAMPLING = ({"temperature": 0.7, "top_p": 0.8, "presence_penalty": 1.5} if opts.fast
                else {"temperature": 0.6, "top_p": 0.95})
    EXTRA = {**EXTRA, "top_k": 20}

OLD_TOOL_RESULT_CHARS = 1500
KEEP_FULL_RESULTS = 2


def compact(history):
    tool_msgs = [m for m in history if isinstance(m, dict) and m.get("role") == "tool"]
    for m in tool_msgs[:-KEEP_FULL_RESULTS]:
        c = m["content"]
        if len(c) > OLD_TOOL_RESULT_CHARS and not c.startswith("[shortened]"):
            m["content"] = "[shortened] " + c[:OLD_TOOL_RESULT_CHARS] + "\n...(older result cut)"


def as_dict(msg):
    d = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        d["tool_calls"] = []
        for c in msg.tool_calls:
            call = {"id": c.id, "type": "function", "function": {
                "name": c.function.name, "arguments": c.function.arguments}}
            extra = (getattr(c, "model_extra", None) or {}).get("extra_content")
            if extra:
                call["extra_content"] = extra
            d["tool_calls"].append(call)
    return d


# ---------------- shared web / file tools (same as PC agent) ----------------
def safe_path(path):
    full = os.path.abspath(os.path.join(WORKSPACE, path))
    if not full.startswith(os.path.abspath(WORKSPACE)):
        raise ValueError("Path must stay inside the workspace folder.")
    return full


def search_web(query, max_results=8):
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    results = DDGS().text(query, max_results=int(max_results))
    return "\n".join(f"- {r.get('title')}\n  {r.get('href')}\n  {r.get('body')}" for r in results) \
        or "No results."


def search_images(query, max_results=8):
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    results = DDGS().images(query, max_results=int(max_results))
    return "\n".join(
        f"- {r.get('title')} ({r.get('width')}x{r.get('height')})\n  image_url: {r.get('image')}\n"
        f"  source page: {r.get('url')}" for r in results) or "No images found."


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def page_preview(soup):
    wanted = {"og:title": "Title", "og:description": "Description", "og:site_name": "Site",
              "og:type": "Type", "og:image": "Image", "og:video": "Video",
              "twitter:title": "Title", "twitter:description": "Description",
              "description": "Description", "author": "Author",
              "article:published_time": "Published"}
    found = {}
    for m in soup.find_all("meta"):
        key = (m.get("property") or m.get("name") or "").lower()
        val = (m.get("content") or "").strip()
        if key in wanted and val and wanted[key] not in found:
            found[wanted[key]] = val
    return "\n".join(f"{k}: {v}" for k, v in found.items())


def read_page(url):
    r = requests.get(url, headers=BROWSER_HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    preview = page_preview(soup)
    title = soup.title.get_text(strip=True) if soup.title else ""
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    text = re.sub(r"\n\s*\n+", "\n\n", soup.get_text("\n")).strip()
    links = [f"{a.get_text(strip=True)[:60]} -> {a['href']}" for a in soup.find_all("a", href=True)
             if a["href"].startswith("http")][:40]
    out = []
    if preview:
        out.append("LINK PREVIEW:\n" + preview)
    if title and not preview:
        out.append(f"TITLE: {title}")
    out.append("PAGE TEXT:\n" + text[:6000] + ("\n...[page cut]" if len(text) > 6000 else ""))
    out.append("LINKS:\n" + "\n".join(links))
    return "\n\n".join(out)


def download_file(url, filename=None):
    name = filename or os.path.basename(urlparse(url).path) or "download.bin"
    dest = safe_path(os.path.join("downloads", name))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    size = 0
    with requests.get(url, headers=HEADERS, stream=True, timeout=60) as r:
        r.raise_for_status()
        ctype = r.headers.get("Content-Type", "")
        if "text/html" in ctype:
            return "Not a direct file link (got a web page). Try another URL."
        if not os.path.splitext(name)[1] and "/" in ctype:
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
                   "image/gif": ".gif", "application/pdf": ".pdf", "application/zip": ".zip"}
            name += ext.get(ctype.split(";")[0].strip(), "")
            dest = safe_path(os.path.join("downloads", name))
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                size += len(chunk)
                if size > MAX_DOWNLOAD_MB * (1 << 20):
                    f.close()
                    os.remove(dest)
                    return f"Stopped: file is bigger than {MAX_DOWNLOAD_MB} MB."
                f.write(chunk)
    return f"Saved downloads/{name} ({size / (1 << 20):.1f} MB)"


def write_file(path, content):
    full = safe_path(path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Wrote {path} ({len(content)} characters)"


def read_file(path):
    with open(safe_path(path), encoding="utf-8", errors="ignore") as f:
        return f.read()[:8000]


def list_files(path="."):
    full = safe_path(path)
    return "\n".join(sorted(os.listdir(full))) or "(empty)"


def workspace_tree(max_files=200):
    lines = []
    for root, dirs, files in os.walk(WORKSPACE):
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".git", "__pycache__")]
        for f in sorted(files):
            lines.append(os.path.relpath(os.path.join(root, f), WORKSPACE).replace("\\", "/"))
            if len(lines) >= max_files:
                return "\n".join(lines) + "\n..."
    return "\n".join(lines) or "(workspace is empty)"


# ---------------- Android helpers ----------------
IS_ANDROID = os.path.exists("/data/data/com.termux") or bool(shutil.which("termux-battery-status"))


def _run(cmd, timeout=20):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, errors="replace",
                       timeout=int(timeout), cwd=WORKSPACE)
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    return r.returncode, out[:4000]


def _need_termux():
    if not IS_ANDROID:
        return ("Not on Android Termux. This tool needs the Termux app with termux-api installed. "
                "On PC it only returns this message.")
    if not shutil.which("termux-battery-status"):
        return ("termux-api is missing. In Termux run:  pkg install termux-api  "
                "and install the Termux:API app from F-Droid.")
    return None


def confirm(question):
    print(f"\n       !! {question}")
    return input("       Allow? [y/N] ").strip().lower() == "y"


DECLINED = "The user DECLINED this. Do not retry it; ask the user what to do instead."

RISKY_CMD = re.compile(
    r"\b(rm|rmdir|rd|del|erase|format|shutdown|reboot|taskkill|kill|killall|pkill|"
    r"stop-process|remove-item|move-item|reg|regedit|sc|netsh|setx|chmod|chown|sudo|runas|"
    r"winget|choco|scoop|apt|pkg|pip\s+uninstall|npm\s+uninstall)\b", re.I)


def ask_user(message):
    print(f"\n       >> AGENT NEEDS YOU: {message}")
    reply = input("       Press Enter when done, or type a reply: ").strip()
    return reply or "Done. The user has completed it."


def run_command(command, timeout=60):
    """Run a shell command in Termux and return its output."""
    if RISKY_CMD.search(command):
        if not confirm(f"The agent wants to run:  {command}"):
            return DECLINED
    try:
        code, out = _run(command, timeout)
    except subprocess.TimeoutExpired:
        return f"Command still running after {timeout}s and was stopped."
    return f"(exit code {code})\n{out}"


def system_info():
    """Battery, device, storage, OS. Needs termux-api on Android."""
    import platform
    info = [f"OS: {platform.platform()}", f"Android Termux: {IS_ANDROID}"]
    if not IS_ANDROID:
        total, _, free = shutil.disk_usage(WORKSPACE)
        return "\n".join(info + [f"Disk: {free / 1e9:.1f} GB free of {total / 1e9:.1f} GB",
                                 "(full phone info is available on Android Termux)"])
    err = _need_termux()
    if err:
        return err
    code, bat = _run("termux-battery-status", 10)
    if code == 0:
        try:
            b = json.loads(bat)
            info.append(f"Battery: {b.get('percentage')}% "
                        f"({'charging' if b.get('status') == 'CHARGING' else b.get('status', '?')})")
        except ValueError:
            info.append(f"Battery raw: {bat[:300]}")
    code, tel = _run("termux-telephony-deviceinfo", 10)
    if code == 0:
        info.append(f"Device: {tel[:400]}")
    code, loc = _run("termux-location -p network -r once 2>/dev/null", 15)
    if code == 0 and loc:
        info.append(f"Location: {loc[:200]}")
    total, _, free = shutil.disk_usage(os.path.expanduser("~/storage/shared"
                                                           if os.path.exists(os.path.expanduser("~/storage/shared"))
                                                           else WORKSPACE))
    info.append(f"Storage: {free / 1e9:.1f} GB free of {total / 1e9:.1f} GB")
    return "\n".join(info)


COMMON_APPS = {
    "spotify": "com.spotify.music", "whatsapp": "com.whatsapp",
    "chrome": "com.android.chrome", "gmail": "com.google.android.gm",
    "maps": "com.google.android.apps.maps", "camera": "com.android.camera2",
    "gallery": "com.google.android.apps.photos", "photos": "com.google.android.apps.photos",
    "youtube": "com.google.android.youtube", "contacts": "com.android.contacts",
    "messages": "com.google.android.apps.messaging", "sms": "com.google.android.apps.messaging",
    "settings": "com.android.settings", "clock": "com.google.android.deskclock",
    "calendar": "com.google.android.calendar",
}


def open_app(name):
    """Launch an app by name or package (no root). Uses monkey launcher."""
    err = _need_termux()
    if err:
        return err
    clean = re.sub(r"[^\w .+\-]", "", name).strip()
    if not clean:
        return "ERROR: empty app name."
    key = clean.lower()
    pkg = COMMON_APPS.get(key, clean if "." in clean else None)
    if not pkg:
        code, out = _run(f"pm list packages | grep -i {key.split()[0]}", 10)
        m = re.search(r"package:([\w.]+)", out)
        if not m:
            return (f"ERROR: couldn't find an app called '{clean}'. "
                    f"Try the full package name, e.g. open_app('com.spotify.music').")
        pkg = m.group(1)
    code, out = _run(f"monkey -p {pkg} -c android.intent.category.LAUNCHER 1", 15)
    if code == 0 and "No activities found" not in out:
        return f"Launched '{clean}' ({pkg})."
    code2, out2 = _run(f"am start --user 0 -n {pkg}/.MainActivity 2>&1 || "
                       f"am start --user 0 {pkg} 2>&1 || "
                       f"cmd package resolve-activity --brief {pkg}", 15)
    return f"Launch attempt for {pkg}: {out[-300:]} {out2[-300:]}".strip()


SETTING_SCREENS = {
    "wifi": "android.settings.WIFI_SETTINGS", "bluetooth": "android.settings.BLUETOOTH_SETTINGS",
    "display": "android.settings.DISPLAY_SETTINGS", "brightness": "android.settings.DISPLAY_SETTINGS",
    "sound": "android.settings.SOUND_SETTINGS", "volume": "android.settings.SOUND_SETTINGS",
    "battery": "android.settings.BATTERY_SAVER_SETTINGS",
    "location": "android.settings.LOCATION_SOURCE_SETTINGS",
    "apps": "android.settings.APPLICATION_SETTINGS", "storage": "android.settings.INTERNAL_STORAGE_SETTINGS",
    "hotspot": "android.settings.TETHER_SETTINGS",
}


def open_settings(screen="main"):
    """Open an Android Settings screen (no root). Some toggles must be tapped by the user."""
    err = _need_termux()
    if err:
        return err
    key = screen.strip().lower()
    action = SETTING_SCREENS.get(key, "android.settings.SETTINGS")
    code, out = _run(f"am start -a {action}", 15)
    if code == 0:
        extra = "" if key in ("main",) else \
            " (Android blocks silent changes for mobile data/GPS on new versions: tap it yourself.)"
        return f"Opened Settings screen '{key}'.{extra}"
    return f"ERROR opening settings: {out[-400:]}"


def phone_control(action, value="", title="Kuber"):
    """Change a phone setting or send a notification (no root, via termux-api).

    action: brightness | volume_music | volume_ring | wifi_on | wifi_off |
            bluetooth_on | bluetooth_off | torch_on | torch_off | vibrate | notify
    value: brightness 1-255, volume 0-15, notify text, vibrate ms (default 300).
    """
    err = _need_termux()
    if err:
        return err
    a = action.strip().lower()
    if a == "brightness":
        try:
            v = max(1, min(255, int(float(value))))
        except ValueError:
            return "ERROR: brightness value must be 1-255."
        code, out = _run(f"termux-brightness {v}", 10)
        return f"Brightness set to {v}." if code == 0 else f"ERROR: {out[-300:]}"
    if a in ("volume_music", "volume_ring"):
        stream = "music" if "music" in a else "ring"
        try:
            v = max(0, min(15, int(float(value))))
        except ValueError:
            return "ERROR: volume must be 0-15."
        code, out = _run(f"termux-volume {stream} {v}", 10)
        return f"Volume {stream} set to {v}." if code == 0 else f"ERROR: {out[-300:]}"
    if a == "wifi_on":
        code, out = _run("termux-wifi -e true", 10)
        return "WiFi turned on." if code == 0 else f"ERROR: {out[-300:]}"
    if a == "wifi_off":
        code, out = _run("termux-wifi -e false", 10)
        return "WiFi turned off." if code == 0 else f"ERROR: {out[-300:]}"
    if a == "bluetooth_on":
        code, out = _run("termux-bluetooth -e true || termux-bluetooth enable", 10)
        return "Bluetooth on." if code == 0 else f"ERROR: {out[-300:]}"
    if a == "bluetooth_off":
        code, out = _run("termux-bluetooth -e false || termux-bluetooth disable", 10)
        return "Bluetooth off." if code == 0 else f"ERROR: {out[-300:]}"
    if a == "torch_on":
        code, out = _run("termux-torch on", 10)
        return "Torch on." if code == 0 else f"ERROR: {out[-300:]}"
    if a == "torch_off":
        code, out = _run("termux-torch off", 10)
        return "Torch off." if code == 0 else f"ERROR: {out[-300:]}"
    if a == "vibrate":
        try:
            ms = int(float(value or 300))
        except ValueError:
            ms = 300
        code, out = _run(f"termux-vibrate -d {ms}", 10)
        return f"Vibrated {ms}ms." if code == 0 else f"ERROR: {out[-300:]}"
    if a == "notify":
        if not str(value).strip():
            return "ERROR: notify needs value=text."
        safe = str(value).replace('"', "'")[:600]
        code, out = _run(f'termux-notification --title "{title[:60]}" --content "{safe}"', 10)
        return "Notification shown." if code == 0 else f"ERROR: {out[-300:]}"
    return ("ERROR: unknown action. Use brightness, volume_music, volume_ring, wifi_on, wifi_off, "
            "bluetooth_on, bluetooth_off, torch_on, torch_off, vibrate, notify.")


def _resolve_number(number_or_name):
    target = str(number_or_name).strip()
    if re.fullmatch(r"\+?[\d\s\-()]{7,17}", target):
        return re.sub(r"[\s\-()]", "", target), None
    err = _need_termux()
    if err:
        return None, err
    code, out = _run("termux-contact-list", 10)
    if code != 0:
        return None, f"Couldn't read contacts: {out[-300:]}. Pass a full phone number instead."
    try:
        contacts = json.loads(out)
    except ValueError:
        return None, "Couldn't parse contacts. Pass a full phone number instead."
    want = target.lower()
    for c in contacts:
        if want in str(c.get("name", "")).lower():
            nums = c.get("number") or c.get("numbers") or []
            if isinstance(nums, str):
                nums = [nums]
            if nums:
                n = nums[0] if isinstance(nums[0], str) else nums[0].get("number", "")
                return re.sub(r"[\s\-()]", "", str(n)), None
    return None, (f"No contact matching '{target}'. Say the full number with country code, "
                  "e.g. +919876543210.")


def list_contacts(query=""):
    err = _need_termux()
    if err:
        return err
    code, out = _run("termux-contact-list", 10)
    if code != 0:
        return f"ERROR reading contacts (grant Contacts permission): {out[-300:]}"
    try:
        contacts = json.loads(out)
    except ValueError:
        return "ERROR parsing contacts."
    q = query.strip().lower()
    lines = []
    for c in contacts:
        name = str(c.get("name", ""))
        nums = c.get("number") or c.get("numbers") or ""
        if isinstance(nums, list):
            nums = ", ".join(n if isinstance(n, str) else n.get("number", "") for n in nums)
        if q and q not in name.lower() and q not in str(nums):
            continue
        lines.append(f"{name} - {nums}")
        if len(lines) >= 40:
            break
    return "\n".join(lines) or "(no matching contacts)"


def send_sms(number_or_name, message):
    """Send an SMS via termux-sms-send. Always asks the user first."""
    if not str(message).strip():
        return "ERROR: message is empty."
    number, err = _resolve_number(number_or_name)
    if err:
        return err
    if not confirm(f"The agent wants to SMS {number}:  {message[:120]}"):
        return DECLINED
    t_err = _need_termux()
    if t_err:
        return t_err
    import tempfile
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
        f.write(str(message))
        tmp = f.name
    code, out = _run(f'termux-sms-send -n "{number}" "$(cat {tmp})"; rm -f {tmp}', 20)
    if code == 0:
        return f"SMS sent to {number}."
    return f"ERROR sending SMS (grant SMS permission): {out[-400:]}"


def send_whatsapp(number_or_name, message):
    """Open a WhatsApp chat with pre-filled text. The user taps Send (no-root limit)."""
    if not str(message).strip():
        return "ERROR: message is empty."
    number, err = _resolve_number(number_or_name)
    if err:
        return err
    digits = re.sub(r"\D", "", number)
    text = urllib.parse.quote(str(message)[:1000])
    t_err = _need_termux()
    if t_err:
        return t_err
    code, out = _run(f'termux-open-url "https://wa.me/{digits}?text={text}"', 15)
    if code == 0:
        return (f"Opened WhatsApp chat with {number} and filled the text. "
                "You tap Send yourself (Android does not allow silent WhatsApp sends without root).")
    return f"ERROR: {out[-300:]}"


def open_url(url):
    """Open a URL in the phone browser."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    err = _need_termux()
    if err:
        return err
    code, out = _run(f'termux-open-url "{url}"', 15)
    return f"Opened {url}" if code == 0 else f"ERROR: {out[-300:]}"


TOOLS = {f.__name__: f for f in [search_web, search_images, read_page, download_file,
                                 write_file, read_file, list_files,
                                 ask_user, run_command, system_info, open_app,
                                 open_settings, phone_control, list_contacts,
                                 send_sms, send_whatsapp, open_url]}


def spec(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, "required": required}}}


S = {"type": "string"}
I = {"type": "integer"}
TOOL_SPECS = [
    spec("search_web", "Search the web. Returns titles, links and snippets.",
         {"query": S, "max_results": I}, ["query"]),
    spec("search_images", "Search for images. Returns direct image_url links.",
         {"query": S, "max_results": I}, ["query"]),
    spec("read_page", "Read a web page: preview data, text and links.", {"url": S}, ["url"]),
    spec("download_file", "Download a file into workspace/downloads.",
         {"url": S, "filename": S}, ["url"]),
    spec("write_file", "Create or overwrite a text file in the workspace.", {"path": S, "content": S},
         ["path", "content"]),
    spec("read_file", "Read a text file from the workspace.", {"path": S}, ["path"]),
    spec("list_files", "List files in a workspace folder.", {"path": S}, []),
    spec("ask_user", "Ask the human to do/confirm something or answer a question.",
         {"message": S}, ["message"]),
    spec("run_command", "Run a shell command in Termux and return output.", {"command": S}, ["command"]),
    spec("system_info", "Battery, device, storage, location (termux-api).", {}, []),
    spec("open_app", "Launch an app by name or package, e.g. Spotify or com.spotify.music.",
         {"name": S}, ["name"]),
    spec("open_settings", "Open a Settings screen: wifi, bluetooth, display, sound, battery, "
         "location, apps, storage, hotspot, main.", {"screen": S}, []),
    spec("phone_control", "Headless phone control: brightness (1-255), volume_music/volume_ring "
         "(0-15), wifi_on/off, bluetooth_on/off, torch_on/off, vibrate, notify.",
         {"action": S, "value": S, "title": S}, ["action"]),
    spec("list_contacts", "Search phone contacts.", {"query": S}, []),
    spec("send_sms", "Send an SMS (asks the user first). Use full number or contact name.",
         {"number_or_name": S, "message": S}, ["number_or_name", "message"]),
    spec("send_whatsapp", "Open WhatsApp with pre-filled text; the user taps Send.",
         {"number_or_name": S, "message": S}, ["number_or_name", "message"]),
    spec("open_url", "Open a URL in the phone browser.", {"url": S}, ["url"]),
]

SYSTEM = (
    "You are Kuber on the user's Android phone (Termux, no root). Complete tasks step by step.\n"
    "RESEARCH: search, then read the best pages; never invent facts or links. Save results with write_file.\n"
    "PHONE RULES:\n"
    "- Prefer headless tools: phone_control, system_info, open_url, run_command.\n"
    "- open_settings only opens the screen; on modern Android mobile data/GPS need a human tap. "
    "Say so and use ask_user.\n"
    "- send_sms always confirms first (the tool does this). Never send silently.\n"
    "- send_whatsapp only pre-fills; the human taps Send. Say that clearly.\n"
    "- Never guess phone numbers. Resolve names with list_contacts; if missing, ask_user.\n"
    "- Never repeat the same tool call with the same arguments.\n"
    "When done, reply with a short summary and which files were saved."
)

# ---------------- terminal UI ----------------
try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text
except ImportError:
    sys.exit("Run:  pip install rich   then try again.")

console = Console(highlight=False)
ACCENT = "#7C83FD"

TOOL_ICONS = {
    "search_web": ("🔎", "Searching"), "search_images": ("🖼", "Images"),
    "read_page": ("🌐", "Reading"), "download_file": ("⬇", "Downloading"),
    "write_file": ("✎", "Writing"), "read_file": ("📄", "Reading"),
    "list_files": ("📁", "Listing"), "ask_user": ("🙋", "Asking you"),
    "run_command": ("⚙", "Running"), "system_info": ("💻", "Phone info"),
    "open_app": ("🚀", "Opening"), "open_settings": ("⚙", "Settings"),
    "phone_control": ("📱", "Phone"), "list_contacts": ("👥", "Contacts"),
    "send_sms": ("✉", "SMS"), "send_whatsapp": ("✉", "WhatsApp"),
    "open_url": ("🌐", "Opening"),
}
MAIN_ARG = {"search_web": "query", "search_images": "query", "read_page": "url",
            "download_file": "url", "write_file": "path", "read_file": "path",
            "list_files": "path", "ask_user": "message", "run_command": "command",
            "open_app": "name", "open_settings": "screen", "phone_control": "action",
            "list_contacts": "query", "send_sms": "message", "send_whatsapp": "message",
            "open_url": "url"}


def short(value, n=70):
    text = " | ".join(map(str, value)) if isinstance(value, list) else str(value)
    text = text.replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


def show_tool(step, name, args):
    icon, label = TOOL_ICONS.get(name, ("•", name))
    detail = short(args.get(MAIN_ARG.get(name, ""), "")) if args else ""
    line = Text(f"  {step:>2} ", style="dim")
    line.append(f"{icon}  {label} ", style="bold")
    line.append(detail, style="cyan")
    console.print(line)


def show_result(name, result):
    if result.startswith(("ERROR", "BLOCKED")) or "DECLINED" in result:
        console.print(f"       [red]↳ {short(result, 110)}[/red]")
    elif name in ("send_sms", "send_whatsapp", "phone_control", "download_file"):
        console.print(f"       [green]↳ {short(result, 110)}[/green]")


def ask_brain(history, step):
    t0 = time.time()
    with console.status(f"[{ACCENT}]Thinking[/] [dim](step {step})[/dim]", spinner="dots"):
        reply = client.chat.completions.create(model=MODEL, messages=history, tools=TOOL_SPECS,
                                               extra_body=EXTRA or None, **SAMPLING)
    return reply.choices[0].message, time.time() - t0


def show_answer(text, seconds, steps):
    console.print()
    console.print(Panel(Markdown(text or "_(no answer)_"), border_style=ACCENT,
                        title=f"[bold {ACCENT}]Kuber Android[/]", title_align="left",
                        subtitle=f"[dim]{steps} steps · {seconds:.0f}s[/dim]",
                        subtitle_align="right", padding=(1, 2)))
    console.print()


def run_task(task, history):
    history.append({"role": "user", "content":
                    f"{task}\n\n[Files in workspace]\n{workspace_tree()}"})
    start = time.time()
    for step in range(1, MAX_STEPS + 1):
        compact(history)
        msg, _ = ask_brain(history, step)
        if not msg.tool_calls:
            history.append({"role": "assistant", "content": msg.content or ""})
            show_answer(msg.content, time.time() - start, step)
            return
        history.append(as_dict(msg))
        for call in msg.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
                show_tool(step, name, args)
                result = str(TOOLS[name](**args))
            except Exception as e:
                result = f"ERROR: {e}"
            show_result(name, result)
            history.append({"role": "tool", "tool_call_id": call.id, "content": result[:12000]})
    console.print(f"\n[yellow]Stopped after {MAX_STEPS} steps. Type 'continue'.[/yellow]\n")


HELP = Table.grid(padding=(0, 2))
HELP.add_column(style=f"bold {ACCENT}")
HELP.add_column(style="dim")
for cmd, desc in [("/new", "fresh conversation"), ("/files", "show workspace files"),
                  ("/info", "phone battery/storage info"), ("/help", "this help"),
                  ("/exit", "quit")]:
    HELP.add_row(cmd, desc)


def banner():
    head = Text()
    head.append("◆ Kuber Android\n", style=f"bold {ACCENT}")
    head.append("brain     ", style="dim")
    head.append(f"{BRAIN}\n")
    head.append("workspace ", style="dim")
    head.append(WORKSPACE)
    console.print(Panel(head, border_style=ACCENT, padding=(1, 2)))
    console.print("[dim]Type a task. /help for commands.[/dim]\n")


def main():
    console.clear()
    banner()
    history = [{"role": "system", "content": SYSTEM}]
    first = " ".join(opts.task).strip() if opts.task else ""
    if first:
        console.print(Rule(style="dim"))
        run_task(first, history)
        if not opts.stay:
            return
    while True:
        try:
            task = console.input(f"[bold {ACCENT}]❯[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye[/dim]")
            break
        cmd = task.lower().lstrip("/")
        if cmd in ("exit", "quit"):
            console.print("[dim]bye[/dim]")
            break
        if cmd in ("new", "clear"):
            history = history[:1]
            console.clear()
            banner()
            continue
        if cmd == "help":
            console.print(HELP)
            console.print()
            continue
        if cmd == "files":
            console.print(Panel(workspace_tree(), title="[bold]workspace[/bold]",
                                title_align="left", border_style="dim"))
            continue
        if cmd == "info":
            console.print(Panel(system_info(), title="[bold]phone[/bold]",
                                title_align="left", border_style="dim"))
            continue
        if not task:
            continue
        console.print(Rule(style="dim"))
        try:
            run_task(task, history)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]\n")
        except Exception as e:
            console.print(Panel(f"{type(e).__name__}: {str(e)[:600]}",
                                title="[bold red]Couldn't reach the brain[/bold red]",
                                border_style="red"))


if __name__ == "__main__":
    main()
