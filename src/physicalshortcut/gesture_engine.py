"""Moteur de reconnaissance de gestes.

- capture la webcam en continu (thread dedie) ;
- MediaPipe Hands extrait 21 points 3D par main ;
- les points sont normalises (invariants a la position et a la taille) ;
- types de gestes :
    * "static"   : une pose enregistree (1 ou 2 mains), tenue pendant hold_ms ;
    * "sequence" : un mouvement compare a un gabarit de N images-cles ;
    * "pose"     : doigts leves / replies decrits sans enregistrement (1 ou 2 mains) ;
    * "count"    : nombre de doigts leves (la valeur est transmise a l'action) ;
    * "draw"     : dessin en l'air avec le doigt (chiffre ou forme reconnu, transmis a l'action) ;
- conditions systeme optionnelles par geste (uptime, CPU, temperature...) ;
- mode enregistrement pilote par l'interface web (creation de gabarits).

Le module ne depend de MediaPipe qu'a l'execution du moteur : les fonctions
mathematiques restent importables (et testables) sans camera ni mediapipe.
"""

from __future__ import annotations

import collections
import inspect
import logging
import math
import sys
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

from . import ai, draw, events, system_metrics
from . import hands as handlib
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
DEFAULT_COUNT_MIN = 1
DEFAULT_COUNT_MAX = 10
DEFAULT_DRAW_CONFIDENCE = 0.7
BLOCKED_EVENT_INTERVAL = 5.0  # secondes entre deux messages « geste bloque par une condition »

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


def extract_pointers(multi_hand_landmarks: Sequence[Any] | None) -> list[dict]:
    """Position du bout de l'index (coordonnees image 0..1) et pincement de chaque main,
    dans le meme ordre (gauche -> droite) que ``extract_frame_vector``."""
    if not multi_hand_landmarks:
        return []
    hands = []
    for hand in list(multi_hand_landmarks)[:MAX_HANDS]:
        pts = hand.landmark
        mean_x = sum(p.x for p in pts) / NUM_LANDMARKS
        palm = math.dist((pts[0].x, pts[0].y), (pts[9].x, pts[9].y)) or 1e-6
        pinch = math.dist((pts[4].x, pts[4].y), (pts[8].x, pts[8].y)) / palm
        hands.append((mean_x, {"x": pts[8].x, "y": pts[8].y, "pinch": pinch}))
    hands.sort(key=lambda h: h[0])
    return [h[1] for h in hands]


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


