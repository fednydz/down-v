from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp, os, tempfile

app = FastAPI()

# السماح للواجهة بالاتصال (ضع رابط موقعك الحقيقي للأمان)
app.add_middleware(CORSMiddleware, allow_origins=["https://mounirdjouida.yzz.me", "*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/api/info")
async def get_info(url: str = Query(...)):
    opts = {"quiet": True, "no_warnings": True, "extract_flat": False, "socket_timeout": 15}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = []
            for f in info.get("formats", []):
                if f.get("vcodec") != "none" or f.get("acodec") != "none":
                    formats.append({
                        "format_id": f["format_id"], 
                        "resolution": f.get("resolution", "صوت فقط"),
                        "ext": f.get("ext", "mp4"), 
                        "filesize": f.get("filesize_approx") or f.get("filesize", 0)
                    })
            return {
                "title": info.get("title", "غير معروف"), 
                "duration": info.get("duration", 0),
                "uploader": info.get("uploader", "غير معروف"), 
                "formats": sorted(formats, key=lambda x: x["filesize"], reverse=True)[:12]
            }
    except Exception as e: 
        return JSONResponse(status_code=400, content={"error": str(e)})

@app.get("/api/download")
async def download(url: str = Query(...), format_id: str = Query(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp: 
        temp_path = tmp.name
    opts = {
        "format": format_id, 
        "merge_output_format": "mp4", 
        "outtmpl": temp_path, 
        "quiet": True, 
        "socket_timeout": 30
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl: 
            ydl.download([url])
        def stream():
            with open(temp_path, "rb") as f:
                while chunk := f.read(8192): 
                    yield chunk
        return StreamingResponse(
            stream(), 
            media_type="video/mp4", 
            headers={"Content-Disposition": f'attachment; filename="video.mp4"'}
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if os.path.exists(temp_path): 
            os.remove(temp_path)

if __name__ == "__main__":
    import uvicorn
    # Railway يحدد المنفذ عبر متغير البيئة PORT
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
