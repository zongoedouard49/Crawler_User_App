/**
 * auth.js — gestion JWT, intercepteur API, affichage conditionnel selon rôle
 */

/* Icônes SVG inline : aucun emoji, aucune librairie externe. */
const ICON_PATHS = {
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M4 5.5v16M8 7h8M8 11h8"/>',
  link: '<path d="m10 13.5 4-4"/><path d="M7.5 17.5H6a4 4 0 0 1 0-8h3"/><path d="M16.5 6.5H18a4 4 0 0 1 0 8h-3"/>',
  download: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M4 20h16"/>',
  upload: '<path d="M12 21V9"/><path d="m7 14 5-5 5 5"/><path d="M4 4h16"/>',
  heart: '<path d="M20.8 8.7c0 5.1-8.8 10.2-8.8 10.2S3.2 13.8 3.2 8.7A4.7 4.7 0 0 1 12 6.1a4.7 4.7 0 0 1 8.8 2.6Z"/>',
  search: '<circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4.5 4.5"/>',
  eye: '<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.5"/>',
  file: '<path d="M6 2.8h8l4 4V21H6z"/><path d="M14 2.8V7h4M8.5 11h7M8.5 14.5h7M8.5 18h4"/>',
  package: '<path d="m4 7 8-4 8 4-8 4-8-4Z"/><path d="M4 7v10l8 4 8-4V7M12 11v10"/>',
  merge: '<path d="M6 4v5a3 3 0 0 0 3 3h6a3 3 0 0 1 3 3v5"/><path d="m15 17 3 3 3-3M9 7 6 4 3 7"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/>',
  sun: '<circle cx="12" cy="12" r="3.5"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z"/>',
  user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 21a7 7 0 0 1 14 0"/>',
  crown: '<path d="m3 7 4 3 5-6 5 6 4-3-2 12H5L3 7Z"/><path d="M5 19h14"/>',
  login: '<path d="M14 4h5v16h-5M11 8l4 4-4 4M15 12H3"/>',
  logout: '<path d="M10 4H5v16h5M14 8l4 4-4 4M18 12H7"/>',
};

