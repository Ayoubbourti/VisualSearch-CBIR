// Comportements globaux (aucun script inline : compatible avec la CSP « script-src 'self' »).
document.addEventListener('DOMContentLoaded', () => {
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  // --- Confirmation : data-confirm="..." sur un formulaire ou un bouton
  document.addEventListener('submit', ev => {
    const msg = ev.target.dataset && ev.target.dataset.confirm;
    if (msg && !confirm(msg)) ev.preventDefault();
  });
  document.addEventListener('click', ev => {
    const btn = ev.target.closest('button[data-confirm]');
    if (btn && !confirm(btn.dataset.confirm)) ev.preventDefault();
  });

  // --- Thème clair / sombre (mémorisé dans le navigateur)
  const root = document.documentElement;
  const paintTheme = () => {
    const light = root.dataset.theme === 'light';
    $$('[data-theme-toggle] use').forEach(u => u.setAttribute('href', light ? '#i-moon' : '#i-sun'));
    $$('[data-theme-label]').forEach(l => { l.textContent = light ? 'Thème sombre' : 'Thème clair'; });
  };
  $$('[data-theme-toggle]').forEach(b => b.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
    try { localStorage.setItem('vs-theme', root.dataset.theme); } catch (e) { /* ignoré */ }
    paintTheme();
  }));
  paintTheme();

  // --- Tri : soumission automatique
  $$('[data-autosubmit]').forEach(s => s.addEventListener('change', () => s.form.submit()));

  // --- Sélection multiple dans la galerie
  const picks = $$('.pick');
  const label = document.querySelector('[data-sel-label]');
  const refresh = () => {
    const n = picks.filter(c => c.checked).length;
    picks.forEach(c => c.closest('.thumb').classList.toggle('selected', c.checked));
    if (label) label.textContent = n ? `${n} sélectionnée${n > 1 ? 's' : ''}` : 'Tout sélectionner';
  };
  $$('[data-select-all]').forEach(box => box.addEventListener('change', () => {
    $$(box.dataset.selectAll).forEach(c => { c.checked = box.checked; });
    refresh();
  }));
  picks.forEach(c => c.addEventListener('change', refresh));

  // --- Zone de dépôt d'images
  $$('[data-dropzone]').forEach(zone => {
    const input = zone.querySelector('input[type=file]');
    const title = zone.querySelector('[data-dz-title]');
    const hint = zone.querySelector('[data-dz-hint]');
    const submit = zone.querySelector('[data-dz-submit]');
    const update = () => {
      const files = [...input.files];
      submit.disabled = files.length === 0;
      if (!files.length) return;
      const mb = files.reduce((t, f) => t + f.size, 0) / 1048576;
      title.textContent = `${files.length} fichier${files.length > 1 ? 's' : ''} prêt${files.length > 1 ? 's' : ''} à importer`;
      hint.textContent = `${mb.toFixed(1)} Mo au total. Choisissez une catégorie puis cliquez sur Importer.`;
    };
    input.addEventListener('change', update);
    ['dragenter', 'dragover'].forEach(t => zone.addEventListener(t, e => { e.preventDefault(); zone.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(t => zone.addEventListener(t, e => { e.preventDefault(); zone.classList.remove('over'); }));
    zone.addEventListener('drop', e => {
      if (e.dataTransfer && e.dataTransfer.files.length) { input.files = e.dataTransfer.files; update(); }
    });
    zone.addEventListener('submit', () => { submit.disabled = true; submit.textContent = 'Import en cours…'; });
  });
});
