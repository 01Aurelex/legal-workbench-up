# -*- coding: utf-8 -*-
"""本地多模态能力适配：OCR、语音转文字、图片处理、文档转换。
全部为本地推理，不上传任何外部服务；引擎按需安装，未安装时返回明确状态而非报错。
引擎探测顺序（OCR）：内置 resources/tesseract → RapidOCR(onnx,模型随包) → pytesseract → PaddleOCR。
语音：resources/models 下的本地 faster-whisper 模型目录优先，避免运行时联网。"""
from __future__ import annotations
import io
import os
import shutil
from pathlib import Path

from . import db
from .config import RESOURCES_DIR

_WHISPER_MODEL = None  # 进程内复用，避免每次转写重新加载模型


def _bundled_tesseract() -> str | None:
    """定位 Tesseract：先看随包内置目录，再退回系统 PATH。

    可执行文件名按平台区分——Windows 是 tesseract.exe，macOS / Linux 无扩展名
    （macOS 上多为 `brew install tesseract tesseract-lang`，落在 /opt/homebrew/bin）。
    """
    names = ("tesseract.exe", "tesseract") if os.name == "nt" else ("tesseract",)
    for name in names:
        for cand in (RESOURCES_DIR / "tesseract" / name,
                     RESOURCES_DIR / "tesseract" / "bin" / name):
            if cand.exists():
                return str(cand)
    return shutil.which("tesseract")


def _whisper_model_path(prefer: str = "small") -> str:
    """优先返回 resources/models 下已下载好的本地模型目录，否则回退模型名（由引擎自行下载）。"""
    root = RESOURCES_DIR / "models"
    for name in (prefer, "small", "base"):
        p = root / f"whisper-{name}"
        if (p / "model.bin").exists():
            return str(p)
    return prefer


def capabilities() -> dict:
    caps = {"ocr": {"available": False, "engine": "", "note": ""},
            "stt": {"available": False, "engine": "", "note": ""},
            "image": {"available": False, "engine": "Pillow", "note": ""},
            "docx": {"available": False, "engine": "python-docx", "note": ""}}
    # ---- OCR ----
    bt = _bundled_tesseract()
    if bt:
        caps["ocr"] = {"available": True, "engine": "Tesseract(chi_sim)",
                       "note": f"使用本地 Tesseract 引擎：{bt}"}
    else:
        try:
            from rapidocr_onnxruntime import RapidOCR  # noqa
            caps["ocr"] = {"available": True, "engine": "RapidOCR(ONNX·内置中文模型)",
                           "note": "免安装本地中文OCR，识别模型随引擎内置，离线可用"}
        except Exception:
            try:
                import pytesseract  # noqa
                import PIL  # noqa
                caps["ocr"] = {"available": True, "engine": "Tesseract+pytesseract",
                               "note": "需本机安装 Tesseract 并勾选 chi_sim 中文语言包"}
            except Exception:
                try:
                    import paddleocr  # noqa
                    caps["ocr"] = {"available": True, "engine": "PaddleOCR", "note": "本地中文OCR"}
                except Exception:
                    caps["ocr"]["note"] = ("未安装本地OCR引擎。测试版已内置 RapidOCR；"
                                           "也可运行 tools/prepare_engines.ps1（Windows）或 "
                                           "tools/prepare_engines.sh（macOS）准备内置引擎")
    # ---- 语音转写 ----
    local = _whisper_model_path()
    try:
        import faster_whisper  # noqa
        local_note = "本地模型目录" if Path(local).is_absolute() else "模型将在首次使用时下载（建议先运行准备脚本）"
        caps["stt"] = {"available": True, "engine": "faster-whisper",
                       "note": f"本地语音转写；模型：{local}（{local_note}）"}
    except Exception:
        caps["stt"]["note"] = ("未安装本地语音引擎（运行 tools/prepare_engines.ps1 / "
                               "tools/prepare_engines.sh，或 pip install faster-whisper）")
    # ---- 图片 / docx ----
    try:
        import PIL  # noqa
        caps["image"] = {"available": True, "engine": "Pillow", "note": "旋转/灰度/增强锐化/二值化/格式转换"}
    except Exception:
        caps["image"]["note"] = "pip install pillow"
    try:
        import docx  # noqa
        caps["docx"] = {"available": True, "engine": "python-docx", "note": "Word 文书生成"}
    except Exception:
        caps["docx"]["note"] = "pip install python-docx"
    return caps


def _ocr_rapid(file_bytes: bytes) -> str:
    from rapidocr_onnxruntime import RapidOCR
    import numpy as np
    from PIL import Image
    engine = RapidOCR()
    arr = np.array(Image.open(io.BytesIO(file_bytes)).convert("RGB"))
    result, _ = engine(arr)
    if not result:
        return ""
    return "\n".join(line[1] for line in result)


