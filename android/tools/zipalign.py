#!/usr/bin/env python3
"""Minimal zipalign: rewrites an APK so every uncompressed entry's data starts on a 4-byte
boundary (4096 for .so), using the same 0xD935 alignment extra field as Android's zipalign.
`zipalign.py --check file.apk` only verifies."""
import struct
import sys
import zipfile


def alignment(name):
    return 4096 if name.endswith('.so') else 4


def align(src, dst):
    with zipfile.ZipFile(src) as zin, open(dst, 'wb') as f, zipfile.ZipFile(f, 'w') as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            out = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            out.compress_type = info.compress_type
            out.external_attr = info.external_attr
            if info.compress_type == zipfile.ZIP_STORED:
                al = alignment(info.filename)
                header = 30 + len(info.filename.encode('utf-8')) + 6
                pad = (-(f.tell() + header)) % al
                out.extra = struct.pack('<HHH', 0xD935, 2 + pad, al) + b'\0' * pad
            zout.writestr(out, data)


def check(path):
    bad = []
    with open(path, 'rb') as raw, zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.compress_type != zipfile.ZIP_STORED:
                continue
            raw.seek(info.header_offset)
            hdr = raw.read(30)
            n, e = struct.unpack('<HH', hdr[26:30])
            start = info.header_offset + 30 + n + e
            if start % alignment(info.filename):
                bad.append((info.filename, start))
    for name, off in bad:
        print(f'misaligned: {name} @ {off}')
    print('alignment ok' if not bad else f'{len(bad)} misaligned entries')
    return not bad


if __name__ == '__main__':
    if sys.argv[1] == '--check':
        sys.exit(0 if check(sys.argv[2]) else 1)
    align(sys.argv[1], sys.argv[2])
