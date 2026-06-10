import os
import sys
import re
import json
import csv
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import yt_dlp
import requests
import webbrowser
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Version ────────────────────────────────────────────────────────────────
CURRENT_VERSION = "1.0.0"
VERSION_URL     = "https://raw.githubusercontent.com/GogoChad/Smash-Music-Ultimate-Conversion-Tool/main/version.txt"
RELEASES_URL    = "https://github.com/GogoChad/Smash-Music-Ultimate-Conversion-Tool/releases/latest"

# ── Windows: Hide cmd windows ──────────────────────────────────────────────
if os.name == 'nt':
    CREATE_NO_WINDOW = 0x08000000
else:
    CREATE_NO_WINDOW = 0

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(sys.argv[0]))
TOOLS_DIR  = os.path.join(BASE_DIR, "tools")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
MP3_DIR    = os.path.join(OUTPUT_DIR, "mp3")
NUS3_DIR   = os.path.join(OUTPUT_DIR, "nus3audio")
TMP_DIR    = os.path.join(BASE_DIR, "tmp")
CSV_PATH   = os.path.join(OUTPUT_DIR, "music_log.csv")

FFMPEG    = r"C:\ffmpeg\bin\ffmpeg.exe"
SOX       = os.path.join(TOOLS_DIR, "sox", "sox.exe")
VGMSTREAM = os.path.join(TOOLS_DIR, "vgmstream", "test.exe")
NUS3AUDIO = os.path.join(TOOLS_DIR, "nus3audio.exe")
VGAUDIO   = os.path.join(TOOLS_DIR, "VGAudioCli.exe")

for d in [MP3_DIR, NUS3_DIR, TMP_DIR]:
    os.makedirs(d, exist_ok=True)

# ── CSV helpers ────────────────────────────────────────────────────────────
CSV_HEADERS = [
    "Title", "Safe Filename", "Date Added", "Source URL",
    "Normalized", "Target LUFS", "MP3 Only", "Status"
]

def _init_csv():
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(CSV_HEADERS)

def _csv_exists(safe_title):
    if not os.path.exists(CSV_PATH):
        return False
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("Safe Filename") == safe_title:
                return True
    return False

def _csv_write(title, safe_title, url, normalized,
               target_lufs, mp3_only, status):
    _init_csv()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            title, safe_title,
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            url,
            "Yes" if normalized else "No",
            f"{target_lufs:.1f}",
            "Yes" if mp3_only else "No",
            status
        ])

def _csv_update_status(safe_title, new_status):
    if not os.path.exists(CSV_PATH):
        return
    rows = []
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["Safe Filename"] == safe_title:
                row["Status"] = new_status
            rows.append(row)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        w.writeheader()
        w.writerows(rows)

