from __future__ import annotations

import gc
from pathlib import Path

import numpy as np

from .cache import file_sha256
from .config import SETTINGS
from .segments import Detection

_PREDICTOR = None


def predictor(max_num_objects: int = 64):
    global _PREDICTOR
    if _PREDICTOR is None:
        from huggingface_hub import hf_hub_download
        from sam3.model_builder import build_sam3_multiplex_video_predictor
        ckpt = hf_hub_download("facebook/sam3.1", "sam3.1_multiplex.pt")
        _PREDICTOR = build_sam3_multiplex_video_predictor(checkpoint_path=ckpt, max_num_objects=max_num_objects,
                                                          use_fa3=False, async_loading_frames=False)
    return _PREDICTOR


def _to_detection(frame: int, obj: int, prob: float, mask: np.ndarray, concept: str, dx: float, dy: float):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    x1, x2, y1, y2 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    return Detection(frame, str(obj), concept, float(x1 + dx), float(y1 + dy), float(x2 + dx), float(y2 + dy),
                     mask[y1:y2, x1:x2].astype(np.uint8), float(prob))


def track_video(mp4: Path, concept: str, max_num_objects: int = 64, dx: float = 0.0, dy: float = 0.0,
                cache: bool = True) -> list[Detection]:
    key = f"{file_sha256(mp4)[:24]}_{concept}_{max_num_objects}"
    cpath = SETTINGS.cache_dir / "sam_local" / f"{key}.npz"
    if cache and cpath.exists():
        z = np.load(cpath, allow_pickle=True)
        return list(z["dets"])
    import torch
    p = predictor(max_num_objects)
    sid = p.handle_request({"type": "start_session", "resource_path": str(mp4)})["session_id"]
    p.handle_request({"type": "add_prompt", "session_id": sid, "frame_index": 0, "text": concept})
    dets: list[Detection] = []
    with torch.inference_mode():
        for res in p.handle_stream_request({"type": "propagate_in_video", "session_id": sid,
                                            "propagation_direction": "forward"}):
            out = res["outputs"]
            masks = out["out_binary_masks"]
            masks = masks.cpu().numpy() if hasattr(masks, "cpu") else np.asarray(masks)
            for obj, prob, m in zip(out["out_obj_ids"], out["out_probs"], masks):
                d = _to_detection(int(res["frame_index"]), int(obj), float(prob), m, concept, dx, dy)
                if d is not None:
                    dets.append(d)
    p.handle_request({"type": "close_session", "session_id": sid})
    gc.collect()
    torch.cuda.empty_cache()
    if cache:
        cpath.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cpath, dets=np.array(dets, dtype=object))
    return dets
