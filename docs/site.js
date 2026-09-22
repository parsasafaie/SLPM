/* The two toggles, and the screenshots that follow them.
 *
 * The page is static (GitHub Pages), so there is no server to render a language.
 * Instead both languages are in the HTML and CSS shows one of them, which means the
 * text is correct on the first paint. What JavaScript adds is:
 *
 *   - remembering the choice in localStorage,
 *   - flipping <html dir> for Persian,
 *   - pointing every <img data-shot> at the matching screenshot, so a Persian page
 *     in dark mode shows the Persian dark screenshots,
 *   - and filling in the GitHub links.
 */

(function () {
  const root = document.documentElement;
  const KEY_THEME = 'slpm-site-theme';
  const KEY_LANG = 'slpm-site-lang';

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

  /* --------------------------------------------------------- screenshots */

  // Alt text is written here rather than in the markup so it follows the language.
  const ALT = {
    install: {
      en: 'The Install page: a box to drop a downloaded file into, and a list of the file types SLPM can install.',
      fa: 'صفحهٔ نصب: کادری برای رها کردن فایل دانلودشده و فهرستی از قالب‌هایی که SLPM می‌تواند نصب کند.',
    },
    apps: {
      en: 'The Installed Apps page in Simple mode, showing everyday applications with their icons, versions and Launch, Details and Remove buttons.',
      fa: 'صفحهٔ برنامه‌های نصب‌شده در حالت ساده، با آیکون و نسخهٔ برنامه‌های روزمره و دکمه‌های اجرا، جزئیات و حذف.',
    },
    advanced: {
      en: 'The Installed Apps page in Advanced mode, listing every installed package including libraries and system components.',
      fa: 'صفحهٔ برنامه‌های نصب‌شده در حالت پیشرفته، با فهرست همهٔ بسته‌های نصب‌شده از جمله کتابخانه‌ها و اجزای سیستمی.',
    },
    warning: {
      en: 'A warning dialog asking the reader to confirm before switching to Advanced mode, explaining that removing essential packages can break the system.',
      fa: 'پنجرهٔ هشدار که قبل از رفتن به حالت پیشرفته تأیید می‌خواهد و توضیح می‌دهد حذف بسته‌های حیاتی می‌تواند سیستم را از کار بیندازد.',
    },
  };

  function syncShots() {
    const lang = root.dataset.lang === 'fa' ? 'fa' : 'en';
    const theme = root.dataset.theme === 'dark' ? 'dark' : 'light';
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
    root.dataset.theme = theme;
    const meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) meta.content = theme;
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
      btn.setAttribute('title', theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
    }
    syncShots();
  }

  /* ----------------------------------------------------------- language */

  function applyLang(lang) {
    root.dataset.lang = lang;
    root.lang = lang;
    root.dir = lang === 'fa' ? 'rtl' : 'ltr';
    const btn = document.getElementById('lang-toggle');
    if (btn) btn.setAttribute('title', lang === 'fa' ? 'Switch to English' : 'تغییر به فارسی');
    syncShots();
  }

  /* -------------------------------------------------------------- wiring */

  applyTheme(root.dataset.theme === 'dark' ? 'dark' : 'light');
  applyLang(root.dataset.lang === 'fa' ? 'fa' : 'en');
  fillRepoLinks();

  const themeBtn = document.getElementById('theme-toggle');
  if (themeBtn) themeBtn.addEventListener('click', () => {
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    store(KEY_THEME, next);
  });

  const langBtn = document.getElementById('lang-toggle');
  if (langBtn) langBtn.addEventListener('click', () => {
    const next = root.dataset.lang === 'fa' ? 'en' : 'fa';
    applyLang(next);
    store(KEY_LANG, next);
  });
})();
