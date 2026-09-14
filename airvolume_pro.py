"""
AirVolume Pro - AI Hand Gesture Volume Controller (starter implementation)

Controls Windows system volume with hand gestures via webcam:
  - Pinch (thumb <-> index finger) distance -> volume 0-100%
  - Closed fist -> toggle mute/unmute
  - Open palm -> neutral (hold current volume)

Requires (Windows only, for real audio control):
    pip install opencv-python mediapipe numpy pycaw comtypes

Run:
    python airvolume_pro.py

Keys:
    SPACE - pause/resume    M - mute/unmute    R - reset to 50%
    C     - calibrate (press once at pinched-closed, again at fully-open)
    Q/ESC - quit
"""

import time
import collections
import numpy as np
import cv2
import mediapipe as mp

# --- Try to import pycaw (Windows-only). Fall back to a dummy controller
# so the script still runs (without real volume control) on other OSes. ---
try:
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    class AudioController:
        def __init__(self):
            device = AudioUtilities.GetSpeakers()
            # Modern pycaw wraps the endpoint in an AudioDevice object that
            # exposes .EndpointVolume directly (no manual COM Activate() needed).
            if hasattr(device, "EndpointVolume"):
                self.volume = device.EndpointVolume
            else:
                # Fallback for older pycaw versions that still return a raw
                # COM device requiring manual interface activation.
                interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                self.volume = cast(interface, POINTER(IAudioEndpointVolume))

        def set_volume(self, pct):
            pct = max(0.0, min(1.0, pct))
            self.volume.SetMasterVolumeLevelScalar(pct, None)

        def get_volume(self):
            return self.volume.GetMasterVolumeLevelScalar()

        def set_mute(self, muted: bool):
            self.volume.SetMute(1 if muted else 0, None)

        def is_muted(self):
            return bool(self.volume.GetMute())

    AUDIO_BACKEND = "pycaw"

except Exception:
    class AudioController:
        """Dummy fallback so the app still runs without real audio control."""
        def __init__(self):
            self._vol = 0.5
            self._muted = False

        def set_volume(self, pct):
            self._vol = max(0.0, min(1.0, pct))

        def get_volume(self):
            return self._vol

        def set_mute(self, muted: bool):
            self._muted = muted

        def is_muted(self):
            return self._muted

    AUDIO_BACKEND = "dummy (pycaw not available)"


# ---------------- Config ----------------
CAM_INDEX = 0
MIN_DIST, MAX_DIST = 25, 200      # pinch distance calibration (px)
DEAD_ZONE = 0.015                 # ignore volume changes smaller than 1.5%
BASE_ALPHA, MAX_ALPHA = 0.25, 0.8 # EMA smoothing bounds
FIST_DEBOUNCE_SEC = 0.7
HISTORY_LEN = 60

FINGER_TIPS_PIPS = [(8, 6), (12, 10), (16, 14), (20, 18)]  # (tip, pip) landmark indices


def landmark_px(landmark, w, h):
    return np.array([landmark.x * w, landmark.y * h])


def is_fist(landmarks, w, h):
    """All four fingers curled (tip below its PIP joint in image-y)."""
    for tip_i, pip_i in FINGER_TIPS_PIPS:
        tip_y = landmarks[tip_i].y * h
        pip_y = landmarks[pip_i].y * h
        if tip_y < pip_y:  # extended, not curled
            return False
    return True


def is_open_palm(landmarks, w, h):
    for tip_i, pip_i in FINGER_TIPS_PIPS:
        tip_y = landmarks[tip_i].y * h
        pip_y = landmarks[pip_i].y * h
        if tip_y > pip_y:  # curled, not extended
            return False
    return True


def adaptive_ema(new_val, prev_raw, prev_smoothed, base_alpha=BASE_ALPHA, max_alpha=MAX_ALPHA):
    velocity = abs(new_val - prev_raw)
    alpha = min(max_alpha, base_alpha + velocity * 0.02)
    return alpha * new_val + (1 - alpha) * prev_smoothed


def draw_panel(frame, x, y, w, h, alpha=0.55, color=(20, 20, 20)):
    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + w, y + h), color, -1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


