# Kuber Android — setup (no root)

Phone agent that reuses your Cloudflare brain. No Kaggle server needed.

## What you got

* `my_agent_android.py` — the agent. Same loop as PC `my_agent.py`, but PC tools
  (`pyautogui`, Outlook, desktop Chrome) are replaced with Android tools:
  `system_info`, `open_app`, `open_settings`, `phone_control`
  (brightness/volume/wifi/bluetooth/torch/notify), `send_sms`,
  `list_contacts`, `send_whatsapp`, `open_url`, `run_command`.
* `requirements-android.txt` — pip deps.
* `termux-setup.sh` — one-time Termux installer.
* `workspace/` — agent files go here (created on first run).

## Setup

### 1. Install apps (from F-Droid, not Play Store)
1. `Termux`
2. `Termux:API` — without this, phone control tools only return an error message.

Play Store versions are outdated and `termux-api` calls will fail.

### 2. Copy this folder to the phone
Any way works:
* USB cable → `Internal storage/Download/android/`
* `git clone` your repo in Termux, or
* `scp -r android phone:/data/data/com.termux/files/home/kuber-android`

Then in Termux:
```bash
cd ~/kuber-android   # wherever you put it
bash termux-setup.sh
```

Accept the storage popup. Grant SMS / Contacts / Location when asked later —
each tool asks only when it needs it.

### 3. Connect the Cloudflare brain
Same account as your PC (`cf-setup`). In Termux:
```bash
export CF_ACCOUNT_ID="your-account-id"
export CF_API_TOKEN="your-token"
```
Keep them permanently:
```bash
echo 'export CF_ACCOUNT_ID="..."' >> ~/.bashrc
echo 'export CF_API_TOKEN="..."' >> ~/.bashrc
echo 'export CF_AGENT_MODEL="@cf/qwen/qwen3-30b-a3b-fp8"' >> ~/.bashrc
source ~/.bashrc
```

Alternative brains (same as PC):
```bash
export GEMINI_API_KEY="..." && python my_agent_android.py --gemini
export ANTHROPIC_API_KEY="..." && python my_agent_android.py --claude
```

### 4. Run
```bash
python my_agent_android.py --cloudflare
```

Try:
```
/info
what is my battery and storage
set brightness to 120 and send me a test notification
open wifi settings
list my contacts for mom
```

One-shot mode (for Termux:Widget buttons):
```bash
python my_agent_android.py --cloudflare --stay "turn on wifi and tell me battery"
```

## Permissions map

| Task | What happens | Permission |
|---|---|---|
| battery/storage/device | `termux-battery-status`, disk check | none |
| brightness/volume/torch/vibrate/notify | `termux-*` headless | none |
| wifi/bluetooth toggle | `termux-wifi`, `termux-bluetooth` | location for scan |
| open settings page | `am start -a android.settings.*` | none |
| launch app | `monkey -p <package>` | none |
| list contacts | `termux-contact-list` | Contacts |
| SMS | `termux-sms-send` (asks y/n first) | SMS |
| WhatsApp | opens `wa.me` chat pre-filled, you tap Send | none |
| open link | `termux-open-url` | none |

## No-root limits (important)

* Mobile data toggle, GPS on/off, and tapping buttons inside other apps
  cannot be done silently without root/Shizuku. The agent opens the right
  Settings screen and asks you to tap — same as `ask_user` on PC.
* WhatsApp has no official send API. The agent pre-fills the chat; you tap Send.
* Android kills background Termux after a while. Keep Termux foreground or
  use `termux-wake-lock` while the agent works.
* First SMS/contact call shows a permission popup — accept it, then retry.

## Troubleshooting

* `termux-api not found` → `pkg install termux-api` + install Termux:API app, restart Termux.
* `Cloudflare not set` → `export` vars above, then open a new Termux session.
* `4006 / neurons` → daily Cloudflare free quota used (resets 5:30 AM IST). Use `--gemini`.
* `No app found` → use full package: `open Spotify` works, else `com.spotify.music`.
* Storage empty → run `termux-setup-storage` and accept the popup.
