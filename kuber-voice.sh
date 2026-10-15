#!/data/data/com.termux/files/usr/bin/bash
# kuber-voice: one-tap voice Kuber. Tap it (or the home-screen button), it greets
# you, listens once, does the task, and speaks the answer. Nothing runs in the
# background, so there is zero idle battery drain.
#
# Needs: Termux:API app (for speech + TTS). Optional: Termux:Widget app, then copy
# this file to ~/.shortcuts/ to get a "Kuber" button on your home screen.
set -u
cd "$(dirname "$0")"

H=$(date +%H)
if [ "$H" -lt 12 ]; then G="Good morning"; elif [ "$H" -lt 17 ]; then G="Good afternoon"; else G="Good evening"; fi
BAT=$(termux-battery-status 2>/dev/null | grep -o '"percentage":[0-9]*' | grep -o '[0-9]*')
[ -n "${BAT:-}" ] && G="$G. Battery $BAT percent."
termux-tts-speak "$G. I am Kuber. What can I do for you?" 2>/dev/null

TASK=$(termux-speech-to-text 2>/dev/null | head -1 | tr -d '\r')
# If the user only said the name ("Kuber", "hey Kuber"), strip it and listen again
# for the real task instead of sending a one-word task to the brain.
TASK=$(echo "$TASK" | sed -E 's/^[^A-Za-z]*(hey|hi|ok|okay|hello)?[^A-Za-z]*(kuber|kubera|kubair|cuber|cooper)[^A-Za-z]*//I' | sed 's/^ *//')
if [ -z "${TASK:-}" ]; then
  termux-tts-speak "Yes? What can I do for you?" 2>/dev/null
  TASK=$(termux-speech-to-text 2>/dev/null | head -1 | tr -d '\r')
fi
if [ -z "${TASK:-}" ]; then
  termux-tts-speak "I did not catch that. Run me again to retry." 2>/dev/null
  exit 0
fi
echo "Heard: $TASK"
termux-tts-speak "Working on it." 2>/dev/null

ANS="$PREFIX/tmp/kuber-ans.txt"
export PYTHONDONTWRITEBYTECODE=1
python my_agent_android.py --cloudflare --voice-out "$ANS" -- "$TASK"
[ -f "$ANS" ] && termux-tts-speak "$(head -c 600 "$ANS")" 2>/dev/null
rm -f "$ANS"
