#!/usr/bin/env python3
"""Repairs stale DT_INIT/DT_FINI dynamic-tag values left behind by
linuxdeploy's RUNPATH ($ORIGIN) patching step (see issue #212).

linuxdeploy rewrites every bundled library's RUNPATH so bundled copies
resolve each other via $ORIGIN instead of system paths. That rewrite
relocates where a library's legacy .init/.fini code physically lands in
the file, and correctly fixes up INIT_ARRAY/FINI_ARRAY to match -- but
leaves the legacy DT_INIT (and sometimes DT_FINI) dynamic tag pointing at
the pre-patch address. glibc calls DT_INIT unconditionally at process
startup, before any real constructor runs, so the first library to
initialize crashes immediately.

Confirmed via a real coredump: rip lands on zero-filled bytes at the
stale DT_INIT offset, while the real _init trampoline sits, untouched and
correct, at the address the section header table already reports.

Usage:
    python3 fix_appimage_dtinit.py <AppDir> [--dry-run]
"""

import struct
import sys
from pathlib import Path

DT_NULL = 0
DT_INIT = 12
DT_FINI = 13
TAG_TO_SECTION = {DT_INIT: ".init", DT_FINI: ".fini"}

ELF_MAGIC = b"\x7fELF"


def read_elf_sections(data: bytes):
    """Returns (dynamic_offset, dynamic_size, section_addr_by_name)."""
    if data[:4] != ELF_MAGIC:
        return None
    ei_class = data[4]
    ei_data = data[5]
    if ei_class != 2 or ei_data != 1:
        return None  # only handling ELFCLASS64 / little-endian, all we bundle

    (e_shoff,) = struct.unpack_from("<Q", data, 0x28)
    (e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from("<HHH", data, 0x3A)
    if e_shoff == 0 or e_shnum == 0:
        return None

    sections = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        (sh_name, sh_type) = struct.unpack_from("<II", data, off)
        (sh_addr,) = struct.unpack_from("<Q", data, off + 16)
        (sh_offset,) = struct.unpack_from("<Q", data, off + 24)
        (sh_size,) = struct.unpack_from("<Q", data, off + 32)
        sections.append((sh_name, sh_type, sh_addr, sh_offset, sh_size))

    shstrtab_off = sections[e_shstrndx][3]
    shstrtab_size = sections[e_shstrndx][4]
    shstrtab = data[shstrtab_off : shstrtab_off + shstrtab_size]

    def name_of(sh_name_off):
        end = shstrtab.index(b"\x00", sh_name_off)
        return shstrtab[sh_name_off:end].decode("ascii", "replace")

    section_addr_by_name = {}
    dynamic_offset = dynamic_size = None
    for sh_name, sh_type, sh_addr, sh_offset, sh_size in sections:
        name = name_of(sh_name)
        section_addr_by_name[name] = sh_addr
        if name == ".dynamic":
            dynamic_offset, dynamic_size = sh_offset, sh_size

    return dynamic_offset, dynamic_size, section_addr_by_name


def fix_file(path: Path, dry_run: bool) -> list[str]:
    data = path.read_bytes()
    parsed = read_elf_sections(data)
    if parsed is None:
        return []
    dynamic_offset, dynamic_size, section_addr = parsed
    if dynamic_offset is None:
        return []

    fixes = []  # (file_offset_of_value, tag, old_val, new_val)
    off = dynamic_offset
    end = dynamic_offset + dynamic_size
    while off + 16 <= end:
        d_tag, d_val = struct.unpack_from("<qQ", data, off)
        if d_tag == DT_NULL:
            break
        section_name = TAG_TO_SECTION.get(d_tag)
        if section_name is not None and d_val != 0:
            expected = section_addr.get(section_name)
            if expected is not None and expected != d_val:
                fixes.append((off + 8, d_tag, d_val, expected))
        off += 16

    if not fixes:
        return []

    lines = []
    for value_off, tag, old_val, new_val in fixes:
        tag_name = "DT_INIT" if tag == DT_INIT else "DT_FINI"
        lines.append(f"  {tag_name}: 0x{old_val:x} -> 0x{new_val:x}")

    if not dry_run:
        with path.open("r+b") as f:
            for value_off, _tag, _old_val, new_val in fixes:
                f.seek(value_off)
                f.write(struct.pack("<Q", new_val))

    return lines


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    if len(args) != 1:
        print(f"Usage: {sys.argv[0]} <AppDir> [--dry-run]", file=sys.stderr)
        sys.exit(1)

    appdir = Path(args[0])
    targets = list((appdir / "usr" / "lib").glob("*.so*"))
    desktop_bin = appdir / "usr" / "bin" / "desktop"
    if desktop_bin.exists():
        targets.append(desktop_bin)

    scanned = 0
    patched = 0
    for path in targets:
        if path.is_symlink() or not path.is_file():
            continue
        scanned += 1
        lines = fix_file(path, dry_run)
        if lines:
            patched += 1
            verb = "would patch" if dry_run else "patched"
            print(f"{verb} {path.name}:")
            for line in lines:
                print(line)

    action = "would patch" if dry_run else "patched"
    print(f"\nscanned={scanned} {action}={patched}")
    if dry_run and patched:
        sys.exit(2)  # non-zero so the build script / CI can detect remaining mismatches


if __name__ == "__main__":
    main()
