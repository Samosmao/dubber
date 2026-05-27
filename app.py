import os
import json
import time
import shutil
import asyncio
import subprocess
import edge_tts
import google.generativeai as genai

from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from moviepy import VideoFileClip
from pydub import AudioSegment

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
TEMP_DIR = "temp"

for p in [UPLOAD_DIR, OUTPUT_DIR, TEMP_DIR]:
    os.makedirs(p, exist_ok=True)

KEY = os.getenv("GEMINI_API_KEY")
if not KEY:
    raise Exception("Missing GEMINI_API_KEY")

genai.configure(api_key=KEY)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# អនុគមន៍សម្រាប់លុបឯកសារបណ្ដោះអាសន្ន និងឯកសារលទ្ធផល
def cleanup_files(filename: str):
    try:
        # ១. លុបឯកសារ Original នៅក្នុង uploads/
        input_path = os.path.join(UPLOAD_DIR, filename)
        if os.path.exists(input_path):
            os.remove(input_path)
            
        # ២. លុបឯកសារលទ្ធផលនៅក្នុង outputs/
        output_path = os.path.join(OUTPUT_DIR, f"kh_{filename}")
        if os.path.exists(output_path):
            os.remove(output_path)
            
        # ៣. ជម្រះឯកសារផ្សេងៗនៅក្នុង temp/
        if os.path.exists(TEMP_DIR):
            for f in os.listdir(TEMP_DIR):
                file_path = os.path.join(TEMP_DIR, f)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    
        print(f"🎯 ជោគជ័យ: បានសម្អាតឯកសារទាំងអស់របស់ {filename} រួចរាល់។")
    except Exception as e:
        print(f"❌ កំហុសក្នុងការសម្អាតឯកសារ: {e}")

@app.get("/", response_class=HTMLResponse)
async def home():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(current_dir, "index.html")
    
    with open(html_path, "r", encoding="utf8") as f:
        return f.read()

def extract_audio(video, output):
    clip = VideoFileClip(video)
    clip.audio.write_audiofile(output, logger=None)
    clip.close()

def transcribe(audio):
    up = genai.upload_file(path=audio)
    while up.state.name == "PROCESSING":
        time.sleep(2)
        up = genai.get_file(up.name)

    prompt = """
You receive audio. Detect language. Return JSON ONLY inside a list.
Format:
[
  {"start":"00:00:02,000","end":"00:00:05,300","original":"Hello","khmer":"សួស្តី"}
]
Strict Rules: Use EXACT SRT format "HH:MM:SS,mmm". DO NOT confuse minutes with hours.
"""
    model = genai.GenerativeModel("gemini-3.5-flash")
    r = model.generate_content(
        [up, prompt],
        generation_config={"response_mime_type": "application/json"}
    )
    genai.delete_file(up.name)
    return json.loads(r.text.strip())

def sec(t):
    t = t.replace(",", ".")
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)

async def tts(items, output):
    total = int((sec(items[-1]["end"]) / 1.25) * 1000) + 4000
    final = AudioSegment.silent(total)
    voice = "km-KH-SreymomNeural"

    for i, x in enumerate(items):
        mp3 = f"{TEMP_DIR}/{i}.mp3"
        try:
            await edge_tts.Communicate(x["khmer"], voice, rate="+25%").save(mp3)
            clip = AudioSegment.from_mp3(mp3)
            pos = int((sec(x["start"]) / 1.25) * 1000)
            final = final.overlay(clip, position=pos)
        except:
            pass
        if os.path.exists(mp3):
            os.remove(mp3)
            
    final.export(output, format="mp3")

@app.post("/subtitle")
async def subtitle(file: UploadFile = File(...)):
    path = f"{UPLOAD_DIR}/{file.filename}"
    mp3 = f"{TEMP_DIR}/a.mp3"
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    extract_audio(path, mp3)
    s = transcribe(mp3)
    return JSONResponse(s)

@app.post("/dub_edited")
async def dub_edited(file: UploadFile = File(...), items_json: str = Form(...)):
    items = json.loads(items_json)
    video_path = f"{UPLOAD_DIR}/{file.filename}"
    audio_orig = f"{TEMP_DIR}/a.mp3"
    dub_voice = f"{TEMP_DIR}/kh.mp3"
    out_video = f"{OUTPUT_DIR}/kh_{file.filename}"

    with open(video_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    extract_audio(video_path, audio_orig)
    await tts(items, dub_voice)
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-i", dub_voice,
        "-filter_complex", 
        "[0:v]setpts=PTS/1.25[v]; "
        "[0:a]atempo=1.25,lowpass=f=300,volume=0.3[bg]; "
        "[1:a]volume=1.5[kh]; "
        "[bg][kh]amix=inputs=2:duration=first[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-c:a", "aac", "-preset", "ultrafast",
        out_video
    ]
    
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    if process.returncode != 0:
        cmd_fallback = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", dub_voice,
            "-filter_complex", "[0:v]setpts=PTS/1.25[v]",
            "-map", "[v]", "-map", "1:a",
            "-c:v", "libx264", "-c:a", "aac", "-preset", "ultrafast",
            out_video
        ]
        subprocess.run(cmd_fallback)

    # ត្រឡប់ឈ្មោះឯកសារទៅឱ្យ Frontend ដើម្បីឱ្យវាដឹងលីងសម្រាប់ទាញយកពិតប្រាកដ
    return JSONResponse({"status": "success", "filename": file.filename})

# Endpoint ថ្មីសម្រាប់ដំណើរការ Download រួចលុបចោលភ្លាមៗ
@app.get("/download/{filename}")
async def download_and_delete(filename: str, background_tasks: BackgroundTasks):
    out_video = f"{OUTPUT_DIR}/kh_{filename}"
    if not os.path.exists(out_video):
        raise HTTPException(status_code=404, detail="រកមិនឃើញវីដេអូ ឬឯកសារនេះត្រូវបានលុបរួចហើយ។")
    
    # ដាក់ Task ចូល Background ដើម្បីដំណើរការក្រោយ File បញ្ជូនចប់
    background_tasks.add_task(cleanup_files, filename)
    return FileResponse(out_video, media_type="video/mp4", filename=f"khmer_{filename}")
