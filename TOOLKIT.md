# Toolkit map

| File | What it is |
|---|---|
| `make_viewer.py` | the generator: reads a folder of recordings and writes the viewer, the manifest, the README and the checksums |
| `viewer_template.html` | the viewer source. The generator injects the manifest at the `/*__MANIFEST__*/` marker |
| `REPLICATE.md` | **the guide**: how to build a viewer for another folder of videos |
| `README.md` | the entry point |
| `tests/` | browser test suites (not tracked in git — see below) |

## Running the generator

```bash
python3 make_viewer.py /path/to/videos --hash
```

Full option list: `python3 make_viewer.py --help`, and see
[REPLICATE.md](REPLICATE.md) for what the options mean and how the timezone is
worked out.

## What it writes

Into the video folder (or `--out`):

| File | |
|---|---|
| `index.html` | the viewer. Self-contained; opens by double-click, no server needed |
| `evidence-manifest.json` | machine-readable index: start times, durations, geometry, hashes |
| `README.txt` | a short guide describing that particular archive |
| `SHA256SUMS.txt` | checksums, with `--hash` |

## Tests

The suites drive a real headless Chrome over the DevTools protocol against a
built viewer. They need `node` and `google-chrome` on the path.

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

The test suites are not tracked in git — they are development tooling rather
than part of the deliverable. To start tracking them, remove the `tests/`
line from `.gitignore` and `git add tests/`.
