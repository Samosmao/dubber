import os
import re
import json
import time
import shutil
import asyncio
import edge_tts
import google.generativeai as genai

from fastapi import FastAPI
from fastapi import UploadFile
from fastapi import File
from fastapi.responses import (
    HTMLResponse,
    FileResponse,
    JSONResponse
)

from fastapi.middleware.cors import CORSMiddleware

from moviepy import (
    VideoFileClip,
    AudioFileClip
)

from pydub import AudioSegment


# ---------------------
# CONFIG
# ---------------------

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
TEMP_DIR = "temp"

for p in [
    UPLOAD_DIR,
    OUTPUT_DIR,
    TEMP_DIR
]:
    os.makedirs(
        p,
        exist_ok=True
    )

KEY = os.getenv(
    "GEMINI_API_KEY"
)

if not KEY:
    raise Exception(
        "Missing GEMINI_API_KEY"
    )

genai.configure(
    api_key=KEY
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------
# UI
# ---------------------

@app.get(
    "/",
    response_class=HTMLResponse
)
async def home():

    with open(
        "index.html",
        "r",
        encoding="utf8"
    ) as f:

        return f.read()


# ---------------------
# AUDIO
# ---------------------

def extract_audio(
    video,
    output
):

    clip = VideoFileClip(
        video
    )

    clip.audio.write_audiofile(
        output,
        logger=None
    )

    clip.close()


# ---------------------
# GEMINI
# ---------------------

def transcribe(
    audio
):

    up = genai.upload_file(
        path=audio
    )

    while (
        up.state.name
        ==
        "PROCESSING"
    ):

        time.sleep(
            2
        )

        up = (
            genai
            .get_file(
                up.name
            )
        )

    prompt = """
You receive audio.

Detect language.

Return JSON ONLY.

[
{
"start":"00:00:00,000",
"end":"00:00:02,000",
"original":"你好",
"khmer":"សួស្តី"
}
]

Rules:
translate to Khmer.
keep timestamps.
"""

    model = (
        genai
        .GenerativeModel(
            "gemini-2.5-flash"
        )
    )

    r = (
        model
        .generate_content(
            [
                up,
                prompt
            ]
        )
    )

    txt = (
        r.text
        .replace(
            "```json",
            ""
        )
        .replace(
            "```",
            ""
        )
        .strip()
    )

    genai.delete_file(
        up.name
    )

    return json.loads(
        txt
    )


# ---------------------
# TIME
# ---------------------

def sec(t):

    t = (
        t
        .replace(
            ",",
            "."
        )
    )

    h, m, s = (
        t.split(
            ":"
        )
    )

    return (
        int(h)
        *
        3600
        +
        int(m)
        *
        60
        +
        float(s)
    )


# ---------------------
# EDGE
# ---------------------

async def tts(
    items,
    output
):

    total = (
        int(
            sec(
                items[-1]["end"]
            )
            *
            1000
        )
        +
        3000
    )

    final = (
        AudioSegment
        .silent(
            total
        )
    )

    voice = (
        "km-KH-SreymomNeural"
    )

    for i, x in enumerate(
        items
    ):

        mp3 = (
            f"{TEMP_DIR}/"
            f"{i}.mp3"
        )

        try:

            await (
                edge_tts
                .Communicate(
                    x["khmer"],
                    voice,
                    rate="+15%"
                )
                .save(
                    mp3
                )
            )

            clip = (
                AudioSegment
                .from_mp3(
                    mp3
                )
            )

            final = (
                final
                .overlay(
                    clip,
                    position=int(
                        sec(
                            x["start"]
                        )
                        *
                        1000
                    )
                )
            )

        except:

            pass

        if os.path.exists(
            mp3
        ):

            os.remove(
                mp3
            )

    final.export(
        output,
        format="mp3"
    )


# ---------------------
# MERGE
# ---------------------

def merge(
    video,
    audio,
    out
):

    v = (
        VideoFileClip(
            video
        )
    )

    a = (
        AudioFileClip(
            audio
        )
    )

    r = (
        v.with_audio(
            a
        )
    )

    r.write_videofile(
        out,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast"
    )

    v.close()

    a.close()


# ---------------------
# SUBTITLE
# ---------------------

@app.post(
    "/subtitle"
)
async def subtitle(
    file:
    UploadFile
    =
    File(...)
):

    path = (
        f"{UPLOAD_DIR}/"
        f"{file.filename}"
    )

    mp3 = (
        f"{TEMP_DIR}/a.mp3"
    )

    with open(
        path,
        "wb"
    ) as f:

        shutil.copyfileobj(
            file.file,
            f
        )

    extract_audio(
        path,
        mp3
    )

    s = transcribe(
        mp3
    )

    return (
        JSONResponse(
            s
        )
    )


# ---------------------
# DUB
# ---------------------

@app.post(
    "/dub"
)
async def dub(
    file:
    UploadFile
    =
    File(...)
):

    video = (
        f"{UPLOAD_DIR}/"
        f"{file.filename}"
    )

    audio = (
        f"{TEMP_DIR}/a.mp3"
    )

    dub = (
        f"{TEMP_DIR}/kh.mp3"
    )

    out = (
        f"{OUTPUT_DIR}/"
        f"kh_"
        f"{file.filename}"
    )

    with open(
        video,
        "wb"
    ) as f:

        shutil.copyfileobj(
            file.file,
            f
        )

    extract_audio(
        video,
        audio
    )

    items = (
        transcribe(
            audio
        )
    )

    await tts(
        items,
        dub
    )

    merge(
        video,
        dub,
        out
    )

    return FileResponse(
        out
    )