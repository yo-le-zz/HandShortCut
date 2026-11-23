"""Moteur de reconnaissance de gestes.

- capture la webcam en continu (thread dedie) ;
- MediaPipe Hands extrait 21 points 3D par main ;
- les points sont normalises (invariants a la position et a la taille) ;
- deux types de gestes :
    * "static"   : une pose tenue pendant une duree donnee (hold_ms) ;
    * "sequence" : un mouvement compare a un gabarit de N images-cles ;
- mode enregistrement pilote par l'interface web (creation de gabarits).

Le module ne depend de MediaPipe qu'a l'execution du moteur : les fonctions
mathematiques restent importables (et testables) sans camera ni mediapipe.
"""

from __future__ import annotations

import collections
import logging
import math
import sys
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

from .schema import FRAME_VEC_LEN, SEQUENCE_KEYFRAMES, hold_ms_of

log = logging.getLogger(__name__)

NUM_LANDMARKS = 21
MAX_HANDS = 2

SEQUENCE_MIN_SECONDS = 0.5
SEQUENCE_MAX_SECONDS = 6.0
SEQUENCE_DEFAULT_SECONDS = 3.0
DEFAULT_STATIC_THRESHOLD = 0.16
DEFAULT_SEQUENCE_THRESHOLD = 0.22
DEFAULT_COOLDOWN_SECONDS = 10

RECORD_MAX_SECONDS = 20.0
MIN_STATIC_FRAMES = 1
MIN_SEQUENCE_FRAMES = 3

FPS_SMOOTHING = 0.1  # poids de la derniere mesure dans la moyenne glissante des images/s
FRAME_GAP_RESET_SECONDS = 0.5  # trou plus long entre deux images : la tenue d'une pose repart de 0
LIVE_SCORE_TTL = 1.5  # secondes pendant lesquelles un score de detection reste affiche

CAMERA_RETRY_SECONDS = 3.0
CAMERA_MAX_READ_FAILURES = 60
PREVIEW_IDLE_SECONDS = 2.0  # sans spectateur, on n'encode/dessine pas le flux


# --------------------------------------------------------------------------
# Mathematiques (pures)
# --------------------------------------------------------------------------


def normalize_hand(landmarks: Sequence[Any]) -> list[float]:
    """21 points (x, y, z) -> 63 floats centres sur le poignet, a l'echelle de la main."""
    wrist = landmarks[0]
    ref = landmarks[9]  # base du majeur
    scale = math.dist((wrist.x, wrist.y, wrist.z), (ref.x, ref.y, ref.z)) or 1e-6
    vec: list[float] = []
    for lm in landmarks:
        vec.extend(((lm.x - wrist.x) / scale, (lm.y - wrist.y) / scale, (lm.z - wrist.z) / scale))
    return vec


def extract_frame_vector(multi_hand_landmarks: Sequence[Any] | None) -> list[float] | None:
    """Resultat MediaPipe -> vecteur fixe de FRAME_VEC_LEN (mains triees de
    gauche a droite, completees par des zeros s'il y en a moins de 2)."""
    if not multi_hand_landmarks:
        return None
    hands = []
    for hand in list(multi_hand_landmarks)[:MAX_HANDS]:
        points = hand.landmark
        mean_x = sum(p.x for p in points) / NUM_LANDMARKS
        hands.append((mean_x, normalize_hand(points)))
    hands.sort(key=lambda h: h[0])
    vec: list[float] = []
    for _, hand_vec in hands:
        vec.extend(hand_vec)
    vec.extend([0.0] * (FRAME_VEC_LEN - len(vec)))
    return vec[:FRAME_VEC_LEN]


def distance(v1: Sequence[float], v2: Sequence[float]) -> float:
    """Distance euclidienne moyenne (RMS) entre deux vecteurs."""
    n = min(len(v1), len(v2))
    if n == 0:
        return float("inf")
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1[:n], v2[:n], strict=False)) / n)


def resample(frames: Sequence[Any], count: int) -> list[Any]:
    """Reechantillonne une suite temporelle a exactement `count` elements."""
    if not frames:
        return []
    if len(frames) == count:
        return list(frames)
    last = len(frames) - 1
    return [frames[round(i * last / max(count - 1, 1))] for i in range(count)]


