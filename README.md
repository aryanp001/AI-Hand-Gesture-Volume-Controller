# 🎛️ AirVolume Pro — AI Hand Gesture Volume Controller

Control your Windows system volume in real time using nothing but your webcam and your hand. No keyboard, no mouse, no touching your device — just pinch, fist, or open your palm.

---

## 📖 Overview

**AirVolume Pro** is a real-time computer vision application that turns hand gestures captured from a standard webcam into system audio control on Windows. It combines hand-landmark tracking, custom gesture-recognition logic, and signal smoothing to turn a naturally noisy input (a hand moving in front of a camera) into a stable, responsive volume control — all wrapped in a live "cyberpunk HUD" overlay showing exactly what the system is seeing and doing.

It was built as an exploration of applied computer vision: hand tracking, gesture classification, temporal signal filtering, and direct OS-level audio integration, combined into a single polished, usable tool.

---

## ✨ Features

- **🤏 Pinch-to-volume** — the distance between your thumb and index finger maps continuously to system volume (0–100%).
- **✊ Fist to mute** — a closed fist toggles mute/unmute, with debouncing so it doesn't fire repeatedly on a single gesture.
- **🖐️ Open palm = neutral** — an open hand holds the current volume steady, so you can reposition your hand without accidentally changing anything.
- **⚡ Jitter-free tracking** — a velocity-adaptive Exponential Moving Average (EMA) plus a dead-zone filter smooth out natural hand tremor and camera noise, so volume changes feel deliberate, not twitchy.
- **🎯 Self-calibrating** — press a single key to recalibrate the pinch distance range to your own hand size, camera, and seating distance.
- **🖥️ Live HUD** — real-time skeleton overlay, gesture state, pinch distance readout, a 20-segment volume level meter, a 60-frame scrolling volume history graph, and an FPS counter.
- **⌨️ Full keyboard control** — pause/resume, manual mute, reset, calibrate, and quit, all without leaving the window.

---

## 🧠 How It Works

```
Webcam Frame
    │
    ▼
MediaPipe Hands ──► 21 (x, y, z) hand landmarks per frame
    │
    ▼
Gesture Logic
    ├─ pinch_distance = |thumb_tip − index_tip|   (Euclidean, in pixels)
    ├─ is_fist  = all 4 fingertips curled below their PIP joints
    └─ is_palm  = all 4 fingertips extended above their PIP joints
    │
    ▼
Signal Conditioning
    ├─ Velocity-adaptive EMA smoothing (fast hand = responsive, still hand = damped)
    └─ Dead-zone filter (ignores sub-1.5% volume deltas from residual jitter)
    │
    ▼
Audio Controller (Pycaw) ──► sets real Windows master volume / mute state
    │
    ▼
HUD Renderer (OpenCV overlay) ──► skeleton, metrics, level meter, history graph
    │
    ▼
Live window (cv2.imshow)
```

### Gesture detection details

| Gesture | Detection logic | Action |
|---|---|---|
| Pinch | Distance between landmark 4 (thumb tip) and landmark 8 (index tip), normalized against a calibrated `[MIN_DIST, MAX_DIST]` pixel range via `numpy.interp` | Sets volume 0–100% |
| Fist | For each fingertip/PIP pair `(8,6) (12,10) (16,14) (20,18)`, the finger counts as curled if the tip sits below its PIP joint in image-space; a fist is all four curled | Toggles mute (700ms debounce) |
| Open palm | Same landmark pairs, inverse condition — all four fingers extended | Holds volume steady (no-op) |

### Smoothing

Raw pinch distance is noisy frame-to-frame due to hand tremor and camera sensor noise. Rather than a fixed-weight moving average (which either lags behind fast intentional movement or lets through jitter during slow movement), the smoothing factor itself adapts to how fast the hand is moving:

```python
velocity = abs(new_distance - previous_distance)
alpha = min(MAX_ALPHA, BASE_ALPHA + velocity * 0.02)
smoothed = alpha * new_distance + (1 - alpha) * previous_smoothed
```

A dead zone on top of this ignores any resulting volume change smaller than 1.5%, so the app doesn't chase noise once your hand is effectively still.

---

## 🛠️ Tech Stack

