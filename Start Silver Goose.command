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
if ! xcode-select -p >/dev/null 2>&1 || ! xcrun --find swiftc >/dev/null 2>&1; then
  echo 'Apple Command Line Tools are needed. Approve the Apple installation dialog.'
  xcode-select --install || true
  fail 'Finish installing Apple Command Line Tools, then double-click this file again.'
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
  echo 'Missing requirements will be installed with Homebrew (Python and/or FFmpeg).'
  read -r -p 'Install missing requirements? [Y/n] ' SG_ANSWER
  case "$SG_ANSWER" in n|N|no|NO) fail 'Requirements were not installed.' ;; esac
  if ! command -v brew >/dev/null 2>&1; then
    echo 'Installing Homebrew. Its installer may request your Mac password and confirmation.'
    SG_BREW_SCRIPT="$(mktemp -t silver-goose-homebrew)"
    curl --proto '=https' --tlsv1.2 -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$SG_BREW_SCRIPT"
    /bin/bash "$SG_BREW_SCRIPT"
    rm -f "$SG_BREW_SCRIPT"
  fi
  command -v brew >/dev/null 2>&1 || fail 'Homebrew is not available. Finish its setup, then run again.'
  if [ "$SG_NEED_PYTHON" -eq 1 ]; then brew install python@3.12; SG_PYTHON="$(brew --prefix python@3.12)/bin/python3.12"; fi
  if [ "$SG_NEED_FFMPEG" -eq 1 ]; then brew install ffmpeg; fi
fi
# A virtual environment contains absolute paths. Recreate it if this folder was moved.
if [ -x .venv/bin/python ] && ! .venv/bin/python -c 'import sys,pathlib; assert pathlib.Path(sys.prefix).resolve()==pathlib.Path(".venv").resolve()' >/dev/null 2>&1; then
  mv .venv ".venv-old-$(date +%s)"
fi
if [ ! -x .venv/bin/python ]; then "$SG_PYTHON" -m venv .venv; fi
SG_ENV_PYTHON="$SG_ROOT/.venv/bin/python"
"$SG_ENV_PYTHON" source/bootstrap.py
export SG_LIBRARY="$SG_ROOT/library"
trap - ERR
"$SG_ENV_PYTHON" source/app.py "$@" || fail 'The panel stopped. See the error above.'
