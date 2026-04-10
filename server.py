"""
SaveAll Video Downloader API
Backend Server - Production Ready for Railway
Author: Mounir Djouida
Version: 1.3.0 - Fixed sorting and YouTube access issues
"""

import os
import re
import logging
import tempfile
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import yt_dlp

# ─────────────────────────────────────────────────────────────
# 📋 إعداد السجلات (Logging)
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 🔄 دورة حياة التطبيق (Lifespan)
# ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """تهيئة الموارد عند بدء التشغيل، وتنظيفها عند الإيقاف"""
    logger.info("🚀 بدء تشغيل خادم SaveAll API")
    logger.info(f"📦 إصدار yt-dlp: {yt_dlp.version.__version__}")
    yield
    logger.info("🛑 إيقاف الخادم - تنظيف الموارد")

# ─────────────────────────────────────────────────────────────
# ⚙️ تهيئة التطبيق
# ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="SaveAll Video Downloader API",
    description="واجهة برمجية لتحميل الفيديوهات من يوتيوب، فيسبوك، انستغرام، وتيك توك",
    version="1.3.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# ─────────────────────────────────────────────────────────────
# 🔐 إعدادات الأمان والوسيط (Middleware)
# ─────────────────────────────────────────────────────────────

# تحديد معدل الطلبات
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# سياسة CORS
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://mounirdjouida.yzz.me,*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in ALLOWED_ORIGINS if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Length", "Content-Disposition"]
)

# ضغط الاستجابات
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ─────────────────────────────────────────────────────────────
# 🔧 دوال مساعدة (Helpers)
# ─────────────────────────────────────────────────────────────

def sanitize_filename(filename: str) -> str:
    """تنظيف اسم الملف من الأحرف غير الصالحة"""
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    filename = ' '.join(filename.split())
    return filename[:100]

def format_filesize(bytes_size: Optional[int]) -> str:
    """تحويل حجم الملف من بايت إلى صيغة مقروءة"""
    if not bytes_size:
        return "غير معروف"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"

def is_valid_video_url(url: str) -> bool:
    """التحقق الأساسي من صحة رابط الفيديو"""
    patterns = [
        r'(youtube\.com|youtu\.be)',
        r'(facebook\.com|fb\.watch)',
        r'instagram\.com',
        r'(tiktok\.com|vt\.tiktok\.com)',
        r'twitter\.com',
        r'x\.com'
    ]
    return any(re.search(p, url, re.I) for p in patterns)

# ─────────────────────────────────────────────────────────────
# 📡 نقاط النهاية (Endpoints)
# ─────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """نقطة جذرية للتحقق من عمل الخادم"""
    return {
        "service": "SaveAll API",
        "version": "1.3.0",
        "status": "running",
        "docs": "/api/docs"
    }

@app.get("/api/health")
async def health_check():
    """فحص صحة الخادم والمكتبات"""
    return {
        "status": "healthy",
        "yt_dlp_version": yt_dlp.version.__version__,
        "ffmpeg_available": os.system("ffmpeg -version > /dev/null 2>&1") == 0
    }

@app.get("/api/info")
@limiter.limit("10/minute")
async def get_video_info(request: Request, url: str = Query(..., min_length=10, description="رابط الفيديو المراد تحليله")):
    """
    استخراج معلومات الفيديو والجودات المتاحة
    """
    # التحقق من صحة الرابط
    if not is_valid_video_url(url):
        logger.warning(f"❌ رابط غير مدعوم: {url[:50]}...")
        raise HTTPException(status_code=400, detail="الرابط غير مدعوم. استخدم يوتيوب، فيسبوك، انستغرام، أو تيك توك")
    
    logger.info(f"🔍 تحليل الرابط: {url[:60]}...")
    
    # خيارات yt-dlp المحسّنة لتجاوز حظر يوتيوب
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        # استخدام متصفحات وعملاء مختلفين لتجاوز الحظر
        "extractor_args": {
            "youtube": {
                "skip": ["hls", "dash"],
                "player_client": ["ios", "web", "tv"],  # تجربة عملاء متعددين
                "player_skip": ["webpage"]
            }
        },
        # محاكاة متصفح حقيقي
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-us,en;q=0.5",
            "Sec-Fetch-Mode": "navigate"
        },
        # تجنب بعض القيود
        "no_check_certificate": True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                raise ValueError("فشل في استخراج البيانات")
            
            # تصفية وتنسيق الجودات المتاحة
            formats = []
            seen_resolutions = set()
            
            for f in info.get("formats", []):
                # تخطي الصيغ غير المفيدة
                if f.get("vcodec") == "none" and f.get("acodec") == "none":
                    continue
                
                resolution = f.get("resolution") or f.get("format_note") or "غير معروف"
                
                # تجنب التكرار
                if resolution in seen_resolutions and f.get("filesize", 0) == 0:
                    continue
                seen_resolutions.add(resolution)
                
                formats.append({
                    "format_id": f["format_id"],
                    "resolution": resolution,
                    "ext": f.get("ext", "mp4"),
                    "filesize": f.get("filesize_approx") or f.get("filesize", 0),
                    "filesize_human": format_filesize(f.get("filesize_approx") or f.get("filesize")),
                    "vcodec": None if f.get("vcodec") == "none" else f.get("vcodec"),
                    "acodec": None if f.get("acodec") == "none" else f.get("acodec"),
                    "fps": f.get("fps"),
                    "is_audio_only": f.get("vcodec") == "none" and f.get("acodec") != "none"
                })
            
            # ✅ الحل: ترتيب مع معالجة القيم الفارغة (None)
            formats.sort(key=lambda x: (x["filesize"] or 0, x["resolution"] or ""), reverse=True)
            
            # إرجاع أفضل 15 جودة فقط
            response_data = {
                "success": True,
                "data": {
                    "title": info.get("title", "عنوان غير معروف"),
                    "thumbnail": info.get("thumbnail", ""),
                    "duration": info.get("duration", 0),
                    "duration_human": f"{info.get('duration', 0)//60}:{info.get('duration', 0)%60:02d}" if info.get("duration") else "00:00",
                    "uploader": info.get("uploader", "غير معروف"),
                    "view_count": info.get("view_count"),
                    "platform": info.get("extractor_key", "unknown"),
                    "formats": formats[:15]
                }
            }
            
            logger.info(f"✅ تم استخراج {len(formats[:15])} جودة لـ: {info.get('title', '')[:40]}...")
            return response_data
            
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        logger.error(f"❌ خطأ yt-dlp: {error_msg}")
        
        # رسائل خطأ مخصصة
        if "Sign in to confirm" in error_msg or "bot" in error_msg:
            raise HTTPException(
                status_code=400, 
                detail="يوتيوب يمنع الوصول من الخادم. جرب استخدام رابط آخر أو انتظر قليلاً."
            )
        elif "Private video" in error_msg:
            raise HTTPException(status_code=400, detail="هذا الفيديو خاص. لا يمكن تحميله.")
        elif "unavailable" in error_msg:
            raise HTTPException(status_code=400, detail="الفيديو غير متوفر أو تم حذفه.")
        else:
            raise HTTPException(status_code=400, detail=f"لا يمكن الوصول للفيديو: {error_msg[:150]}")
            
    except Exception as e:
        logger.exception(f"❌ خطأ غير متوقع: {str(e)}")
        raise HTTPException(status_code=500, detail="خطأ داخلي في الخادم. حاول مرة أخرى لاحقاً")

