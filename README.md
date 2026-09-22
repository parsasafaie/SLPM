# SLPM — Simple Linux Package Manager

[فارسی](README.fa.md)

A simple local web app for installing, viewing, launching, and removing Linux software without using package-manager commands directly.

> SLPM runs locally on your computer at `127.0.0.1:8686`.

## Features

- Simple and Advanced views for installed applications and packages
- A Startup Apps tab that lists what a session starts by itself, with one-click adding and removal
- Support for `.deb`, AppImage, Flatpak references, archives, and installer files
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
                    (autostart.py manages the startup-program entries)
templates/          HTML templates
static/             CSS and JavaScript assets
docs/               GitHub Pages website
requirements.txt    Python dependencies
```

## License

This project is licensed under the [MIT License](LICENSE).
