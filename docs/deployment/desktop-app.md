# IMS Desktop — Setup Guide

IMS Desktop is an app that runs your inventory system on your own computer.
You don't need to be a programmer to use it — this guide walks through
everything step by step.

**Right now, IMS Desktop is only officially released for Linux computers.**
A Windows installer can be built from source and installs/runs, but it
hasn't been fully verified end-to-end yet, so there's no official Windows
download here. Mac support may come later.

## Before you start: install Docker

IMS Desktop needs another free program called **Docker** already installed
on your computer. Think of Docker as the engine — IMS Desktop is the car
that drives it. Without Docker installed and running, IMS Desktop can't
start.

Most Linux systems let you install Docker through their normal app store —
search for "Docker" there first. If that doesn't work, your system likely
has instructions at [docker.com](https://docs.docker.com/engine/install/).

Once installed, make sure Docker is actually **running** before you open
IMS Desktop — it usually shows an icon somewhere on your screen, or has its
own app you can open, when it's active.

### Windows setup: Docker Desktop and WSL2

If you're on Windows, Docker works a little differently than on Linux — it
needs a Windows feature called **WSL2** (Windows Subsystem for Linux)
installed alongside it. Docker Desktop's own installer sometimes sets this
up for you automatically, but not always, so it's worth checking directly:

1. Open **Command Prompt** (search for it in your Start menu) and run:

   ```
   wsl --install
   ```

   If it says WSL2 is already installed, you're done with this step. If it
   installs something, **restart your computer** afterward — this step
   doesn't take effect until you do.

2. Download and install
   [Docker Desktop](https://www.docker.com/products/docker-desktop/) for
   Windows, if you haven't already.

3. Open Docker Desktop from your Start menu and wait for it to say it's
   running (this can take a minute or two, especially the first time).

If your computer's virtualization setting is turned off in its BIOS/UEFI
firmware, IMS Desktop can detect that too, and will tell you directly
instead of just saying WSL2 is missing — this is usually on by default, but
some computers (especially older ones, or ones set up by an IT department)
have it turned off. Fixing it means restarting your computer, entering
BIOS/UEFI setup (often by pressing a key like F2, F10, Del, or Esc right
after powering on), and enabling virtualization (sometimes called "Intel
VT-x", "AMD-V", or "SVM Mode"). This setting is outside of what IMS Desktop
or Docker can fix for you directly; your computer manufacturer's support
site will have instructions specific to your model.

## Installing IMS Desktop

1. Download the `.rpm` file from the
   [latest release](https://github.com/sinan-can-demir/ims/releases/latest)
   (as of this writing, `v0.1.0`).
2. Double-click the downloaded file. Your system's normal app installer
   should open and offer to install it — click through that like you would
   for any other program.

   If double-clicking doesn't do anything (this varies by system), open a
   terminal and run:

   ```
   sudo dnf install ~/Downloads/IMS\ Desktop-0.1.0-1.x86_64.rpm
   ```

   (adjust the path if you saved the file somewhere other than Downloads).
   It'll ask for your password — that's normal, it's just confirming you're
   allowed to install new programs.

3. **(Optional but recommended) Verify the download is genuine.** IMS
   Desktop releases are digitally signed, so you can confirm a downloaded
   file really came from the official project and wasn't tampered with:

   ```
   sudo rpm --import https://raw.githubusercontent.com/sinan-can-demir/ims/main/tauri/keys/RPM-GPG-KEY-ims-desktop
   rpm -K ~/Downloads/IMS\ Desktop-0.1.0-1.x86_64.rpm
   ```

   You should see `digests signatures OK`. This is a one-time setup — once
   the key is imported, `dnf install` will also verify future updates
   automatically. Skipping this step doesn't stop the app from installing
   or working; it's purely about confirming authenticity.

### Not on Fedora/RHEL? Use the AppImage instead

The `.rpm` above only installs on Fedora/RHEL-family systems. Every release
also ships an `.AppImage` file that runs on most Linux distributions without
any installation step:

1. Download the `.AppImage` file from the
   [latest release](https://github.com/sinan-can-demir/ims/releases/latest).
2. Make it executable and run it:

   ```
   chmod +x ~/Downloads/IMS\ Desktop-0.1.0-1.x86_64.AppImage
   ~/Downloads/IMS\ Desktop-0.1.0-1.x86_64.AppImage
   ```

There's nothing to uninstall later — just delete the file. It doesn't
integrate with your applications menu the way an installed `.rpm` does.

## Opening it for the first time

Find "IMS Desktop" in your applications menu, just like any other program,
and open it.

A window will appear showing what it's doing, one step at a time:

- **Checking Docker...** — making sure Docker is installed and running.
- **Building images...** — the very first time you open it, this step can
  take a while (several minutes, sometimes longer) while everything gets
  set up. After this first time, it's much faster.
- **Starting services...** and **Waiting for IMS to respond...** — almost
  there.

If Docker isn't installed or isn't running, you'll see a clear message
telling you that instead of getting stuck — go back and check the Docker
step above.

### Creating your account

The very first time, you'll see a simple form: **Email**, **Display name**,
and **Password**. Fill it in and click **Create account**. This creates the
one admin account for your business — everyone else you add later signs in
with their own account, but this first one is set up right here in the app.

Once your account is created, you're taken straight into your inventory
dashboard. That's it — you're set up.

## Using it day to day

Every time you open IMS Desktop after that first setup, it goes through
the same steps (checking Docker, starting things up) and takes you
straight to your dashboard — no need to create an account again.

**When you close the IMS Desktop window, everything shuts down cleanly**
in the background — nothing keeps running on your computer after you
close it. Reopening it starts everything fresh.

## If something goes wrong

The app tries to tell you plainly what's wrong rather than showing a
confusing technical error:

- **"Docker is not installed" / "Docker isn't running"** — go back to the
  [Before you start](#before-you-start-install-docker) step above.
- **"Docker Desktop needs the Windows Subsystem for Linux (WSL2)..."** — see
  [Windows setup: Docker Desktop and WSL2](#windows-setup-docker-desktop-and-wsl2)
  above.
- **"Docker needs hardware virtualization..."** — your computer's BIOS/UEFI
  firmware has virtualization turned off; see the note at the end of
  [Windows setup: Docker Desktop and WSL2](#windows-setup-docker-desktop-and-wsl2)
  above.
- **"Another application is already using port ___"** — some other program
  on your computer is using a resource IMS Desktop needs. Closing that
  other program and reopening IMS Desktop usually fixes this.
- **"The database container failed its health check"** — something went
  wrong starting up the internal database. This one's less common; if you
  see it, it's worth reaching out for help rather than trying to fix it
  yourself.

If none of these match what you're seeing, or the same problem keeps
happening, that's worth reporting so it can be looked into.
