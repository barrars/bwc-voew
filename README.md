# Evidence viewer

A generator that turns a folder of recordings into a self-contained,
synchronized multi-video viewer: one continuous case-time timeline, footage
from different devices lined up frame-for-frame, and an evidence-style
timecode on every tile.

Nothing in the output needs a server, a network connection, Python or anything
else installed — the reviewer double-clicks `index.html` and it works.

**→ [REPLICATE.md](REPLICATE.md) is the full guide: how to build one for
another folder of videos, what the options do, and how to check the result.**

## Quick start

```bash
python3 make_viewer.py /path/to/videos --hash
```

That writes `index.html`, `evidence-manifest.json`, `README.txt` and (with
`--hash`) `SHA256SUMS.txt` into the video folder.

It also takes an archive:

```bash
python3 make_viewer.py Evidence-27items-2026-10-20.zip
```

The start times are read from inside the archive without unpacking it, and the
recordings are then unpacked next to the viewer so it can play them.

## What is in this repository

| | |
|---|---|
| `make_viewer.py` | the generator. Reads each file's start time, duration and frame size out of the MP4 boxes, works out the case timezone, and writes the viewer |
| `viewer_template.html` | the viewer itself, with a `/*__MANIFEST__*/` marker where the generated data is injected |
| `REPLICATE.md` | how to replicate this for another folder of videos |
| `TOOLKIT.md` | a map of the toolkit and how to run the tests |

The viewer, the generator and the instructions are the whole repository. Media
files, archives and generated output are deliberately not tracked — see
`.gitignore`.

## Requirements

* **Python 3.8+** to run the generator.
* **ffprobe** is optional. When present it is used for extra detail; the start
  times, durations and frame sizes are read out of the MP4 boxes either way.
* **A browser** to view the result. Any current Chrome, Edge or Firefox.

## Licence

The viewer and generator are yours to adapt. If you change
`viewer_template.html`, keep the `/*__MANIFEST__*/` marker where the data is
injected.