@app.get("/api/download")
@limiter.limit("3/minute")
async def download_video(
    request: Request,
    background_tasks: BackgroundTasks,
    url: str = Query(..., min_length=10),
    format_id: str = Query(..., min_length=1),
    filename: Optional[str] = Query(None, description="اسم مخصص للملف (اختياري)")
):
    """
    تحميل الفيديو وإرساله كمجرى بيانات (Streaming)
    """
    if not is_valid_video_url(url):
        raise HTTPException(status_code=400, detail="الرابط غير مدعوم")
    
    logger.info(f"⬇️ بدء التحميل: {url[:60]}... | الجودة: {format_id}")
    
    # إنشاء ملف مؤقت فريد
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4", prefix="saveall_")
    temp_path = temp_file.name
    temp_file.close()
    
    # خيارات التحميل والدمج المحسّنة
    ydl_opts = {
        "format": format_id,
        "merge_output_format": "mp4",
        "outtmpl": temp_path,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 60,
        "retries": 3,
        "fragment_retries": 3,
        # نفس الخيارات لتجاوز الحظر
        "extractor_args": {
            "youtube": {
                "player_client": ["ios", "web"]
            }
        },
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
        "no_check_certificate": True,
    }
    
    try:
        # تنفيذ التحميل الفعلي
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        
        # التحقق من نجاح إنشاء الملف
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            raise RuntimeError("فشل في إنشاء ملف الفيديو")
        
        # إعداد اسم الملف للتنزيل
        safe_title = sanitize_filename(filename or info.get("title", "video"))
        content_disposition = f'attachment; filename="{safe_title}.mp4"'
        
        # دالة لتدفق الملف
        def stream_file():
            try:
                with open(temp_path, "rb") as f:
                    while chunk := f.read(8192):
                        yield chunk
            finally:
                # تنظيف: حذف الملف المؤقت
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    logger.info(f"🗑️ تم حذف الملف المؤقت: {temp_path}")
        
        logger.info(f"✅ جاهز للإرسال: {os.path.getsize(temp_path) / 1024 / 1024:.2f} MB")
        
        return StreamingResponse(
            stream_file(),
            media_type="video/mp4",
            headers={
                "Content-Disposition": content_disposition,
                "X-Video-Title": safe_title,
                "X-File-Size": str(os.path.getsize(temp_path))
            }
        )
        
    except yt_dlp.utils.DownloadError as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        logger.error(f"❌ فشل التحميل: {str(e)}")
        raise HTTPException(status_code=500, detail=f"فشل في تحميل الفيديو: {str(e)[:150]}")
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        logger.exception(f"❌ خطأ غير متوقع أثناء التحميل: {str(e)}")
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء معالجة الفيديو")

# ─────────────────────────────────────────────────────────────
# 🚫 معالجة الأخطاء العامة
# ─────────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """معالجة موحدة لأخطاء HTTP"""
    logger.warning(f"⚠️ خطأ HTTP {exc.status_code}: {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": exc.detail, "path": request.url.path}
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """معالجة الأخطاء غير المتوقعة"""
    logger.exception(f"💥 خطأ غير متوقع: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "خطأ داخلي في الخادم", "path": request.url.path}
    )

# ─────────────────────────────────────────────────────────────
# 🏁 نقطة الدخول الرئيسية
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", os.getenv("RAILWAY_PORT", 8000)))
    host = os.getenv("HOST", "0.0.0.0")
    workers = int(os.getenv("UVICORN_WORKERS", 1))
    
    logger.info(f"🔧 الإعدادات: {host}:{port} | Workers: {workers}")
    
    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        workers=workers,
        log_level="info",
        access_log=True
    )
