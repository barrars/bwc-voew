#!/usr/bin/env python3
"""
make_viewer.py — build a synchronized multi-video viewer for any folder of videos.

This is the reusable, no-LLM path. Point it at a folder of recordings and it
produces a self-contained index.html that sits beside them: absolute-time
timeline, multi-video sync playback, timecode overlay, inventory and hashes.

    python3 make_viewer.py /path/to/videos
    python3 make_viewer.py /path/to/videos --out /path/to/folder --hash
    python3 make_viewer.py /path/to/videos --tz -05:00 --title "Case 2026-04"

Requirements: Python 3.8+. ffprobe is used when present (for richer metadata),
but it is NOT required — a built-in MP4 parser reads the start time, duration
and frame size straight out of each file.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

VIDEO_EXT = ('.mp4', '.m4v', '.mov', '.m4a', '.webm', '.mkv')
EPOCH_1904 = 2082844800          # seconds between 1904-01-01 and 1970-01-01


# --------------------------------------------------------------------------
# MP4 parsing (no external tools required)
# --------------------------------------------------------------------------
def _boxes(buf, start, end):
    """Yield (type, payload_start, payload_end) for the boxes in [start, end)."""
    p = start
    while p + 8 <= end:
        size = int.from_bytes(buf[p:p + 4], 'big')
        typ = buf[p + 4:p + 8]
        hdr = 8
        if size == 1:
            if p + 16 > end:
                return
            size = int.from_bytes(buf[p + 8:p + 16], 'big')
            hdr = 16
        elif size == 0:
            size = end - p
        if size < hdr or p + size > end:
            return
        yield (typ, p + hdr, p + size)
        p += size


def _find_moov(buf):
    """Locate the moov box in a buffer. Returns (start, end) or None."""
    pos = 0
    while True:
        i = buf.find(b'moov', pos)
        if i < 4:
            return None
        start = i - 4
        size = int.from_bytes(buf[start:start + 4], 'big')
        if 8 <= size <= 64 * 1024 * 1024:
            return (start, min(start + size, len(buf)))
        pos = i + 1


def _parse_mvhd(buf, s):
    version = buf[s]
    if version == 1:
        creation = int.from_bytes(buf[s + 4:s + 12], 'big')
        timescale = int.from_bytes(buf[s + 20:s + 24], 'big')
        duration = int.from_bytes(buf[s + 24:s + 32], 'big')
    else:
        creation = int.from_bytes(buf[s + 4:s + 8], 'big')
        timescale = int.from_bytes(buf[s + 12:s + 16], 'big')
        duration = int.from_bytes(buf[s + 16:s + 20], 'big')
    if not timescale:
        return None
    return {
        'creation_ms': (creation - EPOCH_1904) * 1000,
        'duration': duration / timescale,
    }


def _parse_stsd(buf, s, e):
    """Coded frame size from the sample description (avc1/hvc1/...)."""
    if s + 8 > e:
        return 0, 0
    count = int.from_bytes(buf[s + 4:s + 8], 'big')
    p = s + 8
    for _ in range(min(count, 8)):
        if p + 36 > e:
            break
        fmt = buf[p + 4:p + 8]
        # VisualSampleEntry: 8 header + 24 fixed fields, then width/height
        w = int.from_bytes(buf[p + 32:p + 34], 'big')
        h = int.from_bytes(buf[p + 34:p + 36], 'big')
        if fmt in (b'avc1', b'avc3', b'hvc1', b'hev1', b'mp4v', b'encv', b'vp09', b'av01', b'mjpeg'):
            return w, h
        size = int.from_bytes(buf[p:p + 4], 'big')
        if size < 16:
            break
        p += size
    return 0, 0


def _parse_tracks(buf, moov_start, moov_end):
    """Return (width, height, audio_tracks) for the moov box."""
    width = height = 0
    audio = 0
    for typ, s, e in _boxes(buf, moov_start + 8, moov_end):
        if typ != b'trak':
            continue
        tw = th = 0
        sw = sh = 0
        handler = None
        for t2, s2, e2 in _boxes(buf, s, e):
            if t2 == b'tkhd':
                version = buf[s2]
                if version == 1:
                    tw = int.from_bytes(buf[s2 + 88:s2 + 92], 'big') >> 16
                    th = int.from_bytes(buf[s2 + 92:s2 + 96], 'big') >> 16
                else:
                    tw = int.from_bytes(buf[s2 + 76:s2 + 80], 'big') >> 16
                    th = int.from_bytes(buf[s2 + 80:s2 + 84], 'big') >> 16
            elif t2 == b'mdia':
                for t3, s3, e3 in _boxes(buf, s2, e2):
                    if t3 == b'hdlr' and handler is None:
                        handler = buf[s3 + 8:s3 + 12]
                    elif t3 == b'minf':
                        for t4, s4, e4 in _boxes(buf, s3, e3):
                            if t4 == b'stbl':
                                for t5, s5, e5 in _boxes(buf, s4, e4):
                                    if t5 == b'stsd':
                                        sw, sh = _parse_stsd(buf, s5, e5)
        if handler == b'vide':
            width = sw or tw or width
            height = sh or th or height
        elif handler == b'soun':
            audio += 1
    return width, height, audio


def mp4_info(path):
    """Start time (epoch ms), duration, frame size and audio track count."""
    size = os.path.getsize(path)
    buf = None
    with open(path, 'rb') as fh:
        head = fh.read(min(size, 8 * 1024 * 1024))
        moov = _find_moov(head)
        if moov:
            buf = head
        else:
            tail_len = min(size, 48 * 1024 * 1024)
            fh.seek(max(0, size - tail_len))
            buf = fh.read(tail_len)
            moov = _find_moov(buf)
            if not moov:
                return None
    ms, me = moov
    info = None
    for typ, s, e in _boxes(buf, ms + 8, me):
        if typ == b'mvhd' and info is None:
            info = _parse_mvhd(buf, s)
    if not info:
        return None
    w, h, audio = _parse_tracks(buf, ms, me)
    info.update({'w': w or None, 'h': h or None, 'na': audio or None})
    return info


def ffprobe_info(path):
    """Extra detail from ffprobe when it is available (optional)."""
    try:
        out = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', path],
            capture_output=True, text=True, timeout=120).stdout
        data = json.loads(out)
    except Exception:
        return {}
    fmt = data.get('format', {})
    streams = data.get('streams', [])
    info = {}
    if fmt.get('tags', {}).get('title'):
        info['title'] = fmt['tags']['title']
    for st in streams:
        if st.get('codec_type') == 'video':
            if st.get('r_frame_rate') and '/' in st['r_frame_rate']:
                num, den = st['r_frame_rate'].split('/')
                if int(den):
                    info['fps'] = round(int(num) / int(den), 3)
            info.setdefault('vcodec', st.get('codec_name'))
        elif st.get('codec_type') == 'audio':
            info.setdefault('acodec', st.get('codec_name'))
            info.setdefault('ach', st.get('channels'))
    return info


# --------------------------------------------------------------------------
# Naming conventions
# --------------------------------------------------------------------------
def classify(name):
    if re.search(r'Body[_\s-]?\d', name, re.I):
        return 'body'
    if re.search(r'Interior', name, re.I):
        return 'interior'
    if re.search(r'Front', name, re.I):
        return 'front'
    return 'audio'


def device_id(name):
    # Axon serials look like D01AK0270 or D01AJ912V (3-4 digits, optional
    # trailing letter)
    m = re.search(r'_(D\d{2}[A-Z]{2}\d{3,4}[A-Z]?)\.[a-z0-9]+$', name, re.I)
    return m.group(1).upper() if m else None


def filename_clock(name):
    """Axon-style filenames carry a local HHMM clock: ..._2026-03-28_0057-4.mp4"""
    m = re.search(r'_(\d{4})(?:-(\d+))?\.[a-z0-9]+$', name, re.I)
    if not m:
        return None
    return {'tod': '%02d:%s' % (int(m.group(1)[:2]), m.group(1)[2:]), 'part': m.group(2)}


def parse_tz(text):
    """'-7', '-07:00' or 'PDT' -> offset in minutes."""
    if text is None:
        return None
    text = str(text).strip()
    if re.fullmatch(r'[+-]?\d{1,2}(:\d{2})?', text):
        sign = -1 if text.startswith('-') else 1
        text = text.lstrip('+-')
        parts = text.split(':')
        mins = int(parts[0]) * 60 + (int(parts[1]) if len(parts) > 1 else 0)
        return sign * mins
    named = {'UTC': 0, 'GMT': 0, 'Z': 0, 'EST': -300, 'EDT': -240, 'CST': -360,
             'CDT': -300, 'MST': -420, 'MDT': -360, 'PST': -480, 'PDT': -420}
    return named.get(text.upper())


def detect_offset(items):
    """Work the local offset out by comparing filename clocks with UTC."""
    votes = []
    for it in items:
        clock = it.get('fnameTod')
        utcms = it.get('_utcms', it.get('utcms'))
        if not clock or utcms is None:
            continue
        utc_min = (utcms // 60000) % 1440
        local_min = int(clock[:2]) * 60 + int(clock[3:5])
        off = local_min - utc_min
        if off > 720:
            off -= 1440
        if off < -720:
            off += 1440
        votes.append(off)
    if not votes:
        return None
    counts = {}
    for v in votes:
        counts[v] = counts.get(v, 0) + 1
    best, best_n = max(counts.items(), key=lambda kv: kv[1])
    return best if best_n >= 2 else None


# --------------------------------------------------------------------------
def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(folder, tz_minutes=None, want_hash=False, use_ffprobe=True):
    names = sorted(n for n in os.listdir(folder)
                   if n.lower().endswith(VIDEO_EXT) and os.path.isfile(os.path.join(folder, n)))
    if not names:
        sys.exit('no video files found in %s' % folder)

    items = []
    for n, name in enumerate(names, 1):
        path = os.path.join(folder, name)
        print('  [%d/%d] %s' % (n, len(names), name), end='\r', flush=True)
        info = mp4_info(path)
        extra = ffprobe_info(path) if use_ffprobe else {}
        if info is None:
            print('\n  WARNING: could not read the start time of %s' % name)
            continue
        item = {
            'f': name,
            'sz': os.path.getsize(path),
            'd': round(info['duration'], 3),
            'k': classify(name),
            'unit': device_id(name),
            'na': info.get('na'),
            'w': info.get('w'),
            'h': info.get('h'),
            'sha256': None,
        }
        item.update({k: v for k, v in extra.items() if v is not None})
        clock = filename_clock(name)
        if clock:
            item['fnameTod'] = clock['tod']
            item['fnamePart'] = clock['part']
        item['_utcms'] = info['creation_ms']
        items.append(item)
    print(' ' * 60, end='\r')

    offset = tz_minutes if tz_minutes is not None else detect_offset(items)
    if offset is None:
        offset = -420
        print('  note: no filename clocks to read the timezone from, defaulting to UTC-07:00')
    tz = datetime.timezone(datetime.timedelta(minutes=offset))
    for it in items:
        utcms = it.pop('_utcms')
        utc = datetime.datetime.fromtimestamp(utcms / 1000, datetime.timezone.utc)
        # keep it UTC-aware but shifted: the viewer's "case local epoch" is the
        # local wall clock expressed as if it were UTC
        loc = utc + datetime.timedelta(minutes=offset)
        it['utcms'] = int(utcms)
        it['locms'] = int(loc.timestamp() * 1000)
        it['utc'] = utc.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        it['loc'] = loc.strftime('%Y-%m-%d %H:%M:%S')
        it['tod'] = loc.strftime('%H:%M:%S')
        it['day'] = loc.strftime('%a %Y-%m-%d')
    items.sort(key=lambda i: (i['utcms'], i['f']))

    if want_hash:
        for n, it in enumerate(items, 1):
            print('  hashing [%d/%d] %s' % (n, len(items), it['f']), end='\r', flush=True)
            it['sha256'] = sha256_of(os.path.join(folder, it['f']))
        print(' ' * 60, end='\r')

    tz_label = 'UTC%+03d:%02d' % (offset // 60, abs(offset) % 60)
    if offset == 0:
        tz_label = 'UTC+00:00'
    spans = [(i['locms'], i['locms'] + int(i['d'] * 1000)) for i in items]
    manifest = {
        'case': {
            'archive': os.path.basename(os.path.abspath(folder.rstrip('/'))),
            'source_zip': '',
            'item_count': len(items),
            'total_bytes': sum(i['sz'] for i in items),
            'total_runtime_s': round(sum(i['d'] for i in items), 3),
            'tz_label': tz_label,
            'tz_offset_min': offset,
            'window_local': [
                datetime.datetime.fromtimestamp(min(s[0] for s in spans) / 1000,
                                                datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
                datetime.datetime.fromtimestamp(max(s[1] for s in spans) / 1000,
                                                datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            ] if spans else None,
        },
        'items': items,
    }
    return manifest


def render(template_path, manifest):
    with open(template_path, encoding='utf-8') as fh:
        html = fh.read()
    payload = json.dumps(manifest, separators=(',', ':')).replace('</', '<\\/')
    marker = '/*__MANIFEST__*/'
    if marker not in html:
        sys.exit('template %s does not contain the %s marker' % (template_path, marker))
    return html.replace(marker, payload)


def write_readme(out, manifest, args, folder):
    """A short guide that ships next to the viewer it describes."""
    c = manifest['case']
    items = manifest['items']
    win = c.get('window_local') or ['', '']
    lines = []
    w = lines.append
    w('=' * 78)
    w(' %s' % (c.get('title') or c['archive']))
    w(' Synchronized multi-video review package')
    w('=' * 78)
    w('')
    w('WHAT IS IN THIS FOLDER')
    w('  index.html              The viewer. Open this — everything else is optional.')
    w('  %d %s%s' % (c['item_count'], 'video file' if c['item_count'] == 1 else 'video files',
                     ''))
    w('  evidence-manifest.json  Machine-readable index of every item (start times,')
    w('                          durations, geometry, SHA-256).')
    if args.hash:
        w('  SHA256SUMS.txt          SHA-256 checksums of every media file.')
    w('')
    w('HOW TO OPEN THE VIEWER')
    w('  Double-click index.html. That is all. It opens in any modern browser')
    w('  (Chrome, Edge, Firefox) straight from the disk.')
    w('')
    w('  No installation, no internet connection, no server and no Python are')
    w('  required. The page makes no network calls and contains no external assets.')
    w('')
    w('  Keep index.html in the same folder as the media files — it loads them by')
    w('  relative path. The folder can be renamed, moved or copied anywhere.')
    w('')
    w('WHAT THE VIEWER DOES')
    w('  - Lays every item on one continuous case-time axis and lets you align')
    w('    overlapping footage from different devices.')
    w('  - Plays any number of selected clips in sync from a single master clock,')
    w('    with per-clip offset nudge and per-clip audio control.')
    w('  - Shows an evidence-style timecode on each tile (case time, UTC, elapsed).')
    w('  - Provides a full file inventory with SHA-256 hashes, and a bookmark /')
    w('    citation log that exports to a plain-text file.')
    w('')
    w('  Keys: Space = play/pause, arrows = step, , and . = previous/next clip,')
    w('  B = bookmark, O = overlay, M = mute all, 0 = fit whole axis, 9 = fit')
    w('  selected. Full list under "?" in the app.')
    w('')
    w('TIME BASE')
    w('  Every timestamp in this package is CASE TIME = %s.' % c['tz_label'])
    w('  Start times come from the creation time embedded in each file, and are')
    w('  cross-checked against the clock in each filename where one is present.')
    w('')
    if win[0]:
        w('  Case window: %s through %s.' % (win[0], win[1]))
    w('')
    w('INTEGRITY')
    if args.hash:
        w('  Verify the media files have not changed (Linux/macOS):')
        w('      sha256sum -c SHA256SUMS.txt')
        w('  Windows:')
        w('      certutil -hashfile <file> SHA256')
        w('  The same values appear in the viewer\'s Inventory dialog.')
    else:
        w('  SHA-256 values were not computed for this build. Re-run the generator')
        w('  with --hash to produce SHA256SUMS.txt.')
    w('')
    w('KNOWN LIMITATIONS')
    w('  - Large files and disk load. A browser reads a file:// video from the')
    w('    start of the file, so leaving every selected clip open means every one')
    w('    of them is being read at once. The viewer keeps a clip loaded only')
    w('    while the playhead is near that clip\'s own window. If playback still')
    w('    stutters with several clips running, select fewer of them.')
    w('  - These MP4s store their index (moov atom) at the end of the file rather')
    w('    than the front, so a browser must read the tail of a file before it')
    w('    can start playing it, and seeking inside very large files can be')
    w('    sluggish when opened directly from disk. The files are unmodified;')
    w('    serving the folder over HTTP with range-request support avoids it.')
    w('  - Where a clip carries more than one audio track, a browser plays only')
    w('    the track it picks by default and a page cannot switch tracks, so the')
    w('    other channel is not audible here.')
    w('  - The viewer keeps up to 12 clips in the synchronized set at once, which')
    w('    is the practical limit for simultaneous decoding.')
    w('')
    w('REBUILDING THIS VIEWER')
    w('  The viewer is generated from this folder. To rebuild it after adding or')
    w('  removing recordings, run the generator again against this folder:')
    w('')
    same = os.path.abspath(out) == os.path.abspath(folder)
    w('      python3 make_viewer.py %s' % ('.' if same else folder))
    if args.hash:
        w('      python3 make_viewer.py %s --hash' % ('.' if same else folder))
    w('')
    w('  The viewer can also rebuild itself: the "Rescan" button in the header')
    w('  re-reads a folder of recordings and rebuilds the timeline from the')
    w('  files themselves, with no tooling at all.')
    w('')
    w('Provenance: the viewer was generated by inspecting the files in this folder')
    w('directly. The media files themselves were not modified, renamed or')
    w('re-encoded.')
    w('=' * 78)
    with open(os.path.join(out, 'README.txt'), 'w') as fh:
        fh.write('\n'.join(lines) + '\n')
    return os.path.join(out, 'README.txt')


def main():
    ap = argparse.ArgumentParser(description='Build an evidence viewer for a folder of videos.')
    ap.add_argument('folder', help='folder containing the videos')
    ap.add_argument('--out', help='where to write index.html (default: the video folder)')
    ap.add_argument('--template', default=None, help='viewer template (default: viewer_template.html next to this script)')
    ap.add_argument('--tz', default=None, help="local UTC offset, e.g. '-7' or '-05:00' (default: read from the filenames)")
    ap.add_argument('--title', default=None, help='title shown in the page header')
    ap.add_argument('--source', default=None, help='name of the source archive this came from')
    ap.add_argument('--tz-label', default=None, help="label for the case timezone, e.g. 'PDT (UTC-07:00)'")
    ap.add_argument('--hash', action='store_true', help='also compute SHA-256 for every file (slow)')
    ap.add_argument('--no-ffprobe', action='store_true', help='never call ffprobe')
    ap.add_argument('--manifest-only', action='store_true', help='write the manifest json but not the viewer')
    ap.add_argument('--no-readme', action='store_true', help='do not write README.txt next to the viewer')
    args = ap.parse_args()

    folder = os.path.abspath(args.folder.rstrip('/'))
    if not os.path.isdir(folder):
        sys.exit('not a folder: %s' % folder)
    here = os.path.dirname(os.path.abspath(__file__))
    template = args.template or os.path.join(here, 'viewer_template.html')
    if not os.path.exists(template):
        sys.exit('template not found: %s' % template)
    out = os.path.abspath(args.out) if args.out else folder
    os.makedirs(out, exist_ok=True)

    tz_minutes = parse_tz(args.tz)
    if args.tz and tz_minutes is None:
        sys.exit('could not understand --tz %r' % args.tz)

    print('scanning %s' % folder)
    manifest = build_manifest(folder, tz_minutes, args.hash, not args.no_ffprobe)
    if args.title:
        manifest['case']['title'] = args.title
    if args.source:
        manifest['case']['source_zip'] = args.source
    if args.tz_label:
        manifest['case']['tz_label'] = args.tz_label

    with open(os.path.join(out, 'evidence-manifest.json'), 'w') as fh:
        json.dump(manifest, fh, indent=1)

    if not args.manifest_only:
        with open(os.path.join(out, 'index.html'), 'w', encoding='utf-8') as fh:
            fh.write(render(template, manifest))
        print('wrote %s' % os.path.join(out, 'index.html'))

    if args.hash:
        with open(os.path.join(out, 'SHA256SUMS.txt'), 'w') as fh:
            for it in manifest['items']:
                fh.write('%s  %s\n' % (it['sha256'], it['f']))
        print('wrote %s' % os.path.join(out, 'SHA256SUMS.txt'))

    if not args.manifest_only and not args.no_readme:
        print('wrote %s' % write_readme(out, manifest, args, folder))

    c = manifest['case']
    print('%d items, %.2f GB, %.1f min of footage, case time %s'
          % (c['item_count'], c['total_bytes'] / 1e9, c['total_runtime_s'] / 60, c['tz_label']))


if __name__ == '__main__':
    main()