function icon(name, className = 'icon') {
  const path = ICON_PATHS[name] || ICON_PATHS.file;
  return `<svg class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}

function hydrateIcons(root = document) {
  root.querySelectorAll('[data-icon]').forEach(el => {
    el.innerHTML = icon(el.dataset.icon, 'icon');
  });
}

const Auth = {
  getToken: () => localStorage.getItem('auth_token'),
  getUser: () => {
    try { return JSON.parse(localStorage.getItem('auth_user') || 'null'); } catch { return null; }
  },
  isLoggedIn: () => !!localStorage.getItem('auth_token'),
  isAdmin: () => {
    const u = Auth.getUser();
    return u && u.role === 'admin';
  },
  setToken(token, user) {
    localStorage.setItem('auth_token', token);
    if (user) localStorage.setItem('auth_user', JSON.stringify(user));
  },
  logout() {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('auth_user');
    window.location.href = '/login';
  },
  // Renouvelle le token via POST /auth/refresh ; retourne true si succès
  async refresh() {
    try {
      const token = Auth.getToken();
      if (!token) return false;
      const r = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      });
      if (!r.ok) return false;
      const data = await r.json();
      Auth.setToken(data.access_token, { username: data.username, role: data.role });
      console.log('[Auth] Token renouvelé');
      return true;
    } catch { return false; }
  },
};

// ── Refresh automatique : renouvelle 15 min avant expiration ─────
(function _scheduleAutoRefresh() {
  // Durée du token côté serveur = 8h → on rafraîchit toutes les 7h30
  const REFRESH_INTERVAL_MS = (8 * 60 - 30) * 60 * 1000;
  setInterval(async () => {
    if (Auth.isLoggedIn()) {
      const ok = await Auth.refresh();
      if (!ok) Auth.logout();
    }
  }, REFRESH_INTERVAL_MS);
})();

/**
 * API helper avec token JWT automatique.
 * Pour les routes publiques (GET /files, thumbnails), pas de token requis.
 */
const API = {
  _headers(extra = {}) {
    const h = { 'Content-Type': 'application/json', ...extra };
    const token = Auth.getToken();
    if (token) h['Authorization'] = `Bearer ${token}`;
    return h;
  },
  async _fetch(method, path, body, isFormData = false, _retry = true) {
    const opts = { method, headers: isFormData ? {} : this._headers() };
    if (isFormData) {
      const token = Auth.getToken();
      if (token) opts.headers['Authorization'] = `Bearer ${token}`;
    }
    if (body) opts.body = isFormData ? body : JSON.stringify(body);
    const r = await fetch('/api' + path, opts);
    if (r.status === 401) {
      // Tente un refresh une seule fois avant de déconnecter
      if (_retry) {
        const ok = await Auth.refresh();
        if (ok) return API._fetch(method, path, body, isFormData, false);
      }
      Auth.logout();
      return;
    }
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw err;
    }
    if (r.status === 204) return null;
    return r.json();
  },
  get: (path) => API._fetch('GET', path),
  post: (path, body) => API._fetch('POST', path, body),
  put: (path, body) => API._fetch('PUT', path, body),
  patch: (path, body) => API._fetch('PATCH', path, body),
  delete: (path) => API._fetch('DELETE', path),
  postForm: (path, formData) => API._fetch('POST', path, formData, true),
};

/**
 * Met à jour l'interface selon l'état d'authentification.
 * - Affiche/masque les éléments marqués data-auth="required" ou data-auth="admin"
 * - Met à jour la topbar
 */
function applyAuthUI() {
  const loggedIn = Auth.isLoggedIn();
  const isAdmin = Auth.isAdmin();
  const user = Auth.getUser();

  // Éléments visibles seulement si connecté
  document.querySelectorAll('[data-auth="required"]').forEach(el => {
    el.style.display = loggedIn ? '' : 'none';
  });
  // Éléments visibles seulement si admin
  document.querySelectorAll('[data-auth="admin"]').forEach(el => {
    el.style.display = isAdmin ? '' : 'none';
  });
  // Éléments visibles seulement si NON connecté
  document.querySelectorAll('[data-auth="guest"]').forEach(el => {
    el.style.display = loggedIn ? 'none' : '';
  });

  // Topbar user info
  const userInfo = document.getElementById('topbar-user');
  if (userInfo) {
    const themeBtn = `<button class="btn-theme" id="theme-toggle-btn" onclick="toggleTheme()" title="Changer de thème">${icon('sun')}</button>`;
    if (loggedIn && user) {
      userInfo.innerHTML = `
        ${themeBtn}
        <span class="topbar-username">
          <span class="role-badge role-${user.role}">${icon(user.role === 'admin' ? 'crown' : 'user')}</span>
          ${user.username}
        </span>
        <button class="btn btn-danger btn-sm" onclick="Auth.logout()">${icon('logout')} Déconnexion</button>
      `;
    } else {
      userInfo.innerHTML = `${themeBtn}<a href="/login" class="btn btn-primary btn-sm">${icon('login')} Se connecter</a>`;
    }
    // Appliquer le thème sauvegardé
    _applyTheme(localStorage.getItem('theme') || 'dark');
  }

  // Onglets de navigation — masquer crawl/headers si non connecté
  const navCrawl = document.querySelector('[data-nav="crawl"]');
  const navHeaders = document.querySelector('[data-nav="headers"]');
  if (navCrawl) navCrawl.style.display = loggedIn ? '' : 'none';
  if (navHeaders) navHeaders.style.display = loggedIn ? '' : 'none';
}

/* ── Theme toggle ─────────────────────────────────────────────── */
function _applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('theme', theme);
  const btn = document.getElementById('theme-toggle-btn');
  if (btn) btn.innerHTML = icon(theme === 'dark' ? 'sun' : 'moon');
}

function toggleTheme() {
  const cur = localStorage.getItem('theme') || 'dark';
  _applyTheme(cur === 'dark' ? 'light' : 'dark');
}

// Appliquer immédiatement au chargement (avant DOMContentLoaded)
(function() {
  const t = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', t);
})();

document.addEventListener('DOMContentLoaded', () => hydrateIcons());
