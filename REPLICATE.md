# Replicating the viewer for another folder of videos

This is the complete recipe for producing the same viewer for a different set of
recordings. No assistance is needed — the generator is a standalone script.

---

## 1. What you need

| | |
|---|---|
| **Python 3.8+** | required, for the generator |
| **ffprobe** | *optional* — used only for extra detail (frame rate, encoder tags). The script reads start times, durations, frame sizes and audio-track counts straight out of the MP4 boxes itself |
| **A browser** | Chrome, Edge or Firefox, for whoever reviews the footage |
| **The video files** | the folder you want to build a viewer for |

Nothing has to be installed on the reviewer's machine. The finished viewer is a
single HTML file that opens by double-click, with no server and no network.

---

## 2. The one command

```bash
python3 make_viewer.py /path/to/videos
```

That writes, into the video folder:

```
index.html              the viewer — self-contained, nothing else needed
evidence-manifest.json  machine-readable index of every file
README.txt              a short guide describing this particular archive
```

Open `index.html` in a browser and it works. The videos are loaded by relative
path, so **keep `index.html` in the same folder as the recordings** — the folder
can be renamed, moved, zipped or copied anywhere.

Add `--hash` to also produce `SHA256SUMS.txt` (slow on large archives — it
reads every byte).

### Pointing it at an archive instead

It takes an archive just as happily:

```bash
python3 make_viewer.py Evidence-27items-2026-10-20.zip
```

* **The metadata is read from inside the archive.** The MP4 boxes are parsed
  in place, so there is no need to unpack 17 GB to find out when the footage
  starts. Scanning the archive this way takes about half a minute.
* **The media is unpacked next to the viewer**, preserving the folder structure
  inside the archive, because the viewer can only play files that sit beside it.
  By default the output folder is named after the archive and placed next to
  it: `Evidence-27items-2026-10-20.zip` → `Evidence-27items-2026-10-20/`.
* Non-media files in the archive are left alone — only the recordings are
  unpacked.
* `.tar`, `.tar.gz` and `.tgz` work the same way.

To see the timeline without unpacking anything at all:

```bash
python3 make_viewer.py Evidence-27items-2026-10-20.zip --manifest-only
```

That writes just `evidence-manifest.json` — the start time, duration, frame
size and audio tracks of every recording, read straight out of the archive.


---

## 3. What it does with your files

For every video in the folder it reads:

* **the start time** from the MP4 `mvhd` box (the `creation_time` field) — the
  same value `ffprobe` reports as `creation_time`
* **the duration** from the same box
* **the frame size** from the video track's sample description (`stsd`), falling
  back to the track header
* **the number of audio tracks**
* the file size, and (with `--hash`) its SHA-256

It then sorts everything by start time and lays it out on a single continuous
case-time axis.

### Naming conventions it recognises

The generator classifies each file by its name, which drives the colour coding
and the badge in the viewer:

| Pattern in the filename | Kind | Colour |
|---|---|---|
| `Body` + a number, e.g. `Axon_Body_4_Video_...` | body camera | amber |
| `Interior`, e.g. `Axon_Fleet_3_Interior_...` | interior camera | violet |
| `Front`, e.g. `Axon_Fleet_3_Front_...` | front camera | blue |
| anything else | audio / other | green |

A device serial in the name — `..._D01AK0270.mp4` — is picked up and shown on
the clip.

**None of this is required.** Files that match no pattern are simply treated as
"other" and appear in the list with a green badge.

### How the timezone is worked out

This is the important one, because it is what lets clips from different devices
line up on one axis.

Many body-worn and fleet-camera systems put a **local clock** in the filename:
`..._2026-03-28_0057.mp4` means "00:57 local on 28 March". The generator
compares that clock against the UTC time embedded in the file and works out the
offset. In this archive all 27 files agreed, giving **UTC−07:00 (PDT)**.

If your filenames carry no clock, the script says so and falls back to
UTC−07:00. Override it with:

```bash
python3 make_viewer.py /path/to/videos --tz -05:00
python3 make_viewer.py /path/to/videos --tz -5        # same thing
python3 make_viewer.py /path/to/videos --tz EST      # or a named zone
```

If you have a time zone abbreviation you would rather see in the header:

```bash
python3 make_viewer.py /path/to/videos --tz -5 --tz-label "EST (UTC-05:00)"
```

---

## 4. Options

| Flag | What it does |
|---|---|
| `--out DIR` | write the viewer somewhere other than the video folder |
| `--title TEXT` | title in the page header |
| `--source-name TEXT` | name of the archive this came from, shown under the title |
| `--tz OFFSET` | case timezone, e.g. `-7` or `-05:00` (default: read from the filenames) |
| `--tz-label TEXT` | how the timezone is labelled, e.g. `PDT (UTC-07:00)` |
| `--hash` | also compute SHA-256 for every file |
| `--no-ffprobe` | never call ffprobe |
| `--manifest-only` | write the manifest json but not the viewer (for an archive: read it in place, without unpacking) |
| `--no-extract` | for an archive: do not unpack the media (the viewer will not be able to play it) |
| `--no-readme` | do not write README.txt next to the viewer |
| `--template PATH` | use a different viewer template (default: `viewer_template.html` beside the script) |

A worked example:

```bash
python3 make_viewer.py ~/Cases/2026-04-traffic \
    --title "Case 2026-04 traffic stop" \
    --source "Case-2026-04-traffic.zip" \
    --tz -04:00 --tz-label "EDT (UTC-04:00)" \
    --hash
```

