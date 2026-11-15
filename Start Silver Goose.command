#!/bin/bash
# Double-click in Finder. Keep this file beside source/, or use a Desktop alias.
set -euo pipefail
fail() { echo; echo "Silver Goose: $*"; read -r -p 'Press Return to close. ' _sg_reply || true; exit 1; }
trap 'fail "Setup stopped at line $LINENO. See the error above, then run this launcher again."' ERR
[ "$(uname -s)" = Darwin ] || fail 'This version runs on a Mac.'
export PATH="/opt/homebrew/bin:/opt/homebrew/opt/python@3.12/bin:/usr/local/bin:/usr/local/opt/python@3.12/bin:/Library/Frameworks/Python.framework/Versions/3.12/bin:$PATH"
export HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ANALYTICS=1
SG_SCRIPT="${BASH_SOURCE[0]}"
while [ -L "$SG_SCRIPT" ]; do
  SG_LINK_DIR="$(cd -P "$(dirname "$SG_SCRIPT")" && pwd)"
  SG_SCRIPT="$(readlink "$SG_SCRIPT")"
  case "$SG_SCRIPT" in /*) ;; *) SG_SCRIPT="$SG_LINK_DIR/$SG_SCRIPT" ;; esac
done
SG_ROOT="$(cd -P "$(dirname "$SG_SCRIPT")" && pwd)"
SG_POINTER="$HOME/Library/Application Support/Silver Goose/folder.txt"
if [ ! -f "$SG_ROOT/source/app.py" ]; then
  if [ -f "$SG_POINTER" ]; then IFS= read -r SG_ROOT < "$SG_POINTER" || true; fi
  if [ ! -f "$SG_ROOT/source/app.py" ]; then
    SG_ROOT="$(osascript -e 'POSIX path of (choose folder with prompt "Choose your Silver Goose folder (the folder containing source)")')" || fail 'No folder selected.'
  fi
fi
[ -f "$SG_ROOT/source/app.py" ] || fail 'Choose the Silver Goose folder containing source/app.py.'
SG_ROOT="$(cd "$SG_ROOT" && pwd -P)"
mkdir -p "$(dirname "$SG_POINTER")"
printf '%s\n' "$SG_ROOT" > "$SG_POINTER"
cd "$SG_ROOT"
echo 'Silver Goose · local video builder'
SG_MAC_MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
[ "$SG_MAC_MAJOR" -ge 26 ] || fail 'macOS 26 or newer is required for local automatic captions. Update macOS in System Settings, then run again.'
sg_has_swift() { xcode-select -p >/dev/null 2>&1 && xcrun --find swiftc >/dev/null 2>&1; }
if ! sg_has_swift; then
  # Wait for Apple's installer instead of asking for a second double-click.
  echo "Apple's Command Line Tools are needed. Click Install in Apple's window and agree."
  echo 'Leave this window open: Silver Goose carries on by itself when they are installed.'
  xcode-select --install >/dev/null 2>&1 || true
  SG_WAITED=0
  until sg_has_swift; do
    sleep 10
    SG_WAITED=$((SG_WAITED + 10))
    if [ $((SG_WAITED % 300)) -eq 0 ]; then
      echo "Still waiting for Apple's installer ($((SG_WAITED / 60)) minutes so far)…"
    fi
    [ "$SG_WAITED" -lt 7200 ] || fail "Apple's Command Line Tools did not finish installing. If you closed Apple's window, double-click this file again."
  done
  echo "Apple's Command Line Tools are installed."
fi
SG_PYTHON=''
for SG_CANDIDATE in python3.12 python3; do
  if command -v "$SG_CANDIDATE" >/dev/null 2>&1 && "$SG_CANDIDATE" -c 'import sys; assert (3,11) <= sys.version_info[:2] < (3,14)' >/dev/null 2>&1; then
    SG_PYTHON="$(command -v "$SG_CANDIDATE")"; break
  fi
done
SG_NEED_PYTHON=0; SG_NEED_FFMPEG=0
[ -n "$SG_PYTHON" ] || SG_NEED_PYTHON=1
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then SG_NEED_FFMPEG=1; fi
if [ "$SG_NEED_PYTHON" -eq 1 ] || [ "$SG_NEED_FFMPEG" -eq 1 ]; then
  echo 'Silver Goose needs Python and FFmpeg (both free), installed with Homebrew.'
  read -r -p 'Press Return to install them, or type n and Return to stop. ' SG_ANSWER
  case "$SG_ANSWER" in n|N|no|NO) fail 'Requirements were not installed.' ;; esac
  if ! command -v brew >/dev/null 2>&1; then
    # One password prompt here; Homebrew then runs without its own prompts. Its
    # non-interactive mode uses the password sudo has just remembered, kept fresh below
    # for a long install.
    echo 'Installing Homebrew (free). Type your Mac password and press Return.'
    echo 'Nothing appears while you type. An administrator account is needed.'
    sudo -v || fail 'Homebrew needs the password of an administrator account on this Mac.'
    ( SG_NAP=''
      trap 'kill "$SG_NAP" 2>/dev/null; exit 0' TERM
      while kill -0 "$$" 2>/dev/null; do
        sudo -n true 2>/dev/null || true
        sleep 50 & SG_NAP=$!
        wait "$SG_NAP" || true
      done ) &
    SG_SUDO_KEEPALIVE=$!
    SG_BREW_SCRIPT="$(mktemp -t silver-goose-homebrew)"
    curl --proto '=https' --tlsv1.2 -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$SG_BREW_SCRIPT"
    NONINTERACTIVE=1 /bin/bash "$SG_BREW_SCRIPT"
    rm -f "$SG_BREW_SCRIPT"
    kill "$SG_SUDO_KEEPALIVE" 2>/dev/null || true
  fi
  command -v brew >/dev/null 2>&1 || fail 'Homebrew is not available. Finish its setup, then run again.'
  if [ "$SG_NEED_PYTHON" -eq 1 ]; then brew install python@3.12; SG_PYTHON="$(brew --prefix python@3.12)/bin/python3.12"; fi
  if [ "$SG_NEED_FFMPEG" -eq 1 ]; then brew install ffmpeg; fi
fi
# A copied or interrupted environment may contain dangling interpreter links.
# Move it aside before venv creation; venv does not repair those links in place.
if [ -e .venv ] || [ -L .venv ]; then
  if [ ! -x .venv/bin/python ] || ! .venv/bin/python -c 'import sys,pathlib,pip; assert (3,11) <= sys.version_info[:2] < (3,14); assert sys.prefix != sys.base_prefix; assert pathlib.Path(sys.prefix).resolve()==pathlib.Path(".venv").resolve()' >/dev/null 2>&1; then
    echo 'Repairing the local Python environment…'
    SG_OLD_ENV="$(mktemp -d "$SG_ROOT/.venv-old-XXXXXXXX")"
    mv .venv "$SG_OLD_ENV/environment"
  fi
fi
if [ ! -x .venv/bin/python ]; then "$SG_PYTHON" -m venv .venv; fi
SG_ENV_PYTHON="$SG_ROOT/.venv/bin/python"
"$SG_ENV_PYTHON" source/bootstrap.py
export SG_LIBRARY="$SG_ROOT/library"
trap - ERR
"$SG_ENV_PYTHON" source/app.py "$@" || fail 'The panel stopped. See the error above.'
