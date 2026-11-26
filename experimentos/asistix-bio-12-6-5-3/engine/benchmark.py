"""Synthetic CPU-only YuNet/SFace comparison, separate from ASISTIX."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import socket
import sys
from threading import Lock
import time

os.environ['ORT_DISABLE_TELEMETRY'] = '1'


def block_network(event, args):
    if event.startswith('socket.'):
        raise PermissionError('Network disabled for this experiment')


sys.addaudithook(block_network)
try:
    socket.socket()
except PermissionError:
    pass
else:
    raise RuntimeError('Network guard inactive')

import cv2
import numpy as np


HERE = Path(__file__).resolve().parent
SIZE = 640
STRIDES = (8, 16, 32)
OUTPUTS = [f'{prefix}_{step}' for prefix in ('cls', 'obj', 'bbox', 'kps') for step in STRIDES]
LANDMARKS = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
                      [41.5493, 92.3655], [70.7299, 92.2041]], dtype=np.float64)
DETECTOR = 'face_detection_yunet_2023mar.onnx'
ENCODER = 'face_recognition_sface_2021dec.onnx'
cv2.setNumThreads(1)


def verify_artifacts():
    manifest = json.loads((HERE / 'models/manifest.json').read_text(encoding='utf-8-sig'))
    if {entry['file'] for entry in manifest} != {DETECTOR, ENCODER}:
        raise ValueError('Unexpected model set')
    for entry in manifest:
        data = (HERE / 'models' / entry['file']).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry['sha256'] or len(data) != entry['bytes']:
            raise ValueError('Model checksum or size mismatch')


def model(engine, filename):
    path = str(HERE / 'models' / filename)
    if engine == 'ort':
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        options.log_severity_level = 3
        session = ort.InferenceSession(path, sess_options=options, providers=['CPUExecutionProvider'])
        name = session.get_inputs()[0].name
        return lambda tensor, outputs=None: session.run(outputs, {name: tensor})
    net = cv2.dnn.readNetFromONNX(path)
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    lock = Lock()

    def forward(tensor, outputs=None):
        with lock:
            net.setInput(tensor)
            return [a.copy() for a in net.forward(outputs)] if outputs else [net.forward().copy()]

    return forward


def decode(outputs):
    # YuNet layout follows the reference implementation in OpenCV face_detect.cpp.
    candidates = []
    for index, step in enumerate(STRIDES):
        scores = np.sqrt(np.clip(outputs[index].ravel(), 0, 1) *
                         np.clip(outputs[index + 3].ravel(), 0, 1))
        selected = np.flatnonzero(scores >= .65)
        if not len(selected):
            continue
        y, x = np.divmod(selected, SIZE // step)
        grid = np.stack((x, y), axis=1)
        boxes = outputs[index + 6].reshape(-1, 4)[selected]
        sizes = np.exp(boxes[:, 2:]) * step
        corner = (boxes[:, :2] + grid) * step - sizes / 2
        points = (outputs[index + 9].reshape(-1, 5, 2)[selected] + grid[:, None, :]) * step
        candidates.append(np.column_stack((corner, sizes, points.reshape(-1, 10), scores[selected])))
    if not candidates:
        return np.empty((0, 15), dtype=np.float32)
    faces = np.concatenate(candidates).astype(np.float32)
    keep = cv2.dnn.NMSBoxes(faces[:, :4].astype(int).tolist(), faces[:, 14].tolist(), .65, .30, top_k=5000)
    return faces[np.asarray(keep, dtype=int).reshape(-1)]


def align(image, face):
    points = face[4:14].reshape(5, 2).astype(np.float64)
    centered = points - points.mean(axis=0)
    target = LANDMARKS - LANDMARKS.mean(axis=0)
    u, singular, vt = np.linalg.svd(centered.T @ target)
    signs = np.array([1, np.linalg.det(u @ vt)])
    transform = (u @ np.diag(signs) @ vt) * (singular @ signs / np.square(centered).sum())
    shift = LANDMARKS.mean(axis=0) - points.mean(axis=0) @ transform
    return cv2.warpAffine(image, np.column_stack((transform.T, shift)), (112, 112))


def normalize(vector):
    vector = np.asarray(vector, dtype=np.float64).ravel()
    norm = np.linalg.norm(vector)
    if norm == 0 or not np.isfinite(norm):
        raise ValueError('Invalid embedding')
    return vector / norm


def compare(first, second):
    return float(np.clip(normalize(first) @ normalize(second), -1, 1))


def run_case(detector, encoder, image):
    start = time.perf_counter()
    faces = decode(detector(cv2.dnn.blobFromImage(image), OUTPUTS))
    detected = time.perf_counter()
    metrics = {'faces': len(faces), 'detect_ms': (detected - start) * 1e3}
    if len(faces) != 1:
        return metrics | {'result': 'no_face' if not len(faces) else 'multiple_faces'}, None
    face = faces[0]
    x, y, width, height = face[:4]
    if min(x, y, SIZE - x - width, SIZE - y - height) < 5 or min(width, height) < 80:
        return metrics | {'result': 'framing'}, None
    cropped = align(image, face)
    gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    metrics.update(brightness=brightness, sharpness=sharpness, box=face[:4].tolist(), score=float(face[-1]))
    if brightness < 40 or sharpness < 20:
        return metrics | {'result': 'dark' if brightness < 40 else 'blurred'}, None
    aligned = time.perf_counter()
    embedding = normalize(encoder(cv2.dnn.blobFromImage(cropped, swapRB=True))[0])
    end = time.perf_counter()
    return metrics | {'result': 'accepted', 'align_ms': (aligned - detected) * 1e3,
                      'embedding_ms': (end - aligned) * 1e3, 'total_ms': (end - start) * 1e3,
                      'embedding_dimensions': len(embedding)}, embedding


def memory():
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ('peak', 'working', 'peak_paged', 'paged', 'peak_nonpaged',
                                                'nonpaged', 'pagefile', 'peak_pagefile')]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    reader = ctypes.WinDLL('psapi', use_last_error=True).GetProcessMemoryInfo
    reader.argtypes = (wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD)
    values = Counters()
    values.cb = ctypes.sizeof(values)
    if not reader(kernel.GetCurrentProcess(), ctypes.byref(values), values.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return {'working_mib': values.working / 2**20, 'peak_mib': values.peak / 2**20}


def summarize(values):
    return {'p50_ms': float(np.percentile(values, 50)), 'p95_ms': float(np.percentile(values, 95))}


def experiment(engine, cases, count):
    before = memory()
    start = time.perf_counter()
    detector, encoder = model(engine, DETECTOR), model(engine, ENCODER)
    loaded = (time.perf_counter() - start) * 1e3
    initial = memory()
    outcomes = {name: run_case(detector, encoder, image) for name, image in cases.items()}
    reference = outcomes['original'][1]
    if reference is None:
        raise ValueError(f'{engine}: the synthetic reference was not accepted: {outcomes["original"][0]}')
    assert reference.size == 128
    for label in ('original', 'noise', 'second'):
        if label in outcomes:
            other = outcomes[label][1]
            assert other is not None, (engine, label, outcomes[label][0])
            outcomes[label][0]['similarity_to_original'] = compare(reference, other)
    warm = [run_case(detector, encoder, cases['original'])[0] for _ in range(5)]
    series = {}
    for workers in (1, 2, 4, 8):
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            batch = list(pool.map(lambda _: run_case(detector, encoder, cases['original']), range(count)))
        elapsed = time.perf_counter() - started
        assert all(result is not None and compare(reference, result) > .99999 for _, result in batch)
        series[str(workers)] = summarize([item['total_ms'] for item, _ in batch]) | {
            'requests_per_sec': count / elapsed, 'requests': count, 'errors': 0}
    return {
        'load_ms': loaded, 'memory_before': before, 'memory_loaded': initial, 'memory_peak': memory(),
        'warmup': warm[0], 'concurrency': series, 'cases': {name: values[0] for name, values in outcomes.items()},
    }, reference


def load_cases(first, second):
    def read(path):
        image = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f'Invalid synthetic image: {path}')
        return cv2.resize(image, (SIZE, SIZE))

    original = read(first)
    other = read(second) if second else original
    tiles = np.full_like(original, 128)
    tiles[160:480, :320] = cv2.resize(original, (320, 320))
    tiles[160:480, 320:] = cv2.resize(other, (320, 320))
    framing = cv2.warpAffine(original, np.float32([[1, 0, -235], [0, 1, 0]]), (SIZE, SIZE),
                             borderMode=cv2.BORDER_CONSTANT, borderValue=(128, 128, 128))
    cases = {
        'original': original, 'noise': cv2.convertScaleAbs(original, alpha=.92, beta=8),
        'no_face': np.full_like(original, 128), 'multiple': tiles,
        'dark': cv2.convertScaleAbs(original, alpha=.22),
        'blurred': cv2.GaussianBlur(original, (41, 41), 10),
        'framing': framing,
    }
    if second:
        cases['second'] = other
    return cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('portrait')
    parser.add_argument('--second')
    parser.add_argument('--engine', choices=('ort', 'opencv', 'both'), default='both')
    parser.add_argument('--count', type=int, default=24)
    args = parser.parse_args()
    if args.engine != 'opencv':
        import onnxruntime as ort

        ort.disable_telemetry_events()
    verify_artifacts()
    first, orthogonal = np.identity(128)[:2]
    assert compare(first, first) == 1 and compare(first, orthogonal) == 0 and compare(first, -first) == -1
    cases = load_cases(args.portrait, args.second)
    report, vectors = {}, {}
    for engine in ('ort', 'opencv') if args.engine == 'both' else (args.engine,):
        report[engine], vectors[engine] = experiment(engine, cases, args.count)
    if len(vectors) == 2:
        report['parity'] = {'embedding_cosine': compare(vectors['ort'], vectors['opencv'])}
        assert report['parity']['embedding_cosine'] > .9999
        for name in cases:
            assert report['ort']['cases'][name]['result'] == report['opencv']['cases'][name]['result'], name
    print(json.dumps({'python': sys.version.split()[0], 'opencv': cv2.__version__, 'onnxruntime': version('onnxruntime'),
                      'network': 'Python socket audit guard; ORT telemetry disabled', 'result': report}, indent=2))


if __name__ == '__main__':
    main()
