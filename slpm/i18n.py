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
    "No file chosen": "فایلی انتخاب نشده است",
    "Type or paste the path of the file you downloaded.":
        "مسیر فایل دانلودشده را بنویسید یا بچسبانید.",
    "Folder": "پوشه",
    "Provide the file to install, not a folder.":
        "به‌جای پوشه، فایلی را که می‌خواهید نصب کنید انتخاب کنید.",
    "File not found": "فایل پیدا نشد",
    "Check the path - this file does not exist.":
        "مسیر را بررسی کنید؛ این فایل وجود ندارد.",
    "Debian package (.deb)": "بستهٔ Debian (.deb)",
    "Will be installed system-wide with apt/dpkg.":
        "با apt/dpkg برای کل سیستم نصب می‌شود.",
    "AppImage": "AppImage",
    "Will be placed in ~/Applications with a menu shortcut.":
        "در ~/Applications قرار می‌گیرد و میان‌بری در منو ساخته می‌شود.",
    "Flatpak reference": "مرجع Flatpak",
    "Will be installed with flatpak.": "با flatpak نصب می‌شود.",
    "Archive": "آرشیو",
    "Will be extracted to ~/.local/share/slpm/apps, then you pick which program "
    "inside to register.":
        "در ~/.local/share/slpm/apps استخراج می‌شود؛ سپس برنامه‌ای را که می‌خواهید "
        "ثبت کنید انتخاب می‌کنید.",
    "Installer script": "اسکریپت نصب",
    "Installer scripts run arbitrary commands. SLPM will extract nothing and only "
    "offer to register it as a menu entry.":
        "اسکریپت‌های نصب می‌توانند هر دستوری را اجرا کنند. SLPM هیچ فایلی را استخراج "
        "نمی‌کند و فقط پیشنهاد می‌کند اسکریپت را به‌عنوان میان‌بر منو ثبت کنید.",
    "Unsupported file type": "نوع فایل پشتیبانی نمی‌شود",
    "SLPM installs .deb, .AppImage, .flatpakref and archives "
    "({formats}). Convert this file first.":
        "SLPM فایل‌های .deb، .AppImage، .flatpakref و آرشیوهای ({formats}) را نصب "
        "می‌کند. ابتدا این فایل را تبدیل کنید.",

    "Installation failed": "نصب انجام نشد",
    "Installation failed\n{detail}": "نصب انجام نشد\n{detail}",
    "The package was not installed.": "بسته نصب نشد.",
    "Debian package": "بستهٔ Debian",
    "Flatpak is not installed": "Flatpak نصب نیست",
    "This computer has no flatpak command. Install flatpak first "
    "(Advanced mode -> flatpak).":
        "دستور flatpak روی این رایانه موجود نیست. ابتدا flatpak را نصب کنید "
        "(حالت پیشرفته ← flatpak).",
    "Installed.": "نصب شد.",
    "Flatpak installation failed": "نصب Flatpak انجام نشد",
    "Could not extract the archive": "آرشیو استخراج نشد",
    "Extracted to {root}. No runnable program was found inside, so nothing was added "
    "to your menu.":
        "در {root} استخراج شد. هیچ برنامهٔ قابل اجرایی پیدا نشد، بنابراین چیزی به منو "
        "اضافه نشد.",
    "Which program should I add?": "کدام برنامه اضافه شود؟",
    "Extracted to {root}. This archive contains several runnable items - pick one to "
    "add to your menu.":
        "در {root} استخراج شد. این آرشیو چند مورد قابل اجرا دارد؛ یکی را برای "
        "افزودن به منو انتخاب کنید.",
    "The extracted file is gone": "فایل استخراج‌شده دیگر وجود ندارد",
    "{name} is no longer in {root}. Extract the archive again.":
        "{name} دیگر در {root} نیست. آرشیو را دوباره استخراج کنید.",
    "{name} was added to your applications menu.":
        "{name} به منوی برنامه‌ها اضافه شد.",
    "{name} is a script that installs itself. SLPM will not run it for you, but you "
    "can register it as a menu entry.":
        "{name} اسکریپتی است که خودش را نصب می‌کند. SLPM آن را اجرا نمی‌کند، اما "
        "می‌توانید آن را به‌عنوان میان‌بر منو ثبت کنید.",
    "Run it in a terminal if you trust its source.":
        "اگر به منبع آن اعتماد دارید، در ترمینال اجرایش کنید.",
    "SLPM did not execute it.": "SLPM آن را اجرا نکرد.",
    "That shortcut no longer exists.": "این میان‌بر دیگر وجود ندارد.",
    "SLPM only removes shortcuts it created itself.":
        "SLPM فقط میان‌برهایی را حذف می‌کند که خودش ساخته است.",
    "The shortcut was removed.": "میان‌بر حذف شد.",
    "The shortcut could not be removed.": "میان‌بر حذف نشد.",
    "Installed with SLPM": "نصب‌شده با SLPM",
    "Registered with SLPM": "ثبت‌شده با SLPM",

    # ------------------------------------------------------------------ appimage
    "This file is not a working AppImage. Only self-contained AppImage files can be "
    "installed this way":
        "این فایل یک AppImage قابل اجرا نیست. فقط فایل‌های مستقل AppImage را می‌توان "
        "با این روش نصب کرد",
    "{name} was installed. A shortcut is available in your applications menu.":
        "{name} نصب شد. میان‌بر آن در منوی برنامه‌ها در دسترس است.",
    "File not found: {path}": "فایل پیدا نشد: {path}",
    "Could not read the AppImage: {exc}": "خواندن AppImage ممکن نشد: {exc}",
    "This file could not be unpacked as an AppImage. If it came out of a .zip or "
    ".tar.gz, extract it first and install the AppImage inside.":
        "این فایل به‌شکل AppImage باز نشد. اگر از یک .zip یا .tar.gz بیرون آمده، "
        "ابتدا آرشیو را استخراج و AppImage داخل آن را نصب کنید.",
    "The shortcut was removed. The application files were left in place (they are not "
    "managed by SLPM).":
        "میان‌بر حذف شد، اما فایل‌های برنامه باقی ماندند (SLPM آن‌ها را مدیریت نمی‌کند).",
    "Removed {name} and its shortcut.": "{name} و میان‌برش حذف شدند.",
    "No zip extractor is installed (unzip).":
        "ابزار بازکردن فایل‌های zip نصب نیست (unzip).",
    "This archive format needs the '7z' tool, which is not installed.":
        "این قالب آرشیو به ابزار 7z نیاز دارد که نصب نیست.",
    "Extraction failed.": "استخراج انجام نشد.",

    # ----------------------------------------------------------------------- apt
    "{name} was removed.": "{name} حذف شد.",
    "{name} was purged.": "{name} حذف و پاک‌سازی شد.",
    "Could not remove {name}.": "{name} حذف نشد.",
    "Could not purge {name}.": "{name} پاک‌سازی نشد.",
    "The package could not be installed. It may be built for a different distribution "
    "or architecture.\n{detail}":
        "بسته نصب نشد. ممکن است برای توزیع یا معماری دیگری ساخته شده باشد.\n{detail}",
    "The package was unpacked but its dependencies could not be installed.\n{detail}":
        "بسته باز شد، اما وابستگی‌هایش نصب نشدند.\n{detail}",
    "Root permission was refused, so nothing was changed.":
        "دسترسی مدیر سیستم داده نشد؛ هیچ تغییری انجام نشد.",
    "Dependencies are missing or broken. Try Advanced mode and install the missing "
    "libraries first.":
        "وابستگی‌ها ناقص یا خراب‌اند. در حالت پیشرفته، ابتدا کتابخانه‌های لازم را نصب کنید.",
    "Required dependencies are not available from your configured repositories.":
        "وابستگی‌های لازم در مخازن تنظیم‌شده موجود نیستند.",
    "Another package tool is already running. Close it and try again.":
        "ابزار مدیریت بستهٔ دیگری در حال اجراست. آن را ببندید و دوباره تلاش کنید.",
    "This package was built for a different CPU architecture than this computer.":
        "این بسته برای معماری پردازندهٔ دیگری ساخته شده است، نه این رایانه.",
    "There is not enough free disk space.": "فضای آزاد کافی روی دیسک وجود ندارد.",
    "No details reported.": "جزئیاتی گزارش نشده است.",

    # ----------------------------------------------------- flatpak / snap / misc
    "{app_id} was removed.": "{app_id} حذف شد.",
    "Could not remove {app_id}.": "{app_id} حذف نشد.",
    "(no description)": "(بدون توضیح)",
    "Installed application": "برنامهٔ نصب‌شده",
    "Extracted.": "استخراج شد.",
    "No graphical session detected - cannot launch apps.":
        "نشست گرافیکی فعالی پیدا نشد؛ اجرای برنامه‌ها ممکن نیست.",
    "This app has no launch command.": "این برنامه فرمان اجرا ندارد.",
    "This app is no longer installed.": "این برنامه دیگر نصب نیست.",

    # ------------------------------------------------------------------ app.py
    "SLPM hit an unexpected problem.": "SLPM با مشکل پیش‌بینی‌نشده‌ای روبه‌رو شد.",
    "{label} is still running. Wait for it to finish.":
        "{label} هنوز در حال اجراست. صبر کنید تا تمام شود.",
    "Installation": "نصب",
    "Removal": "حذف",
    "Cleaning up": "پاک‌سازی",
    "Removing {name}": "در حال حذف {name}",
    "Launching.": "در حال اجرا.",
    "Could not start this app.": "اجرای این برنامه ممکن نشد.",
    "Nothing was named to remove.": "هیچ برنامه‌ای برای حذف مشخص نشده است.",
    "SLPM does not manage this item.": "SLPM این مورد را مدیریت نمی‌کند.",
    "{name} is not installed.": "{name} نصب نیست.",
    "No package name given.": "نام بسته‌ای وارد نشده است.",
    "Confirmation text did not match the package name. Nothing was removed.":
        "متن تأیید با نام بسته یکسان نبود؛ هیچ چیزی حذف نشد.",
    "Unused dependencies were cleaned up.": "وابستگی‌های بی‌استفاده پاک‌سازی شدند.",
    "Cleanup failed.": "پاک‌سازی انجام نشد.",
    "No file chooser is installed on this computer. Paste the file path instead.":
        "برنامهٔ انتخاب فایل روی این رایانه نصب نیست. به‌جای آن مسیر فایل را بچسبانید.",
    "Choose a file to install": "انتخاب فایل برای نصب",
    "Unknown endpoint.": "نشانی درخواست شناخته نشد.",
    "This is only available in Advanced Mode.":
        "این بخش فقط در حالت پیشرفته در دسترس است.",

    # -------------------------------------------------------------- proc.py
    "The command did not finish in time. It may still be running; close any package "
    "tool and try again.":
        "فرمان به‌موقع تمام نشد. ممکن است هنوز در حال اجرا باشد؛ ابزارهای مدیریت بسته "
        "را ببندید و دوباره تلاش کنید.",
    "Root permission was not granted. SLPM asked for it with pkexec/sudo and the "
    "request was declined or no authentication dialog could be shown.\n"
    "Details: {detail}":
        "دسترسی مدیر سیستم داده نشد. SLPM آن را با pkexec/sudo درخواست کرد، اما درخواست "
        "رد شد یا پنجرهٔ احراز هویت نمایش داده نشد.\nجزئیات: {detail}",

    # ------------------------------------------------------------------ helper.py
    "Neither pkexec nor sudo is available, so privileged actions cannot run.":
        "ابزار pkexec یا sudo در دسترس نیست؛ بنابراین عملیات نیازمند دسترسی مدیر "
        "اجرا نمی‌شود.",
    " (password prompt may appear in the terminal that started SLPM)":
        " (ممکن است در ترمینالی که SLPM را اجرا کرده، رمز عبور خواسته شود)",
    "Could not start the privileged helper: {exc}":
        "اجرای سرویس کمکی مدیریت بسته‌ها ممکن نشد: {exc}",
    "Privileged helper is running.": "سرویس کمکی مدیریت بسته‌ها در حال اجراست.",
    "Root permission was not granted. SLPM asked for it with pkexec and the request "
    "was dismissed or denied.":
        "دسترسی مدیر سیستم داده نشد. SLPM آن را با pkexec درخواست کرد، اما درخواست بسته "
        "یا رد شد.",
    "Refused by helper: {argv}": "درخواست توسط ابزار کمکی رد شد: {argv}",

    # ------------------------------------------------- the page itself (templates)
    # Strings the server renders straight into the HTML. Package names, file
    # extensions and the names of package managers stay in Latin script on purpose:
    # they are what the user will type or see in a terminal.
    "Simple Linux Package Manager": "مدیر بستهٔ سادهٔ لینوکس",
    "Install": "نصب",
    "Installed Apps": "برنامه‌های نصب‌شده",
    "Running as root": "اجرا با دسترسی root",
    "Admin access ready": "دسترسی مدیر آماده است",
    "Admin access on demand": "دسترسی مدیر هنگام نیاز",
    "Switch language": "تغییر زبان",
    "Switch to dark theme": "تغییر به تم تاریک",
    "Switch to light theme": "تغییر به تم روشن",

    "Install an app": "نصب برنامه",
    "Downloaded a file? Point SLPM at it. It works out what the file is and does "
    "the rest — you do not need to know anything about packages.":
        "فایلی دانلود کرده‌اید؟ آن را به SLPM بدهید. نوع فایل را تشخیص می‌دهد و "
        "مراحل بعدی را انجام می‌دهد؛ لازم نیست دربارهٔ بسته‌ها چیزی بدانید.",
    "File to install": "فایلی برای نصب",
    "Drop a file here, or paste a path like /home/you/Downloads/app.AppImage":
        "فایل را اینجا رها کنید یا مسیری مثل /home/you/Downloads/app.AppImage را بچسبانید",
    "Browse…": "انتخاب فایل…",
    "Clear": "پاک‌کردن",
    "What SLPM can install": "فایل‌های قابل نصب با SLPM",
    "Debian and Ubuntu installers. Installed system-wide with your admin password.":
        "بسته‌های Debian و Ubuntu. برای کل سیستم نصب می‌شوند و ممکن است رمز عبور مدیر "
        "سیستم را بخواهند.",
    "Portable apps. Copied to ~/Applications and given a menu shortcut.":
        "برنامه‌های قابل‌حمل. در ~/Applications کپی می‌شوند و میان‌بری در منو می‌گیرند.",
    "Flatpak apps, when Flatpak is installed.":
        "برنامه‌های Flatpak، در صورت نصب Flatpak.",
    "Archives. Extracted to a managed folder, then you choose what to add to the "
    "menu.":
        "آرشیوها. در پوشه‌ای که SLPM مدیریت می‌کند استخراج می‌شوند؛ سپس می‌توانید "
        "برنامه‌ای را برای افزودن به منو انتخاب کنید.",
    "Download and install": "دانلود و نصب",
    "Paste a download link and SLPM will download it and install it automatically.":
        "لینک دانلود را بچسبانید؛ SLPM فایل را دانلود و خودکار نصب می‌کند.",
    "Paste a link. SLPM downloads it in the background and tries to detect and install "
    "it when it finishes unless another file is selected.":
        "لینک را بچسبانید. SLPM آن را در پس‌زمینه دانلود می‌کند و پس از پایان، تلاش "
        "می‌کند فایل را تشخیص دهد و نصب کند؛ مگر فایل دیگری انتخاب شده باشد.",
    "Download": "دانلود",
    "Downloads": "دانلودها",
    "Paste a download link, like https://example.com/app.AppImage":
        "لینک دانلودی مثل https://example.com/app.AppImage بچسبانید",
    "Saved to Downloads, then pointed at the installer above.":
        "در Downloads ذخیره می‌شود و سپس برای نصب انتخاب می‌شود.",
    "This does not look like a web link.": "این نشانی یک لینک وب معتبر نیست.",
    "Install method": "روش نصب",
    "Install from file": "نصب از فایل",
    "Download ready, installing…": "دانلود تمام شد؛ در حال نصب…",
    "in progress": "در حال انجام",
    "Enter a link starting with http:// or https://":
        "لینکی را وارد کنید که با http:// یا https:// شروع شود.",
    "Download failed.": "دانلود انجام نشد.",
    "Unknown action.": "عملیات ناشناخته.",
    "That download is no longer running.": "این دانلود دیگر در حال اجرا نیست.",

    "Waiting…": "در انتظار…",
    "Downloading…": "در حال دانلود…",
    "Paused": "موقتاً متوقف شد",
    "Done": "انجام شد",
    "Failed": "ناموفق",
    "Stopped": "لغو شد",
    "Ready to install": "آمادهٔ نصب",
    "Continue": "ادامه",
    "Pause": "مکث",
    "Stop": "لغو",
    "Download failed": "دانلود ناموفق بود",
    "Not installable": "قابل نصب نیست",
    "This file could not be installed.": "نصب این فایل ممکن نشد.",

    "Installed apps": "برنامه‌های نصب‌شده",
    "Installed apps on this computer.": "برنامه‌های نصب‌شده روی این رایانه.",
    "Reading installed apps…": "در حال خواندن برنامه‌های نصب‌شده…",
    "Everyday applications on this computer.":
        "برنامه‌های روزمره روی این رایانه.",
    "Simple": "ساده",
    "Advanced": "پیشرفته",
    "View mode": "حالت نمایش",
    "Search apps…": "جست‌وجوی برنامه‌ها…",
    "Filter": "فیلتر",
    "All sources": "همهٔ منابع",
    "All packages": "همهٔ بسته‌ها",
    "System packages": "بسته‌های سیستمی",
    "Refresh": "تازه‌سازی",
    "Clean unused dependencies": "پاک‌سازی وابستگی‌های بلااستفاده",
    "Nothing to show": "موردی برای نمایش نیست",
    "No applications matched.": "برنامه‌ای پیدا نشد.",
    "No apps matched.": "برنامه‌ای پیدا نشد.",
    "Working…": "در حال انجام…",
    "This can take a minute. Keep this window open.":
        "ممکن است یک دقیقه طول بکشد. این پنجره را باز نگه دارید.",
    "Reading installed programs…": "در حال خواندن فهرست برنامه‌های نصب‌شده…",

    # --------------------------------------------------------------- autostart
    # The backend half of the Startup Apps page. Every one of these is raised from
    # slpm/autostart.py and carries a program name in Latin script on purpose.
    "This program has no name, so it cannot be added.":
        "این برنامه نام ندارد، بنابراین نمی‌توان آن را اضافه کرد.",
    "This program has no command to run.":
        "فرمان اجرایی برای این برنامه وجود ندارد.",
    "The command for this program was not found on this computer.":
        "فرمان این برنامه روی این رایانه پیدا نشد.",
    "{name} already starts when you log in.":
        "{name} از قبل هنگام ورود به سیستم اجرا می‌شود.",
    "{name} will now start when you log in.":
        "از این پس، {name} هنگام ورود به سیستم اجرا می‌شود.",
    "{name} will no longer start when you log in.":
        "از این پس، {name} هنگام ورود به سیستم اجرا نمی‌شود.",
    "This startup entry is no longer there.":
        "این برنامهٔ استارتاپ دیگر در فهرست نیست.",
    "This startup entry could not be read.":
        "خواندن این برنامهٔ استارتاپ ممکن نشد.",
    "This startup entry could not be removed.":
        "این برنامهٔ استارتاپ حذف نشد.",
    "This entry belongs to the system and cannot be deleted. Turn it off instead.":
        "این مورد متعلق به سیستم است و قابل حذف نیست. به‌جای حذف، غیرفعال‌کردنش کنید.",
    "{name} was removed from your startup apps.":
        "{name} از برنامه‌های استارتاپ حذف شد.",

    "Startup Apps": "برنامه‌های استارتاپ",
    "Startup apps": "برنامه‌های استارتاپ",
    "Startup apps that start when you log in.":
        "برنامه‌های استارتاپ که هنگام ورود به سیستم اجرا می‌شوند.",
    "Programs that start by themselves when you log in.":
        "برنامه‌هایی که هنگام ورود به سیستم خودکار اجرا می‌شوند.",
    "Add startup app": "افزودن برنامهٔ استارتاپ",
    "Search startup apps…": "جست‌وجوی برنامه‌های استارتاپ…",
    "Added by you": "افزوده‌شده توسط شما",
    "System": "سیستم",
    "Turned off": "غیرفعال‌شده",
    "No startup programs matched.": "برنامهٔ استارتاپ پیدا نشد.",
    "Reading startup programs…": "در حال خواندن برنامه‌های استارتاپ…",
    "Reading startup apps…": "در حال خواندن برنامه‌های استارتاپ…",
    "Startup apps that start when you log in, including system startup apps.":
        "برنامه‌های استارتاپ که هنگام ورود به سیستم اجرا می‌شوند، شامل برنامه‌های استارتاپ سیستم هم می‌شوند.",
    "Only the startup apps you added yourself. Switch to Advanced Mode to see system startup apps.":
        "فقط برنامه‌های استارتاپ که خودتان اضافه کرده‌اید. برای دیدن برنامه‌های استارتاپ سیستم، به حالت پیشرفته بروید.",
    "No startup apps added yet. Switch to Advanced Mode to see system startup apps.":
        "هنوز برنامهٔ استارتاپ اضافه نکرده‌اید. برای دیدن برنامه‌های استارتاپ سیستم، به حالت پیشرفته بروید.",
    "No startup apps matched.": "برنامهٔ استارتاپ پیدا نشد.",
}
