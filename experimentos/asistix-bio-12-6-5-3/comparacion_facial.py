"""In-memory decoding and 1:1 cosine comparison for existing SFace templates."""
from math import fsum, isfinite, sqrt
import struct

DEFAULT_THRESHOLD = 0.363
FORMAT = struct.Struct('>128f')


def vector(value):
    if not isinstance(value, bytes) or len(value) != FORMAT.size:
        raise ValueError('Invalid SFace representation size')
    values = FORMAT.unpack(value)
    if not all(map(isfinite, values)) or not any(values):
        raise ValueError('Invalid SFace representation')
    return values


def matches(reference, probe, threshold):
    first, second = vector(reference), vector(probe)
    dot = fsum(a*b for a,b in zip(first,second))
    norm = sqrt(fsum(a*a for a in first)*fsum(b*b for b in second))
    return max(-1.0,min(1.0,dot/norm)) >= threshold
