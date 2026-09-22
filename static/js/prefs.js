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
  const LANGS = ['en', 'fa'];

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
  };

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
      'دیگر به SLPM دسترسی نیست. آیا سرور هنوز در حال اجراست؟',
    'The server sent a reply SLPM could not read.':
      'پاسخی که سرور فرستاد قابل خواندن نبود.',

    /* --------------------------------------------------------- install.js */
    'Working…': 'در حال انجام…',
    'This can take a minute. Keep this window open.':
      'ممکن است یک دقیقه طول بکشد. این پنجره را باز نگه دارید.',
    'Checking the file…': 'در حال بررسی فایل…',
    'Skip': 'رد کردن',
    'Done': 'انجام شد',
    'Installation failed': 'نصب انجام نشد',
    'Close': 'بستن',
    'Finishing up…': 'در حال تمام کردن…',
    'Installing…': 'در حال نصب…',
    'Package operations can take a while. Keep this window open.':
      'عملیات بسته‌ها ممکن است طول بکشد. این پنجره را باز نگه دارید.',
    'Already busy': 'در حال انجام کار دیگری است',
    'No file chooser': 'برنامهٔ انتخاب فایل وجود ندارد',

    /* ------------------------------------------------------------ apps.js */
    'Every installed package, including system components.':
      'همهٔ بسته‌های نصب‌شده، شامل اجزای سیستمی.',
    'Everyday applications on this computer.':
      'برنامه‌های روزمرهٔ این کامپیوتر.',
    'Switch to Advanced Mode?': 'به حالت پیشرفته برویم؟',
    'Stay in Simple Mode': 'در حالت ساده بمان',
    'I understand, continue': 'می‌فهمم، ادامه بده',
    'Reading installed programs…': 'در حال خواندن برنامه‌های نصب‌شده…',
    'Reading the package database…': 'در حال خواندن پایگاه‌دادهٔ بسته‌ها…',
    'Could not list apps': 'فهرست برنامه‌ها خوانده نشد',
    'Could not list packages': 'فهرست بسته‌ها خوانده نشد',
    'No applications matched.': 'برنامه‌ای مطابقت نداشت.',
    'Nothing matched “{q}”.': 'چیزی با «{q}» مطابقت نداشت.',
    'Showing the first 600 of {n} items — narrow the search to see the rest.':
      'نمایش ۶۰۰ مورد اول از {n} مورد — برای دیدن بقیه جست‌وجو را محدود کنید.',
    'system': 'سیستمی',
    'os': 'سیستم‌عامل',
    'Launch': 'اجرا',
    'Launching': 'در حال اجرا',
    'Could not launch': 'اجرا نشد',
    'Details': 'جزئیات',
    'Remove': 'حذف',
    'Cancel': 'انصراف',
    'Reading details…': 'در حال خواندن جزئیات…',
    'Version': 'نسخه',
    'Size': 'اندازه',
    'Section': 'بخش',
    'Maintainer': 'نگه‌دارنده',
    'Homepage': 'صفحهٔ اصلی',
    'Description': 'توضیحات',
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
    'half-installed': 'نیمه‌نصب',
    'half-configured': 'نیمه‌تنظیم',
    'unpacked': 'باز شده',
    'triggers awaited': 'در انتظار triggers',
    'triggers pending': 'triggers در صف',
    'config files only': 'فقط فایل‌های تنظیمات',
    'installed (held)': 'نصب‌شده (نگه‌داشته‌شده)',
    'not installed': 'نصب نیست',
    'This package is essential to the system and cannot be removed.':
      'این بسته برای سیستم حیاتی است و حذف نمی‌شود.',
    'Remove {name}?': '{name} حذف شود؟',
    'Package: {name}': 'بسته: {name}',
    'You will be asked for your admin password to make this change.':
      'برای اعمال این تغییر رمز مدیر از شما پرسیده می‌شود.',
    'Removing {name}…': 'در حال حذف {name}…',
    /* The server's busy label (app.py) uses the same sentence without the ellipsis. */
    'Removing {name}': 'در حال حذف {name}',
    'Removed': 'حذف شد',
    'Could not remove': 'حذف نشد',
    'Remove {name}': 'حذف {name}',
    'Remove package': 'حذف بسته',
    'Backups are not created by SLPM.': 'SLPM از چیزی نسخهٔ پشتیبان نمی‌سازد.',
    'Type the package name to confirm': 'برای تأیید نام بسته را تایپ کنید',
    'Also delete configuration files (purge)':
      'فایل‌های تنظیمات هم پاک شوند (purge)',
    'Not confirmed': 'تأیید نشد',
    'The name did not match.': 'نام وارد‌شده یکسان نبود.',
    'Clean unused dependencies?': 'وابستگی‌های بی‌استفاده پاک‌سازی شوند؟',
    'Clean up': 'پاک‌سازی',
    'Cleaning up…': 'در حال پاک‌سازی…',
    'Cleaned up': 'پاک‌سازی شد',
    'Cleanup failed': 'پاک‌سازی انجام نشد',

    /* --------------------------------------------------------- startup.js */
    'No applications matched.': 'برنامه‌ای مطابقت نداشت.',
    'Could not list startup apps': 'فهرست برنامه‌های هنگام ورود خوانده نشد',
    'Reading startup programs…': 'در حال خواندن برنامه‌های هنگام ورود…',
    'yours': 'مال شما',
    'turned off': 'خاموش',
    'Saving…': 'در حال ذخیره…',
    'Saved': 'ذخیره شد',
    'Could not change this': 'تغییر انجام نشد',
    'Turn off {name}': 'خاموش‌کردن {name}',
    'Turn off {name}?': '{name} خاموش شود؟',
    'Turn off': 'خاموش کن',
    ['This app will no longer start when you log in. The application stays installed '
      + 'and can still be opened from your menu.']:
      'این برنامه دیگر هنگام ورود شما اجرا نمی‌شود. خود برنامه نصب‌شده می‌ماند و '
      + 'همچنان از منوی شما باز می‌شود.',
    'You can add it again later from Add startup app.':
      'بعداً می‌توانید آن را از «افزودن برنامهٔ هنگام ورود» دوباره اضافه کنید.',
    'Add a startup app': 'افزودن برنامهٔ هنگام ورود',
    'Reading installed apps…': 'در حال خواندن برنامه‌های نصب‌شده…',
    ['No installed application with a launch command was found.']:
      'هیچ برنامهٔ نصب‌شده‌ای با فرمان اجرا پیدا نشد.',
    ['Pick the application that should start when you log in.']:
      'برنامه‌ای را انتخاب کنید که هنگام ورود شما اجرا شود.',
    'Adding…': 'در حال افزودن…',
    'Added': 'افزوده شد',
    'Could not add': 'افزوده نشد',
    'No startup programs matched.': 'برنامهٔ هنگام ورودی مطابقت نداشت.',

    /* The theme button's own label. The language button is labelled in the template,
       because the server knows the current language while it renders the page. */
    'Switch to dark theme': 'تغییر به تم تاریک',
    'Switch to light theme': 'تغییر به تم روشن',

    /* --- Warning boxes and dialogs, where the browser prints the whole paragraph.
           Each of these is one key written as a bracketed concatenation. --- */
    ['This is a system component. Removing it can stop programs from working or '
      + 'prevent the computer from starting.']:
      'این یک جزء سیستمی است. حذف آن می‌تواند برنامه‌ها را از کار بیندازد یا مانع '
      + 'روشن‌شدن کامپیوتر شود.',
    ['The system package for this app will be uninstalled. Your personal files are '
      + 'not touched.']:
      'بستهٔ سیستمی این برنامه حذف می‌شود. به فایل‌های شخصی شما دستی زده نمی‌شود.',
    ['The snap package will be removed, together with the icon it added to your menu. '
      + 'Your personal files are not touched.']:
      'بستهٔ snap حذف می‌شود، همراه با میان‌بری که به منوی شما اضافه کرده بود. به '
      + 'فایل‌های شخصی شما دستی زده نمی‌شود.',
    ['The Flatpak app will be removed, together with the icon it added to your menu. '
      + 'Your personal files are not touched.']:
      'برنامهٔ Flatpak حذف می‌شود، همراه با میان‌بری که به منوی شما اضافه کرده بود. '
      + 'به فایل‌های شخصی شما دستی زده نمی‌شود.',
    'The shortcut and the installed files for this app will be deleted.':
      'میان‌بر و فایل‌های نصب‌شدهٔ این برنامه حذف می‌شوند.',
    ['Advanced Mode displays critical system components. Removing essential packages '
      + 'may break your operating system.']:
      'حالت پیشرفته اجزای حیاتی سیستم را نشان می‌دهد. حذف بسته‌های حیاتی می‌تواند '
      + 'سیستم‌عامل شما را از کار بیندازد.',
    ['Proceed with caution. In this view you can see and remove libraries, drivers '
      + 'and core services — not just applications. Windows programs never expose '
      + 'this, because on Linux a wrong removal can leave the computer unable to '
      + 'start.']:
      'با احتیاط ادامه دهید. در این نما کتابخانه‌ها، درایورها و سرویس‌های اصلی را '
      + 'می‌بینید و می‌توانید حذفشان کنید — نه فقط برنامه‌ها. نرم‌افزارهای ویندوزی '
      + 'هرگز این را نشان نمی‌دهند، چون در لینوکس یک حذف اشتباه می‌تواند کامپیوتر را '
      + 'از روشن‌شدن باز دارد.',
    'App and package name searches still work normally.':
      'جست‌وجوی نام برنامه‌ها و بسته‌ها مثل قبل کار می‌کند.',
    ['Packages that were installed automatically as dependencies and are no longer '
      + 'needed by anything will be removed.']:
      'بسته‌هایی که خودکار به‌عنوان وابستگی نصب شده‌اند و دیگر چیزی به آن‌ها نیاز '
      + 'ندارد حذف می‌شوند.',
    ['Review is not possible from here; SLPM runs <code>apt-get autoremove</code> '
      + 'with the default settings.']:
      'از اینجا امکان بازبینی نیست؛ SLPM دستور <code>apt-get autoremove</code> را '
      + 'با تنظیمات پیش‌فرض اجرا می‌کند.',
    ['<strong>This package is essential to the system.</strong> Removing it can make '
      + 'the computer unable to start and can break package management permanently, '
      + 'so nothing else can be installed or removed afterwards. This is very likely '
      + 'to destroy this installation of Linux. There is no undo.']:
      '<strong>این بسته برای سیستم حیاتی است.</strong> حذف آن می‌تواند کامپیوتر را '
      + 'از روشن‌شدن باز دارد و مدیریت بسته‌ها را برای همیشه خراب کند، طوری که بعد از '
      + 'آن هیچ چیز دیگری نصب یا حذف نشود. احتمال زیادی هست که این نصب لینوکس از بین '
      + 'برود. راه بازگشتی وجود ندارد.',
    ['You are about to remove a system component. Other programs may depend on it, '
      + 'and on some packages the computer may not start afterwards. Continue only '
      + 'if you know what this package does.']:
      'شما در حال حذف یک جزء سیستمی هستید. برنامه‌های دیگر ممکن است به آن وابسته '
      + 'باشند و در مورد بعضی بسته‌ها ممکن است کامپیوتر بعد از آن روشن نشود. فقط اگر '
      + 'می‌دانید این بسته چه‌کار می‌کند ادامه دهید.',
    ['You are about to remove a package. Other programs may depend on it - check the '
      + 'details first if you are unsure what it does.']:
      'شما در حال حذف یک بسته هستید. برنامه‌های دیگر ممکن است به آن وابسته باشند؛ '
      + 'اگر مطمئن نیستید چه‌کار می‌کند اول جزئیاتش را ببینید.',
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
     '$1 نصب شد. یک میان‌بر در منوی برنامه‌های شما هست.'],
    [/^(.+) was added to your applications menu\.$/,
     '$1 به منوی برنامه‌های شما اضافه شد.'],
    [/^Removed (.+) and its shortcut\.$/, '$1 و میان‌برش حذف شدند.'],
    [/^File not found: (.+)$/, 'فایل پیدا نشد: $1'],
    [/^(.+) is no longer in (.+)\. Extract the archive again\.$/,
     '$1 دیگر در $2 نیست. آرشیو را دوباره استخراج کنید.'],
    /* The startup-app messages (slpm/autostart.py) carry a program name, so one pattern
       covers every name rather than one catalog row per application. */
    [/^(.+) already starts when you log in\.$/, '$1 از قبل هنگام ورود شما اجرا می‌شود.'],
    [/^(.+) will now start when you log in\.$/, 'از این پس $1 هنگام ورود شما اجرا می‌شود.'],
    [/^(.+) will no longer start when you log in\.$/,
     'از این پس $1 هنگام ورود شما اجرا نمی‌شود.'],
    [/^(.+) was removed from your startup apps\.$/,
     '$1 از برنامه‌های هنگام ورود شما حذف شد.'],
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

  return { state, tt, setLang, setTheme, toggleLang, toggleTheme, applyTheme, normalize };
})();

/** Shorthand used across the page scripts. */
function TT(text, values) { return SLPM.tt(text, values); }
