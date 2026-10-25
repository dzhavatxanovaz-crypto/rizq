#!/usr/bin/env python3
"""Сборка финального ролика в одном из двух фирменных форматов.

  bez-stuka   вертикаль 720x1280, картинка окном 4:3 по центру, субтитры на чёрном под окном
  ai-creator  горизонталь 1280x720, «акцентный стек» слов по слову, афоризм + карточка курса

Вход:  --video клип (после склейки в монтажке), --script JSON (см. templates/).
Выход: --out mp4 (H.264 + AAC, -14 LUFS), рядом .ass, чтобы можно было поправить тайминги.

Примеры:
  python3 render_video.py --format bez-stuka  --video cut.mp4 --script ep01.json --out ep01.mp4
  python3 render_video.py --format ai-creator --video cut.mp4 --script ac01.json --out ac01.mp4
  python3 render_video.py --format bez-stuka  --video cut.mp4 --script ep01.json --ass-only
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

FORMATS = {
    "bez-stuka": {
        "W": 720, "H": 1280,
        "window": (720, 540, 0, 370),  # w, h, x, y — окно 4:3 по центру холста
    },
    "ai-creator": {"W": 1280, "H": 720},
}

DEFAULT_FONTS = {
    "bez-stuka": {"sub": "Roboto Condensed", "card": "Roboto Condensed"},
    "ai-creator": {"sub": "Bebas Neue", "card": "Bebas Neue", "light": "Montserrat"},
}

WHITE = "&H00FFFFFF"
GREY = "&H00B4B4B4"


def ass_time(t):
    t = max(t, 0.0)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def has_audio(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True).stdout.strip()
    return bool(out)


def wrap(text, limit):
    """Перенос по словам: сперва пробуем 2 сбалансированные строки, иначе жадно на N строк."""
    if len(text) <= limit:
        return text
    words = text.split()
    best, best_diff = None, 10 ** 9
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        if len(a) <= limit and len(b) <= limit and abs(len(a) - len(b)) < best_diff:
            best, best_diff = a + r"\N" + b, abs(len(a) - len(b))
    if best:
        return best
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > limit:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    return r"\N".join(lines)


def esc(text):
    return text.replace("{", "(").replace("}", ")")


def ass_header(W, H, styles):
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
             "WrapStyle: 2", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
             "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,"
             "Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
             "MarginL,MarginR,MarginV,Encoding"]
    lines += styles
    lines += ["", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]
    return lines


def style_line(name, font, size, bold=0, italic=0, color=WHITE):
    return (f"Style: {name},{font},{size},{color},{color},&H00000000,&H00000000,{bold},{italic},0,0,100,100,0,0,1,0,0,5,0,0,0,1")


def event(start, end, style, text):
    return f"Dialogue: 0,{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{text}"


# ---------------------------------------------------------------- bez-stuka

def build_bez_stuka(script, fonts, video_end):
    W, H = FORMATS["bez-stuka"]["W"], FORMATS["bez-stuka"]["H"]
    font = fonts.get("sub", DEFAULT_FONTS["bez-stuka"]["sub"])
    styles = [style_line("Sub", font, 30, bold=-1, italic=-1),
              style_line("CardBig", fonts.get("card", font), 40, bold=-1),
              style_line("CardSmall", fonts.get("card", font), 26, bold=0, color=GREY)]
    ev = []
    # окно кончается на y=910; центр строки субтитра ≈ y=962
    for ln in script["lines"]:
        text = esc(wrap(ln["text"], 52))
        ev.append(event(ln["start"], ln["end"], "Sub", r"{\an8\pos(360,944)\fad(150,150)}" + text))
    card = script.get("end_card", {})
    dur = card.get("duration", 3.0)
    lines = card.get("lines") or [{"text": "@handle", "style": "CardBig"}]
    y = H // 2 - 14 * (len(lines) - 1)
    for i, c in enumerate(lines):
        ev.append(event(video_end, video_end + dur, c.get("style", "CardBig"),
                        r"{\an5\pos(360,%d)\fad(250,0)}%s" % (y + i * 52, esc(c["text"]))))
    return ass_header(W, H, styles) + ev, dur


# --------------------------------------------------------------- ai-creator

def chunk_words(text, max_chars=15):
    chunks, cur = [], []
    for w in text.upper().split():
        if re.fullmatch(r"[—–-]+", w):
            continue
        probe = " ".join(cur + [w])
        if cur and (len(probe) > max_chars or len(cur) >= 2):
            chunks.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def build_ai_creator(script, fonts, video_end):
    W, H = FORMATS["ai-creator"]["W"], FORMATS["ai-creator"]["H"]
    font = fonts.get("sub", DEFAULT_FONTS["ai-creator"]["sub"])
    light = fonts.get("light", DEFAULT_FONTS["ai-creator"]["light"])
    styles = [style_line("Acc", font, 64, bold=0),
              style_line("Card", font, 66),
              style_line("CardSmall", font, 34),
              style_line("Brand", font, 104, color=GREY),
              style_line("Light", light, 28, color=GREY)]
    ev = []
    for ln in script["lines"]:
        chunks = chunk_words(ln["text"])
        weights = [max(len(c), 3) for c in chunks]
        total, t = sum(weights), ln["start"]
        span = ln["end"] - ln["start"]
        side = ln.get("side", "right")
        x, an = {"right": (int(W * 0.58), 4), "left": (int(W * 0.42), 6), "center": (W // 2, 5)}[side]
        y = int(H * ln.get("y", 0.74))
        for k, c in enumerate(chunks):
            seg = span * weights[k] / total
            end = ln["end"] if k == len(chunks) - 1 else t + seg
            prev = chunks[max(0, k - 2):k]
            body = "".join(r"{\fs46\alpha&H8C&}%s\N" % esc(p) for p in prev)
            body += r"{\fs64\alpha&H00&}%s" % esc(c)
            tags = r"{\an%d\pos(%d,%d)\fad(%d,%d)\fscx93\fscy93\t(0,140,\fscx100\fscy100)}" % (
                an, x, y, 70 if k == 0 else 0, 150 if k == len(chunks) - 1 else 0)
            ev.append(event(t, end, "Acc", tags + body))
            t = end
    card = script.get("end_card", {})
    t0 = video_end
    if card.get("aphorism"):
        d = card.get("aphorism_duration", 2.8)
        text = esc(wrap(card["aphorism"].upper(), 34))
        ev.append(event(t0, t0 + d, "Card", r"{\an5\pos(%d,%d)\fad(250,200)}%s" % (W // 2, H // 2, text)))
        t0 += d
    d = card.get("duration", 3.0)
    for text, style, dy in [(card.get("kicker", "КУРС ОБУЧЕНИЯ НЕЙРОСЕТЯМ"), "CardSmall", -92),
                            (card.get("brand", "· AI CREATOR ·"), "Brand", -10),
                            (card.get("cta", "подробности в директ"), "Light", 70)]:
        if text:
            ev.append(event(t0, t0 + d, style, r"{\an5\pos(%d,%d)\fad(300,0)}%s" % (W // 2, H // 2 + dy, esc(text))))
    return ass_header(W, H, styles) + ev, (t0 + d) - video_end


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--format", required=True, choices=FORMATS)
    ap.add_argument("--video", required=True)
    ap.add_argument("--script", required=True)
    ap.add_argument("--out")
    ap.add_argument("--fonts-dir", help="папка со шрифтами (Roboto Condensed / Bebas Neue / Montserrat)")
    ap.add_argument("--fit", choices=["crop", "pad"], default="crop",
                    help="bez-stuka: crop — обрезать клип до 4:3 по центру; pad — вписать с полями")
    ap.add_argument("--ass-only", action="store_true")
    ap.add_argument("--no-loudnorm", action="store_true")
    a = ap.parse_args()

    script = json.loads(pathlib.Path(a.script).read_text(encoding="utf-8"))
    fonts = script.get("fonts", {})
    vdur = probe_duration(a.video)
    build = build_bez_stuka if a.format == "bez-stuka" else build_ai_creator
    ass_lines, tail = build(script, fonts, vdur)

    out = pathlib.Path(a.out) if a.out else pathlib.Path(a.video).with_suffix(".final.mp4")
    ass_path = out.with_suffix(".ass")
    ass_path.write_text("\n".join(ass_lines) + "\n", encoding="utf-8")
    print(f"ASS: {ass_path}  (клип {vdur:.2f}s + карточки {tail:.2f}s)")
    if a.ass_only:
        return

    fmt = FORMATS[a.format]
    W, H = fmt["W"], fmt["H"]
    if a.format == "bez-stuka":
        ww, wh, wx, wy = fmt["window"]
        scale = (f"scale={ww}:{wh}:force_original_aspect_ratio=increase,crop={ww}:{wh}" if a.fit == "crop"
                 else f"scale={ww}:{wh}:force_original_aspect_ratio=decrease,pad={ww}:{wh}:(ow-iw)/2:(oh-ih)/2:black")
        vf = f"{scale},pad={W}:{H}:{wx}:{wy}:black"
    else:
        vf = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black"
    ass_arg = "ass=" + str(ass_path).replace("\\", "/").replace(":", r"\:")
    if a.fonts_dir:
        ass_arg += ":fontsdir=" + str(a.fonts_dir).replace(":", r"\:")
    vf += f",fps=30,setsar=1,tpad=stop_mode=add:stop_duration={tail:.3f}:color=black,{ass_arg},format=yuv420p"

    cmd = ["ffmpeg", "-v", "error", "-y", "-i", a.video, "-vf", vf]
    if has_audio(a.video):
        af = [] if a.no_loudnorm else ["loudnorm=I=-14:TP=-1.5:LRA=11"]
        af += [f"afade=t=out:st={max(vdur - 0.5, 0):.2f}:d=0.5", f"apad=pad_dur={tail:.3f}"]
        cmd += ["-af", ",".join(af), "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    cmd += ["-t", f"{vdur + tail:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-movflags", "+faststart", str(out)]
    print(" ".join(cmd[:6]), "...")
    subprocess.run(cmd, check=True)
    print(f"OK: {out}")


if __name__ == "__main__":
    sys.exit(main())
