#!/data/data/com.termux/files/usr/bin/bash
# kuber-speak: say TEXT out loud. Uses ElevenLabs (natural voice) when
# ELEVEN_API_KEY is set, otherwise the free on-device Android voice.
#
# Setup:  export ELEVEN_API_KEY="sk_..."   (free 10k chars/month at elevenlabs.io)
# Optional: ELEVEN_VOICE (default Rachel), ELEVEN_MODEL (default eleven_turbo_v2_5).
# Find other voice IDs in your ElevenLabs dashboard / voice library.
TEXT="$*"
[ -z "${TEXT:-}" ] && exit 0

if [ -z "${ELEVEN_API_KEY:-}" ]; then
  termux-tts-speak "$TEXT" 2>/dev/null
  exit 0
fi

VOICE="${ELEVEN_VOICE:-21m00Tcm4TlvDq8ikWAM}"
MODEL="${ELEVEN_MODEL:-eleven_turbo_v2_5}"
OUT="$PREFIX/tmp/kuber-voice.mp3"
JSON=$(python -c 'import json,sys; print(json.dumps({"text": sys.argv[1][:1000], "model_id": sys.argv[2], "voice_settings": {"stability": 0.5, "similarity_boost": 0.5}}))' "$TEXT" "$MODEL")
CODE=$(curl -sS -o "$OUT" -w "%{http_code}" -X POST "https://api.elevenlabs.io/v1/text-to-speech/$VOICE" \
  -H "xi-api-key: $ELEVEN_API_KEY" -H "Content-Type: application/json" -H "Accept: audio/mpeg" \
  --max-time 60 -d "$JSON")
if [ "$CODE" = "200" ]; then
  termux-media-player play "$OUT" >/dev/null 2>&1
  # wait out the playback before deleting the file (~14 chars/sec + margin)
  WAIT=$(( ${#TEXT} / 14 + 4 ))
  [ "$WAIT" -gt 120 ] && WAIT=120
  sleep "$WAIT"
else
  echo "ElevenLabs error $CODE, using device voice" >&2
  termux-tts-speak "$TEXT" 2>/dev/null
fi
rm -f "$OUT"
