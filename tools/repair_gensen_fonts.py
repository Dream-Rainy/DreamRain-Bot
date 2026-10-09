"""Rebuild browser-compatible TW fonts from the bundled GenSen TTCs.

The overflowing format-4 cmap is redundant with the intact format-12 cmap.
Keep the original glyphs, names, metrics and layout tables, including OFL metadata.
Run with --check to verify the bundled outputs without writing files.
"""

import argparse
import io
import struct
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.ttLib.sfnt import SFNTWriter

FONTS = (
    Path(__file__).resolve().parents[1]
    / "src/plugins/chiffon_bot/shared/render_templates/fonts/GenSenRounded2-ttc"
)
WEIGHTS = ("EL", "L", "R", "M", "B", "H")


def repair_cmap(raw: bytes) -> bytes:
    records = []
    removed = 0
    for index in range(struct.unpack_from(">H", raw, 2)[0]):
        platform, encoding, offset = struct.unpack_from(">HHI", raw, 4 + index * 8)
        fmt = struct.unpack_from(">H", raw, offset)[0]
        length_offset = 2 if fmt < 8 or fmt == 14 else 4
        length = struct.unpack_from(">H" if fmt < 8 else ">I", raw, offset + length_offset)[0]
        if fmt == 4 and length < 16 + 8 * (struct.unpack_from(">H", raw, offset + 6)[0] // 2):
            removed += 1
            continue
        if offset + length > len(raw):
            raise ValueError("cmap subtable extends beyond its table")
        records.append((platform, encoding, raw[offset : offset + length]))
    if not removed or not any(struct.unpack_from(">H", blob)[0] == 12 for _, _, blob in records):
        raise ValueError("Expected broken format-4 and intact format-12 cmap")
    header = bytearray(struct.pack(">HH", 0, len(records)))
    body = bytearray()
    offsets = {}
    for platform, encoding, blob in records:
        if blob not in offsets:
            offsets[blob] = 4 + 8 * len(records) + len(body)
            body.extend(blob)
        header.extend(struct.pack(">HHI", platform, encoding, offsets[blob]))
    return bytes(header + body)


def rebuild(source: Path, weight: str) -> bytes:
    with TTFont(source, fontNumber=0, lazy=True) as original:
        if original["name"].getDebugName(6) != f"GenSenRounded2TW-{weight}":
            raise ValueError(f"Unexpected TW face: {source}")
        tables = {tag: original.reader[tag] for tag in original.reader.keys()}
        tables["cmap"] = repair_cmap(tables["cmap"])
        stream = io.BytesIO()
        writer = SFNTWriter(stream, len(tables), original.sfntVersion)
        for tag, data in sorted(tables.items()):
            writer[tag] = data
        writer.close()
        result = stream.getvalue()
        with TTFont(io.BytesIO(result), lazy=True) as repaired:
            before = {cp: original.getGlyphID(name) for cp, name in original.getBestCmap().items()}
            after = {cp: repaired.getGlyphID(name) for cp, name in repaired.getBestCmap().items()}
            if before != after or original["maxp"].numGlyphs != repaired["maxp"].numGlyphs:
                raise ValueError(f"Glyph mapping changed: {source}")
            for tag in tables.keys() - {"cmap", "head"}:
                if original.reader[tag] != repaired.reader[tag]:
                    raise ValueError(f"Original {tag} table changed: {source}")
            print(f"{weight}: {len(before)} codepoints, {repaired['maxp'].numGlyphs} glyphs; original tables verified")
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify generated files without writing")
    args = parser.parse_args()
    for weight in WEIGHTS:
        result = rebuild(FONTS / f"GenSenRounded2-{weight}.ttc", weight)
        target = FONTS / f"GenSenRounded2-TW-{weight}.ttf"
        if args.check:
            if target.read_bytes() != result:
                raise ValueError(f"Generated font differs: {target}")
        else:
            target.write_bytes(result)


if __name__ == "__main__":
    main()