# ── Sanitize ───────────────────────────────────────────────────────────────
def sanitize(name):
    name = re.sub(r'[^A-Za-z0-9]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    return name

# ── Auto-update ───────────────────────────────────────────────────────────
def check_for_update(parent):
    def _check():
        try:
            r = requests.get(VERSION_URL, timeout=5)
            latest = r.text.strip()
            if latest != CURRENT_VERSION:
                parent.after(0, lambda: _prompt(latest))
        except Exception:
            pass

    def _prompt(latest):
        if messagebox.askyesno(
            "Update Available",
            f"A new version is available!\n\n"
            f"Current: v{CURRENT_VERSION}\n"
            f"Latest:  v{latest}\n\n"
            f"Open the download page?",
            parent=parent
        ):
            webbrowser.open(RELEASES_URL)

    threading.Thread(target=_check, daemon=True).start()

# ── Normalize ─────────────────────────────────────────────────────────────
def normalize_audio(mp3_path, log, target_lufs=-14.0, skip_measure=False):
    base           = os.path.splitext(os.path.basename(mp3_path))[0]
    tmp_normalized = os.path.join(TMP_DIR, base + "_norm.mp3")
    log(f"  Normalizing {base}...")

    stats = None
    
    # ── Skip measurement for speed (use dynaudnorm directly) ────────────────
    if not skip_measure:
        r = subprocess.run(
            [FFMPEG, "-y", "-i", mp3_path,
             "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
             "-f", "null", "-"],
            capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW
        )

        if r.stderr:
            try:
                js    = r.stderr
                start = js.rfind('{')
                end   = js.rfind('}') + 1
                if start != -1 and end > start:
                    stats = json.loads(js[start:end])
                    log(f"  Measured {stats['input_i']:.1f} LUFS → Targeting {target_lufs} LUFS")
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                log(f"  Loudnorm parse failed ({e}), using dynaudnorm")

    # ── Apply normalization ────────────────────────────────────────────────
    if stats:
        af = (
            f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:"
            f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
            f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
            f"offset={stats['target_offset']}:linear=true"
        )
    else:
        # Fast path: use dynaudnorm only (single pass instead of two)
        af = "dynaudnorm=f=200:g=3:b=1"
        if not skip_measure:
            log(f"  Using fallback normalization (dynaudnorm)")

    r2 = subprocess.run(
        [FFMPEG, "-y", "-i", mp3_path,
         "-af", af, "-codec:a", "libmp3lame", "-q:a", "0",
         tmp_normalized],
        capture_output=True, text=True,
        creationflags=CREATE_NO_WINDOW
    )

    if r2.returncode == 0 and os.path.exists(tmp_normalized):
        os.replace(tmp_normalized, mp3_path)
        log(f"  ✓ Done normalizing {base}")
    else:
        log(f"  ✗ Normalization failed: {r2.stderr[:100]}")

# ── Convert pipeline ───────────────────────────────────────────────────────
def convert_to_nus3audio(mp3_path, log):
    base      = os.path.splitext(os.path.basename(mp3_path))[0]
    tmp_wav   = os.path.join(TMP_DIR, base + "_tmp.wav")
    tmp_lopus = os.path.join(TMP_DIR, base + "_tmp.lopus")
    nus3      = os.path.join(NUS3_DIR, base + ".nus3audio")

    log(f"  Converting to WAV...")
    r = subprocess.run([SOX, mp3_path, "-r", "48000", tmp_wav],
                       capture_output=True, text=True,
                       creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        log(f"  SOX failed: {r.stderr}")
        return False

    r = subprocess.run([VGMSTREAM, "-m", tmp_wav],
                       capture_output=True, text=True,
                       creationflags=CREATE_NO_WINDOW)
    match = re.search(r"stream total samples:\s+(\d+)", r.stdout)
    if not match:
        log(f"  Could not read sample count")
        return False

    end_loop = match.group(1)
    log(f"  Loop: 0 → {end_loop} samples")

    r = subprocess.run(
        [VGAUDIO, "-i", tmp_wav, "-o", tmp_lopus,
         "-l", f"0-{end_loop}", "--bitrate", "64000",
         "--cbr", "--opusheader", "Namco"],
        capture_output=True, text=True,
        creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        log(f"  VGAudio failed: {r.stderr[:150]}")
        return False

    r = subprocess.run(
        [NUS3AUDIO, "-n", "-A", "Smash Ultimate Music Tool",
         tmp_lopus, "-w", nus3],
        capture_output=True, text=True,
        creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        log(f"  Nus3audio failed: {r.stderr}")
        return False

    for f in [tmp_wav, tmp_lopus]:
        if os.path.exists(f):
            os.remove(f)

    log(f"  ✓ Converted → {base}.nus3audio")
    return True

# ── Download Worker (for parallel downloads) ───────────────────────────────
def download_song(entry, i, total, mp3_quality, log_queue):
    """Download a single song and return metadata"""
    try:
        title      = entry.get("title", f"track_{i}")
        safe_title = sanitize(title)
        mp3_path   = os.path.join(MP3_DIR, safe_title + ".mp3")
        nus3_path  = os.path.join(NUS3_DIR, safe_title + ".nus3audio")
        video_url  = entry.get("url") or entry.get("webpage_url")

        # Check if already exists
        if os.path.exists(nus3_path):
            log_queue.append((i, f"  ⚠ Already exists, skipping"))
            return {
                "status": "skipped",
                "title": title,
                "safe_title": safe_title,
                "mp3_path": mp3_path,
                "nus3_path": nus3_path,
                "video_url": video_url,
                "index": i
            }

        log_queue.append((i, f"[DOWNLOAD {i}/{total}] {title}"))

        quality_map = {"128k": "128", "192k": "192", "320k": "320"}
        q = quality_map.get(mp3_quality, "320")

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(MP3_DIR, safe_title + ".%(ext)s"),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": q,
                },
                {
                    "key": "EmbedThumbnail",
                },
                {
                    "key": "FFmpegMetadata",
                    "add_metadata": True,
                }
            ],
            "writethumbnail": True,
            "ffmpeg_location": r"C:\ffmpeg\bin",
            "quiet": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        if not os.path.exists(mp3_path):
            log_queue.append((i, f"  ✗ MP3 not found after download"))
            return {
                "status": "failed",
                "title": title,
                "safe_title": safe_title,
                "error": "MP3 Missing"
            }

        log_queue.append((i, f"  ✓ Downloaded"))
        return {
            "status": "downloaded",
            "title": title,
            "safe_title": safe_title,
            "mp3_path": mp3_path,
            "nus3_path": nus3_path,
            "video_url": video_url,
            "index": i
        }
    except Exception as e:
        log_queue.append((i, f"  ✗ Download failed: {e}"))
        return {
            "status": "failed",
            "title": entry.get("title", f"track_{i}"),
            "safe_title": sanitize(entry.get("title", f"track_{i}")),
            "error": str(e)
        }

# ── Worker ─────────────────────────────────────────────────────────────────
def download_and_convert(url, log, progress_var, status_var,
                         normalize, target_lufs, skip_existing,
                         mp3_only, mp3_quality, on_done,
                         per_song_var=None, fast_mode=False, max_workers=3):
    _init_csv()
    log("Fetching info...")
    status_var.set("Fetching info...")

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        log(f"Failed to fetch: {e}")
        status_var.set("Error fetching URL")
        on_done()
        return

    entries = info.get("entries") or [info]
    total   = len(entries)
    log(f"Found {total} track(s)\n")
    
    if fast_mode:
        log(f"🚀 FAST MODE enabled\n")

    ok = fail = skipped = 0
    
    # ── PHASE 1: Parallel Downloads ────────────────────────────────────────
    log("=" * 60)
    log("DOWNLOAD PHASE (Parallel)\n")
    
    downloaded = []
    failed_downloads = []
    log_queue = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(download_song, entry, i, total, mp3_quality, log_queue): i
            for i, entry in enumerate(entries, 1)
        }
        
        completed = 0
        for future in as_completed(futures):
            completed += 1
            progress_var.set(int((completed - 1) / total * 25))  # 0-25%
            
            result = future.result()
            
            # Flush log queue
            for idx, msg in sorted(log_queue):
                log(msg)
            log_queue.clear()
            
            if result["status"] == "downloaded":
                downloaded.append(result)
            elif result["status"] == "skipped":
                skipped += 1
                _csv_write(result["title"], result["safe_title"], 
                          result.get("video_url", url),
                          normalize, target_lufs, mp3_only, "Skipped")
            elif result["status"] == "failed":
                fail += 1
                failed_downloads.append(result)
                _csv_write(result["title"], result["safe_title"], url,
                          normalize, target_lufs, mp3_only, 
                          f"Failed — {result.get('error', 'Unknown')}")
            
            status_var.set(f"Downloading {completed}/{total}")

    log("")
    log(f"Downloaded: {len(downloaded)} | Skipped: {skipped} | Failed: {fail}\n")

    # ── PHASE 2: Process downloaded files (normalize + convert) ────────────
    if downloaded:
        log("=" * 60)
        log("PROCESSING PHASE\n")
        
        for batch_idx, song_data in enumerate(downloaded, 1):
            title      = song_data["title"]
            safe_title = song_data["safe_title"]
            mp3_path   = song_data["mp3_path"]
            nus3_path  = song_data["nus3_path"]
            video_url  = song_data["video_url"]

            progress_var.set(25 + int((batch_idx - 1) / len(downloaded) * 75))  # 25-100%
            if per_song_var is not None:
                per_song_var.set(0)
            
            log(f"[PROCESS {batch_idx}/{len(downloaded)}] {title}")
            status_var.set(f"Processing {batch_idx}/{len(downloaded)}  {title[:35]}")

            if normalize:
                normalize_audio(mp3_path, log, target_lufs, skip_measure=fast_mode)

            if per_song_var is not None:
                per_song_var.set(50)

            if not mp3_only:
                result = convert_to_nus3audio(mp3_path, log)
                if result:
                    _csv_write(title, safe_title, video_url,
                               normalize, target_lufs, mp3_only, "Converted")
                    ok += 1
                else:
                    _csv_write(title, safe_title, video_url,
                               normalize, target_lufs, mp3_only, "Failed — Conversion")
                    fail += 1
            else:
                _csv_write(title, safe_title, video_url,
                           normalize, target_lufs, mp3_only, "MP3 Only")
                ok += 1

            if per_song_var is not None:
                per_song_var.set(100)

            log("")

    progress_var.set(100)
    status_var.set(f"Done — {ok} converted, {skipped} skipped, {fail} failed")
    log(f"Finished. {ok} converted  {skipped} skipped  {fail} failed")
    log(f"  Log saved → {CSV_PATH}")
    on_done()

# ── GUI ────────────────────────────────────────────────────────────────────
BG      = "#16161e"
PANEL   = "#1f1f2b"
BORDER  = "#2a2a3a"
TEXT    = "#c8ccd4"
DIM     = "#6b6f7a"
ACCENT  = "#7c6af7"
SUCCESS = "#79c99e"
ERROR   = "#e06c75"
WARN    = "#d4a85a"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Smash Music Tool")
        self.geometry("780x820")
        self.resizable(False, False)
        self.configure(bg=BG)
        self._running = False
        self._build()
        # Check for updates on startup (silent if no update)
        check_for_update(self)

    def _build(self):
        # ── Header ────────────────────────────────────────────────────────
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=26, pady=(22, 0))

        tk.Label(header, text="Smash Music Tool",
                 bg=BG, fg=TEXT,
                 font=("Segoe UI", 17)).pack(side="left")

        # Version badge
        tk.Label(header, text=f"v{CURRENT_VERSION}",
                 bg=BORDER, fg=DIM,
                 font=("Segoe UI", 8),
                 padx=6, pady=2).pack(side="left", padx=(10, 0))

        tk.Label(self, text="YouTube  →  MP3  →  NUS3Audio",
                 bg=BG, fg=DIM,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=27)

        # ── URL row ───────────────────────────────────────────────────────
        self._gap(10)
        url_outer = tk.Frame(self, bg=PANEL,
                             highlightbackground=BORDER,
                             highlightthickness=1)
        url_outer.pack(fill="x", padx=22)

        self.url_var = tk.StringVar()
        tk.Entry(url_outer, textvariable=self.url_var,
                 bg=PANEL, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=("Segoe UI", 10), bd=0).pack(
                     side="left", fill="x", expand=True,
                     ipady=9, padx=12)

        tk.Button(url_outer, text="Paste",
                  bg=PANEL, fg=DIM,
                  activebackground=BORDER, activeforeground=TEXT,
                  relief="flat", font=("Segoe UI", 9),
                  bd=0, padx=10, cursor="hand2",
                  command=self._paste).pack(side="right", padx=4)

        # ── Options card ──────────────────────────────────────────────────
        self._gap(14)
        card = tk.Frame(self, bg=PANEL,
                        highlightbackground=BORDER,
                        highlightthickness=1)
        card.pack(fill="x", padx=22)

        # Normalize row
        norm_row = tk.Frame(card, bg=PANEL)
        norm_row.pack(fill="x", padx=14, pady=(12, 4))

        self.normalize_var = tk.BooleanVar(value=True)
        self._checkbox(norm_row, "Normalize Volume",
                       self.normalize_var,
                       command=self._toggle_lufs).pack(side="left")

        lufs_row = tk.Frame(norm_row, bg=PANEL)
        lufs_row.pack(side="right")

        tk.Label(lufs_row, text="Target",
                 bg=PANEL, fg=DIM,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))

        self.lufs_var = tk.DoubleVar(value=-14.0)
        self.lufs_slider = tk.Scale(
            lufs_row, from_=-23, to=-5, orient="horizontal",
            variable=self.lufs_var, bg=PANEL, fg=TEXT,
            troughcolor=BORDER, highlightthickness=0,
            length=120, command=self._lufs_changed)
        self.lufs_slider.pack(side="left")

        self.lufs_label = tk.Label(lufs_row, text="-14.0 LUFS",
                                   bg=PANEL, fg=ACCENT,
                                   font=("Segoe UI", 9, "bold"))
        self.lufs_label.pack(side="left", padx=(8, 0))

        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=14, pady=4)

        # Quality row
        quality_row = tk.Frame(card, bg=PANEL)
        quality_row.pack(fill="x", padx=14, pady=(4, 8))

        tk.Label(quality_row, text="MP3 Quality",
                 bg=PANEL, fg=DIM,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 14))

        self.quality_var = tk.StringVar(value="320k")
        for q in ["128k", "192k", "320k"]:
            tk.Radiobutton(
                quality_row, text=q,
                variable=self.quality_var, value=q,
                bg=PANEL, fg=TEXT,
                selectcolor=BORDER,
                activebackground=PANEL,
                activeforeground=TEXT,
                font=("Segoe UI", 9),
                relief="flat", bd=0,
                cursor="hand2"
            ).pack(side="left", padx=(14, 0))

        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", padx=14, pady=4)

        # Misc row
        misc_row = tk.Frame(card, bg=PANEL)
        misc_row.pack(fill="x", padx=14, pady=(4, 8))

        self.skip_var     = tk.BooleanVar(value=True)
        self.mp3only_var  = tk.BooleanVar(value=False)
        self.fast_mode_var = tk.BooleanVar(value=False)

        self._checkbox(misc_row, "Skip Already Converted",
                       self.skip_var).pack(side="left", padx=(0, 20))
        self._checkbox(misc_row, "MP3 Only",
                       self.mp3only_var).pack(side="left", padx=(0, 20))
        self._checkbox(misc_row, "⚡ Fast Mode",
                       self.fast_mode_var).pack(side="left")

        # ── Buttons ───────────────────────────────────────────────────────
        self._gap(14)
        act = tk.Frame(self, bg=BG)
        act.pack(fill="x", padx=22)

        self.run_btn = tk.Button(
            act, text="Download & Convert",
            bg=ACCENT, fg="#ffffff",
            activebackground="#6a59e0",
            activeforeground="#ffffff",
            relief="flat", font=("Segoe UI", 10, "bold"),
            padx=18, pady=8, cursor="hand2",
            bd=0, command=self.start)
        self.run_btn.pack(side="left")

        tk.Button(act, text="Open Output",
                  bg=PANEL, fg=TEXT,
                  activebackground=BORDER, activeforeground=TEXT,
                  relief="flat", font=("Segoe UI", 10),
                  padx=14, pady=8, cursor="hand2", bd=0,
                  command=lambda: os.startfile(OUTPUT_DIR)).pack(
                      side="left", padx=8)

        tk.Button(act, text="Open MP3",
                  bg=PANEL, fg=TEXT,
                  activebackground=BORDER, activeforeground=TEXT,
                  relief="flat", font=("Segoe UI", 10),
                  padx=14, pady=8, cursor="hand2", bd=0,
                  command=lambda: os.startfile(MP3_DIR)).pack(side="left")

        tk.Button(act, text="Open Log CSV",
                  bg=PANEL, fg=TEXT,
                  activebackground=BORDER, activeforeground=TEXT,
                  relief="flat", font=("Segoe UI", 10),
                  padx=14, pady=8, cursor="hand2", bd=0,
                  command=self._open_csv).pack(side="left", padx=8)

        tk.Button(act, text="History",
                  bg=PANEL, fg=TEXT,
                  activebackground=BORDER, activeforeground=TEXT,
                  relief="flat", font=("Segoe UI", 10),
                  padx=14, pady=8, cursor="hand2", bd=0,
                  command=self._open_history).pack(side="left")

        tk.Button(act, text="Clear Log",
                  bg=PANEL, fg=DIM,
                  activebackground=BORDER, activeforeground=TEXT,
                  relief="flat", font=("Segoe UI", 10),
                  padx=14, pady=8, cursor="hand2", bd=0,
                  command=self._clear_log).pack(side="right")

        # ── Global Progress ───────────────────────────────────────────────
        self._gap(12)
        tk.Label(self, text="Overall Progress",
                 bg=BG, fg=DIM,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=24)

        self.progress_var = tk.IntVar()
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("flat.Horizontal.TProgressbar",
                        troughcolor=BORDER,
                        background=ACCENT,
                        bordercolor=BG,
                        lightcolor=ACCENT,
                        darkcolor=ACCENT,
                        thickness=5)
        style.configure("song.Horizontal.TProgressbar",
                        troughcolor=BORDER,
                        background=SUCCESS,
                        bordercolor=BG,
                        lightcolor=SUCCESS,
                        darkcolor=SUCCESS,
                        thickness=3)
        ttk.Progressbar(self,
                        variable=self.progress_var,
                        style="flat.Horizontal.TProgressbar",
                        maximum=100).pack(fill="x", padx=22)

        # ── Per-song Progress ─────────────────────────────────────────────
        self._gap(4)
        tk.Label(self, text="Current Track",
                 bg=BG, fg=DIM,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=24)

        self.per_song_var = tk.IntVar()
        ttk.Progressbar(self,
                        variable=self.per_song_var,
                        style="song.Horizontal.TProgressbar",
                        maximum=100).pack(fill="x", padx=22)

        # ── Status + Log ───────────────────────────────────────────────────
        self._gap(8)
        status_frame = tk.Frame(self, bg=BG)
        status_frame.pack(fill="x", padx=24)

        tk.Label(status_frame, text="Status",
                 bg=BG, fg=DIM,
                 font=("Segoe UI", 8)).pack(anchor="w")

        self.status_var = tk.StringVar(value="Ready")
        tk.Label(self, textvariable=self.status_var,
                 bg=BG, fg=TEXT,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=24, pady=(2, 8))

        tk.Label(self, text="Conversion Log",
                 bg=BG, fg=DIM,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=24)

        # ── Log box ────────────────────────────────────────────────────────
        log_frame = tk.Frame(self, bg=BG)
        log_frame.pack(fill="both", expand=True, padx=22, pady=(0, 22))

        self.log_box = tk.Text(
            log_frame, bg=PANEL, fg=TEXT,
            insertbackground=TEXT,
            relief="flat", font=("Consolas", 9),
            bd=0, wrap="word"
        )
        self.log_box.pack(fill="both", expand=True, side="left")

        scrollbar = tk.Scrollbar(log_frame, bg=BORDER,
                                 troughcolor=PANEL,
                                 highlightthickness=0,
                                 command=self.log_box.yview)
        scrollbar.pack(fill="y", side="right", padx=(4, 0))
        self.log_box.configure(yscrollcommand=scrollbar.set)

        self.log_box.tag_config("fail", foreground=ERROR)
        self.log_box.tag_config("err",  foreground=ERROR)
        self.log_box.tag_config("ok",   foreground=SUCCESS)
        self.log_box.tag_config("warn", foreground=WARN)
        self.log_box.tag_config("dim",  foreground=DIM)
        self.log_box.tag_config("head", foreground=TEXT,
                                font=("Consolas", 9, "bold"))

    # ── History Window ────────────────────────────────────────────────────
    def _open_history(self):
        _init_csv()
        win = tk.Toplevel(self)
        win.title("Music History")
        win.geometry("900x500")
        win.configure(bg=BG)
        win.resizable(True, True)

        # Search bar
        search_frame = tk.Frame(win, bg=BG)
        search_frame.pack(fill="x", padx=16, pady=(14, 6))

        tk.Label(search_frame, text="Search:",
                 bg=BG, fg=TEXT,
                 font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))

        self._search_var = tk.StringVar()
        tk.Entry(search_frame, textvariable=self._search_var,
                 bg=PANEL, fg=TEXT, insertbackground=TEXT,
                 relief="flat", font=("Segoe UI", 10),
                 bd=0).pack(side="left", fill="x", expand=True, ipady=6, padx=4)

        # Stats
        self._stats_label = tk.Label(search_frame, text="",
                                    bg=BG, fg=ACCENT,
                                    font=("Segoe UI", 9, "bold"))
        self._stats_label.pack(side="right", padx=8)

        # Treeview
        tree_frame = tk.Frame(win, bg=BG)
        tree_frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        tree = ttk.Treeview(tree_frame, columns=CSV_HEADERS, height=18)
        tree.column("#0", width=0, stretch=False)
        for h in CSV_HEADERS:
            tree.column(h, anchor="w", width=100)
            tree.heading(h, text=h)

        tree.tag_configure("ok",   foreground=SUCCESS)
        tree.tag_configure("fail", foreground=ERROR)
        tree.tag_configure("warn", foreground=WARN)

        scrollbar = tk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscroll=scrollbar.set)
        tree.pack(fill="both", expand=True)

        def update_tree(*args):
            for item in tree.get_children():
                tree.delete(item)

            query = self._search_var.get().lower() if hasattr(self, '_search_var') else ""

            with open(CSV_PATH, "r", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    values = [row.get(h, "") for h in CSV_HEADERS]
                    if query and not any(query in v.lower() for v in values):
                        continue
                    status = row.get("Status", "")
                    if "Converted" in status or "MP3" in status:
                        tag = "ok"
                    elif "Failed" in status:
                        tag = "fail"
                    else:
                        tag = "warn"
                    tree.insert("", "end", values=values, tags=(tag,))

            self._update_stats()

        if hasattr(self, '_search_var'):
            self._search_var.trace("w", update_tree)

        update_tree()

    def _update_stats(self):
        if not hasattr(self, '_stats_label'):
            return
        if not os.path.exists(CSV_PATH):
            return
        total = converted = failed = skipped = 0
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                total += 1
                s = row.get("Status", "")
                if "Converted" in s or "MP3" in s:
                    converted += 1
                elif "Failed" in s:
                    failed += 1
                elif "Skipped" in s:
                    skipped += 1
        self._stats_label.configure(
            text=f"Total: {total}  |  ✓ {converted}  |  ✗ {failed}  |  ⚠ {skipped}"
        )

    # ── Helpers ───────────────────────────────────────────────────────────
    def _checkbox(self, parent, text, variable, command=None):
        return tk.Checkbutton(
            parent, text=text,
            variable=variable,
            bg=PANEL, fg=TEXT,
            selectcolor=BORDER,
            activebackground=PANEL,
            activeforeground=TEXT,
            font=("Segoe UI", 9),
            command=command,
            relief="flat", bd=0,
            cursor="hand2")

    def _gap(self, h=8):
        tk.Frame(self, bg=BG, height=h).pack(fill="x")

    def _paste(self):
        try:
            self.url_var.set(self.clipboard_get())
        except Exception:
            pass

    def _toggle_lufs(self):
        s = "normal" if self.normalize_var.get() else "disabled"
        self.lufs_slider.configure(state=s)

    def _lufs_changed(self, _=None):
        self.lufs_label.configure(text=f"{self.lufs_var.get():.1f} LUFS")

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _open_csv(self):
        _init_csv()
        os.startfile(CSV_PATH)

    def log(self, msg):
        m = msg.lower()
        if "failed" in m or "error" in m:    tag = "err"
        elif "saved" in m or "done" in m or \
             "finished" in m or "✓" in m:    tag = "ok"
        elif "skip" in m or "fallback" in m \
             or "duplicate" in m or "⚠" in m:  tag = "warn"
        elif msg.startswith("  "):            tag = "dim"
        else:                                 tag = "head"

        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n", tag)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def start(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("Error", "Paste a YouTube URL first")
            return
        if self._running:
            return

        self._clear_log()
        self.progress_var.set(0)
        self.per_song_var.set(0)
        self.status_var.set("Starting...")
        self._running = True
        self.run_btn.configure(state="disabled",
                               text="Running...",
                               bg=BORDER)

        threading.Thread(
            target=download_and_convert,
            args=(
                url, self.log,
                self.progress_var, self.status_var,
                self.normalize_var.get(),
                self.lufs_var.get(),
                self.skip_var.get(),
                self.mp3only_var.get(),
                self.quality_var.get(),
                self._on_done,
                self.per_song_var,
                self.fast_mode_var.get(),  # Fast mode parameter
                3  # max_workers for parallel downloads
            ),
            daemon=True
        ).start()

    def _on_done(self):
        self._running = False
        self.run_btn.configure(state="normal",
                               text="Download & Convert",
                               bg=ACCENT)

if __name__ == "__main__":
    App().mainloop()
