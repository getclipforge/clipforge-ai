import os, json, re, subprocess, uuid, zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify, send_from_directory
from faster_whisper import WhisperModel
import anthropic, yt_dlp

app = Flask(__name__, static_folder="static")
OUT = Path("outputs"); OUT.mkdir(exist_ok=True)
whisper = WhisperModel(os.getenv("WHISPER_MODEL", "base"), compute_type="int8")
ai = anthropic.Anthropic()  # needs ANTHROPIC_API_KEY env var
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")

def t(x):  # ASS time
    return f"{int(x//3600)}:{int(x%3600//60):02d}:{x%60:05.2f}"

def ass(words, hook, dur, captions):
    h = ("[Script Info]\nPlayResX: 1080\nPlayResY: 1920\n[V4+ Styles]\n"
         "Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
         "Style: Cap,Arial,84,&H0000FFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,6,0,2,60,60,480,1\n"
         "Style: Hook,Arial,70,&H00FFFFFF,&H000000FF,&H00000000,1,0,0,0,100,100,0,0,1,8,0,8,70,70,200,1\n"
         "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    h += f"Dialogue: 0,{t(0)},{t(min(3.5,dur))},Hook,,0,0,0,,{hook.upper()}\n"
    if captions:
        for i in range(0, len(words), 3):
            g = words[i:i+3]
            h += f"Dialogue: 0,{t(g[0][0])},{t(g[-1][1])},Cap,,0,0,0,,{' '.join(w[2] for w in g).upper()}\n"
    return h

def pick_clips(segs, total):
    tr = "\n".join(f"[{s.start:.0f}-{s.end:.0f}] {s.text.strip()}" for s in segs)[:60000]
    p = (f"Video length {total:.0f}s. Transcript:\n{tr}\n\nPick 10-12 best viral short clips (20-60s each, "
         "start/end on sentence boundaries, non-overlapping). For each write a strong scroll-stopping HOOK "
         "(max 8 words, curiosity/shock/benefit, same language as video). Reply ONLY JSON: "
         '[{"start":0,"end":30,"hook":"...","title":"..."}]')
    r = ai.messages.create(model=MODEL, max_tokens=2000, messages=[{"role": "user", "content": p}])
    txt = re.sub(r"```json|```", "", r.content[0].text).strip()
    return json.loads(txt)

def make(job, src, i, c, words, captions):
    w = [x for x in words if x[0] >= c["start"] and x[1] <= c["end"]]
    w = [(a-c["start"], b-c["start"], s) for a, b, s in w]
    dur = c["end"] - c["start"]
    sub = job / f"c{i}.ass"; sub.write_text(ass(w, c["hook"], dur, captions), encoding="utf-8")
    out = job / f"clip{i}.mp4"
    subprocess.run(["ffmpeg", "-y", "-ss", str(c["start"]), "-t", str(dur), "-i", str(src),
        "-vf", f"crop=ih*9/16:ih,scale=1080:1920,ass={sub.name}", "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "23", "-c:a", "aac", out.name],
        cwd=job, check=True, capture_output=True)
    return {"url": f"/outputs/{job.name}/{out.name}", "hook": c["hook"], "title": c.get("title", "")}

@app.route("/")
def home(): return send_from_directory("static", "index.html")

@app.route("/outputs/<path:p>")
def files(p): return send_from_directory("outputs", p)

@app.route("/process", methods=["POST"])
def process():
    try:
        job = OUT / uuid.uuid4().hex[:8]; job.mkdir()
        captions = request.form.get("captions") == "on"
        if request.files.get("file"):
            src = job / "src.mp4"; request.files["file"].save(src)
        else:
            with yt_dlp.YoutubeDL({"outtmpl": str(job / "src.%(ext)s"), "format": "mp4/best[height<=1080]",
                                   "merge_output_format": "mp4", "quiet": True}) as y:
                y.download([request.form["url"]])
            src = next(job.glob("src.*"))
        segs, info = whisper.transcribe(str(src), word_timestamps=True, vad_filter=True)
        segs = list(segs)
        words = [(w.start, w.end, w.word.strip()) for s in segs for w in s.words]
        clips = pick_clips(segs, info.duration)
        with ThreadPoolExecutor(4) as ex:
            res = list(ex.map(lambda a: make(job, src, a[0], a[1], words, captions), enumerate(clips)))
        with zipfile.ZipFile(job / "all_clips.zip", "w") as z:
            for f in job.glob("clip*.mp4"): z.write(f, f.name)
        return jsonify(clips=res, zip=f"/outputs/{job.name}/all_clips.zip")
    except Exception as e:
        return jsonify(error=str(e)), 500

if __name__ == "__main__": app.run(port=5000)
