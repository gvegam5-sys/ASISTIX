"""Server-side contract for a bounded active challenge and passive PAD."""
from dataclasses import dataclass
from hashlib import sha256
from hmac import digest
from math import isfinite
from secrets import randbelow, token_hex
from secrets import token_bytes
from threading import Lock
from time import monotonic


MEDIA_TYPE = 'application/vnd.asistix.liveness'
FRAME_LIMIT = 60 * 1024
FRAMES = 6
MAX_BODY = FRAMES * (4 + FRAME_LIMIT)
CAPTURE_WINDOW_SECONDS = 25
PROCESS_WINDOW_SECONDS = 9
POSES = ('center', 'left', 'right')


@dataclass(frozen=True)
class Plan:
    challenge: str
    student_id: int
    session_id: int
    nonce: str
    steps: tuple[str, ...]


@dataclass(frozen=True)
class VerifiedProbe:
    plan: Plan
    embedding: tuple[float, ...]
    source: str = 'simulated'


@dataclass(frozen=True)
class Observation:
    yaw: float
    live_probability: float
    embedding: bytes


class LivenessRejected(ValueError):
    pass


class InsufficientCapture(ValueError):
    pass


class ReplayCache:
    """Short-lived, keyed and in-memory only. Detects byte-identical batches."""
    def __init__(self):
        self.key=token_bytes(32)
        self.entries={}
        self.lock=Lock()

    def claim(self, account, body):
        stamp=monotonic()
        tag=(account,digest(self.key,body,'sha256'))
        with self.lock:
            self.entries={item:expires for item,expires in self.entries.items() if expires>stamp}
            if tag in self.entries or len(self.entries)>=64:
                raise LivenessRejected()
            self.entries[tag]=stamp+120


def generate_plan(challenge, student_id, session_id):
    sides = ('left', 'right') if randbelow(2) else ('right', 'left')
    return Plan(challenge, student_id, session_id, token_hex(16), ('center', *sides))


def unpack_frames(body):
    if not 0 < len(body) <= MAX_BODY:
        raise InsufficientCapture()
    frames = []
    cursor = 0
    for _ in range(FRAMES):
        size = int.from_bytes(body[cursor:cursor+4], 'big')
        cursor += 4
        if not 4 <= size <= FRAME_LIMIT or cursor + size > len(body):
            raise InsufficientCapture()
        jpeg = body[cursor:cursor+size]
        if jpeg[:2] != b'\xff\xd8' or jpeg[-2:] != b'\xff\xd9':
            raise InsufficientCapture()
        frames.append(jpeg)
        cursor += size
    if cursor != len(body) or len({sha256(frame).digest() for frame in frames}) != FRAMES:
        raise InsufficientCapture()
    return tuple(frames)


def evaluate(plan, body, observe, *, passive_threshold, continuity_threshold):
    from .pilot_comparison import matches, vector

    if not (0 < passive_threshold < 1 and 0 < continuity_threshold < 1):
        raise ValueError('Invalid experimental PAD policy')
    frames = unpack_frames(body)
    observations = tuple(observe(frame) for frame in frames)
    if any(not isfinite(item.yaw) or not 0 <= item.live_probability <= 1 for item in observations):
        raise InsufficientCapture()
    if any(item.live_probability < passive_threshold for item in observations):
        raise LivenessRejected()
    for pose, pair in zip(plan.steps, zip(observations[::2], observations[1::2]), strict=True):
        for item in pair:
            correct = abs(item.yaw) <= .10 if pose == 'center' else (item.yaw >= .18 if pose == 'left' else item.yaw <= -.18)
            if not correct:
                raise LivenessRejected()
    reference = observations[0].embedding
    if not all(matches(reference, item.embedding, continuity_threshold) for item in observations[1:]):
        raise LivenessRejected()
    return VerifiedProbe(plan, vector(reference))
