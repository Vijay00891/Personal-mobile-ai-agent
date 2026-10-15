# Always-on "Hey Kuber" (Tasker + AutoVoice)

Tap-to-talk (`kuber-voice.sh`) costs zero idle battery. True always-listening costs
battery and needs paid apps — set it up only if you accept that trade.

## What you need

* Tasker (paid) + AutoVoice plugin (paid, hotword/continuous are pro features)
* Termux:Tasker add-on — **from the same source as your Termux**
  (same signature rule as Termux:API; GitHub releases if Termux came from GitHub)
* All three installed, then open each once and grant microphone access (AutoVoice).

## 1. Let Tasker run Termux commands

In Termux:
```bash
mkdir -p ~/.termux
echo "allow-external-apps=true" >> ~/.termux/termux.properties
```
Android Settings → Apps → turn OFF battery optimization for
Termux, Termux:API, Termux:Tasker, Tasker, AutoVoice.
On Android 10+, background Termux commands may wait for a notification tap —
that is an Android restriction, not a bug.

## 2. The task that wakes Kuber

Tasker → Tasks → `+` → name it `Kuber` → `+` action → Plugin → Termux:Tasker →
(pencil icon) Executable: `~/kuber-android/kuber-voice.sh`, check
"Run in Termux session" (so approvals and questions work in a visible terminal).

Test it now: play button on the task. Kuber should greet you out loud.

## 3. The always-on trigger (pick ONE)

**A. Hotword (recommended):** AutoVoice app → Settings → Hotword → phrase
`hey kuber`. Uses Android's built-in hotword engine: low-to-moderate battery.
Then Tasker → Profiles → `+` → Event → Plugin → AutoVoice Recognized →
Command Filter: `hey kuber` → link it to the `Kuber` task.

**B. Continuous listening:** Tasker action Plugin → AutoVoice Continuous, plus a
Profile on AutoVoice Recognized with filter `kuber`. Hears everything, so the
AutoVoice dev himself warns it **drains battery considerably** and Android may
kill it unless its persistent notification stays on. Use only in windows
(e.g. Tasker turns it on when connected to home WiFi, off otherwise).

## 4. Middle ground (no always-on mic)

If the drain is too much: skip AutoVoice. Use the Termux:Widget home-screen
`Kuber` button, a Tasker shake/headset-button trigger, or a Bixby/Google routine
that launches the widget — all run the same `kuber-voice.sh`.

## ElevenLabs 401 (invalid key)

`ElevenLabs error 401` means the key itself is rejected (you still hear the
robotic fallback voice, so nothing is broken). Check in the SAME Termux session:

```bash
echo ${#ELEVEN_API_KEY}   # expect ~32, starting with sk_
env | grep ELEVEN         # must show your key, no spaces/quotes inside
```

Then re-test: `bash ~/kuber-android/kuber-speak.sh "test"`.
If still 401: regenerate the key at elevenlabs.io (profile → API keys) and
`export ELEVEN_API_KEY="newkey"` again. Keys pasted with a trailing space or
from a different account both give 401.