---

## 5. Adding or removing recordings

Re-run the same command against the same source. The generator rebuilds the
viewer from whatever is there now, so deleted files disappear and new ones
appear with their correct start times.

```bash
python3 make_viewer.py /path/to/videos --hash
```

If the source is an archive, re-running it re-unpacks the media over the top of
the previous build.

You can also do it **inside the viewer**, with no tooling at all: the
**Rescan** button in the header asks you to pick the folder, reads the start
time out of each MP4's `mvhd` box in the browser, re-derives the timezone from
the filenames, and rebuilds the axis, the clusters and the clip list. The result
is kept in that browser, so reloading the page keeps it.

> Browsers cannot list a folder on their own when a page is opened from disk,
> which is why Rescan asks you to pick the folder once. If the browser declines
> to offer a file (some skip names that look like duplicates, e.g. `clip_1.mp4`),
> the viewer keeps the metadata it already had and tells you, rather than
> silently dropping the item.

---

## 6. Checking the result

**Hashes.** With `--hash`, verify nothing changed:

```bash
cd /path/to/videos
sha256sum -c SHA256SUMS.txt     # Linux / macOS
certutil -hashfile <file> SHA256 # Windows, one file at a time
```

**Eyeball it.** The Inventory button in the viewer lists every file with its
start time in both case time and UTC, its duration, resolution, size and
SHA-256, and the values match `evidence-manifest.json`.

**The fastest sanity check** is that two clips taken from the same device at the
same moment land on top of each other on the timeline.

---

## 7. Optional customisation

`viewer_template.html` is the source of the viewer. It contains a single
marker, `/*__MANIFEST__*/`, where the generated data is injected; everything
else is ordinary HTML, CSS and JavaScript. A few things worth knowing:

| What | Where |
|---|---|
| the four device colours | `:root { --body: … --front: … --interior: … --audio: … }` |
| the badge wording | `KIND_LABEL` / `KIND_SHORT` |
| how many clips can play at once | `const MAX_SYNC = 12` |
| how long a clip is buffered before it is released | `const PRELOAD_LEAD = 45` (seconds) |
| how tightly the clips are held in sync | `HARD_SEEK`, `TRIM_DEAD`, `MAX_TRIM` |
| the case-time calculations | `dU()`, `fmtLocal()`, `fmtUTC()` |

To use a modified template, keep it beside `make_viewer.py` as
`viewer_template.html`, or point at it with `--template`.

---

## 8. If something looks wrong

**Clips are not lining up.** The timezone is the usual cause. Check what the
generator decided (it prints the case time on the last line) and force it with
`--tz`. A wrong offset shifts every clip by the same number of hours, which is
very visible on the axis.

**Everything is one colour / labelled "other".** The filenames do not match the
patterns in section 3. Nothing is broken — the viewer still works, the rows are
just not colour-coded. Rename them, or adjust the patterns in `classify()` in
`make_viewer.py` and `classifyName()` in the template.

**Playback stutters with several clips running.** A browser reads a `file://`
video from the start of the file, so several large recordings being read at
once saturate the disk. The viewer already keeps only the clips near the
playhead loaded, but if it still stutters, select fewer clips — or serve the
folder over HTTP from a machine that has a web server with range-request
support, which removes the problem entirely.

**Seeking inside very large files is slow.** These recordings store their index
at the *end* of the MP4 rather than the front, so the browser has to read the
tail of a file before it can start playing it. It is a property of the source
files, not the viewer. Remuxing with
`ffmpeg -i in.mp4 -c copy -movflags faststart out.mp4` puts the index at the
front and makes seeking instant — but it rewrites the evidence, so only do that
on a copy.

**A file is missing from the viewer.** Check it is really in the folder and
really has a video extension (`.mp4 .m4v .mov .m4a .webm .mkv`). The generator
prints a warning for any file whose start time it could not read.

---

## 9. What the viewer does

For reference, once built:

* every clip on one continuous absolute case-time axis, with a ruler, tick
  marks that adapt to the zoom, and cluster buttons for each group of activity
* multi-video synchronised playback from a single master clock, with per-clip
  offset nudge, per-clip audio control, and play rates from 0.25× to 4×
* an evidence-style timecode on each tile: case time, UTC and elapsed
* a file inventory with SHA-256 hashes
* a bookmark / citation log that exports to a plain text file
* horizontal scrolling of the ruler and the clip bars, so the whole archive can
  be walked through at any zoom
* the whole page is offline: no network calls, no external assets, no analytics,
  and the reviewer's selections and bookmarks stay in that browser only

---

## 10. Running the tests

The test suites drive a real headless Chrome against a built viewer. They need
`node` and `google-chrome` on the path.

```bash
node tests/cdp_bars_test.js        # bar geometry
node tests/cdp_playback_test.js    # sync accuracy, buffering, disk load
node tests/cdp_ui_test.js          # dialogs, filters, keyboard, clusters
node tests/cdp_wheel_test.js       # wheel behaviour and zoom easing
node tests/cdp_hscroll_test.js     # horizontal scrolling model
node tests/cdp_playhead_test.js    # playhead label placement
node tests/cdp_sync_test.js        # multi-video sync accuracy
node tests/cdp_rescan_test.js      # in-browser folder rescan
```

The rescan test points the folder picker at a scratch copy in `/tmp`, never at
a real evidence folder.
