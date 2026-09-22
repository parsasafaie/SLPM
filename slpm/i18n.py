"""Smallest thing that turns an English message into a Persian one.

The backend emits its messages as plain English sentences (a few of them with a
value interpolated into them, e.g. "vlc was removed."). Rather than restructure
every module to carry a message id around, the strings themselves are the keys:
catalog() is a lookup table from the English sentence to its Persian translation,
and tr() is the lookup, falling back to the English original.

That fallback is the whole safety net. A sentence that is missing from the
catalog - a new one, or one arriving from apt/dpkg - is shown unchanged in
Persian mode rather than disappearing or turning into a placeholder.

Package names, file paths, .deb, AppImage, Flatpak, Snap, pkexec, sudo and polkit
stay in Latin script inside the Persian text on purpose: they are what the user
sees in a terminal and on a package page, so translating them would make the
message harder to act on, not easier.
"""
from functools import lru_cache
from string import Formatter

LANGS = ("en", "fa")
DEFAULT = "en"
DIRECTIONS = {"en": "ltr", "fa": "rtl"}
HTML_LANGS = {"en": "en", "fa": "fa"}


def normalize(lang):
    """Coerce anything (a cookie, a header, None) into a supported language code."""
    code = str(lang or "").strip().lower().replace("_", "-")
    if code in LANGS:
        return code
    base = code.split("-", 1)[0]
    return base if base in LANGS else DEFAULT


@lru_cache(maxsize=16)
def catalog(lang):
    return _FA if normalize(lang) == "fa" else {}


@lru_cache(maxsize=256)
def _template(english):
    """The named fields in an English sentence, e.g. {'name'} for '{name} was removed.'"""
    fields = []
    for _, field, _, _ in Formatter().parse(english):
        if field:
            fields.append(field)
    return tuple(fields)


def _fill(text, values):
    """Substitute {name}-style fields, leaving the sentence alone if a field is missing."""
    if not values:
        return text
    try:
        return text.format(**values)
    except (KeyError, IndexError, ValueError):
        return text


def tr(lang, english, **values):
    """Translate one English sentence, interpolating any values into it."""
    if not english:
        return english
    if normalize(lang) == "en":
        # English is the source language, but it still carries the placeholders: a
        # caller asking for English wants "vlc was removed.", not "{name} was removed.".
        return _fill(english, values)
    text = catalog(lang).get(english)
    if text is None:
        # Unknown sentence: hand back the original, but keep it populated.
        return _fill(english, values)
    return _fill(text, values)


