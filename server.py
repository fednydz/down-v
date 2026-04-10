"""
SaveAll Video Downloader API
Version: 1.3.2 - Fixed all issues
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
# ⚙️ Logging
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 🔄 Lifespan
# ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 بدء تشغيل خادم SaveAll API v1.3.2")
    yield
    logger.info("🛑 إيقاف الخادم")

# ─────────────────────────────────────────────────────────────
# 🏗️ App Init
# ─────────────────────────────────────────────────────────────
app = FastAPI(title="SaveAll API", version="1.3.2", lifespan=lifespan)

# ─────────────────────────────────────────────────────────────
# 🔐 Middleware
# ─────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ─────────────────────────────────────────────────────────────
# 🔧 Helper Functions
# ─────────────────────────────────────────────────────────────

def format_duration(duration_val):
    """✅ تحويل آمن للمدة من float إلى int"""
    if not duration_val:
        return "00:00"
    try:
        d = int(float(duration_val))  # تحويل آمن
        return f"{d // 60}:{d % 60:02d}"
    except:
        return "00:00"

def format_filesize(bytes_size):
    """تنسيق حجم الملف"""
    if not bytes_size:
        return "غير معروف"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"

# ─────────────────────────────────────────────────────────────
# 📡 Endpoints
# ─────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.3.2"}

@app.get("/api/info")
@limiter.limit("10/minute")
async def get_video_info(request: Request, url: str = Query(...)):
    """استخراج معلومات الفيديو"""
    logger.info(f"🔍 تحليل: {url[:50]}...")

    # ✅ خيارات محسّنة لتجاوز حظر يوتيوب
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        # ✅ استخدام عملاء متعددين لتجاوز الحظر
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "web", "tv", "web_embedded", "mweb"],
                "player_skip": ["configs", "webpage"]
            }
        },
        # ✅ محاكاة متصفح حقيقي
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        },
        "no_check_certificate": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                raise ValueError("Empty response")

            formats = []
            for f in info.get("formats", []):
                if f.get("vcodec") == "none" and f.get("acodec") == "none":
                    continue
                
                size = f.get("filesize_approx") or f.get("filesize") or 0
                
                formats.append({
                    "format_id": f["format_id"],
                    "resolution": f.get("resolution") or f.get("format_note") or "Unknown",
                    "ext": f.get("ext", "mp4"),
                    "filesize": int(size) if size else 0,
                    "filesize_human": format_filesize(size),
                    "is_audio_only": f.get("vcodec") == "none" and f.get("acodec") != "none"
                })

            # ✅ ترتيب آمن مع معالجة القيم الفارغة
            formats.sort(key=lambda x: (x["filesize"] or 0), reverse=True)

            return {
                "success": True,
                "data": {
                    "title": info.get("title", "عنوان غير معروف"),
                    "thumbnail": info.get("thumbnail", ""),
                    "duration": info.get("duration"),
                    "duration_human": format_duration(info.get("duration")),  # ✅ الإصلاح هنا
                    "uploader": info.get("uploader", "غير معروف"),
                    "view_count": info.get("view_count"),
                    "platform": info.get("extractor_key", "unknown"),
                    "formats": formats[:15]
                }
            }

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        logger.error(f"❌ yt-dlp error: {msg}")
        
        # ✅ معالجة أخطاء مختلفة
        if "bot" in msg.lower() or "sign in" in msg.lower():
            raise HTTPException(
                status_code=400, 
                detail="🚫 يوتيوب يمنع الوصول من الخادم. جرب فيديو آخر أو انتظر قليلاً."
            )
        elif "unavailable" in msg.lower() or "error code" in msg.lower():
            raise HTTPException(
                status_code=400,
                detail="❌ الفيديو غير متوفر أو تم حذفه أو مقيد في منطقتك."
            )
        elif "private" in msg.lower():
            raise HTTPException(status_code=400, detail="🔒 الفيديو خاص.")
        else:
            raise HTTPException(status_code=400, detail=f"❌ خطأ: {msg[:150]}")
            
    except Exception as e:
        logger.exception(f"💥 Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"❌ خطأ داخلي: {str(e)[:100]}")

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
        "socket_timeout": 60,
        "retries": 3,
        "extractor_args": {"youtube": {"player_client": ["ios", "web"]}},
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        },
        "no_check_certificate": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            raise RuntimeError("فشل في إنشاء الملف")

        def stream():
            with open(temp_path, "rb") as f:
                yield from f.read()
            if os.path.exists(temp_path): 
                os.remove(temp_path)

        return StreamingResponse(
            stream(), 
            media_type="video/mp4",
            headers={"Content-Disposition": 'attachment; filename="video.mp4"'}
        )
        
    except Exception as e:
        if os.path.exists(temp_path): 
            os.remove(temp_path)
        logger.error(f"❌ Download error: {e}")
        raise HTTPException(status_code=500, detail=str(e)[:150])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
