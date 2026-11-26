"""Local YuNet/SFace inference for the enrollment pilot."""
import hashlib
import os
from pathlib import Path

import cv2
import numpy as np

os.environ['ORT_DISABLE_TELEMETRY']='1'
cv2.setNumThreads(1)
MODELS = Path(__file__).resolve().parent / 'engine/models'
SIZE = 640
STRIDES = (8, 16, 32)
OUTPUTS = [f'{prefix}_{step}' for prefix in ('cls', 'obj', 'bbox', 'kps') for step in STRIDES]
LANDMARKS = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.2041], [70.7299, 92.2041]])
MODEL_HASHES = {
    'face_detection_yunet_2023mar.onnx': '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4',
    'face_recognition_sface_2021dec.onnx': '0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79',
}

from errores_captura import CaptureError


def jpeg_size(content):
    if content[:2] != b'\xff\xd8':
        raise CaptureError('INVALID')
    cursor = 2
    while cursor < len(content) and content[cursor] == 255:
        while cursor < len(content) and content[cursor] == 255:
            cursor += 1
        if cursor + 3 > len(content):
            break
        marker = content[cursor]
        if marker in (0, 216, 217, 218):
            break
        size = int.from_bytes(content[cursor+1:cursor+3], 'big')
        if size < 2 or cursor + size >= len(content):
            break
        if marker in (192, 194) and size >= 8:
            rows = int.from_bytes(content[cursor+4:cursor+6], 'big')
            columns = int.from_bytes(content[cursor+6:cursor+8], 'big')
            if 240 <= min(rows, columns) and max(rows, columns) <= 1280 and rows * columns <= 1_310_720:
                return rows, columns
            break
        cursor += size + 1
    raise CaptureError('INVALID')


def load_model(filename, checksum):
    import onnxruntime as ort

    weights = (MODELS / filename).read_bytes()
    if hashlib.sha256(weights).hexdigest() != checksum:
        raise RuntimeError('Model checksum mismatch')
    ort.disable_telemetry_events()
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    options.log_severity_level = 3
    session = ort.InferenceSession(weights, sess_options=options, providers=['CPUExecutionProvider'])
    name = session.get_inputs()[0].name
    return lambda tensor, outputs=None: session.run(outputs, {name: tensor})

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

class FacialEngine:
    def __init__(self):
        self.detect, self.encode = [load_model(name, digest) for name, digest in MODEL_HASHES.items()]

    def capture(self, content):
        rows, columns = jpeg_size(content)
        image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
        if image is None or image.shape[:2] != (rows, columns):
            raise CaptureError('INVALID')
        scale = SIZE / max(rows, columns)
        width, height = round(columns * scale), round(rows * scale)
        left, top = (SIZE - width)//2, (SIZE - height)//2
        canvas = np.full((SIZE, SIZE, 3), 128, dtype=np.uint8)
        canvas[top:top+height, left:left+width] = cv2.resize(image, (width,height))
        faces = decode(self.detect(cv2.dnn.blobFromImage(canvas), OUTPUTS))
        if not len(faces):
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            raise CaptureError('DARK' if float(gray.mean()) < 40 else 'NO_FACE')
        if len(faces) != 1:
            raise CaptureError('MULTIPLE')
        face = faces[0]
        x, y, w, h = face[:4]
        if min(x-left, y-top, left+width-x-w, top+height-y-h) < 5:
            raise CaptureError('FRAMING')
        if w < width*.16 or h < height*.20 or w > width*.76 or h > height*.82:
            raise CaptureError('DISTANCE')
        if abs(x+w/2-SIZE/2) > width*.23 or abs(y+h/2-SIZE/2) > height*.24:
            raise CaptureError('FRAMING')
        aligned = align(canvas, face)
        gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
        if float(gray.mean()) < 40:
            raise CaptureError('DARK')
        if float(cv2.Laplacian(gray, cv2.CV_64F).var()) < 20:
            raise CaptureError('BLUR')
        result = normalize(self.encode(cv2.dnn.blobFromImage(aligned, swapRB=True))[0])
        if result.shape != (128,) or not np.all(np.isfinite(result)):
            raise RuntimeError('Invalid template dimensions')
        return result.astype('>f4').tobytes()