_FA = {
    # ---------------------------------------------------------------- installer
    "No file chosen": "فایلی انتخاب نشده",
    "Type or paste the path of the file you downloaded.":
        "مسیر فایلی را که دانلود کرده‌اید بنویسید یا بچسبانید.",
    "Folder": "پوشه",
    "Provide the file to install, not a folder.":
        "فایلی را که می‌خواهید نصب کنید بدهید، نه یک پوشه.",
    "File not found": "فایل پیدا نشد",
    "Check the path - this file does not exist.":
        "مسیر را بررسی کنید؛ این فایل وجود ندارد.",
    "Debian package (.deb)": "بستهٔ Debian (‎.deb‎)",
    "Will be installed system-wide with apt/dpkg.":
        "به‌صورت سیستمی با apt/dpkg نصب می‌شود.",
    "AppImage": "AppImage",
    "Will be placed in ~/Applications with a menu shortcut.":
        "در ‎~/Applications‎ قرار می‌گیرد و میان‌بری در منو ساخته می‌شود.",
    "Flatpak reference": "ارجاع Flatpak",
    "Will be installed with flatpak.": "با flatpak نصب می‌شود.",
    "Archive": "آرشیو",
    "Will be extracted to ~/.local/share/slpm/apps, then you pick which program "
    "inside to register.":
        "در ‎~/.local/share/slpm/apps‎ استخراج می‌شود و بعد خودتان انتخاب می‌کنید "
        "کدام برنامه داخلش به منو اضافه شود.",
    "Installer script": "اسکریپت نصب",
    "Installer scripts run arbitrary commands. SLPM will extract nothing and only "
    "offer to register it as a menu entry.":
        "اسکریپت‌های نصب هر دستوری را اجرا می‌کنند. SLPM چیزی را استخراج نمی‌کند و "
        "فقط پیشنهاد می‌دهد آن را به‌عنوان یک میان‌بر در منو ثبت کند.",
    "Unsupported file type": "نوع فایل پشتیبانی نمی‌شود",
    "SLPM installs .deb, .AppImage, .flatpakref and archives "
    "({formats}). Convert this file first.":
        "SLPM فایل‌های ‎.deb‎، ‎.AppImage‎، ‎.flatpakref‎ و آرشیوها ({formats}) را نصب "
        "می‌کند. اول این فایل را تبدیل کنید.",

    "Installation failed": "نصب انجام نشد",
    "The package was not installed.": "این بسته نصب نشد.",
    "Debian package": "بستهٔ Debian",
    "Flatpak is not installed": "Flatpak نصب نیست",
    "This computer has no flatpak command. Install flatpak first "
    "(Advanced mode -> flatpak).":
        "این کامپیوتر دستور flatpak را ندارد. اول flatpak را نصب کنید "
        "(حالت پیشرفته ← flatpak).",
    "Installed.": "نصب شد.",
    "Flatpak installation failed": "نصب Flatpak انجام نشد",
    "Could not extract the archive": "آرشیو استخراج نشد",
    "Extracted to {root}. No runnable program was found inside, so nothing was added "
    "to your menu.":
        "در {root} استخراج شد. برنامهٔ اجرایی داخلش پیدا نشد، پس چیزی به منوی شما "
        "اضافه نشد.",
    "Which program should I add?": "کدام برنامه اضافه شود؟",
    "Extracted to {root}. This archive contains several runnable items - pick one to "
    "add to your menu.":
        "در {root} استخراج شد. این آرشیو چند مورد اجرایی دارد؛ یکی را برای اضافه‌شدن "
        "به منو انتخاب کنید.",
    "The extracted file is gone": "فایل استخراج‌شده از بین رفته است",
    "{name} is no longer in {root}. Extract the archive again.":
        "{name} دیگر در {root} نیست. آرشیو را دوباره استخراج کنید.",
    "{name} was added to your applications menu.":
        "{name} به منوی برنامه‌های شما اضافه شد.",
    "{name} is a script that installs itself. SLPM will not run it for you, but you "
    "can register it as a menu entry.":
        "{name} اسکریپتی است که خودش را نصب می‌کند. SLPM آن را به‌جای شما اجرا "
        "نمی‌کند، اما می‌توانید آن را به‌عنوان یک میان‌بر در منو ثبت کنید.",
    "Run it in a terminal if you trust its source.":
        "اگر به منبعش اعتماد دارید، خودتان آن را در ترمینال اجرا کنید.",
    "SLPM did not execute it.": "SLPM آن را اجرا نکرد.",
    "That shortcut no longer exists.": "آن میان‌بر دیگر وجود ندارد.",
    "SLPM only removes shortcuts it created itself.":
        "SLPM فقط میان‌برهایی را حذف می‌کند که خودش ساخته است.",
    "The shortcut was removed.": "میان‌بر حذف شد.",

    # ------------------------------------------------------------------ appimage
    "This file is not a working AppImage. Only self-contained AppImage files can be "
    "installed this way":
        "این فایل یک AppImage سالم نیست. با این روش فقط فایل‌های AppImage "
        "خودکفا نصب می‌شوند",
    "{name} was installed. A shortcut is available in your applications menu.":
        "{name} نصب شد. یک میان‌بر در منوی برنامه‌های شما هست.",
    "File not found: {path}": "فایل پیدا نشد: {path}",
    "Could not read the AppImage: {exc}": "AppImage خوانده نشد: {exc}",
    "This file could not be unpacked as an AppImage. If it came out of a .zip or "
    ".tar.gz, extract it first and install the AppImage inside.":
        "این فایل به‌عنوان AppImage باز نشد. اگر از یک ‎.zip‎ یا ‎.tar.gz‎ بیرون آمده، "
        "اول آن را استخراج کنید و AppImage داخلش را نصب کنید.",
    "The shortcut was removed. The application files were left in place (they are not "
    "managed by SLPM).":
        "میان‌بر حذف شد. فایل‌های برنامه سر جای خودشان ماندند (SLPM آن‌ها را مدیریت "
        "نمی‌کند).",
    "Removed {name} and its shortcut.": "{name} و میان‌برش حذف شدند.",
    "No zip extractor is installed (unzip).":
        "هیچ برنامهٔ بازکردن zip نصب نیست (unzip).",
    "This archive format needs the '7z' tool, which is not installed.":
        "این قالب آرشیو به ابزار ‎7z‎ نیاز دارد که نصب نیست.",
    "Extraction failed.": "استخراج انجام نشد.",

    # ----------------------------------------------------------------------- apt
    "{name} was removed.": "{name} حذف شد.",
    "{name} was purged.": "{name} حذف و پاک‌سازی شد.",
    "Could not remove {name}.": "{name} حذف نشد.",
    "Could not purge {name}.": "{name} پاک‌سازی نشد.",
    "Installed.": "نصب شد.",
    "The package could not be installed. It may be built for a different distribution "
    "or architecture.\n{detail}":
        "بسته نصب نشد. ممکن است برای توزیع یا معماری دیگری ساخته شده باشد.\n{detail}",
    "The package was unpacked but its dependencies could not be installed.\n{detail}":
        "بسته باز شد اما وابستگی‌هایش نصب نشدند.\n{detail}",
    "Root permission was refused, so nothing was changed.":
        "دسترسی root داده نشد، پس هیچ تغییری اعمال نشد.",
    "Dependencies are missing or broken. Try Advanced mode and install the missing "
    "libraries first.":
        "وابستگی‌ها ناقص یا خراب‌اند. از حالت پیشرفته ابتدا کتابخانه‌های لازم را نصب کنید.",
    "Required dependencies are not available from your configured repositories.":
        "وابستگی‌های لازم در مخزن‌هایی که تنظیم کرده‌اید موجود نیستند.",
    "Another package tool is already running. Close it and try again.":
        "یک ابزار بستهٔ دیگر در حال اجراست. آن را ببندید و دوباره تلاش کنید.",
    "This package was built for a different CPU architecture than this computer.":
        "این بسته برای معماری پردازندهٔ دیگری ساخته شده است، نه این کامپیوتر.",
    "There is not enough free disk space.": "فضای خالی کافی روی دیسک نیست.",
    "No details reported.": "جزئیاتی گزارش نشد.",

    # ----------------------------------------------------- flatpak / snap / misc
    "{app_id} was removed.": "{app_id} حذف شد.",
    "Could not remove {app_id}.": "{app_id} حذف نشد.",
    "(no description)": "(بدون توضیح)",
    "Installed application": "برنامهٔ نصب‌شده",
    "Extracted.": "استخراج شد.",
    "No graphical session detected - cannot launch apps.":
        "هیچ نشست گرافیکی پیدا نشد — برنامه‌ها اجرا نمی‌شوند.",
    "This app has no launch command.": "این برنامه فرمان اجرایی ندارد.",
    "{name} was removed.": "{name} حذف شد.",
    "Could not remove {name}.": "{name} حذف نشد.",

    # ------------------------------------------------------------------ app.py
    "SLPM hit an unexpected problem.": "SLPM به یک مشکل پیش‌بینی‌نشده برخورد.",
    "{label} is still running. Wait for it to finish.":
        "{label} هنوز در حال اجراست. بگذارید تمام شود.",
    "Installation": "نصب",
    "Removal": "حذف",
    "Cleaning up": "پاک‌سازی",
    "Removing {name}": "حذف {name}",
    "Launching.": "در حال اجرا.",
    "Could not start this app.": "این برنامه اجرا نشد.",
    "Nothing was named to remove.": "چیزی برای حذف مشخص نشده بود.",
    "SLPM does not manage this item.": "SLPM این مورد را مدیریت نمی‌کند.",
    "{name} is not installed.": "{name} نصب نیست.",
    "No package name given.": "نام بسته‌ای داده نشد.",
    "Confirmation text did not match the package name. Nothing was removed.":
        "متن تأیید با نام بسته یکسان نبود. چیزی حذف نشد.",
    "Unused dependencies were cleaned up.": "وابستگی‌های بی‌استفاده پاک‌سازی شدند.",
    "Cleanup failed.": "پاک‌سازی انجام نشد.",
    "No file chooser is installed on this computer. Paste the file path instead.":
        "روی این کامپیوتر هیچ برنامهٔ انتخاب فایلی نصب نیست. مسیر فایل را بچسبانید.",
    "Unknown endpoint.": "نقطهٔ پایانی ناشناخته.",

    # ------------------------------------------------- the page itself (templates)
    # Strings the server renders straight into the HTML. Package names, file
    # extensions and the names of package managers stay in Latin script on purpose:
    # they are what the user will type or see in a terminal.
    "Simple Linux Package Manager": "مدیر بستهٔ سادهٔ لینوکس",
    "Install": "نصب",
    "Installed Apps": "برنامه‌های نصب‌شده",
    "Running as root": "در حال اجرا با دسترسی root",
    "Admin access ready": "دسترسی مدیر آماده است",
    "Admin access on demand": "دسترسی مدیر در صورت نیاز",
    "Switch language": "تغییر زبان",
    "Switch to dark theme": "تغییر به تم تاریک",
    "Switch to light theme": "تغییر به تم روشن",

    "Install an app": "نصب یک برنامه",
    "Downloaded a file? Point SLPM at it. It works out what the file is and does "
    "the rest — you do not need to know anything about packages.":
        "فایلی دانلود کرده‌اید؟ آن را به SLPM بدهید. خودش می‌فهمد چه فایلی است و بقیهٔ "
        "کار را انجام می‌دهد — لازم نیست چیزی دربارهٔ بسته‌ها بدانید.",
    "File to install": "فایلی که نصب می‌شود",
    "Drop a file here, or paste a path like /home/you/Downloads/app.AppImage":
        "فایل را اینجا رها کنید، یا مسیری مثل ‎/home/you/Downloads/app.AppImage‎ را "
        "بچسبانید",
    "Browse…": "انتخاب فایل…",
    "Clear": "پاک کردن",
    "What SLPM can install": "SLPM چه چیزهایی می‌تواند نصب کند",
    "Debian and Ubuntu installers. Installed system-wide with your admin password.":
        "نصب‌کننده‌های Debian و Ubuntu. با رمز مدیر شما به‌صورت سیستمی نصب می‌شوند.",
    "Portable apps. Copied to ~/Applications and given a menu shortcut.":
        "برنامه‌های همراه. در ‎~/Applications‎ کپی می‌شوند و میان‌بری در منو می‌گیرند.",
    "Flatpak apps, when Flatpak is installed.":
        "برنامه‌های Flatpak، وقتی Flatpak نصب باشد.",
    "Archives. Extracted to a managed folder, then you choose what to add to the "
    "menu.":
        "آرشیوها. در پوشه‌ای مدیریت‌شده استخراج می‌شوند، بعد خودتان انتخاب می‌کنید چه "
        "چیزی به منو اضافه شود.",

    "Installed apps": "برنامه‌های نصب‌شده",
    "Everyday applications on this computer.":
        "برنامه‌های روزمرهٔ این کامپیوتر.",
    "Simple": "ساده",
    "Advanced": "پیشرفته",
    "Search apps…": "جست‌وجوی برنامه‌ها…",
    "Filter": "صافی",
    "All sources": "همهٔ منابع",
    "System packages": "بسته‌های سیستمی",
    "Refresh": "به‌روزرسانی",
    "Clean unused dependencies": "پاک‌سازی وابستگی‌های بی‌استفاده",
    "Nothing to show": "چیزی برای نمایش نیست",
    "No applications matched.": "برنامه‌ای مطابقت نداشت.",
    "Working…": "در حال انجام…",
    "This can take a minute. Keep this window open.":
        "ممکن است یک دقیقه طول بکشد. این پنجره را باز نگه دارید.",
    "Reading installed programs…": "در حال خواندن برنامه‌های نصب‌شده…",

    # --------------------------------------------------------------- autostart
    # The backend half of the Startup Apps page. Every one of these is raised from
    # slpm/autostart.py and carries a program name in Latin script on purpose.
    "This program has no name, so it cannot be added.":
        "این برنامه نامی ندارد، پس نمی‌شود اضافه‌اش کرد.",
    "This program has no command to run.":
        "این برنامه فرمانی برای اجرا ندارد.",
    "The command for this program was not found on this computer.":
        "فرمان این برنامه روی این کامپیوتر پیدا نشد.",
    "{name} already starts when you log in.":
        "{name} از قبل هنگام ورود شما اجرا می‌شود.",
    "{name} will now start when you log in.":
        "از این پس {name} هنگام ورود شما اجرا می‌شود.",
    "{name} will no longer start when you log in.":
        "از این پس {name} هنگام ورود شما اجرا نمی‌شود.",
    "This startup entry is no longer there.":
        "این مورد از برنامه‌های هنگام ورود دیگر وجود ندارد.",
    "This startup entry could not be read.":
        "این مورد از برنامه‌های هنگام ورود خوانده نشد.",
    "This startup entry could not be removed.":
        "این مورد از برنامه‌های هنگام ورود حذف نشد.",
    "This entry belongs to the system and cannot be deleted. Turn it off instead.":
        "این مورد متعلق به سیستم است و حذف نمی‌شود. به‌جایش خاموشش کنید.",
    "{name} was removed from your startup apps.":
        "{name} از برنامه‌های هنگام ورود شما حذف شد.",

    "Startup Apps": "برنامه‌های هنگام ورود",
    "Startup apps": "برنامه‌های هنگام ورود",
    "Programs that start by themselves when you log in.":
        "برنامه‌هایی که هنگام ورود شما خودکار اجرا می‌شوند.",
    "Add startup app": "افزودن برنامهٔ هنگام ورود",
    "Search startup apps…": "جست‌وجوی برنامه‌های هنگام ورود…",
    "Added by you": "افزودهٔ شما",
    "System": "سیستم",
    "Turned off": "خاموش",
    "No startup programs matched.": "برنامهٔ هنگام ورودی مطابقت نداشت.",
    "Reading startup programs…": "در حال خواندن برنامه‌های هنگام ورود…",
}
