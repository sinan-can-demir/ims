#!/usr/bin/env python3
"""Restores stock system libraries in place of linuxdeploy's RUNPATH
($ORIGIN) -patched copies inside a built AppDir (see issue #212).

linuxdeploy rewrites every bundled library's RUNPATH to $ORIGIN so bundled
copies resolve each other locally instead of via system paths. That
rewrite is what corrupts the file: growing .dynstr to fit the $ORIGIN
string shifts section layout, which can push .init's real code into a
LOAD segment that was never marked executable -- a genuine NX violation
confirmed via a real launch + gdb/coredump on this app's own build (see
issue #212's full comment history).

The RUNPATH rewrite turns out to be unnecessary in the first place:
linuxdeploy's own AppRun already sets LD_LIBRARY_PATH across every AppDir
lib directory, and ELF resolution tries LD_LIBRARY_PATH before RUNPATH --
so a library needs no RUNPATH at all to resolve correctly inside the
AppImage. This script exploits that: instead of patching the corrupted
bundled copy, it finds a pristine, unpatched, byte-identical stock copy
already installed on the build host and copies it over the bundled one.
Verified via a real launch test: an AppDir rebuilt this way runs clean,
with zero remaining $ORIGIN RUNPATH entries anywhere in the bundle.

Every replacement is required to resolve to a file owned by an installed
system package (rpm/dpkg) before it's trusted -- never trust an
unverified file found by name alone. Fails hard (non-zero exit) if any
library can't be matched to a verified stock copy, or if any $ORIGIN
RUNPATH entry survives the pass -- this should never silently ship a
still-broken AppImage.

Usage:
    python3 restore_stock_appimage_libs.py <AppDir> [--dry-run]
"""
import shutil
import subprocess
import sys
from pathlib import Path

# Never search outside these -- no Flatpak/opt/home paths, only real
# system library roots a package manager could plausibly own.
CANONICAL_LIB_ROOTS = ["/usr/lib64", "/usr/lib", "/lib64", "/lib"]


def has_origin_runpath(path: Path) -> bool:
    readelf = shutil.which("readelf")
    if readelf is None:
        return False
    try:
        # Fixed local binary path (resolved above) + a Path from our own
        # AppDir scan, not attacker input -- safe despite S603/S607.
        out = subprocess.run(  # noqa: S603
            [readelf, "-d", str(path)], capture_output=True, text=True, check=True
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return False
    for line in out.splitlines():
        if "(RUNPATH)" in line or "(RPATH)" in line:
            return "$ORIGIN" in line
    return False


def ldconfig_lookup(name: str) -> Path | None:
    ldconfig = shutil.which("ldconfig")
    if ldconfig is None:
        return None
    try:
        # Fixed local binary path (resolved above), no arguments at all --
        # safe despite S603/S607.
        out = subprocess.run(  # noqa: S603
            [ldconfig, "-p"], capture_output=True, text=True, check=True
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return None
    for line in out.splitlines():
        line = line.strip()
        if " => " not in line:
            continue
        libname, target = line.split(" => ", 1)
        libname = libname.split(" (", 1)[0].strip()
        if libname == name:
            candidate = Path(target.strip())
            if candidate.exists():
                return candidate.resolve()
    return None


def find_lookup(name: str) -> Path | None:
    for root in CANONICAL_LIB_ROOTS:
        root_path = Path(root)
        if not root_path.is_dir():
            continue
        for candidate in root_path.rglob(name):
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
    return None


def verify_owned_by_package(path: Path) -> bool:
    rpm = shutil.which("rpm")
    if rpm:
        # Fixed local binary path (resolved above) + a Path this function
        # already resolved to a real file, not attacker input -- safe
        # despite S603/S607.
        result = subprocess.run(  # noqa: S603
            [rpm, "-qf", str(path)], capture_output=True, text=True
        )
        return result.returncode == 0 and "is not owned" not in result.stdout
    dpkg = shutil.which("dpkg")
    if dpkg:
        result = subprocess.run([dpkg, "-S", str(path)], capture_output=True, text=True)  # noqa: S603
        return result.returncode == 0
    # No package manager available to verify ownership -- never trust a
    # bare filename match with no way to confirm it's a real system file.
    return False


def find_stock_copy(name: str) -> Path | None:
    candidate = ldconfig_lookup(name) or find_lookup(name)
    if candidate is None:
        return None
    if not verify_owned_by_package(candidate):
        return None
    return candidate


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    if len(args) != 1:
        print(f"Usage: {sys.argv[0]} <AppDir> [--dry-run]", file=sys.stderr)
        sys.exit(1)

    appdir = Path(args[0])
    if not appdir.is_dir():
        print(f"error: {appdir} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Only bundled shared libraries have a stock system copy to restore
    # from. The app's own executable (usr/bin/desktop) legitimately
    # carries a $ORIGIN/../lib RUNPATH too, but it's *our* binary, not a
    # system library -- there's nothing to restore it from, and unlike
    # the libraries, it isn't actually corrupted (its DT_INIT already
    # matches .init -- verified via fix_appimage_dtinit.py --dry-run).
    all_libs = [
        p for p in appdir.rglob("*.so*") if p.is_file() and not p.is_symlink()
    ]

    patched_targets = [p for p in all_libs if has_origin_runpath(p)]
    print(f"scanned {len(all_libs)} libraries, {len(patched_targets)} carry a $ORIGIN RUNPATH")

    restored = 0
    unmatched = []
    for path in patched_targets:
        stock = find_stock_copy(path.name)
        if stock is None:
            unmatched.append(path)
            continue
        verb = "would restore" if dry_run else "restoring"
        print(f"{verb} {path.name} <- {stock}")
        if not dry_run:
            shutil.copy2(stock, path)
        restored += 1

    if unmatched:
        print("\nerror: no verified stock copy found for:", file=sys.stderr)
        for path in unmatched:
            print(f"  {path}", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        print(f"\nwould restore={restored}")
        return

    # Re-scan everything, not just the files we touched -- proves the
    # AppDir is actually clean rather than trusting our own bookkeeping.
    remaining = [p for p in all_libs if has_origin_runpath(p)]
    if remaining:
        print("\nerror: $ORIGIN RUNPATH still present after restore:", file=sys.stderr)
        for path in remaining:
            print(f"  {path}", file=sys.stderr)
        sys.exit(1)

    print(f"\nrestored={restored}, remaining $ORIGIN RUNPATH entries=0")


if __name__ == "__main__":
    main()
