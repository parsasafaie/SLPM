/* Theme and language for the two buttons in the top bar.
 *
 * Both are cookies, and both are applied twice on purpose:
 *
 *   - The theme is applied from an inline <script> in <head> (see base.html) so the
 *     dark palette is in place before the first paint. Doing it here would let the
 *     page flash white and then go dark.
 *   - The language of the *page* is done by the server, which is the only place that
 *     can render the whole document in Persian in one pass. Switching it reloads.
 *
 * What lives here is the part the server cannot do: text the browser writes after the
 * page has loaded - toasts, modal bodies, the rows in the app list. Those sentences
 * start as English strings in the JavaScript, and TT() turns them into the current
 * language at the moment they are shown. The catalog below is deliberately the same
 * idea as slpm/i18n.py: an English sentence is the key, and anything missing from the
 * catalog is displayed unchanged in its English form rather than breaking the page.
 */

const SLPM = (() => {
  const COOKIE_LANG = 'slpm_lang';
  const COOKIE_THEME = 'slpm_theme';
  const COOKIE_MODE = 'slpm_mode';
  const LANGS = ['en', 'fa'];
  const MODES = ['simple', 'advanced'];

  function cookie(name) {
    const hit = document.cookie.split('; ').find(c => c.startsWith(`${name}=`));
    return hit ? decodeURIComponent(hit.slice(name.length + 1)) : '';
  }

  function setCookie(name, value) {
    document.cookie = `${name}=${encodeURIComponent(value)};path=/;max-age=31536000;samesite=Lax`;
  }

  function normalize(value) {
    const code = String(value || '').trim().toLowerCase().replace('_', '-');
    if (LANGS.includes(code)) return code;
    const base = code.split('-')[0];
    return LANGS.includes(base) ? base : 'en';
  }

  /* The server already decided this; the cookie holds the same value, and the flag
     in <html data-lang> is authoritative because it is what was actually rendered. */
  const state = {
    lang: normalize(document.documentElement.dataset.lang || cookie(COOKIE_LANG)),
    theme: document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light',
    mode: MODES.includes(document.documentElement.dataset.mode)
      ? document.documentElement.dataset.mode : 'simple',
    /* Advanced Mode has been accepted in this page view. The cookie remembers the
       choice across pages, but the warning is shown once per load, so a page the user
       opened fresh does not silently start in the dangerous view. */
    modeAllowed: false,
  };

  /* Notified whenever the mode changes, so the tab scripts can re-read and re-render
     without either of them owning the switch. */
  const modeListeners = [];
  function onModeChange(fn) { modeListeners.push(fn); }

  /* Keys are the exact English sentences the scripts pass to T(). Values are the
     Persian renderings. A sentence missing here is shown in English rather than
     breaking the page, so this table is allowed to be incomplete.
     A long key that needs several source lines is written as ONE string broken by
     `+` inside square brackets: `['a ' + 'b']: value`. A key cannot be built by
     concatenation outside brackets - that is a syntax error, not a key. */
  const FA = {
    /* ------------------------------------------------------------- app.js */
    'Dismiss': 'بستن',
    'SLPM is not reachable any more. Is the server still running?':
      'ارتباط با SLPM قطع شده است. آیا سرور هنوز در حال اجراست؟',
    'The server sent a reply SLPM could not read.':
      'پاسخ سرور قابل خواندن نبود.',

    /* --------------------------------------------------------- install.js */
    'Working…': 'در حال انجام…',
    'This can take a minute. Keep this window open.':
      'ممکن است یک دقیقه طول بکشد. این پنجره را باز نگه دارید.',
    'Checking the file…': 'در حال بررسی فایل…',
    'Skip': 'رد کردن',
    'Done': 'انجام شد',
    'Installation failed': 'نصب انجام نشد',
    'Close': 'بستن',
    'Finishing up…': 'در حال پایان کار…',
    'Installing…': 'در حال نصب…',
    'Package operations can take a while. Keep this window open.':
      'عملیات بسته ممکن است طول بکشد. این پنجره را باز نگه دارید.',
    'Already busy': 'عملیات دیگری در حال انجام است',
    'No file chooser': 'ابزار انتخاب فایل در دسترس نیست',
    /* ------------------------------------------------- downloads (install) */
    'Waiting…': 'در انتظار…',
    'Downloading…': 'در حال دانلود…',
    'Paused': 'موقتاً متوقف شد',
    'Failed': 'ناموفق',
    'Stopped': 'لغو شد',
    'in progress': 'در حال انجام',
    'Continue': 'ادامه',
    'Pause': 'مکث',
    'Stop': 'لغو',
    'Clear': 'پاک‌کردن',
    'Download failed': 'دانلود ناموفق بود',
    'Download complete': 'دانلود کامل شد',
    'Download ready, installing…': 'دانلود تمام شد؛ در حال نصب…',
    'The download could not be completed.': 'دانلود کامل نشد.',
    'Not installable': 'قابل نصب نیست',
    'This file could not be installed.': 'نصب این فایل ممکن نشد.',
    'Saved to Downloads, then pointed at the installer above.':
      'در Downloads ذخیره می‌شود و سپس برای نصب انتخاب می‌شود.',
    'This does not look like a web link.': 'این نشانی یک لینک وب معتبر نیست.',
    'Enter a link starting with http:// or https://':
      'لینکی را وارد کنید که با http:// یا https:// شروع شود.',
    ['A valid link starts a background download; SLPM will try to detect and install the '
      + 'file when it finishes unless another file is selected.']:
      'با یک لینک معتبر، دانلود در پس‌زمینه شروع می‌شود. پس از پایان، SLPM تلاش '
      + 'می‌کند فایل را تشخیص دهد و نصب کند؛ مگر فایل دیگری انتخاب شده باشد.',
    ['Download complete; another file is already selected, so this file was not installed '
      + 'automatically.']:
      'دانلود کامل شد، اما فایل دیگری انتخاب شده بود؛ بنابراین نصب خودکار این فایل انجام '
      + 'نشد.',

    /* ------------------------------------------------------------ apps.js */
    'Every installed package, including system components.':
      'همهٔ بسته‌های نصب‌شده، از جمله اجزای سیستمی.',
    'Installed apt/dpkg packages, including system components.':
      'بسته‌های نصب‌شده با apt/dpkg، از جمله اجزای سیستمی.',
    'Everyday applications on this computer.':
      'برنامه‌های روزمره روی این رایانه.',
    ['Only the apps you installed yourself. Switch to Advanced Mode to see apt/dpkg '
      + 'packages.']:
      'فقط برنامه‌هایی را می‌بینید که خودتان نصب کرده‌اید. برای دیدن بسته‌های apt/dpkg، '
      + 'به حالت پیشرفته بروید.',
    ['Only the apps you installed yourself. Switch to Advanced to see everything the '
      + 'system came with.']:
      'فقط برنامه‌هایی را می‌بینید که خودتان نصب کرده‌اید. برای دیدن همهٔ بسته‌های '
      + 'همراه سیستم، به حالت پیشرفته بروید.',
    'Reading installed programs…': 'در حال خواندن فهرست برنامه‌های نصب‌شده…',
    'Reading your installed apps…': 'در حال خواندن برنامه‌های نصب‌شدهٔ شما…',
    'Reading the package database…': 'در حال خواندن پایگاه‌دادهٔ بسته‌ها…',
    'Reading apt/dpkg packages…': 'در حال خواندن بسته‌های apt/dpkg…',
    'Could not list apps': 'فهرست برنامه‌ها خوانده نشد',
    'Could not list packages': 'فهرست بسته‌ها خوانده نشد',
    'Could not list apt/dpkg packages': 'فهرست بسته‌های apt/dpkg خوانده نشد',
    'No applications matched.': 'برنامه‌ای پیدا نشد.',
    'No apps matched.': 'برنامه‌ای پیدا نشد.',
    ['No apps installed by you yet. Switch to Advanced Mode to see apt/dpkg packages.']:
      'هنوز هیچ برنامه‌ای را خودتان نصب نکرده‌اید. برای دیدن بسته‌های apt/dpkg، به حالت '
      + 'پیشرفته بروید.',
    ['No apt/dpkg packages matched.']: 'هیچ بستهٔ apt/dpkg پیدا نشد.',
    ['You have not installed any apps yourself yet. Switch to Advanced to see everything '
      + 'the system came with.']:
      'هنوز هیچ برنامه‌ای را خودتان نصب نکرده‌اید. برای دیدن همهٔ بسته‌های همراه '
      + 'سیستم، به حالت پیشرفته بروید.',
    'This is only available in Advanced Mode.':
      'این بخش فقط در حالت پیشرفته در دسترس است.',
    'none': 'ندارد',
    'Nothing matched “{q}”.': 'چیزی برای «{q}» پیدا نشد.',
    'Showing the first 600 of {n} items — narrow the search to see the rest.':
      '۶۰۰ مورد اول از {n} مورد نمایش داده می‌شود؛ برای دیدن بقیه، جست‌وجو را محدود کنید.',
    'essential': 'حیاتی سیستم',
    'system': 'سیستمی',
    'os': 'سیستم‌عامل',
    'Launch': 'اجرا',
    'Launching': 'در حال اجرا',
    'Could not launch': 'اجرا نشد',
    'Details': 'جزئیات',
    'Remove': 'حذف',
    'Cancel': 'لغو',
    'Reading details…': 'در حال خواندن جزئیات…',
    'Version': 'نسخه',
    'Size': 'حجم',
    'Section': 'بخش',
    'Maintainer': 'نگه‌دارنده',
    'Homepage': 'صفحهٔ اصلی',
    'Description': 'توضیح',
    'Files installed': 'فایل‌های نصب‌شده',
    'Source': 'منبع',
    'Shortcut': 'میان‌بر',
    'Command': 'فرمان',
    'Priority': 'اولویت',
    'Architecture': 'معماری',
    'Status': 'وضعیت',
    'Dependencies': 'وابستگی‌ها',
    /* Status is one dpkg phrase mapped to one label (see statusLabel in apps.js). */
    'installed': 'نصب‌شده',
    'half-installed': 'نیمه‌نصب‌شده',
    'half-configured': 'نیمه‌پیکربندی‌شده',
    'unpacked': 'بازشده',
    'triggers awaited': 'در انتظار اجرای کارهای پس از نصب',
    'triggers pending': 'کارهای پس از نصب در صف',
    'config files only': 'فقط فایل‌های تنظیمات',
    'installed (held)': 'نصب‌شده (نگه‌داشته‌شده)',
    'not installed': 'نصب نیست',
    'This package is essential to the system and cannot be removed.':
      'این بسته برای سیستم حیاتی است و قابل حذف نیست.',
    ['This package is essential to the system. It can be removed in Advanced Mode only '
      + 'after you type its name to confirm; SLPM will use --allow-remove-essential. '
      + 'Removing it can make the computer unable to start and permanently break package '
      + 'management.']:
      'این بسته برای سیستم حیاتی است. فقط در حالت پیشرفته و پس از واردکردن نام آن برای '
      + 'تأیید قابل حذف است؛ SLPM از --allow-remove-essential استفاده می‌کند. حذف آن '
      + 'می‌تواند مانع روشن‌شدن رایانه شود و مدیریت بسته‌ها را برای همیشه از کار بیندازد.',
    'Remove {name}?': '{name} حذف شود؟',
    'Package: {name}': 'بسته: {name}',
    'You will be asked for your admin password to make this change.':
      'برای این تغییر، رمز مدیر از شما خواسته می‌شود.',
    'Removing {name}…': 'در حال حذف {name}…',
    /* The server's busy label (app.py) uses the same sentence without the ellipsis. */
    'Removing {name}': 'در حال حذف {name}',
    'Removed': 'حذف شد',
    'Could not remove': 'حذف نشد',
    'Remove {name}': 'حذف {name}',
    'Remove package': 'حذف بسته',
    'Backups are not created by SLPM.': 'SLPM از بسته‌ها نسخهٔ پشتیبان نمی‌گیرد.',
    'Type the package name to confirm': 'برای تأیید، نام بسته را وارد کنید',
    'Also delete configuration files (purge)':
      'فایل‌های تنظیمات هم حذف شوند (purge)',
    'Not confirmed': 'تأیید نشد',
    'The name did not match.': 'نام واردشده مطابقت نداشت.',
    'Clean unused dependencies?': 'وابستگی‌های بی‌استفاده پاک‌سازی شوند؟',
    'Clean up': 'پاک‌سازی',
    'Cleaning up…': 'در حال پاک‌سازی…',
    'Cleaned up': 'پاک‌سازی شد',
    'Cleanup failed': 'پاک‌سازی انجام نشد',
    /* install-by-name box on the apps page */
    'Package name, like vlc': 'نام بسته، مثل vlc',
    'Snap name, like code': 'نام snap، مثل code',
    'Flatpak app id, like org.gimp.GIMP': 'شناسهٔ Flatpak، مثل org.gimp.GIMP',
    'Searching…': 'در حال جست‌وجو…',
    'No packages matched.': 'بسته‌ای مطابق پیدا نشد.',

    /* ------------------------------------------------------------ updates.js */
    'This manager is not installed on this system.':
      'این مدیر بسته روی این رایانه نصب نیست.',
    'Updating…': 'در حال به‌روزرسانی…',
    'Show available updates': 'نمایش به‌روزرسانی‌های در دسترس',
    'Hide available updates': 'پنهان‌کردن به‌روزرسانی‌های در دسترس',
    'SLPM will ask for your administrator password.':
      'SLPM رمز عبور مدیر سیستم را خواهد خواست.',
    'Update all system packages?': 'همهٔ بسته‌های سیستمی به‌روزرسانی شوند؟',
    'Update all Flatpak apps?': 'همهٔ برنامه‌های Flatpak به‌روزرسانی شوند؟',
    'Update all snap apps?': 'همهٔ برنامه‌های snap به‌روزرسانی شوند؟',
    'Update': 'به‌روزرسانی',
    'Update {name}?': 'به‌روزرسانی {name}؟',
    'Only {name} will be updated to its newest version.':
      'فقط {name} به جدیدترین نسخه به‌روزرسانی می‌شود.',
    'Running': 'در حال اجرا',
    ['{name} is running now. Close it first, then update.']:
      '{name} همین حالا در حال اجراست. اول آن را ببندید، بعد به‌روزرسانی کنید.',
    ['These are running now. Close them first, then update: {list}']:
      'این‌ها همین حالا در حال اجرا هستند. اول آن‌ها را ببندید، بعد به‌روزرسانی کنید: {list}',
    ['Every package on this system will be upgraded to its newest version. '
      + 'On a large system this can take several minutes.']:
      'همهٔ بسته‌های این سیستم به جدیدترین نسخه ارتقا می‌یابند. روی سیستم بزرگ ممکن '
      + 'است چند دقیقه طول بکشد.',
    ['Every Flatpak app you have installed will be updated to its newest '
      + 'version.']:
      'هر برنامهٔ Flatpak که نصب کرده‌اید به جدیدترین نسخه به‌روزرسانی می‌شود.',
    ['Every snap on this system will be refreshed to its newest revision.']:
      'هر snap این سیستم به جدیدترین نسخهٔ آن تازه می‌شود.',

    /* --------------------------------------------------------- startup.js */
    'Could not list startup apps': 'فهرست برنامه‌های استارتاپ خوانده نشد',
    'Reading startup programs…': 'در حال خواندن برنامه‌های استارتاپ…',
    'Reading startup apps…': 'در حال خواندن برنامه‌های استارتاپ…',
    ['Programs that start by themselves when you log in, including the ones the system '
      + 'set up.']:
      'برنامه‌هایی که هنگام ورود به سیستم خودکار اجرا می‌شوند، از جمله برنامه‌هایی که '
      + 'سیستم تنظیم کرده است.',
    'Startup apps that start when you log in, including system startup apps.':
      'برنامه‌های استارتاپ که هنگام ورود به سیستم اجرا می‌شوند، شامل برنامه‌های استارتاپ '
      + 'سیستم هم می‌شوند.',
    ['Only the startup apps you added yourself. Switch to Advanced Mode to see system '
      + 'startup apps.']:
      'فقط برنامه‌های استارتاپ که خودتان اضافه کرده‌اید. برای دیدن برنامه‌های استارتاپ '
      + 'سیستم، به حالت پیشرفته بروید.',
    ['Only the startup apps you added yourself. Switch to Advanced to see everything '
      + 'that starts with the session.']:
      'فقط برنامه‌های استارتاپ که خودتان اضافه کرده‌اید. برای دیدن همهٔ برنامه‌هایی که '
      + 'هنگام ورود اجرا می‌شوند، به حالت پیشرفته بروید.',
    ['No startup apps added yet. Switch to Advanced Mode to see system startup apps.']:
      'هنوز برنامهٔ استارتاپ اضافه نکرده‌اید. برای دیدن برنامه‌های استارتاپ سیستم، به '
      + 'حالت پیشرفته بروید.',
    'No startup apps matched.': 'برنامهٔ استارتاپ پیدا نشد.',
    ['You have not added any startup apps yourself yet. Switch to Advanced to see '
      + 'everything the system starts on its own.']:
      'هنوز هیچ برنامهٔ استارتاپ اضافه نکرده‌اید. برای دیدن برنامه‌هایی که سیستم خودکار '
      + 'اجرا می‌کند، به حالت پیشرفته بروید.',
    'Startup apps that start when you log in.':
      'برنامه‌های استارتاپ که هنگام ورود به سیستم اجرا می‌شوند.',
    'Search apps…': 'جست‌وجوی برنامه‌ها…',
    ['No installed app with a launch command was found.']:
      'هیچ برنامهٔ نصب‌شده‌ای با فرمان اجرا پیدا نشد.',
    'Pick the app to add as a startup app.':
      'برنامه‌ای را که می‌خواهید به‌عنوان برنامهٔ استارتاپ اضافه شود انتخاب کنید.',
    'yours': 'مال شما',
    'turned off': 'غیرفعال‌شده',
    'Saving…': 'در حال ذخیره…',
    'Saved': 'ذخیره شد',
    'Could not change this': 'تغییر اعمال نشد',
    'Turn off {name}': 'غیرفعال‌کردن {name}',
    'Turn off {name}?': '{name} غیرفعال شود؟',
    'Turn off': 'غیرفعال‌کردن',
    ['This app will no longer start when you log in. The application stays installed '
      + 'and can still be opened from your menu.']:
      'این برنامه دیگر هنگام ورود به سیستم اجرا نمی‌شود. خود برنامه نصب می‌ماند و '
      + 'همچنان از منو قابل اجرا است.',
    ['This startup app will no longer start when you log in. It stays installed and can '
      + 'still be opened from your menu.']:
      'این برنامهٔ استارتاپ دیگر هنگام ورود به سیستم اجرا نمی‌شود. همچنان نصب می‌ماند و '
      + 'از منو قابل اجرا است.',
    'You can add it again later from Add startup app.':
      'بعداً می‌توانید آن را از «افزودن برنامهٔ استارتاپ» دوباره اضافه کنید.',
    'Add a startup app': 'افزودن برنامهٔ استارتاپ',
    'Reading installed apps…': 'در حال خواندن برنامه‌های نصب‌شده…',
    ['No installed application with a launch command was found.']:
      'هیچ برنامهٔ نصب‌شده‌ای با فرمان اجرا پیدا نشد.',
    ['Pick the application that should start when you log in.']:
      'برنامه‌ای را انتخاب کنید که هنگام ورود به سیستم اجرا شود.',
    'Adding…': 'در حال افزودن…',
    'Added': 'افزوده شد',
    'Could not add': 'افزوده نشد',
    'No startup programs matched.': 'برنامهٔ استارتاپ پیدا نشد.',

    /* The theme button's own label. The language button is labelled in the template,
       because the server knows the current language while it renders the page. */
    'Switch to dark theme': 'تغییر به تم تاریک',
    'Switch to light theme': 'تغییر به تم روشن',

    /* The Advanced Mode warning, shown by prefs.js when the switch is used. */
    'Switch to Advanced Mode?': 'به حالت پیشرفته بروید؟',
    'Stay in Simple Mode': 'ماندن در حالت ساده',
    'I understand, continue': 'فهمیدم، ادامه بده',

    /* --- Warning boxes and dialogs, where the browser prints the whole paragraph.
           Each of these is one key written as a bracketed concatenation. --- */
    ['This is a system component. Removing it can stop programs from working or '
      + 'prevent the computer from starting.']:
      'این یک جزء سیستمی است. حذف آن می‌تواند باعث از کار افتادن برنامه‌ها یا جلوگیری '
      + 'از روشن‌شدن رایانه شود.',
    ['The system package for this app will be uninstalled. Your personal files are '
      + 'not touched.']:
      'بستهٔ سیستمی این برنامه حذف می‌شود. فایل‌های شخصی شما حذف نمی‌شوند.',
    ['The snap package will be removed, together with the icon it added to your menu. '
      + 'Your personal files are not touched.']:
      'بستهٔ snap و میان‌بری که به منو اضافه کرده حذف می‌شوند. فایل‌های شخصی شما حذف '
      + 'نمی‌شوند.',
    ['The Flatpak app will be removed, together with the icon it added to your menu. '
      + 'Your personal files are not touched.']:
      'برنامهٔ Flatpak و میان‌بری که به منو اضافه کرده حذف می‌شوند. فایل‌های شخصی شما '
      + 'حذف نمی‌شوند.',
    'The shortcut and the installed files for this app will be deleted.':
      'میان‌بر و فایل‌های نصب‌شدهٔ این برنامه حذف می‌شوند.',
    ['Advanced Mode also shows apt/dpkg packages, including critical system components. '
      + 'Removing essential packages may break your operating system.']:
      'حالت پیشرفته بسته‌های apt/dpkg، از جمله اجزای حیاتی سیستم را هم نشان می‌دهد. '
      + 'حذف بسته‌های حیاتی ممکن است سیستم‌عامل را از کار بیندازد.',
    ['Proceed with caution. In this view you can see and remove libraries, drivers '
      + 'and core services — not just applications. A wrong removal on Linux can leave '
      + 'the computer unable to start.']:
      'با احتیاط ادامه دهید. در این نما کتابخانه‌ها، درایورها و سرویس‌های اصلی را '
      + 'می‌بینید و می‌توانید حذفشان کنید، نه فقط برنامه‌ها. حذف اشتباه در لینوکس می‌تواند '
      + 'مانع روشن‌شدن رایانه شود.',
    ['Simple Mode shows only the apps you installed yourself. You can switch back at '
      + 'any time.']:
      'حالت ساده فقط برنامه‌هایی را نشان می‌دهد که خودتان نصب کرده‌اید. هر زمان خواستید '
      + 'می‌توانید به آن برگردید.',
    'App and package name searches still work normally.':
      'جست‌وجوی نام برنامه‌ها و بسته‌ها مثل قبل کار می‌کند.',
    ['Packages that were installed automatically as dependencies and are no longer '
      + 'needed by anything will be removed.']:
      'بسته‌هایی که به‌صورت خودکار به‌عنوان وابستگی نصب شده‌اند و دیگر به آن‌ها نیازی '
      + 'نیست حذف می‌شوند.',
    ['Review is not possible from here; SLPM runs <code>apt-get autoremove</code> '
      + 'with the default settings.']:
      'امکان بازبینی از این صفحه نیست؛ SLPM دستور <code>apt-get autoremove</code> را '
      + 'با تنظیمات پیش‌فرض اجرا می‌کند.',
    ['<strong>This package is essential to the system.</strong> Removing it can make '
      + 'the computer unable to start and can break package management permanently, '
      + 'so nothing else can be installed or removed afterwards. This is very likely '
      + 'to destroy this installation of Linux. There is no undo.']:
      '<strong>این بسته برای سیستم حیاتی است.</strong> حذف آن می‌تواند مانع روشن‌شدن '
      + 'رایانه شود و مدیریت بسته‌ها را برای همیشه از کار بیندازد؛ در نتیجه دیگر هیچ '
      + 'بسته‌ای نصب یا حذف نخواهد شد. احتمال زیادی وجود دارد که این نصب لینوکس از بین '
      + 'برود. این کار برگشت‌پذیر نیست.',
    ['You are about to remove a system component. Other programs may depend on it, '
      + 'and on some packages the computer may not start afterwards. Continue only '
      + 'if you know what this package does.']:
      'در حال حذف یک جزء سیستمی هستید. برنامه‌های دیگر ممکن است به آن وابسته باشند و در '
      + 'بعضی موارد سیستم پس از حذف بالا نخواهد آمد. فقط اگر می‌دانید این بسته چه کاری '
      + 'می‌کند ادامه دهید.',
    ['You are about to remove a package. Other programs may depend on it - check the '
      + 'details first if you are unsure what it does.']:
      'در حال حذف یک بسته هستید. برنامه‌های دیگر ممکن است به آن وابسته باشند؛ اگر مطمئن '
      + 'نیستید، ابتدا جزئیات آن را بررسی کنید.',
  };

  /* Server messages arrive as finished English sentences, sometimes with a value
     interpolated into them ("vlc was removed."). The pattern form matches that
     sentence whatever the value is, so one row covers every package name. */
  const FA_PATTERNS = [
    [/^(.+) was removed\.$/, '$1 حذف شد.'],
    [/^(.+) was purged\.$/, '$1 حذف و پاک‌سازی شد.'],
    [/^Could not remove (.+)\.$/, '$1 حذف نشد.'],
    [/^Could not purge (.+)\.$/, '$1 پاک‌سازی نشد.'],
    [/^(.+) is not installed\.$/, '$1 نصب نیست.'],
    [/^Removing (.+)…$/, 'در حال حذف $1…'],
    [/^(.+) was installed\. A shortcut is available in your applications menu\.$/,
     '$1 نصب شد. میان‌بر آن در منوی برنامه‌ها در دسترس است.'],
    [/^(.+) was added to your applications menu\.$/,
     '$1 به منوی برنامه‌ها اضافه شد.'],
    [/^Removed (.+) and its shortcut\.$/, '$1 و میان‌برش حذف شدند.'],
    [/^File not found: (.+)$/, 'فایل پیدا نشد: $1'],
    [/^(.+) is no longer in (.+)\. Extract the archive again\.$/,
     '$1 دیگر در $2 نیست. آرشیو را دوباره استخراج کنید.'],
    /* The startup-app messages (slpm/autostart.py) carry a program name, so one pattern
       covers every name rather than one catalog row per application. */
    [/^(.+) already starts when you log in\.$/,
     '$1 از قبل هنگام ورود به سیستم اجرا می‌شود.'],
    [/^(.+) will now start when you log in\.$/,
     'از این پس، $1 هنگام ورود به سیستم اجرا می‌شود.'],
    [/^(.+) will no longer start when you log in\.$/,
     'از این پس، $1 هنگام ورود به سیستم اجرا نمی‌شود.'],
    [/^(.+) was removed from your startup apps\.$/,
     '$1 از برنامه‌های استارتاپ حذف شد.'],
  ];

  /** Translate one string (and any {name} values) into the current language. */
  function tt(text, values) {
    if (text == null) return text;
    /* English is the source language, but the caller's values still have to be
       substituted: T('Removing {name}…', {name: 'vlc'}) must render "Removing vlc…"
       in English too, not the raw placeholder. Only the lookup is skipped. */
    if (state.lang !== 'fa') return fill(text, values);
    let out = FA[text];
    if (out === undefined) {
      for (const [re, replacement] of FA_PATTERNS) {
        if (re.test(text)) { out = text.replace(re, replacement); break; }
      }
    }
    if (out === undefined) return fill(text, values);  // unknown: show English paragraph
    return fill(out, values);
  }

  /** Substitute {name}-style fields; an absent key leaves its placeholder in place. */
  function fill(text, values) {
    if (!values) return text;
    return text.replace(/\{(\w+)\}/g, (m, k) => (k in values ? String(values[k]) : m));
  }

  /** Apply the theme; called from <head> so dark is in place before the first paint. */
  function applyTheme(theme) {
    state.theme = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.dataset.theme = state.theme;
    const meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) meta.content = state.theme;
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      const dark = state.theme === 'dark';
      const label = tt(dark ? 'Switch to light theme' : 'Switch to dark theme');
      btn.setAttribute('aria-label', label);
      btn.setAttribute('title', label);
      btn.setAttribute('aria-pressed', dark ? 'true' : 'false');
    }
  }

  function setTheme(theme) {
    applyTheme(theme);
    setCookie(COOKIE_THEME, state.theme);
    fetch('/api/prefs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme: state.theme }),
    }).catch(() => { /* the cookie is already set; the server copy is a nicety */ });
  }

  function toggleTheme() {
    setTheme(state.theme === 'dark' ? 'light' : 'dark');
  }

  /* The server renders the whole document in one language, so switching means a
     reload. The cookie is written first; the ?lang= flag makes the very first load
     right even if the browser drops the cookie. */
  function setLang(lang) {
    const next = normalize(lang);
    if (next === state.lang) return;
    setCookie(COOKIE_LANG, next);
    const url = new URL(window.location.href);
    url.searchParams.set('lang', next);
    window.location.replace(url.toString());
  }

  function toggleLang() {
    setLang(state.lang === 'fa' ? 'en' : 'fa');
  }

  /* ------------------------------------------------------------ view mode
   *
   * Simple and Advanced are a property of the whole app, not of one tab: Simple shows
   * only what the user put on the machine themselves, while Advanced also exposes
   * apt/dpkg packages. The switch lives in the tab row (see base.html) and both tab
   * scripts listen for the change rather than owning it.
   */

  /** Remember the mode for this browser, and repaint the switch. */
  function applyMode(mode) {
    state.mode = MODES.includes(mode) ? mode : 'simple';
    document.documentElement.dataset.mode = state.mode;
    document.querySelectorAll('.mode-btn').forEach(btn => {
      const on = btn.dataset.mode === state.mode;
      btn.classList.toggle('active', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    setCookie(COOKIE_MODE, state.mode);
    fetch('/api/prefs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: state.mode }),
    }).catch(() => { /* the cookie is already set; the server copy is a nicety */ });
  }

  /** Switch mode. Entering Advanced asks first; leaving it needs no ceremony. */
  function setMode(mode) {
    const next = MODES.includes(mode) ? mode : 'simple';
    if (next === state.mode) return;
    if (next === 'advanced' && !state.modeAllowed) return askAdvanced();
    applyMode(next);
    modeListeners.forEach(fn => fn(state.mode));
  }

  /* The safety gate. Advanced Mode lists libraries, drivers and core services next to
     applications, and removing the wrong one can leave the computer unable to start -
     so the first entry into it in a page view is confirmed, not assumed. */
  function askAdvanced() {
    modal({
      title: tt('Switch to Advanced Mode?'),
      html: `<p>${esc(tt('Advanced Mode also shows apt/dpkg packages, including critical '
        + 'system components. Removing essential packages may break your operating '
        + 'system.'))}</p>
           <div class="warn-box">${esc(tt('Proceed with caution. In this view you can '
        + 'see and remove libraries, drivers and core services — not just applications. '
        + 'A wrong removal on Linux can leave the computer unable to start.'))}</div>
           <p class="small muted">${esc(tt('Simple Mode shows only the apps you '
        + 'installed yourself. You can switch back at any time.'))}</p>`,
      buttons: [
        { label: tt('Stay in Simple Mode'), kind: 'ghost', onClick: closeModal },
        { label: tt('I understand, continue'), kind: 'danger', onClick: () => {
            state.modeAllowed = true;
            closeModal();
            applyMode('advanced');
            modeListeners.forEach(fn => fn(state.mode));
          } }
      ]
    });
  }

  return { state, tt, setLang, setTheme, toggleLang, toggleTheme, applyTheme, normalize,
           setMode, applyMode, onModeChange, askAdvanced };
})();

/** Shorthand used across the page scripts. */
function TT(text, values) { return SLPM.tt(text, values); }
