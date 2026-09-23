# SLPM — Simple Linux Package Manager

[فارسی](README.fa.md)

A simple local web app for installing, viewing, launching, and removing Linux software without using package-manager commands directly.

> SLPM runs locally on your computer at `127.0.0.1:8686`.

## Features

- Simple and Advanced modes, switched from a control in the top bar next to the tabs:
  - **Simple Mode** (the default) lists only the apps you installed yourself, in both the Installed Apps and Startup Apps tabs.
  - **Advanced Mode** shows everything the system has — pre-installed applications, system components, packaged startup entries — where they can also be seen and removed.
  - The Install tab is identical in both modes.
- Telling your apps from pre-installed ones is evidence-based: SLPM reads the package managers' own records — the date each package first appears in the dpkg log, compared against the operating system's install date, the snap seed file, and Flatpak install times. Directory location and file dates are deliberately not used, because they can lie.
- A Startup Apps tab that lists what a session starts by itself, with one-click adding and removal
- Support for `.deb`, AppImage, Flatpak references, archives, and installer files — opening a file you have or downloading one from a link
- Downloads run in the background with pause, continue and stop controls, a live progress bar, and an automatic install once the file is finished
- Automatic detection of available `apt`, Flatpak, and Snap tools
- English and Persian interface with light and dark themes
- Confirmation and safety checks for package operations

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
requirements.txt    Python dependencies
```

## License

This project is licensed under the [MIT License](LICENSE).