def main():
    mp_hands = mp.solutions.hands
    mp_draw = mp.solutions.drawing_utils
    hands = mp_hands.Hands(max_num_hands=1, min_detection_confidence=0.7,
                            min_tracking_confidence=0.7)

    cap = cv2.VideoCapture(CAM_INDEX)
    audio = AudioController()

    smoothed_dist = None
    prev_raw_dist = None
    last_applied_vol = audio.get_volume()
    history = collections.deque([last_applied_vol] * HISTORY_LEN, maxlen=HISTORY_LEN)

    paused = False
    last_fist_toggle = 0.0
    calibrating = False
    calib_stage = 0  # 0 = idle, 1 = waiting for "closed" sample, 2 = waiting for "open" sample
    global MIN_DIST, MAX_DIST

    prev_time = time.time()

    print(f"[AirVolume Pro] audio backend: {AUDIO_BACKEND}")

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.flip(frame, 1)
        h, w, _ = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        state = "NO HAND"
        dist_px = None

        if not paused:
            results = hands.process(rgb)
            if results.multi_hand_landmarks:
                hand_landmarks = results.multi_hand_landmarks[0]
                lm = hand_landmarks.landmark

                mp_draw.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS,
                                        mp_draw.DrawingSpec(color=(255, 200, 0), thickness=1, circle_radius=2),
                                        mp_draw.DrawingSpec(color=(0, 255, 255), thickness=1))

                thumb = landmark_px(lm[4], w, h)
                index = landmark_px(lm[8], w, h)
                dist_px = float(np.linalg.norm(thumb - index))

                cv2.line(frame, tuple(thumb.astype(int)), tuple(index.astype(int)), (0, 255, 0), 2)
                cv2.circle(frame, tuple(thumb.astype(int)), 8, (0, 255, 0), -1)
                cv2.circle(frame, tuple(index.astype(int)), 8, (0, 255, 0), -1)

                if calibrating:
                    if calib_stage == 1:
                        cv2.putText(frame, "Hold PINCH CLOSED, press C", (30, h - 60),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                    elif calib_stage == 2:
                        cv2.putText(frame, "Hold hand FULLY OPEN, press C", (30, h - 60),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

                if is_fist(lm, w, h):
                    state = "FIST (mute toggle)"
                    now = time.time()
                    if now - last_fist_toggle > FIST_DEBOUNCE_SEC:
                        audio.set_mute(not audio.is_muted())
                        last_fist_toggle = now
                elif is_open_palm(lm, w, h):
                    state = "OPEN PALM (hold)"
                elif not calibrating:
                    state = "VOLUME CONTROL ACTIVE"

                    if prev_raw_dist is None:
                        smoothed_dist = dist_px
                        prev_raw_dist = dist_px
                    else:
                        smoothed_dist = adaptive_ema(dist_px, prev_raw_dist, smoothed_dist)
                        prev_raw_dist = dist_px

                    target_vol = float(np.interp(smoothed_dist, [MIN_DIST, MAX_DIST], [0.0, 1.0]))

                    if abs(target_vol - last_applied_vol) > DEAD_ZONE:
                        audio.set_volume(target_vol)
                        last_applied_vol = target_vol
            else:
                prev_raw_dist = None

        history.append(audio.get_volume())

        # ---------------- HUD ----------------
        curr_time = time.time()
        fps = 1.0 / max(curr_time - prev_time, 1e-6)
        prev_time = curr_time

        cv2.rectangle(frame, (0, 0), (w, 40), (10, 10, 10), -1)
        cv2.putText(frame, "AIRVOLUME PRO", (15, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
        cv2.putText(frame, f"{fps:0.1f} FPS", (w - 220, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        status_txt, status_color = ("PAUSED", (0, 0, 255)) if paused else ("ACTIVE", (0, 255, 0))
        cv2.putText(frame, status_txt, (w - 100, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.6, status_color, 2)

        # Left metrics panel
        draw_panel(frame, 10, 55, 250, 130)
        cv2.putText(frame, "GESTURE METRICS", (20, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(frame, f"Distance: {dist_px:.0f} px" if dist_px else "Distance: --",
                    (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        cv2.putText(frame, f"Range: [{MIN_DIST} - {MAX_DIST} px]", (20, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
        cv2.putText(frame, f"State: {state}", (20, 165), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 100), 1)

        # Right volume monitor panel
        vol_pct = audio.get_volume() * 100
        draw_panel(frame, w - 220, 55, 210, 170)
        cv2.putText(frame, "VOLUME MONITOR", (w - 210, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(frame, f"{vol_pct:.0f}%", (w - 210, 115), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 100, 255), 2)
        if audio.is_muted():
            cv2.putText(frame, "MUTED [M to unmute]", (w - 210, 140), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)

        # Level meter (segmented)
        meter_x, meter_y, meter_w = w - 210, 155, 190
        segments = 20
        filled = int((vol_pct / 100) * segments)
        seg_w = meter_w // segments
        for i in range(segments):
            color = (0, 200, 0) if i < filled else (60, 60, 60)
            cv2.rectangle(frame, (meter_x + i * seg_w, meter_y), (meter_x + i * seg_w + seg_w - 2, meter_y + 15), color, -1)

        # History graph
        hist_y0 = 205
        pts = list(history)
        for i in range(1, len(pts)):
            x1 = meter_x + int((i - 1) / HISTORY_LEN * meter_w)
            x2 = meter_x + int(i / HISTORY_LEN * meter_w)
            y1 = hist_y0 + 20 - int(pts[i - 1] * 20)
            y2 = hist_y0 + 20 - int(pts[i] * 20)
            cv2.line(frame, (x1, y1), (x2, y2), (0, 200, 255), 1)

        # Bottom help bar
        help_txt = "[SPACE] Pause  [M] Mute  [R] Reset 50%  [C] Calibrate  [Q/ESC] Exit"
        cv2.rectangle(frame, (0, h - 30), (w, h), (10, 10, 10), -1)
        cv2.putText(frame, help_txt, (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)

        cv2.imshow("AirVolume Pro", frame)
        key = cv2.waitKey(1) & 0xFF

        if key in (ord('q'), 27):
            break
        elif key == ord(' '):
            paused = not paused
        elif key == ord('m'):
            audio.set_mute(not audio.is_muted())
        elif key == ord('r'):
            audio.set_volume(0.5)
            last_applied_vol = 0.5
        elif key == ord('c'):
            if not calibrating:
                calibrating = True
                calib_stage = 1
            elif calib_stage == 1 and dist_px:
                MIN_DIST = int(dist_px)
                calib_stage = 2
            elif calib_stage == 2 and dist_px:
                MAX_DIST = int(dist_px)
                calibrating = False
                calib_stage = 0
                print(f"[Calibrated] MIN_DIST={MIN_DIST} MAX_DIST={MAX_DIST}")

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
