"""Text recognition (offline, RapidOCR). Loaded on first use."""
import threading
from dataclasses import dataclass


@dataclass
class Word:
    text: str
    x: float
    y: float
    w: float
    h: float
    score: float = 1.0

    @property
    def center(self):
        return (self.x + self.w / 2, self.y + self.h / 2)


class Ocr:
    def __init__(self, threads: int = 2):
        self._engine = None
        self._threads = threads
        self._lock = threading.Lock()

    def _load(self):
        if self._engine is None:
            from rapidocr import RapidOCR

            # Few threads so the emulator stays smooth on slower PCs
            self._engine = RapidOCR(params={
                "Global.log_level": "error",
                "Det.limit_side_len": 736,
                "Det.limit_type": "max",
                "EngineConfig.onnxruntime.intra_op_num_threads": self._threads,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            })
        return self._engine

    def read(self, image) -> list:
        """All texts of the picture with their position (pixels of the given picture)."""
        if image is None or image.size == 0:
            return []
        with self._lock:
            # Always pass every switch: RapidOCR remembers the last value
            result = self._load()(image, use_det=True, use_cls=False, use_rec=True)
        boxes = getattr(result, "boxes", None)
        texts = getattr(result, "txts", None)
        if boxes is None or not texts:
            return []
        words = []
        for box, text, score in zip(boxes, texts, result.scores):
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            words.append(Word(text, min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys), float(score)))
        return words
