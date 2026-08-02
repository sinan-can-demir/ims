# IMS Desktop — Setup Guide

IMS Desktop is an app that runs your inventory system on your own computer.
You don't need to be a programmer to use it — this guide walks through
everything step by step.

**Right now, IMS Desktop only works on Linux computers.** Windows and Mac
support may come later.

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

## Installing IMS Desktop

1. Download the IMS Desktop installer file (it ends in `.rpm`).
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

3. **You may see a warning that the installer isn't "signed" or from a
   verified source.** This is expected for now — the app isn't set up with
   a security certificate yet. As long as you downloaded it from the
   official IMS project, it's safe to continue.

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
- **"Another application is already using port ___"** — some other program
  on your computer is using a resource IMS Desktop needs. Closing that
  other program and reopening IMS Desktop usually fixes this.
- **"The database container failed its health check"** — something went
  wrong starting up the internal database. This one's less common; if you
  see it, it's worth reaching out for help rather than trying to fix it
  yourself.

If none of these match what you're seeing, or the same problem keeps
happening, that's worth reporting so it can be looked into.
