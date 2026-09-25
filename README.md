# SLPM — Simple Linux Package Manager

[فارسی](README.fa.md)

A simple local web app for installing, viewing, launching, and removing Linux software without using package-manager commands directly.

> SLPM runs locally on your computer at `127.0.0.1:8686`.

## Features

- Simple and Advanced modes, switched from a control in the top bar next to the tabs:
  - **Simple Mode** (the default) lists only apps that SLPM can identify as user-installed, in both the Installed Apps and Startup Apps tabs. This includes relevant apps from apt/dpkg, Snap, Flatpak, and local desktop entries.
  - **Advanced Mode** changes Installed Apps to the installed dpkg/apt package database, including pre-installed applications and system components, and makes relevant packaged Startup Apps entries visible. It is not a unified list of every software source.
  - The Install tab is identical in both modes.
- Telling your apps from pre-installed ones is evidence-based: SLPM reads the package managers' own records — the date each dpkg package first appears in the dpkg log, the snap seed file, and the earliest modification time of the Flatpak deployment commit directories. It does not infer ownership from where a desktop entry lives or from dpkg `.list` file dates, because those signals can mislead.
- A Startup Apps tab for viewing, adding, and turning off user-owned or packaged startup entries
- An Updates tab (both modes) that lists what apt, Flatpak, and Snap each have available, and runs the refresh or the update per manager
- Install by name (Advanced Mode only): search the apt repositories as you type, or install an apt package, a snap, or a Flatpak app by its exact name
- Support for `.deb`, `.snap`, AppImage, `.flatpakref`, several archive formats, and `.run`/`.sh` files that can be registered without being executed — opening a local file or downloading one from a link
- Downloads run as background jobs with pause, continue and stop controls, a live progress bar, and automatic installation after completion unless another local file is already selected
- Automatic detection of available `apt`, Flatpak, and Snap tools
- English and Persian interface with light and dark themes
- Confirmations and safety warnings for package removal; system-level operations request administrator access through `pkexec` or `sudo`

## Requirements

- Linux desktop environment
- Python 3.9 or newer
- `pkexec` or `sudo` for package operations

## Installation

Run these commands in a terminal:

```bash
sudo apt update && sudo apt install -y git python3 python3-venv  # Install Git, Python, and virtual-environment support
git clone https://github.com/parsasafaie/SLPM.git  # Clone the repository
cd SLPM  # Enter the project directory
python3 -m venv .venv  # Create a virtual environment
source .venv/bin/activate  # Activate the environment
pip install -r requirements.txt  # Install dependencies
python app.py  # Start the application
```

Open <http://127.0.0.1:8686> in your browser. Keep the development server on localhost and do not expose it publicly.

## Testing

```bash
source .venv/bin/activate
python selftest.py
```

The selftest is a plain script, no test framework. It covers the parsing and safety logic (Exec= handling, desktop filtering, the root helper's command allowlist, archive path checks, the HTTP endpoints' refusal behaviour, and the translation catalogs in both the backend and the browser). A few checks read this machine's real state — the dpkg log, the installed apps, the startup entries — to prove the ownership classifier works end to end. On a machine where that state is not interesting (CI, a fresh container), skip them with:

```bash
python selftest.py --skip-machine
```

## Project structure

```text
app.py              Flask application entry point
slpm/               Package and desktop-integration logic
                    (ownership.py decides which software the user installed
                    and which came with the system, and download.py fetches a
                    link in the background with pause, continue and stop)
templates/          HTML templates
static/             CSS and JavaScript assets
docs/               GitHub Pages website
selftest.py         Self-check script (no test framework needed)
requirements.txt    Python dependencies
```

## License

This project is licensed under the [MIT License](LICENSE).
