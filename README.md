# Gameplay → Structured Events: Proof-of-Concept Starter Kit

This little kit answers the one question your whole product depends on:
**can software turn your gameplay footage into accurate, useful game events?**

It does the full loop with the least possible setup:

```
                    (long video only)
your clip  →  [0] pre-filter  →  [1] grab frames  →  [2] Gemini reads them → events.json + events.csv
              drop idle parts                        [3] (optional) PaddleOCR reads numbers → ocr_text.csv
```

You do **not** need a backend, a database, or any of the heavy tools from the big
architecture diagram. That all comes later. Right now you just want a yes/no answer.

---

## What's in this folder

| File | What it's for |
|------|----------------|
| `0_prefilter.py` | *For long videos.* A fast, free pass that finds the active gameplay and drops idle/menu/loading parts before you pay Gemini. Reports the cost saving |
| `1_extract_frames.py` | Turns a recording of **any length** into frames with FFmpeg — either evenly, or only at the moments the screen changes (scene detection) |
| `2_analyze_gemini.py` | Sends those frames to Gemini, gets back structured events |
| `3_read_ocr.py` | *Optional.* Reads exact on-screen text/numbers with PaddleOCR |
| `schema.json` | **The most important file.** Your list of events to capture — edit this for your game |
| `requirements.txt` | The Python packages to install |
| `grade_accuracy.csv` | A blank sheet to score how accurate Gemini was |

---

## One-time setup (about 15 minutes)

### 1. Install Python

1. Go to <https://www.python.org/downloads/> and download Python 3.11 or newer.
2. Run the installer. **On the first screen, tick the box "Add python.exe to PATH"** — this matters.
3. Finish the install.

Check it worked: open a terminal (press the Windows key, type **powershell**, hit Enter) and run:

```powershell
python --version
```

You should see something like `Python 3.12.x`. If it says "not recognized," reinstall and make sure you ticked "Add to PATH."

### 2. Get this folder open in the terminal

In the same PowerShell window, move into this folder (adjust the path if you moved it):

```powershell
cd "C:\Users\16316\Claude\Projects\Video game analytics tool\poc-starter"
```

### 3. Install the Python packages

```powershell
pip install -r requirements.txt
```

This installs the Gemini library and OpenCV (and PaddleOCR). If PaddleOCR gives you
trouble, you can skip it for now — see "If PaddleOCR won't install" at the bottom.

### 4. Get a free Gemini API key

1. Go to <https://aistudio.google.com/app/apikey> and sign in with a Google account.
2. Click **Create API key**. Copy the long string it gives you.
3. Tell your terminal about it (paste your real key in place of the placeholder):

```powershell
$env:GEMINI_API_KEY = "paste-your-key-here"
```

> Note: this only lasts for the current terminal window. To set it permanently,
> search Windows for "Edit environment variables for your account," add a new
> variable named `GEMINI_API_KEY` with your key as the value, then open a fresh terminal.

---

## Running your first test

### Step 0 — Get a short clip

Put a **short** clip (20–60 seconds is plenty) of your game into this folder.
Name it something simple like `myclip.mp4`. Short clips keep cost near zero and
make grading easy.

### Step 0 — Pre-filter (only for long videos)

Skip this for short test clips. For a long recording, run the cheap pass first
to see how much is worth analyzing:

```powershell
python 0_prefilter.py --video longstream.mp4
```

It scans the video using free signals (motion + darkness — no AI), then prints a
report: how many minutes are active vs idle, **what percentage it would drop**,
and the **estimated Gemini cost with and without filtering**. It writes
`keep_segments.csv` (the start/end seconds worth analyzing). Tune it for your game:

- `--motion 6` — lower keeps more footage, higher filters harder
- `--dark 20` — frames darker than this (loading screens, transitions) count as idle
- `--window 4` / `--pad 2` — decision granularity and how much to keep around each segment