def ocr_image(file_bytes: bytes, lang: str = "chi_sim+eng") -> dict:
    # 1) 内置 Tesseract
    bt = _bundled_tesseract()
    if bt:
        try:
            import pytesseract
            from PIL import Image
            pytesseract.pytesseract.tesseract_cmd = bt
            tessdata = str(Path(bt).parent / "tessdata")
            img = Image.open(io.BytesIO(file_bytes))
            text = pytesseract.image_to_string(img, lang=lang, config=f'--tessdata-dir "{tessdata}"')
            return {"ok": True, "engine": "bundled-tesseract", "text": text}
        except Exception as e:
            pass  # 落到下一引擎
    # 2) RapidOCR（免安装、中文模型内置）
    try:
        text = _ocr_rapid(file_bytes)
        return {"ok": True, "engine": "rapidocr-onnx", "text": text}
    except ImportError:
        pass
    except Exception as e:
        return {"ok": False, "error": f"RapidOCR 识别失败：{e}"}
    # 3) 系统 Tesseract
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(img, lang=lang)
        return {"ok": True, "engine": "tesseract", "text": text}
    except ImportError:
        pass
    except Exception as e:
        return {"ok": False, "error": f"OCR失败：{e}"}
    # 4) PaddleOCR
    try:
        from paddleocr import PaddleOCR
        import numpy as np
        from PIL import Image
        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        arr = np.array(Image.open(io.BytesIO(file_bytes)))
        result = ocr.ocr(arr, cls=True)
        lines = []
        for page in result or []:
            for item in page or []:
                lines.append(item[1][0])
        return {"ok": True, "engine": "paddleocr", "text": "\n".join(lines)}
    except Exception as e:
        return {"ok": False, "error": f"本地OCR不可用：{e}"}


def transcribe_audio(file_bytes: bytes, suffix: str = ".wav",
                     model_size: str = "small") -> dict:
    global _WHISPER_MODEL
    try:
        from faster_whisper import WhisperModel
        import tempfile, os
        model_ref = _whisper_model_path(model_size)
        if _WHISPER_MODEL is None or getattr(_WHISPER_MODEL, "_lw_ref", "") != model_ref:
            _WHISPER_MODEL = WhisperModel(model_ref, device="cpu", compute_type="int8")
            _WHISPER_MODEL._lw_ref = model_ref
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
            tf.write(file_bytes)
            tmp = tf.name
        try:
            segments, info = _WHISPER_MODEL.transcribe(tmp, language="zh")
            text = "".join(s.text for s in segments)
            return {"ok": True, "engine": "faster-whisper", "model": model_ref,
                    "lang": getattr(info, "language", "zh"), "text": text}
        finally:
            os.unlink(tmp)
    except Exception as e:
        return {"ok": False, "error": f"本地语音转写不可用：{e}"}


def transcribe_segments(file_bytes: bytes, suffix: str = ".webm",
                        model_size: str = "small") -> dict:
    """带时间戳的分段转写（供接案笔录做角色区分）。"""
    global _WHISPER_MODEL
    tmp = None
    try:
        from faster_whisper import WhisperModel
        import tempfile, os
        model_ref = _whisper_model_path(model_size)
        if _WHISPER_MODEL is None or getattr(_WHISPER_MODEL, "_lw_ref", "") != model_ref:
            _WHISPER_MODEL = WhisperModel(model_ref, device="cpu", compute_type="int8")
            _WHISPER_MODEL._lw_ref = model_ref
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tf:
            tf.write(file_bytes)
            tmp = tf.name
        seg_iter, info = _WHISPER_MODEL.transcribe(
            tmp, language="zh", beam_size=5, vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=600))
        segs = []
        for s in seg_iter:
            text = (s.text or "").strip()
            if text:
                segs.append({"start": round(float(s.start or 0), 2),
                             "end": round(float(s.end or 0), 2),
                             "text": text})
        return {"ok": True, "engine": "faster-whisper", "model": model_ref,
                "duration": round(float(getattr(info, "duration", 0) or 0), 2),
                "segments": segs}
    except Exception as e:
        return {"ok": False, "error": f"本地语音转写不可用：{e}", "segments": []}
    finally:
        import os as _os
        if tmp and _os.path.exists(tmp):
            try:
                _os.unlink(tmp)
            except OSError:
                pass


def process_image(file_bytes: bytes, action: str, value: float = 0.0) -> dict:
    try:
        from PIL import Image, ImageEnhance, ImageOps
        img = Image.open(io.BytesIO(file_bytes))
        if action == "rotate":
            img = img.rotate(int(value) if value else 90, expand=True)
        elif action == "gray":
            img = ImageOps.grayscale(img).convert("RGB")
        elif action == "contrast":
            img = ImageEnhance.Contrast(img).enhance(value or 1.5)
        elif action == "sharpness":
            img = ImageEnhance.Sharpness(img).enhance(value or 2.0)
        elif action == "binarize":
            img = ImageOps.grayscale(img).point(lambda x: 255 if x > (value or 140) else 0).convert("RGB")
        out = io.BytesIO()
        img.save(out, format="PNG")
        from .config import EXPORT_DIR
        target = EXPORT_DIR / f"img_{db.now().replace(':','').replace(' ','_')}.png"
        target.write_bytes(out.getvalue())
        return {"ok": True, "path": str(target), "size": len(out.getvalue())}
    except Exception as e:
        return {"ok": False, "error": f"图片处理失败：{e}"}
