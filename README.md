# CarThing

A touchscreen media console for a Raspberry Pi 3B + 5" HDMI LCD, styled
after Spotify's Car Thing. Runs full-screen with pygame-ce over KMSDRM (no
desktop environment), and plays through a HiFiBerry DAC.

It drives two sources at once — Spotify Connect (via raspotify) and a
Logitech Media Server player (via squeezelite) — sharing the DAC through
ALSA `dmix`, with a safety net that auto-pauses one source if the other
starts playing. From the touchscreen you get:

- A home/clock/weather screen with quick-pick album tiles when nothing's
  playing (biased toward whatever artist you were last listening to)
- Full now-playing screens for both sources, with shuffle — including a
  genuine library-wide shuffle on the LMS side via RandomPlay, which
  Spotify's API has no equivalent for
- A library browser (Albums/Random/Playlists/Artists) with swipe paging,
  on-disk caching, and a manual refresh
- Tap-to-wake sleep, debounced touch handling, and a loading spinner for
  anything that has to hit the network

This is a personal project built out in a running conversation with
Claude — the setup steps below are everything needed to reproduce it on
the same hardware. Not actively maintained for contributions, but feel
free to fork it.

MIT licensed — use it, fork it, build on it, no need to ask.

## 1. Flash RPi OS Lite 64-bit (no desktop)

## 2. config.txt (/boot/firmware/config.txt)
Leave `dtoverlay=vc4-kms-v3d` enabled (full KMS) — the panel's EDID is detected
fine, so no manual HDMI timing overrides are needed. Just add under `[all]`:
```
max_usb_current=1
```

Without this, the touch controller on this panel (LCDWiki 5inch HDMI Display-B)
can fail to enumerate or drop out — it's USB-powered separately from the HDMI
video signal, and the Pi 3B's default USB current limit isn't always enough.

If you ever *do* need to hand-force HDMI timings (e.g. picture is garbled or
wrong resolution because EDID isn't detected), see the fallback config at
https://www.lcdwiki.com/5inch_HDMI_Display-B — that path requires disabling
`vc4-kms-v3d` (legacy firmware KMS instead of full KMS), which is a bigger
change and not needed here since video already works correctly.

### HiFiBerry DAC (standard DAC/DAC+)
Add these as their own lines — **alongside** `dtoverlay=vc4-kms-v3d`, not
replacing it (multiple `dtoverlay=` lines all apply; losing the vc4 one breaks
`kmsdrm` and therefore the whole UI):
```
dtparam=audio=off
dtoverlay=hifiberry-dac
```
`dtparam=audio=off` disables the onboard/HDMI audio so the DAC is the only
card. Check with `aplay -l` (expect `sndrpihifiberry`) and
`speaker-test -c2 -twav -l1`. The overlay loads whether or not the board is
seated, so a listed card doesn't prove the hardware is connected.

### Power
Use a real 5.1V / 2.5A+ supply. With the touchscreen + DAC on a Pi 3B, a 2A
supply throttled at boot. Verify with `vcgencmd get_throttled` (want `0x0`).

## 2b. Spotify Connect on the Pi (raspotify) — plays through the DAC
```bash
sudo apt-get -y install curl && curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
sudo nano /etc/raspotify/conf      # set LIBRESPOT_DEVICE="hw:CARD=sndrpihifiberry,DEV=0"
sudo systemctl restart raspotify
```
Requires Spotify Premium. Pick the Pi once from any Spotify app's device list so
it registers with the account; after that the touchscreen's output button
("play on this device") can move playback to it. The Pi is matched by any
device name containing `raspotify` (the default, e.g. `raspotify(rpi3b)`); if
you renamed it, set `SPOTIFY_DEVICE_NAME` in `.env` to the exact name.

## 3. Install system deps
```bash
sudo apt update
sudo apt install -y python3-venv python3-pip libsdl2-dev libsdl2-image-dev \
  libsdl2-mixer-dev libsdl2-ttf-dev libfreetype6-dev fonts-dejavu
```

## 4. Create venv & install
```bash
cd ~/carthing
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 5. Create .env
```bash
cp .env.example .env
nano .env  # fill in your Spotify creds + API key
```

## 6. Test run
```bash
source venv/bin/activate
python main.py
```

## 7. Auto-start as service
```bash
sudo cp carthing.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable carthing
sudo systemctl start carthing
```
