/* LinkHarvest — bibliothèque de fichiers, sans authentification côté interface. */

const ICON_PATHS = {
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M4 5.5v16M8 7h8M8 11h8"/>',
  search: '<circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4.5 4.5"/>',
  download: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M4 20h16"/>',
  upload: '<path d="M12 21V9"/><path d="m7 14 5-5 5 5"/><path d="M4 4h16"/>',
  eye: '<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.5"/>',
  file: '<path d="M6 2.8h8l4 4V21H6z"/><path d="M14 2.8V7h4M8.5 11h7M8.5 14.5h7M8.5 18h4"/>',
  package: '<path d="m4 7 8-4 8 4-8 4-8-4Z"/><path d="M4 7v10l8 4 8-4V7M12 11v10"/>',
  merge: '<path d="M6 4v5a3 3 0 0 0 3 3h6a3 3 0 0 1 3 3v5"/><path d="m15 17 3 3 3-3M9 7 6 4 3 7"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/>',
  sun: '<circle cx="12" cy="12" r="3.5"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z"/>',
};

function icon(name, className = 'icon') {
  const path = ICON_PATHS[name] || ICON_PATHS.file;
  return `<svg class="${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}

function hydrateIcons(root = document) {
  root.querySelectorAll('[data-icon]').forEach(node => {
    node.innerHTML = icon(node.dataset.icon);
  });
}

const API = {
  async request(method, path, body) {
    const token = localStorage.getItem('auth_token');
    const options = {
      method,
      headers: {
        ...(body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    };
    if (body) options.body = JSON.stringify(body);
    const response = await fetch(`/api${path}`, options);
    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw error;
    }
    if (response.status === 204) return null;
    return response.json();
  },
  get(path) { return this.request('GET', path); },
  post(path, body) { return this.request('POST', path, body); },
};

let files = [];
let selectedIds = new Set();
let pagination = { page: 1, total_pages: 1, total: 0 };
let activeSearch = '';
let searchTimer = null;
let mergeFiles = [];

function sizeStr(bytes) {
  if (!bytes) return null;
  return bytes > 1048576
    ? `${(bytes / 1048576).toFixed(1)} MB`
    : `${(bytes / 1024).toFixed(1)} KB`;
}

function fileExtension(filename = '') {
  const match = filename.match(/\.([a-z0-9]{1,8})$/i);
  return match ? match[1].toUpperCase() : 'FILE';
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
  }[char]));
}

function previewMarkup(filename, hasThumbnail, thumbPath) {
  const safeName = escapeHtml(filename);
  const type = fileExtension(filename);
  if (hasThumbnail && thumbPath) {
    return `<div class="preview-frame">
      <img src="${thumbPath}" alt="Aperçu de ${safeName}" loading="lazy"
        onerror="this.closest('.file-card-thumb').classList.add('preview-fallback'); this.remove()">
      <div class="preview-overlay"><span>${icon('eye')} Aperçu</span></div>
    </div>`;
  }
  return `<div class="thumb-placeholder">
    <span class="placeholder-icon">${icon('file')}</span>
    <strong>${type}</strong>
    <small>Aperçu indisponible</small>
  </div>`;
}

function fileSource(file) {
  return file.file_type === 'uploaded' ? 'uploaded' : 'found';
}

function filePaths(file) {
  const source = fileSource(file);
  const prefix = source === 'uploaded' ? `/api/upload/${file.id}` : `/api/files/${file.id}`;
  return {
    view: `${prefix}/view`,
    serve: `${prefix}/serve`,
    thumb: `${prefix}/thumbnail`,
  };
}

function buildCard(file) {
  const source = fileSource(file);
  const key = `${source}-${file.id}`;
  const paths = filePaths(file);
  const selected = selectedIds.has(key);
  const size = sizeStr(file.file_size);
  const status = source === 'uploaded'
    ? `${icon('upload')} Uploadé`
    : `${icon('download')} Disponible`;

  return `
    <article class="file-card ${selected ? 'selected' : ''}" data-card-key="${key}" tabindex="0">
      <div class="file-card-check">
        <input type="checkbox" ${selected ? 'checked' : ''} aria-label="Sélectionner ${escapeHtml(file.filename)}">
      </div>
      <div class="file-card-thumb">${previewMarkup(file.filename, file.has_thumbnail, paths.thumb)}</div>
      <div class="file-card-info">
        <div class="file-card-name" title="${escapeHtml(file.filename)}">${escapeHtml(file.filename)}</div>
        <div class="file-card-meta">
          ${size ? `<span class="meta-size">${icon('package')} ${size}</span>` : ''}
          <span class="meta-dl">${status}</span>
        </div>
        <div class="card-actions">
          <button class="btn btn-sm" data-action="view" title="Ouvrir l’aperçu">${icon('eye')} Voir</button>
          <a class="btn btn-sm btn-secondary" href="${paths.serve}" download title="Télécharger">${icon('download')}</a>
        </div>
      </div>
    </article>`;
}

function renderFiles() {
  const container = document.getElementById('file-cards');
  const count = document.getElementById('file-count');
  if (!container) return;

  if (count) {
    count.textContent = pagination.total ? `${pagination.total} fichier${pagination.total > 1 ? 's' : ''}` : '';
  }
  if (!files.length) {
    container.innerHTML = `
      <div class="cards-empty">
        <span class="empty-icon">${icon('file')}</span>
        <strong>${activeSearch ? 'Aucun résultat' : 'Aucun fichier disponible'}</strong>
        <span>${activeSearch ? 'Essayez avec un autre terme.' : 'Les fichiers apparaîtront ici.'}</span>
      </div>`;
    return;
  }
  container.innerHTML = files.map(buildCard).join('');
  bindCardEvents(container);
}

function bindCardEvents(container) {
  container.querySelectorAll('.file-card').forEach(card => {
    const key = card.dataset.cardKey;
    const file = files.find(item => `${fileSource(item)}-${item.id}` === key);
    if (!file) return;

    card.addEventListener('click', event => {
      if (event.target.closest('button, a, input')) return;
      toggleSelection(key);
    });
    card.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        toggleSelection(key);
      }
    });
    card.querySelector('input').addEventListener('change', () => toggleSelection(key));
    card.querySelector('[data-action="view"]').addEventListener('click', () => {
      window.open(filePaths(file).view, '_blank', 'noopener');
    });
  });
}

function toggleSelection(key) {
  if (selectedIds.has(key)) selectedIds.delete(key);
  else selectedIds.add(key);
  renderFiles();
  updateSelectionUI();
}

function updateSelectionUI() {
  const hint = document.getElementById('selection-hint');
  const mergeButton = document.getElementById('merge-selected');
  const count = selectedIds.size;
  if (hint) hint.textContent = count ? `${count} sélectionné${count > 1 ? 's' : ''}` : 'Sélectionnez des fichiers pour les fusionner';
  if (mergeButton) mergeButton.disabled = count < 2;
}

function paginationRange(current, total) {
  const result = [1];
  const start = Math.max(2, current - 2);
  const end = Math.min(total - 1, current + 2);
  if (start > 2) result.push('…');
  for (let page = start; page <= end; page++) result.push(page);
  if (end < total - 1) result.push('…');
  if (total > 1) result.push(total);
  return result;
}

function renderPagination() {
  const node = document.getElementById('file-pagination');
  if (!node || pagination.total_pages <= 1) {
    if (node) node.innerHTML = '';
    return;
  }

  node.innerHTML = `
    <button class="pg-btn" data-page="1" ${pagination.page === 1 ? 'disabled' : ''} aria-label="Première page">«</button>
    <button class="pg-btn" data-page="${pagination.page - 1}" ${pagination.page === 1 ? 'disabled' : ''} aria-label="Page précédente">‹</button>
    ${paginationRange(pagination.page, pagination.total_pages).map(page => page === '…'
      ? '<span class="pg-ellipsis">…</span>'
      : `<button class="pg-btn ${page === pagination.page ? 'active' : ''}" data-page="${page}">${page}</button>`
    ).join('')}
    <button class="pg-btn" data-page="${pagination.page + 1}" ${pagination.page === pagination.total_pages ? 'disabled' : ''} aria-label="Page suivante">›</button>
    <button class="pg-btn" data-page="${pagination.total_pages}" ${pagination.page === pagination.total_pages ? 'disabled' : ''} aria-label="Dernière page">»</button>
    <span class="pg-info">Page ${pagination.page} / ${pagination.total_pages}</span>`;

  node.querySelectorAll('[data-page]').forEach(button => {
    button.addEventListener('click', () => loadFiles(activeSearch, Number(button.dataset.page)));
  });
}

async function loadFiles(query = activeSearch, page = 1) {
  activeSearch = query.trim();
  const params = new URLSearchParams({ page, page_size: 20 });
  if (activeSearch) params.set('keywords', activeSearch);

  const container = document.getElementById('file-cards');
  if (container) container.classList.add('is-loading');
  try {
    const data = await API.get(`/files/downloaded?${params.toString()}`);
    files = data.items || [];
    pagination = {
      page: data.page || page,
      total_pages: data.total_pages || 1,
      total: data.total || files.length,
    };
    renderFiles();
    renderPagination();
    updateSelectionUI();
  } catch (error) {
    console.error(error);
    if (container) {
      container.innerHTML = `<div class="cards-empty error-state"><strong>Impossible de charger les fichiers</strong><span>Vérifiez la connexion au serveur.</span></div>`;
    }
  } finally {
    if (container) container.classList.remove('is-loading');
  }
}

function handleSearchInput(event) {
  const value = event.target.value;
  const clearButton = document.getElementById('clear-search');
  if (clearButton) clearButton.hidden = !value;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadFiles(value, 1), 220);
}

function getSelectedFiles() {
  return [...selectedIds]
    .map(key => files.find(file => `${fileSource(file)}-${file.id}` === key))
    .filter(Boolean);
}

function openMergeModal() {
  mergeFiles = getSelectedFiles();
  if (mergeFiles.length < 2) return;
  document.getElementById('merge-info').textContent =
    `${mergeFiles.length} fichiers sélectionnés : ${mergeFiles.map(file => file.filename).join(', ')}`;
  document.getElementById('merge-filename').value = 'fusion.pdf';
  const modal = document.getElementById('modal-merge');
  modal.hidden = false;
  modal.classList.add('open');
  document.getElementById('merge-filename').focus();
}

function closeMergeModal() {
  const modal = document.getElementById('modal-merge');
  modal.classList.remove('open');
  modal.hidden = true;
}

async function confirmMerge() {
  if (mergeFiles.length < 2) return;
  const button = document.getElementById('merge-confirm-btn');
  const output = document.getElementById('merge-filename').value.trim() || 'fusion.pdf';
  button.disabled = true;
  button.innerHTML = `${icon('clock')} Fusion…`;

  try {
    const response = await fetch('/api/files/merge', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(localStorage.getItem('auth_token')
          ? { Authorization: `Bearer ${localStorage.getItem('auth_token')}` }
          : {}),
      },
      body: JSON.stringify({
        files: mergeFiles.map(file => ({ id: file.id, file_type: fileSource(file) })),
        output_filename: output,
      }),
    });
    if (!response.ok) throw await response.json().catch(() => ({}));
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = output;
    link.click();
    URL.revokeObjectURL(link.href);
    toast('Fichier fusionné téléchargé', 'success');
    closeMergeModal();
  } catch (error) {
    toast(error.detail || 'Erreur de fusion', 'error');
  } finally {
    button.disabled = false;
    button.innerHTML = `${icon('merge')} Fusionner et télécharger`;
  }
}

function toast(message, type = 'info') {
  const container = document.getElementById('toasts');
  const item = document.createElement('div');
  item.className = `toast ${type}`;
  item.textContent = message;
  container.appendChild(item);
  setTimeout(() => item.remove(), 3500);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem('theme', theme);
  const button = document.getElementById('theme-toggle-btn');
  if (button) {
    button.innerHTML = icon(theme === 'dark' ? 'sun' : 'moon');
    button.title = theme === 'dark' ? 'Passer au thème clair' : 'Passer au thème sombre';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  hydrateIcons();
  applyTheme(localStorage.getItem('theme') || 'dark');

  document.getElementById('theme-toggle-btn').addEventListener('click', () => {
    applyTheme((localStorage.getItem('theme') || 'dark') === 'dark' ? 'light' : 'dark');
  });
  document.getElementById('file-search').addEventListener('input', handleSearchInput);
  document.getElementById('clear-search').addEventListener('click', () => {
    const input = document.getElementById('file-search');
    input.value = '';
    document.getElementById('clear-search').hidden = true;
    loadFiles('', 1);
    input.focus();
  });
  document.getElementById('merge-selected').addEventListener('click', openMergeModal);
  document.getElementById('close-merge').addEventListener('click', closeMergeModal);
  document.getElementById('cancel-merge').addEventListener('click', closeMergeModal);
  document.getElementById('merge-confirm-btn').addEventListener('click', confirmMerge);
  document.getElementById('modal-merge').addEventListener('click', event => {
    if (event.target.id === 'modal-merge') closeMergeModal();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeMergeModal();
  });

  updateSelectionUI();
  loadFiles('', 1);
});