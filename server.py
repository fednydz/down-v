"""
SaveAll Video Downloader API
Version: 1.3.1 - Fixed Float Duration Error & Improved YouTube Handling
"""

import os
import re
import logging
import tempfile
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import yt_dlp

# ─────────────────────────────────────────────────────────────
# ⚙️ إعدادات التسجيل (Logging)
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 🔄 دورة حياة التطبيق
# ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 بدء تشغيل خادم SaveAll API v1.3.1")
    yield
    logger.info("🛑 إيقاف الخادم")

# ─────────────────────────────────────────────────────────────
# 🏗️ تهيئة التطبيق
# ─────────────────────────────────────────────────────────────
app = FastAPI(title="SaveAll API", version="1.3.1", lifespan=lifespan)

# ─────────────────────────────────────────────────────────────
# 🔐 Middleware & Security
# ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # للسماح بالوصول من واجهتك
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ─────────────────────────────────────────────────────────────
# 🔧 دوال مساعدة
# ─────────────────────────────────────────────────────────────

def get_safe_duration(duration_val):
    """تحويل المدة إلى دقائق:ثواني بأمان"""
    try:
        if not duration_val:
            return "00:00"
        d = int(float(duration_val))  # تحويل إلى عدد صحيح
        return f"{d // 60}:{d % 60:02d}"
    except:
        return "00:00"

# ─────────────────────────────────────────────────────────────
# 📡 Endpoints
# ─────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.3.1"}

@app.get("/api/info")
@limiter.limit("10/minute")
async def get_video_info(request: Request, url: str = Query(...)):
    """استخراج معلومات الفيديو"""
    logger.info(f"🔍 تحليل: {url[:50]}...")

    # خيارات yt-dlp المحسّنة جداً
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "socket_timeout": 30,
        "retries": 3,
        # محاولة تجاوز حظر يوتيوب باستخدام عملاء مختلفين
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "web", "tv", "web_embedded"],
                "player_skip": ["configs", "webpage"]
            }
        },
        "headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                raise ValueError("Empty response")

            formats = []
            # تصفية الجودات
            for f in info.get("formats", []):
                if f.get("vcodec") == "none" and f.get("acodec") == "none":
                    continue
                
                # استخراج الحجم بأمان
                size = f.get("filesize_approx") or f.get("filesize") or 0
                
                formats.append({
                    "format_id": f["format_id"],
                    "resolution": f.get("resolution") or "Unknown",
                    "ext": f.get("ext", "mp4"),
                    "filesize": int(size), # ضمان أن الحجم عدد صحيح
                    "filesize_human": f"{size / 1024 / 1024:.1f} MB" if size else "Unknown",
                    "is_audio_only": f.get("vcodec") == "none"
                })

            # ترتيب النتائج
            formats.sort(key=lambda x: x["filesize"] or 0, reverse=True)

            return {
                "success": True,
                "data": {
                    "title": info.get("title", "Unknown Title"),
                    "duration": info.get("duration"),
                    "duration_human": get_safe_duration(info.get("duration")), # ✅ الإصلاح هنا
                    "uploader": info.get("uploader"),
                    "formats": formats[:12] # عرض أفضل 12 جودة فقط
                }
            }

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if "bot" in msg or "Sign in" in msg:
            raise HTTPException(status_code=400, detail="🚫 يوتيوب يمنع الوصول من هذا الخادم حالياً. يرجى تجربة فيديو آخر أو إعادة المحاولة لاحقاً.")
        raise HTTPException(status_code=400, detail=f"❌ خطأ في التحليل: {msg[:100]}")
    except Exception as e:
        logger.error(f"💥 Error: {e}")
        raise HTTPException(status_code=500, detail=f"❌ خطأ داخلي: {str(e)}")

@app.get("/api/download")
@limiter.limit("3/minute")
async def download_video(request: Request, url: str = Query(...), format_id: str = Query(...)):
    """تحميل الفيديو"""
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    temp_path = temp_file.name
    temp_file.close()

    ydl_opts = {
        "format": format_id,
        "merge_output_format": "mp4",
        "outtmpl": temp_path,
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"player_client": ["ios", "web"]}},
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        def stream():
            with open(temp_path, "rb") as f:
                yield from f.read()
            if os.path.exists(temp_path): os.remove(temp_path)

        return StreamingResponse(stream(), media_type="video/mp4", 
                                 headers={"Content-Disposition": f'attachment; filename="video.mp4"'})
    except Exception as e:
        if os.path.exists(temp_path): os.remove(temp_path)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
