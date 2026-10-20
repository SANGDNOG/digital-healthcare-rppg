import cv2
import numpy as np
import pytest
from rppg.video import extract

def test_no_face_and_manual_video(tmp_path):
    path = str(tmp_path / 'black.avi')
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'MJPG'), 10, (64, 64))
    for _ in range(30): writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    writer.release()
    rows, metadata = extract(video=path)
    assert rows and not any(r['roi_valid'] for r in rows)
    assert metadata['roi_mode'] == 'single_face_proxy'
    rows, metadata = extract(video=path, roi=(0, 0, 32, 32))
    assert all(r['roi_valid'] for r in rows)
    assert metadata['roi_mode'] == 'manual'

def test_camera_release_on_error(monkeypatch):
    class Camera:
        released = False
        def isOpened(self): return True
        def get(self, key): return 30
        def read(self): raise RuntimeError('read failed')
        def release(self): self.released = True
    camera = Camera()
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *a: camera)
    with pytest.raises(RuntimeError): extract(camera=0, duration=1)
    assert camera.released

def test_unknown_fps_release(monkeypatch):
    class BrokenFile:
        released = False
        def isOpened(self): return True
        def get(self, key): return float('nan')
        def release(self): self.released = True
    device = BrokenFile()
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *a: device)
    with pytest.raises(ValueError, match='FPS'): extract(video='fixture')
    assert device.released