| Library | Role |
|---|---|
| [OpenCV](https://opencv.org/) | Webcam capture, HUD rendering |
| [MediaPipe](https://developers.google.com/mediapipe) | Pretrained real-time hand-landmark detection |
| [NumPy](https://numpy.org/) | Distance math, range mapping |
| [Pycaw](https://github.com/AndreMiras/pycaw) | Python wrapper around the Windows Core Audio API |
| [comtypes](https://github.com/enthought/comtypes) | COM interop required by Pycaw |

---

## 📦 Installation

> **Requires Python 3.9–3.12.** MediaPipe's legacy `solutions` API (used here) is not available on Python 3.13+, and newer MediaPipe releases have removed it entirely — see [Troubleshooting](#-troubleshooting) below for why the version pin matters.

```bash
# 1. Clone the repo
git clone https://github.com/<your-username>/airvolume-pro.git
cd airvolume-pro

# 2. Create a virtual environment (use Python 3.9–3.12)
py -3.11 -m venv venv
venv\Scripts\activate

# 3. Install dependencies
pip install opencv-python numpy pycaw comtypes
pip install mediapipe==0.10.21
```

You'll also need the **Microsoft Visual C++ Redistributable (x64)** installed system-wide, since MediaPipe's compiled components depend on it: [aka.ms/vs/17/release/vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe)

---

## ▶️ Usage

```bash
venv\Scripts\activate
python airvolume_pro.py
```

| Key | Action |
|---|---|
| `SPACE` | Pause / resume gesture tracking |
| `M` | Manually mute / unmute |
| `R` | Reset volume to 50% |
| `C` | Calibrate pinch range (press once pinched closed, once fully open) |
| `Q` / `ESC` | Quit |

### Calibrating to your hand

Everyone's hand size, camera field of view, and typical distance from the webcam differ, so the default `[25px, 200px]` pinch range is only a starting point. Press `C`, hold your pinch fully closed and press `C` again, then hold your hand fully open and press `C` a third time. The app will lock in your personal range for the rest of the session.

---

## 📁 Project Structure

```
airvolume-pro/
├── airvolume_pro.py     # Full application (tracking, gestures, audio, HUD)
├── README.md
└── requirements.txt
```

---

## 🩺 Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `Failed to find real location of ...python.exe` during `venv` creation | Known Python 3.13 `venv` bug on Windows, sometimes worsened by OneDrive-synced folders | Use Python 3.9–3.12 instead: `py -3.11 -m venv venv` |
| `AttributeError: module 'mediapipe' has no attribute 'solutions'` | MediaPipe 0.10.30+ removed the legacy Solutions API this project uses | Pin the version: `pip install mediapipe==0.10.21` |
| `No matching distribution found for mediapipe==0.10.21` | You're on Python 3.13; pre-0.10.30 wheels only support 3.9–3.12 | Recreate your venv with `py -3.11` (or 3.9/3.10/3.12) |
| `ImportError: DLL load failed while importing _framework_bindings` | Missing Microsoft Visual C++ Redistributable | Install it from [aka.ms/vs/17/release/vc_redist.x64.exe](https://aka.ms/vs/17/release/vc_redist.x64.exe), then restart your PC |
| `AttributeError: 'AudioDevice' object has no attribute 'Activate'` | Newer Pycaw versions expose `.EndpointVolume` directly instead of the old manual `.Activate()` COM call | Already handled in `airvolume_pro.py` — it detects and uses whichever API your installed Pycaw version supports |
| `ModuleNotFoundError: No module named 'cv2'` (or similar) | Virtual environment isn't activated | Run `venv\Scripts\activate` before `python airvolume_pro.py` — check for `(venv)` at the start of your prompt |
| `python: can't open file 'airvolume_pro.py'` | The file was saved with a hidden extra extension (e.g. `.py.txt`) by a text editor | Run `dir` to check the real filename, or re-save with "All Files" type selected |

---

## 🚧 Known Limitations

- **Windows only** — volume control uses the Windows Core Audio API via Pycaw. Linux/macOS would need a separate audio backend (`pactl`/`amixer` or `osascript`).
- **Single hand** — currently tracks one hand at a time.
- **Lighting-dependent** — like all camera-based hand tracking, accuracy drops in low light or with a cluttered background.

## 🗺️ Roadmap / Ideas

- [ ] Per-application volume control (e.g. gesture targets just Spotify or Chrome)
- [ ] Additional gestures — swipe for track skip, two-finger pinch for brightness/zoom
- [ ] Cross-platform audio backends (macOS/Linux)
- [ ] Custom gesture-to-action macro recording
- [ ] Voice + gesture fusion (wake-word arming to reduce accidental triggers)

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## 🙌 Acknowledgements

- [Google MediaPipe](https://developers.google.com/mediapipe) for real-time hand tracking
- [Pycaw](https://github.com/AndreMiras/pycaw) for Windows audio API access
