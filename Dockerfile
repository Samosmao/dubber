FROM python:3.10-slim

# តំឡើង FFmpeg System Dependency
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# តំឡើង Packages របស់ Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ចម្លងកូដចូល Docker Container
COPY . .

EXPOSE 8000

# ដំណើរការ Server តាមរយៈ Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
