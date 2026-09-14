#! /usr/bin/env bash
# Makes the AppImage's bundled WebKitNetworkProcess/WebKitWebProcess
# helpers reachable on distros whose webkit2gtk libexec path differs from
# the one baked into libwebkit2gtk.so at compile time (see issue #336).
#
# WebKitGTK's process launcher (Source/WebKit/Shared/glib/
# ProcessExecutablePathGLib.cpp, findWebKitProcess()) resolves the helper
# binary path via WEBKIT_EXEC_PATH or the running executable's own
# directory, but ONLY when webkit2gtk was built with
# ENABLE(DEVELOPER_MODE) -- which no distro's shipped package is. Every
# real-world webkit2gtk build (Fedora's rpm, Ubuntu's deb, ...)
# unconditionally falls through to the compile-time PKGLIBEXECDIR
# constant, with no runtime override at all. Confirmed against WebKit's
# own upstream source, and confirmed live: an AppImage built on Ubuntu CI
# (whose libwebkit2gtk.so expects
# /usr/lib/x86_64-linux-gnu/webkit2gtk-4.1) crashes on launch on Fedora
# (which only has /usr/libexec/webkit2gtk-4.1) with "Unable to spawn... No
# such file or directory" -- the bundled helper binaries are sitting right
# there in the AppDir, just not at the one absolute path the library will
# ever look at.
#
# linuxdeploy always bundles those helpers at $APPDIR + <the exact same
# path libwebkit2gtk.so was compiled to expect>, since it copies the
# build host's own webkit2gtk install tree verbatim. So the fix doesn't
# need to know that path in advance -- it's whatever directory
# WebKitNetworkProcess actually landed in under $APPDIR, with the
# "$APPDIR" prefix stripped back off.
#
# The fix: bind-mount that bundled directory over its own absolute path,
# inside a private, unprivileged mount namespace (bwrap/bubblewrap -- the
# same unprivileged-userns mechanism Flatpak's sandbox relies on), so
# from inside that namespace the hardcoded PKGLIBEXECDIR path resolves to
# our bundled copy instead of "does not exist on this host" or (worse) a
# same-named but ABI-incompatible system package.
#
# If bwrap isn't installed, or user namespaces are disabled (some
# hardened kernels), this is skipped and the app launches exactly as
# before -- unchanged behavior, not a new hard dependency.

# Immutable-/usr distros (Fedora among them: /usr/lib is 0555, not even
# root can mkdir into it) refuse to create a brand-new subdirectory under
# an existing real one via a plain bind -- "Can't mkdir parents for
# <target>: Permission denied", even inside an otherwise-unprivileged
# bwrap namespace, because bwrap has to materialize that missing
# directory node on the real (bound) filesystem before it can mount onto
# it. The fix: replace the missing path's *parent* wholesale with a fresh
# tmpfs (an in-memory directory only this sandbox sees, never touching
# the real host disk), then bind every one of that parent's real entries
# back into place so nothing already there is lost -- and only then add
# our new entry, which now lands in a writable tmpfs instead of a
# real, permission-denying directory.
if [ -z "${IMS_APPIMAGE_WEBKIT_BWRAP_DONE:-}" ] && command -v bwrap >/dev/null 2>&1; then
    webkit_helper="$(find "$APPDIR/usr" -maxdepth 4 -type f -name WebKitNetworkProcess 2>/dev/null | head -1)"
    if [ -n "$webkit_helper" ]; then
        bundled_execdir="$(dirname "$webkit_helper")"
        target_execdir="${bundled_execdir#"$APPDIR"}"
        if [ -n "$target_execdir" ] && [ "$target_execdir" != "$bundled_execdir" ] && [ ! -d "$target_execdir" ]; then
            # Walk up to the nearest ancestor that actually exists -- that's
            # the one bwrap can legally tmpfs-replace; anything deeper is
            # missing precisely because it needs to be created, which a
            # plain --bind can't do on a real (and on some distros,
            # literally read-only) host directory.
            target_parent="$target_execdir"
            while [ ! -d "$target_parent" ] && [ "$target_parent" != "/" ]; do
                target_parent="$(dirname "$target_parent")"
            done
            sibling_binds=()
            for sibling in "$target_parent"/*/; do
                [ -d "$sibling" ] && sibling_binds+=(--dev-bind "$sibling" "$sibling")
            done
            export IMS_APPIMAGE_WEBKIT_BWRAP_DONE=1
            exec bwrap --dev-bind / / --tmpfs "$target_parent" "${sibling_binds[@]}" \
                --bind "$bundled_execdir" "$target_execdir" -- "$0" "$@"
        fi
    fi
fi
