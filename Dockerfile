# استخدام صورة Python خفيفة جداً
FROM python:3.11-slim

# تثبيت ffmpeg فقط (بدون تحديثات ثقيلة)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# إنشاء مجلد العمل
WORKDIR /app

# نسخ ملف المتطلبات أولاً (لتسريع التخزين المؤقت)
COPY requirements.txt .

# تثبيت المكتبات بدون تخزين مؤقت
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي الملفات
COPY server.py .

# فتح المنفذ
EXPOSE 8000

# أمر التشغيل
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