EXTERNAL_TYPES = ("sound", "voice", "fingerprint", "device", "sensor")


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
        try:  # les anciens rappels a 2 arguments restent acceptes
            params = inspect.signature(on_trigger).parameters.values()
            self._trigger_takes_context = any(
                p.kind is p.VAR_POSITIONAL for p in params
            ) or len([p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]) >= 3
        except (TypeError, ValueError):
            self._trigger_takes_context = False

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
        self._live_hands: list[dict] = []
        self._count_value: dict[str, Any] = {}
        self._blocked_at: dict[str, float] = {}

        # dessin en l'air : un suivi par geste "draw" ; derniere image brute pour l'IA
        self._trackers: dict[str, draw.Tracker] = {}
        self._last_drawing: dict[str, Any] | None = None
        self._latest_frame = None
        self._latest_vec: list[float] | None = None
        self._latest_at = 0.0

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

    def live_hands(self) -> list[dict]:
        """Doigts leves de chaque main visible (affichage en direct)."""
        with self._lock:
            if time.monotonic() - self._latest_at > LIVE_SCORE_TTL:
                return []
            return [dict(h) for h in self._live_hands]

    def draw_state(self) -> dict:
        """Trait en cours (pour l'apercu) et dernier dessin reconnu."""
        with self._lock:
            trail = []
            for tracker in self._trackers.values():
                if tracker.active:
                    trail = [[round(x, 4), round(y, 4)] for x, y in tracker.points()][-300:]
                    break
            return {"trail": trail, "last": dict(self._last_drawing) if self._last_drawing else None}

    def latest_vector(self) -> list[float] | None:
        """Derniere image analysee (vecteur de la main), si elle date de moins d'une seconde."""
        with self._lock:
            return list(self._latest_vec) if self._latest_vec and time.monotonic() - self._latest_at < 1.0 else None

    def latest_jpeg(self) -> bytes | None:
        """Derniere image de la camera (sans annotations), encodee a la demande."""
        with self._lock:
            frame = self._latest_frame
        if frame is None:
            return None
        try:
            import cv2

            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return buf.tobytes() if ok else None
        except Exception:  # noqa: BLE001
            return None

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

        counts = collections.Counter(len(handlib.split_hands(v)) for _, v in frames)
        hand_count = counts.most_common(1)[0][0] or 1
        if kind == "static":  # on garde les images ayant le nombre de mains le plus frequent
            frames = [(t, v) for t, v in frames if len(handlib.split_hands(v)) == hand_count]
        vectors = [v for _, v in frames]
        elapsed = frames[-1][0] - frames[0][0]
        if kind == "static":
            template = [sum(values) / len(values) for values in zip(*vectors, strict=True)]
            result = {"type": "static", "template": template, "hands": hand_count}
        else:
            result = {
                "type": "sequence",
                "keyframes": resample(vectors, SEQUENCE_KEYFRAMES),
                "duration": round(elapsed, 2),
                "hands": hand_count,
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
                pointers = extract_pointers(landmarks)
                with self._lock:
                    self._latest_frame = frame  # image brute (avant annotations) pour l'IA

                with self._lock:
                    watched = time.monotonic() - self._last_view < PREVIEW_IDLE_SECONDS
                if watched:
                    view = frame.copy()
                    if landmarks:
                        for hand in landmarks:
                            drawing.draw_landmarks(view, hand, connections)
                    self._draw_trail(cv2, view)
                    ok_jpeg, buf = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    if ok_jpeg:
                        with self._lock:
                            self._last_jpeg = buf.tobytes()

                self._handle_vector(vec, pointers)
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

    def _draw_trail(self, cv2, view) -> None:
        """Dessine le trait en cours (dessin en l'air) sur l'apercu."""
        import numpy as np

        height, width = view.shape[:2]
        with self._lock:
            trackers = list(self._trackers.values())
        for tracker in trackers:
            for stroke in list(tracker.strokes):
                if len(stroke) >= 2:
                    pts = [[int(x * width), int(y * height)] for x, y in stroke]
                    cv2.polylines(view, [np.array(pts, dtype="int32")], False, (255, 220, 60), 4, cv2.LINE_AA)

    def _handle_vector(self, vec: list[float] | None, pointers: list[dict] | None = None) -> None:
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
        self._process_detection(vec, now, pointers)

    # -------------------------------------------------------- reconnaissance
    def _process_detection(self, vec: list[float] | None, now: float, pointers: list[dict] | None = None) -> None:
        self._recent.append((now, vec))
        cutoff = now - SEQUENCE_MAX_SECONDS
        while self._recent and self._recent[0][0] < cutoff:
            self._recent.popleft()

        infos = handlib.analyze(vec)
        with self._lock:
            self._live_hands = infos
            self._latest_vec = vec
            self._latest_at = time.monotonic()

        for gesture in self.store.get_gestures():
            gid = gesture.get("id")
            if not gid:
                continue
            kind = gesture.get("type")
            ctx: dict | None = None

            if kind in EXTERNAL_TYPES:
                continue  # declenches par le hub des capteurs (fire_external)
            if kind == "draw":
                self._update_draw(gesture, infos, pointers, now)
                continue
            if kind == "static":
                matched, score = self._check_static(gesture, vec, now)
            elif kind == "pose":
                matched, score, ctx = self._check_pose(gesture, infos, now)
            elif kind == "count":
                matched, score, ctx = self._check_count(gesture, infos, now)
            else:
                matched, score = self._check_sequence(gesture, now)
            if score is not None:
                with self._lock:
                    self._live[gid] = {**score, "at": now}
            self._consider(gesture, matched, ctx, now)

    def _consider(self, gesture: dict, matched: bool, ctx: dict | None, now: float) -> None:
        gid = gesture["id"]
        cooldown = gesture.get("cooldown_seconds", DEFAULT_COOLDOWN_SECONDS)
        if now - self._last_triggered.get(gid, -math.inf) < cooldown:
            self._hold_since[gid] = None  # pendant le cooldown, la tenue ne compte pas
            return
        if matched:
            self._fire(gesture, ctx or {}, now)

    def fire_external(self, gesture: dict, ctx: dict | None = None) -> bool:
        """Declenchement par un capteur (son, voix, empreinte, peripherique...) : meme cooldown et
        memes conditions que les gestes de la camera."""
        gid = gesture.get("id")
        if not gid:
            return False
        now = time.monotonic()
        with self._lock:
            cooldown = gesture.get("cooldown_seconds", DEFAULT_COOLDOWN_SECONDS)
            if now - self._last_triggered.get(gid, -math.inf) < cooldown:
                return False
        return self._fire(gesture, ctx or {}, now)

    def _fire(self, gesture: dict, ctx: dict, now: float) -> bool:
        gid = gesture["id"]
        name = gesture.get("name")
        allowed, reasons = system_metrics.check(gesture.get("conditions"), gesture.get("conditions_mode", "all"))
        if not allowed:
            if now - self._blocked_at.get(gid, -math.inf) >= BLOCKED_EVENT_INTERVAL:
                self._blocked_at[gid] = now
                log.info("Geste %r reconnu mais bloque : %s", name, " ; ".join(reasons))
                events.emit("gesture_blocked", gesture_id=gid, gesture=name, reasons=reasons)
            return False

        self._last_triggered[gid] = now
        self._hold_since[gid] = None
        action = self.store.get_action(gesture.get("action_id"))
        context = {"id": gid, "name": name, "type": gesture.get("type"), **ctx}
        events.emit(
            "gesture",
            gesture_id=gid,
            gesture=name,
            type=gesture.get("type"),
            action_id=action.get("id") if action else None,
            action=action.get("name") if action else None,
            value=ctx.get("value"),
        )
        if not action:
            log.info("Geste %r reconnu mais aucune action n'est liee", name)
            return True
        log.info("Geste %r reconnu -> action %r", name, action.get("name"))
        try:
            if self._trigger_takes_context:
                self.on_trigger(gesture, action, context)
            else:
                self.on_trigger(gesture, action)
        except Exception:
            log.exception("Echec du declenchement de l'action")
        return True

    # ---- tenue d'une pose
    def _hold(self, gid: str, ok: bool, now: float, stable: Any = None) -> float:
        """Duree (ms) depuis laquelle ``ok`` est vrai sans interruption (et avec la meme ``stable``)."""
        previous = self._last_seen.get(gid)
        self._last_seen[gid] = now
        if previous is not None and now - previous > FRAME_GAP_RESET_SECONDS:
            self._hold_since[gid] = None  # trou dans le flux : la tenue repart de 0
        if stable is not None and self._count_value.get(gid) != stable:
            self._hold_since[gid] = None  # la valeur a change (ex. nombre de doigts)
        self._count_value[gid] = stable
        if not ok:
            self._hold_since[gid] = None
            return 0.0
        since = self._hold_since.get(gid)
        if since is None:
            since = self._hold_since[gid] = now
        return (now - since) * 1000

    # ---- poses enregistrees
    @staticmethod
    def _static_distance(gesture: dict, vec: list[float]) -> float | None:
        template = gesture["template"]
        template_hands = gesture.get("hands") or (1 if not any(abs(v) > 1e-9 for v in template[handlib.HAND_LEN:]) else 2)
        chunks = handlib.split_hands(vec)
        if template_hands == 2:
            return distance(vec, template) if len(chunks) == 2 else None
        if not chunks:
            return None
        padded = list(template[: handlib.HAND_LEN]) + [0.0] * handlib.HAND_LEN
        # n'importe quelle main visible peut correspondre (l'autre main est ignoree)
        return min(distance(c + [0.0] * handlib.HAND_LEN, padded) for c in chunks)

    def _check_static(self, gesture: dict, vec: list[float] | None, now: float):
        """Pose tenue sans interruption pendant ``hold_ms`` -> (reconnu, score)."""
        gid = gesture["id"]
        template = gesture.get("template")
        threshold = gesture.get("threshold", DEFAULT_STATIC_THRESHOLD)
        if vec is None or not template:
            self._hold_since[gid] = None
            return False, None
        dist = self._static_distance(gesture, vec)
        if dist is None:  # le nombre de mains ne correspond pas
            self._hold_since[gid] = None
            return False, None
        score = {"distance": round(dist, 4), "threshold": threshold}
        held_ms = self._hold(gid, dist <= threshold, now)
        score["held_ms"] = round(held_ms)
        score["hold_ms"] = hold_ms_of(gesture)
        return dist <= threshold and held_ms >= hold_ms_of(gesture), score

    # ---- poses decrites (doigts) et comptage
    def _check_pose(self, gesture: dict, infos: list[dict], now: float):
        gid = gesture["id"]
        pattern = gesture.get("fingers")
        if not pattern or not infos:
            self._hold_since[gid] = None
            return False, None, None
        if gesture.get("hands", 1) == 2:
            if len(infos) != 2:
                self._hold_since[gid] = None
                return False, None, None
            second = gesture.get("fingers_second") or pattern
            mism = handlib.pose_mismatches(infos[0]["fingers"], pattern) + handlib.pose_mismatches(infos[1]["fingers"], second)
            best = infos[0]
        else:
            ranked = sorted(infos, key=lambda h: handlib.pose_mismatches(h["fingers"], pattern))
            best = ranked[0]
            mism = handlib.pose_mismatches(best["fingers"], pattern)
        ok = mism == 0
        hold = hold_ms_of(gesture)
        held = self._hold(gid, ok, now)
        score = {"kind": "pose", "distance": float(mism), "threshold": 0.5, "held_ms": round(held), "hold_ms": hold}
        ctx = {"fingers": best["fingers"], "hands": len(infos), "count": sum(h["count"] for h in infos)}
        return ok and held >= hold, score, ctx

    def _check_count(self, gesture: dict, infos: list[dict], now: float):
        gid = gesture["id"]
        if not infos:
            self._hold_since[gid] = None
            return False, None, None
        wanted = gesture.get("hands", "any")
        valid_hands = wanted not in (1, 2) or len(infos) == wanted
        total = sum(h["count"] for h in infos)
        low = gesture.get("min_value", DEFAULT_COUNT_MIN)
        high = gesture.get("max_value", DEFAULT_COUNT_MAX)
        ok = valid_hands and low <= total <= high
        hold = hold_ms_of(gesture)
        held = self._hold(gid, ok, now, stable=total)
        score = {
            "kind": "count", "value": total, "distance": 0.0 if ok else 1.0, "threshold": 0.5,
            "held_ms": round(held), "hold_ms": hold,
        }
        ctx = {"value": total, "count": total, "hands": len(infos), "fingers": [h["fingers"] for h in infos]}
        return ok and held >= hold, score, ctx

    # ---- dessin en l'air
    @staticmethod
    def _pen(gesture: dict, infos: list[dict], pointers: list[dict] | None):
        mode = gesture.get("pen", "index")
        for info, pointer in zip(infos, pointers or [], strict=False):
            fingers = info["fingers"]
            if mode == "pinch":
                down = pointer.get("pinch", 9.0) < 0.35
            elif mode == "any":
                down = True
            else:  # "index" : seul l'index est leve (main qui pointe)
                down = fingers[1] == 1 and not any(fingers[2:])
            if down:
                return True, pointer["x"], pointer["y"]
        return False, None, None

    def _update_draw(self, gesture: dict, infos: list[dict], pointers: list[dict] | None, now: float) -> None:
        gid = gesture["id"]
        tracker = self._trackers.get(gid)
        if tracker is None:
            tracker = self._trackers[gid] = draw.Tracker(idle_ms=int(gesture.get("idle_ms", 800)))
        pen, x, y = self._pen(gesture, infos, pointers)
        finished = tracker.update(pen, x, y, now)
        with self._lock:
            self._live[gid] = {
                "kind": "draw", "pen": pen, "strokes": len(tracker.strokes), "distance": 0.0, "threshold": 1.0, "at": now,
            }
        if finished is not None:
            threading.Thread(target=self._recognize, args=(gesture, finished), name="draw-recognize", daemon=True).start()

    @staticmethod
    def _draw_labels(gesture: dict) -> list[str]:
        explicit = gesture.get("labels")
        if explicit:
            return [str(label) for label in explicit]
        charset = gesture.get("charset", "digits")
        labels = list(draw.CHARSETS.get(charset, draw.DIGITS))
        if charset == "all":
            labels += [label for label in draw.library().custom if label not in labels]
        return labels

    def _recognize(self, gesture: dict, drawing: draw.Drawing) -> None:
        """Reconnait un dessin termine (thread : l'IA peut etre lente) puis declenche l'action."""
        gid = gesture["id"]
        labels = self._draw_labels(gesture)
        mode = gesture.get("recognizer", "local")
        minimum = gesture.get("min_confidence", DEFAULT_DRAW_CONFIDENCE)
        label: str | None = None
        confidence = 0.0
        source = "local"
        matches = draw.library().recognize(drawing.strokes, labels) if mode != "ai" else []
        if matches and matches[0].confidence >= minimum:
            label, confidence = matches[0].label, matches[0].confidence
        elif mode in ("ai", "auto") and ai.is_configured():
            try:
                label = ai.classify_drawing(draw.render_png(drawing.strokes), labels)
                confidence, source = (0.9, "ai") if label else (0.0, "ai")
            except ai.AIError as exc:
                log.warning("Reconnaissance IA du dessin impossible : %s", exc)
        summary = {
            "gesture_id": gid, "gesture": gesture.get("name"), "label": label, "confidence": round(confidence, 3),
            "source": source, "candidates": [{"label": m.label, "confidence": m.confidence} for m in matches],
            "at": round(time.time(), 3),
        }
        with self._lock:
            self._last_drawing = summary
        events.emit("drawing", **{k: v for k, v in summary.items() if k != "at"})
        if label is None:
            log.info("Dessin non reconnu (%s)", ", ".join(f"{m.label} {m.confidence:.2f}" for m in matches) or "aucun modele")
            return
        log.info("Dessin reconnu : %s (%.0f %%, %s)", label, confidence * 100, source)
        ctx = {
            "value": draw.label_value(label), "label": label, "shape": "" if label.isdigit() else label,
            "confidence": round(confidence, 3), "source": source, "kind": "draw",
        }
        self._consider(gesture, True, ctx, time.monotonic())

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
