/* The two toggles, the localized metadata and controls, and the screenshots that follow them.
 *
 * The page is static (GitHub Pages), so there is no server to render a language.
 * Instead both languages are in the HTML and CSS shows one of them, which means the
 * text is correct on the first paint. What JavaScript adds is:
 *
 *   - remembering the choice in localStorage,
 *   - flipping <html dir> for Persian,
 *   - switching the document title, description, control labels and screenshots,
 *   - and filling in the GitHub links.
 */

(function () {
  const root = document.documentElement;
  const KEY_THEME = 'slpm-site-theme';
  const KEY_LANG = 'slpm-site-lang';

  const PAGE_META = {
    en: {
      title: 'SLPM — Simple Linux Package Manager',
      description: 'Install and remove Linux software without the terminal. SLPM is a local app that runs on your own computer.',
    },
    fa: {
      title: 'SLPM — مدیر بستهٔ سادهٔ لینوکس',
      description: 'SLPM یک برنامهٔ وب محلی برای نصب، مشاهده، اجرا و حذف نرم‌افزارهای لینوکس است و روی کامپیوتر خودتان اجرا می‌شود.',
    },
  };

  /* Where the READMEs live. GitHub Pages serves only the contents of docs/, so a
     link to ../README.md would 404 — the READMEs have to be linked on github.com.
     The repository is worked out from the Pages URL (https://user.github.io/REPO/
     becomes https://github.com/user/REPO), falling back to FALLBACK_REPO when the
     page is opened from somewhere that is not GitHub Pages, such as a local preview. */
  const FALLBACK_REPO = 'https://github.com/parsasafaie/SLPM';

  function repoUrl() {
    const host = location.hostname;
    if (host.endsWith('.github.io')) {
      const user = host.slice(0, -'.github.io'.length);
      const repo = location.pathname.split('/').filter(Boolean)[0];
      if (user && repo) return `https://github.com/${user}/${repo}`;
    }
    return FALLBACK_REPO;
  }

  function fillRepoLinks() {
    const base = repoUrl();
    document.querySelectorAll('[data-repo]').forEach(el => {
      const file = el.dataset.repo;           // e.g. "README.fa.md"
      el.href = file ? `${base}/blob/main/${file}` : base;
    });
  }

  function store(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* private mode */ }
  }

  function currentLang() {
    return root.dataset.lang === 'fa' ? 'fa' : 'en';
  }

  function currentTheme() {
    return root.dataset.theme === 'dark' ? 'dark' : 'light';
  }

  function setLabel(id, label) {
    const el = document.getElementById(id);
    if (!el) return;
    el.setAttribute('aria-label', label);
    el.setAttribute('title', label);
  }

  function syncControlLabels() {
    const lang = currentLang();
    const theme = currentTheme();
    setLabel('lang-toggle', lang === 'fa' ? 'تغییر زبان به انگلیسی' : 'Switch to Persian');
    setLabel('theme-toggle', theme === 'dark'
      ? (lang === 'fa' ? 'تغییر به تم روشن' : 'Switch to light theme')
      : (lang === 'fa' ? 'تغییر به تم تیره' : 'Switch to dark theme'));
  }

  /* --------------------------------------------------------- screenshots */

  // Alt text is written here rather than in the markup so it follows the language.
  const ALT = {
    install: {
      en: 'The SLPM Install page: controls for choosing a local file or a download link, the file drop box, and examples of supported file types.',
      fa: 'صفحهٔ نصب SLPM؛ گزینه‌های انتخاب فایل محلی یا دانلود از لینک، ناحیهٔ رهاکردن فایل و چند نوع فایل پشتیبانی‌شده را نشان می‌دهد.',
    },
    apps: {
      en: 'The Installed Apps page in Simple Mode, showing only the programs SLPM identifies as user-installed, with the Simple/Advanced switch in the top bar.',
      fa: 'صفحهٔ برنامه‌های نصب‌شده در حالت ساده؛ فقط برنامه‌هایی را نشان می‌دهد که SLPM تشخیص داده است کاربر آن‌ها را نصب کرده است. کلید حالت ساده/پیشرفته در نوار بالا دیده می‌شود.',
    },
    startup: {
      en: 'The Startup Apps page in Advanced Mode, listing user and packaged startup entries with each entry’s enabled state and a control for turning entries off.',
      fa: 'صفحهٔ برنامه‌های استارتاپ در حالت پیشرفته؛ موردهای کاربری و موردهای ارائه‌شده توسط بستهٔ سیستمی را همراه با وضعیت فعال یا غیرفعال و کنترل غیرفعال‌کردن نشان می‌دهد.',
    },
    advanced: {
      en: 'The Installed Apps page in Advanced Mode, listing installed apt/dpkg packages, including libraries, system components and essential packages.',
      fa: 'صفحهٔ برنامه‌های نصب‌شده در حالت پیشرفته؛ بسته‌های نصب‌شدهٔ apt/dpkg، از جمله کتابخانه‌ها، اجزای سیستمی و بسته‌های حیاتی سیستم را فهرست می‌کند.',
    },
    warning: {
      en: 'A warning asking for confirmation before entering Advanced Mode and explaining that removing essential packages can break the operating system.',
      fa: 'پنجرهٔ هشدار برای تأیید ورود به حالت پیشرفته؛ توضیح می‌دهد حذف بستهٔ حیاتی سیستم می‌تواند سیستم‌عامل را از کار بیندازد.',
    },
  };

  function syncShots() {
    const lang = currentLang();
    const theme = currentTheme();
    document.querySelectorAll('img[data-shot]').forEach(img => {
      const name = img.dataset.shot;
      // Relative path: the site is served from a subdirectory on GitHub Pages.
      const src = `screenshots/${name}-${lang}-${theme}.png`;
      if (img.getAttribute('src') !== src) img.setAttribute('src', src);
      const alt = ALT[name];
      if (alt) img.setAttribute('alt', alt[lang]);
    });
  }

  /* -------------------------------------------------------------- theme */

  function applyTheme(theme) {
    root.dataset.theme = theme === 'dark' ? 'dark' : 'light';
    const meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) meta.content = currentTheme();
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.setAttribute('aria-pressed', currentTheme() === 'dark' ? 'true' : 'false');
    syncControlLabels();
    syncShots();
  }

  /* ----------------------------------------------------------- language */

  function applyLang(lang) {
    const next = lang === 'fa' ? 'fa' : 'en';
    root.dataset.lang = next;
    root.lang = next;
    root.dir = next === 'fa' ? 'rtl' : 'ltr';

    const meta = PAGE_META[next];
    document.title = meta.title;
    const description = document.getElementById('site-description');
    if (description) description.setAttribute('content', meta.description);

    syncControlLabels();
    syncShots();
  }

  /* -------------------------------------------------------------- wiring */

  applyTheme(currentTheme());
  applyLang(currentLang());
  fillRepoLinks();

  const themeBtn = document.getElementById('theme-toggle');
  if (themeBtn) themeBtn.addEventListener('click', () => {
    const next = currentTheme() === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    store(KEY_THEME, next);
  });

  const langBtn = document.getElementById('lang-toggle');
  if (langBtn) langBtn.addEventListener('click', () => {
    const next = currentLang() === 'fa' ? 'en' : 'fa';
    applyLang(next);
    store(KEY_LANG, next);
  });
})();