def sequence_window(gesture: dict) -> float:
    """Fenetre d'observation (s) pour un geste sequence : sa duree enregistree + marge."""
    duration = gesture.get("duration")
    if isinstance(duration, (int, float)) and duration > 0:
        return min(max(duration * 1.15, SEQUENCE_MIN_SECONDS), SEQUENCE_MAX_SECONDS)
    return SEQUENCE_DEFAULT_SECONDS


# --------------------------------------------------------------------------
# Moteur
# --------------------------------------------------------------------------


class GestureEngine:
    def __init__(
        self,
        config_store,
        on_trigger: Callable[[dict, dict], None],
        camera_index: int = 0,
    ):
        self.store = config_store
        self.on_trigger = on_trigger
        self.camera_index = camera_index

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

        self._camera_state = "stopped"  # stopped | starting | ok | error
        self._camera_error: str | None = None

        self._last_jpeg: bytes | None = None
        self._last_view = 0.0

        # enregistrement (pilote par l'UI)
        self._record_kind: str | None = None  # None = pas d'enregistrement en cours
        self._recording = False  # False apres expiration, `_record_kind` reste jusqu'au stop
        self._record_started = 0.0
        self._record_buffer: collections.deque = collections.deque(maxlen=900)

        # detection
        self._recent: collections.deque = collections.deque()  # (t, vecteur | None)
        self._hold_since: dict[str, float | None] = {}  # debut de la tenue en cours (s)
        self._last_triggered: dict[str, float] = {}
        self._last_seen: dict[str, float] = {}
        self._last_frame_at: float | None = None

        # mesures affichees dans l'interface
        self._fps = 0.0
        self._live: dict[str, dict] = {}

    # ------------------------------------------------------------------ API
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._set_camera("starting")
        self._thread = threading.Thread(target=self._run, name="gesture-engine", daemon=True)
        self._thread.start()
        log.info("Moteur de gestes demarre (camera %s)", self.camera_index)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._set_camera("stopped")
        log.info("Moteur de gestes arrete")

    def status(self) -> dict:
        with self._lock:
            return {
                "camera": self._camera_state,
                "error": self._camera_error,
                "recording": self._recording,
                "fps": round(self._fps, 1),
            }

    def live_scores(self) -> dict[str, dict]:
        """Distance courante de chaque geste a sa cible (pour regler le seuil dans l'interface)."""
        now = time.monotonic()
        with self._lock:
            return {
                gid: dict(score)
                for gid, score in self._live.items()
                if now - score["at"] < LIVE_SCORE_TTL
            }

    def get_jpeg_frame(self) -> bytes | None:
        """Derniere image annotee. Appeler cette methode signale qu'un
        spectateur regarde : le moteur ne produit le flux que dans ce cas."""
        with self._lock:
            self._last_view = time.monotonic()
            return self._last_jpeg

    # ------------------------------------------------------- enregistrement
    def start_recording(self, kind: str) -> None:
        if kind not in ("static", "sequence"):
            raise ValueError(f"Type d'enregistrement inconnu : {kind!r}")
        with self._lock:
            self._record_kind = kind
            self._recording = True
            self._record_started = time.monotonic()
            self._record_buffer.clear()
        log.info("Enregistrement demarre (%s)", kind)

    def cancel_recording(self) -> None:
        with self._lock:
            self._record_kind = None
            self._recording = False
            self._record_buffer.clear()

    def stop_recording(self) -> dict:
        """Termine l'enregistrement et renvoie le gabarit (ou {'error': ...})."""
        with self._lock:
            kind = self._record_kind
            buffer = list(self._record_buffer)
            self._record_kind = None
            self._recording = False
            self._record_buffer.clear()

        if kind is None:
            return {"error": "Aucun enregistrement en cours."}

        frames = [(t, v) for t, v in buffer if v is not None]
        minimum = MIN_STATIC_FRAMES if kind == "static" else MIN_SEQUENCE_FRAMES
        if len(frames) < minimum:
            return {"error": "Pas assez d'images avec une main detectee. Reessaie."}

        vectors = [v for _, v in frames]
        elapsed = frames[-1][0] - frames[0][0]
        if kind == "static":
            template = [sum(values) / len(values) for values in zip(*vectors, strict=True)]
            result = {"type": "static", "template": template}
        else:
            result = {
                "type": "sequence",
                "keyframes": resample(vectors, SEQUENCE_KEYFRAMES),
                "duration": round(elapsed, 2),
            }
        # mesures pour l'affichage (images captees, duree reelle, cadence)
        result["frames"] = len(frames)
        result["elapsed_ms"] = round(elapsed * 1000)
        result["fps"] = round(len(frames) / elapsed, 1) if elapsed > 0 else None
        log.info("Enregistrement termine (%s, %d images, %.2f s)", kind, len(frames), elapsed)
        return result

    # ------------------------------------------------------------- boucle
    def _set_camera(self, state: str, error: str | None = None) -> None:
        with self._lock:
            self._camera_state = state
            self._camera_error = error

    def _open_camera(self):
        import cv2

        # DirectShow (Windows) et V4L2 (Linux) s'ouvrent plus vite et plus surement que le
        # choix automatique ; on retombe sur le defaut si le backend echoue.
        backends = []
        if sys.platform == "win32":
            backends.append(cv2.CAP_DSHOW)
        elif sys.platform.startswith("linux"):
            backends.append(cv2.CAP_V4L2)
        backends.append(cv2.CAP_ANY)
        for backend in backends:
            cap = cv2.VideoCapture(self.camera_index, backend)
            if cap.isOpened():
                # 640x480 suffit a MediaPipe et reduit la charge CPU ; ignore si non supporte.
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                return cap
            cap.release()
        return None

    def _run(self) -> None:
        try:
            import cv2
            import mediapipe as mp
        except ImportError as exc:
            log.error("Dependance manquante : %s", exc)
            self._set_camera("error", f"Dependance manquante : {exc}")
            return

        hands = mp.solutions.hands.Hands(
            model_complexity=0,
            min_detection_confidence=0.6,
            min_tracking_confidence=0.5,
            max_num_hands=MAX_HANDS,
        )
        drawing = mp.solutions.drawing_utils
        connections = mp.solutions.hands.HAND_CONNECTIONS

        cap = None
        failures = 0
        try:
            while not self._stop.is_set():
                if cap is None:
                    cap = self._open_camera()
                    if cap is None:
                        msg = f"Impossible d'ouvrir la camera {self.camera_index}."
                        if self.status()["error"] != msg:
                            log.warning(msg)
                        self._set_camera("error", msg)
                        self._stop.wait(CAMERA_RETRY_SECONDS)
                        continue
                    failures = 0
                    self._set_camera("ok")
                    log.info("Camera %s ouverte", self.camera_index)

                ok, frame = cap.read()
                if not ok:
                    failures += 1
                    if failures >= CAMERA_MAX_READ_FAILURES:
                        log.warning("Camera perdue, nouvelle tentative")
                        cap.release()
                        cap = None
                        self._set_camera("error", "Camera deconnectee.")
                        self._stop.wait(CAMERA_RETRY_SECONDS)
                    else:
                        self._stop.wait(0.05)
                    continue
                failures = 0

                frame = cv2.flip(frame, 1)  # effet miroir : plus naturel pour l'utilisateur
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                results = hands.process(rgb)
                landmarks = results.multi_hand_landmarks
                vec = extract_frame_vector(landmarks)

                with self._lock:
                    watched = time.monotonic() - self._last_view < PREVIEW_IDLE_SECONDS
                if watched:
                    if landmarks:
                        for hand in landmarks:
                            drawing.draw_landmarks(frame, hand, connections)
                    ok_jpeg, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    if ok_jpeg:
                        with self._lock:
                            self._last_jpeg = buf.tobytes()

                self._handle_vector(vec)
                self._stop.wait(0.005)
        except Exception:
            log.exception("Erreur fatale dans le moteur de gestes")
            self._set_camera("error", "Erreur interne du moteur (voir le journal).")
        finally:
            if cap is not None:
                cap.release()
            hands.close()

    def _track_fps(self, now: float) -> None:
        last = self._last_frame_at
        self._last_frame_at = now
        if last is None or now <= last:
            return
        dt = now - last
        if dt > FRAME_GAP_RESET_SECONDS:  # camera relancee, pas une cadence
            return
        instant = 1.0 / dt
        with self._lock:
            self._fps = instant if self._fps == 0 else self._fps + FPS_SMOOTHING * (instant - self._fps)

    def _handle_vector(self, vec: list[float] | None) -> None:
        now = time.monotonic()
        self._track_fps(now)
        with self._lock:
            if self._record_kind is not None:
                if self._recording and now - self._record_started > RECORD_MAX_SECONDS:
                    self._recording = False  # expire : on garde le tampon jusqu'au stop
                    log.warning("Enregistrement interrompu (duree maximale atteinte)")
                if self._recording:
                    self._record_buffer.append((now, vec))
                return  # detection suspendue tant que l'enregistrement n'est pas clos
        self._process_detection(vec, now)

    # -------------------------------------------------------- reconnaissance
    def _process_detection(self, vec: list[float] | None, now: float) -> None:
        self._recent.append((now, vec))
        cutoff = now - SEQUENCE_MAX_SECONDS
        while self._recent and self._recent[0][0] < cutoff:
            self._recent.popleft()

        for gesture in self.store.get_gestures():
            gid = gesture.get("id")
            if not gid:
                continue

            if gesture.get("type") == "static":
                matched, score = self._check_static(gesture, vec, now)
            else:
                matched, score = self._check_sequence(gesture, now)
            if score is not None:
                with self._lock:
                    self._live[gid] = {**score, "at": now}

            cooldown = gesture.get("cooldown_seconds", DEFAULT_COOLDOWN_SECONDS)
            if now - self._last_triggered.get(gid, -math.inf) < cooldown:
                self._hold_since[gid] = None  # pendant le cooldown, la tenue ne compte pas
                continue
            if not matched:
                continue

            self._last_triggered[gid] = now
            self._hold_since[gid] = None
            action = self.store.get_action(gesture.get("action_id"))
            if action:
                log.info("Geste %r reconnu -> action %r", gesture.get("name"), action.get("name"))
                try:
                    self.on_trigger(gesture, action)
                except Exception:
                    log.exception("Echec du declenchement de l'action")
            else:
                log.info("Geste %r reconnu mais aucune action n'est liee", gesture.get("name"))

    def _check_static(self, gesture: dict, vec: list[float] | None, now: float):
        """Pose tenue sans interruption pendant ``hold_ms`` -> (reconnu, score)."""
        gid = gesture["id"]
        template = gesture.get("template")
        threshold = gesture.get("threshold", DEFAULT_STATIC_THRESHOLD)
        if vec is None or not template:
            self._hold_since[gid] = None
            return False, None
        dist = distance(vec, template)
        score = {"distance": round(dist, 4), "threshold": threshold}
        previous = self._last_seen.get(gid)
        self._last_seen[gid] = now
        if previous is not None and now - previous > FRAME_GAP_RESET_SECONDS:
            self._hold_since[gid] = None  # trou dans le flux : la tenue repart de 0

        if dist > threshold:
            self._hold_since[gid] = None
            score["held_ms"] = 0
            return False, score
        since = self._hold_since.get(gid)
        if since is None:
            since = self._hold_since[gid] = now
        held_ms = (now - since) * 1000
        score["held_ms"] = round(held_ms)
        score["hold_ms"] = hold_ms_of(gesture)
        return held_ms >= hold_ms_of(gesture), score

    def _check_sequence(self, gesture: dict, now: float):
        keyframes = gesture.get("keyframes")
        if not keyframes:
            return False, None
        threshold = gesture.get("threshold", DEFAULT_SEQUENCE_THRESHOLD)
        horizon = now - sequence_window(gesture)
        frames = [v for t, v in self._recent if t >= horizon and v is not None]
        if len(frames) < MIN_SEQUENCE_FRAMES:
            return False, None
        sample = resample(frames, len(keyframes))
        dists = [distance(a, b) for a, b in zip(sample, keyframes, strict=True)]
        mean = sum(dists) / len(dists)
        return mean <= threshold, {"distance": round(mean, 4), "threshold": threshold}
