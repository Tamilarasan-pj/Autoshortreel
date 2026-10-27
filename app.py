import os, json, re, tempfile, requests
import numpy as np
import streamlit as st
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (VideoFileClip, AudioFileClip, ImageClip, ColorClip,
                            CompositeVideoClip, concatenate_videoclips, vfx)

MODEL = "claude-sonnet-5-5"
W, H = 1080, 1920
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf"]


def secret(name):
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, "")


def get_script(topic, n, lang, key):
    import anthropic
    prompt = (f"Write a {n}-scene YouTube Short script about: {topic}. Narration language code: {lang}. "
              "Scene 1 must be a strong hook. Each scene has 1-2 short sentences of narration and "
              "2-3 English stock-footage search keywords. Reply ONLY with a JSON list of objects "
              "with keys 'narration' and 'keywords'.")
    msg = anthropic.Anthropic(api_key=key).messages.create(
        model=MODEL, max_tokens=1500, messages=[{"role": "user", "content": prompt}])
    return json.loads(re.search(r"\[.*\]", msg.content[0].text, re.S).group(0))


def parse_manual(text):
    scenes = []
    for line in text.strip().splitlines():
        if line.strip():
            narr, _, kw = line.partition("|")
            scenes.append({"narration": narr.strip(), "keywords": kw.strip() or narr.strip()})
    return scenes


def fetch_clip(query, key, folder, used):
    try:
        r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": key},
                         params={"query": query, "orientation": "portrait", "per_page": 8}, timeout=20).json()
        for v in r.get("videos", []):
            if v["id"] in used:
                continue
            files = sorted([f for f in v["video_files"] if f.get("height", 0) >= 1280],
                           key=lambda f: f["height"])
            if files:
                used.add(v["id"])
                path = os.path.join(folder, f"{v['id']}.mp4")
                with open(path, "wb") as fh:
                    fh.write(requests.get(files[0]["link"], timeout=60).content)
                return path
    except Exception:
        pass
    return None


def load_font(size):
    for f in FONTS:
        try:
            return ImageFont.truetype(f, size)
        except Exception:
            continue
    return ImageFont.load_default()


def caption(text, dur):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d, font = ImageDraw.Draw(img), load_font(70)
    lines, line = [], ""
    for w in text.split():
        t = (line + " " + w).strip()
        if d.textlength(t, font=font) > W - 160:
            lines.append(line)
            line = w
        else:
            line = t
    lines.append(line)
    y = H - 480 - len(lines) * 45
    for l in lines:
        d.text(((W - d.textlength(l, font=font)) / 2, y), l, font=font,
               fill="white", stroke_width=6, stroke_fill="black")
        y += 90
    return ImageClip(np.array(img)).set_duration(dur)


def build(scenes, pexels_key, lang, captions, out):
    tmp, clips, used = tempfile.mkdtemp(), [], set()
    for i, s in enumerate(scenes):
        mp3 = os.path.join(tmp, f"v{i}.mp3")
        gTTS(s["narration"], lang=lang).save(mp3)
        audio = AudioFileClip(mp3)
        dur = audio.duration + 0.3
        path = fetch_clip(s["keywords"], pexels_key, tmp, used) if pexels_key else None
        if path:
            v = VideoFileClip(path).without_audio()
            v = v.fx(vfx.loop, duration=dur) if v.duration < dur else v.subclip(0, dur)
            v = v.resize(max(W / v.w, H / v.h))
            v = v.crop(x_center=v.w / 2, y_center=v.h / 2, width=W, height=H)
        else:
            v = ColorClip((W, H), color=(20, 20, 40)).set_duration(dur)
        layers = [v] + ([caption(s["narration"], dur)] if captions else [])
        clips.append(CompositeVideoClip(layers, size=(W, H)).set_audio(audio))
    concatenate_videoclips(clips, method="compose").write_videofile(
        out, fps=24, codec="libx264", audio_codec="aac", preset="ultrafast", threads=2, logger=None)


st.set_page_config(page_title="AI Shorts Maker", page_icon="🎬", layout="centered")
st.title("🎬 AI Shorts Maker")
topic = st.text_input("Topic", placeholder="e.g. 3 AI tools that save you hours")
c1, c2, c3 = st.columns(3)
lang = c1.selectbox("Voice", ["en", "ta", "hi"])
n = c2.slider("Scenes", 3, 8, 5)
caps = c3.checkbox("Captions", True)
manual = st.text_area("Or paste your own script", placeholder="One scene per line: narration | keywords")
claude_key, pexels_key = secret("ANTHROPIC_API_KEY"), secret("PEXELS_API_KEY")

if st.button("Generate video", type="primary", use_container_width=True):
    try:
        if manual.strip():
            scenes = parse_manual(manual)
        elif claude_key and topic:
            with st.spinner("Writing script..."):
                scenes = get_script(topic, n, lang, claude_key)
        else:
            st.error("Enter a topic (needs an Anthropic key) or paste a script.")
            st.stop()
        with st.spinner("Rendering video, this takes 1 to 3 minutes..."):
            out = os.path.join(tempfile.mkdtemp(), "short.mp4")
            build(scenes, pexels_key, lang, caps, out)
        st.session_state["video"] = open(out, "rb").read()
        st.session_state["scenes"] = scenes
    except Exception as e:
        st.error(f"Failed: {e}")

if "video" in st.session_state:
    st.video(st.session_state["video"])
    st.download_button("Download MP4", st.session_state["video"], "short.mp4", "video/mp4",
                       use_container_width=True)
    with st.expander("Script used"):
        st.write(st.session_state["scenes"])