This is a **model-cascade**: a cheap filter in front of the expensive model. The file
also has a clearly marked `classify_window_with_yolo()` hook — once you train a small
YOLO model on your game, you can drop it in there for much sharper "is this real
gameplay?" filtering. You don't need YOLO for the proof of concept.

### Step 1 — Grab frames (FFmpeg does the chopping)

For a short test clip, sample one frame per second:

```powershell
python 1_extract_frames.py --video myclip.mp4 --mode uniform --fps 1
```

For a **long** recording (a full match or stream), use scene detection so it
only keeps frames where the screen actually changes — far fewer frames, far
lower cost, and you never chop anything by hand:

```powershell
python 1_extract_frames.py --video longstream.mp4 --mode scene --threshold 0.4
```

Either way you get a `frames` folder plus `frames/manifest.csv` (the exact
timestamp of every frame). The script also prints a rough Gemini cost estimate.
Lower `--threshold` (e.g. 0.2) keeps more frames; higher (0.6) keeps only big changes.

> **How this maps to your real product:** here FFmpeg runs on your computer, but
> in the app it runs on your **server** the moment a user finishes uploading. The
> user just uploads a raw recording and waits — your backend does all the
> segmenting, sampling, and scene-detection automatically. They never see a clip.

### Step 2 — Edit your schema, then analyze

Open `schema.json` and edit it for **your** game:
- set `"game"` to your game's name,
- list the 8–15 `event_types` you care about,
- adjust the fields if you want.

This is the real work — it defines what "an event" means in your product.

Then run:

```powershell
python 2_analyze_gemini.py
```

You'll get `events.json` (full detail) and `events.csv` (easy to open in Excel/Sheets).

### Step 3 — Grade it (this is the actual point)

1. Open `grade_accuracy.csv` in Excel or Google Sheets.
2. Watch your clip second by second. In each row, write what *actually* happened.
3. Compare to what Gemini said in `events.csv`. Mark each correct/incorrect.

The percentage it gets right **is your proof of concept.** If it's good enough that
a player would find it useful — you have something real. If not, try a clearer event
list, a different game, or better wording in `schema.json` before building anything bigger.

### Step 4 (optional) — Exact numbers with PaddleOCR

Only once the above works and you want precise numbers (HP, damage, timers):

```powershell
python 3_read_ocr.py
```

This writes `ocr_text.csv` with every piece of text it read off the screen.

---

## Tips

- **Keep clips short at first.** A 30-second clip is enough to learn a lot and costs pennies.
- **Iterate on `schema.json`.** Small wording changes ("only report events you can see
  clear evidence for") noticeably improve accuracy. Save versions as you go.
- **Try 2 fps for fast games.** `python 1_extract_frames.py --video myclip.mp4 --fps 2`
  then `python 2_analyze_gemini.py --fps 2`.
- **If a model name errors,** open `2_analyze_gemini.py` and change the `MODEL` line.
  Any current Gemini "Flash" model works; check available names at
  <https://ai.google.dev/gemini-api/docs/models>.

## Troubleshooting

**"No API key found"** — you didn't set `GEMINI_API_KEY` in this terminal (see setup step 4).

**"python is not recognized"** — Python isn't on PATH. Reinstall and tick "Add to PATH."

**If PaddleOCR won't install** — it's optional. Install just the essentials and skip step 3:
```powershell
pip install google-genai imageio-ffmpeg opencv-python
```

**"FFmpeg not found"** — run `pip install imageio-ffmpeg`; it bundles a copy the script finds automatically.
Come back to PaddleOCR later when you actually need exact-number reading.

---

## What this proves (and what it doesn't)

This proves whether the *core idea* works: footage in, structured events out, accurately.
It deliberately uses Gemini to do the seeing so you skip months of custom computer-vision
work (YOLO, training data, etc.). That custom-CV pipeline is a real thing you may build
**later** to cut cost at scale — but only after this test says "yes, this works."
