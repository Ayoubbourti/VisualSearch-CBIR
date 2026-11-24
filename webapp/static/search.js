// Logique client de la page de recherche. L'état (itération, images pertinentes) vit ici : le serveur est sans état.
document.addEventListener('DOMContentLoaded', () => {
  const app = document.getElementById('app');
  if (!app) return;
  const $ = id => document.getElementById(id);
  const escapeHtml = value => String(value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
  const state = { iteration: 0, relevant: new Set(), retrieved: [] };
  const CHECK = '<svg class="icon" aria-hidden="true"><use href="#i-check"/></svg>';
  const EXT = '<svg class="icon" aria-hidden="true"><use href="#i-external"/></svg>';

  // POST JSON avec jeton CSRF ; lève une Error portant le message du serveur en cas d'échec.
  async function post(url, body) {
    const r = await fetch(url, { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': app.dataset.csrf },
      body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `Erreur ${r.status}`);
    return data;
  }

  const updateButtons = () => {
    $('nSel').textContent = state.relevant.size;
    $('btnFeedback').disabled = state.relevant.size === 0;
    $('btnReset').disabled = state.retrieved.length === 0;
  };

  // Une barre par bloc de descripteurs : > 1 = le bloc est jugé plus discriminant que la moyenne.
  function renderWeights(weights, updated) {
    const box = $('weights');
    box.hidden = !updated;
    if (!updated) { box.innerHTML = ''; return; }
    const max = Math.max(...Object.values(weights), 1.5);
    box.innerHTML = '<h3>Ce que le système a appris</h3><p class="muted" style="font-size:.85rem">Poids relatif de chaque famille de descripteurs (1 = neutre).</p>' +
      Object.entries(weights).map(([name, v], i) =>
        `<div class="wrow g${i}"><span>${escapeHtml(name)}</span><div class="wbar"><i style="width:${(v / max) * 100}%"></i></div><b>${v.toFixed(2)}</b></div>`).join('');
  }

  function toggle(el) {
    const id = Number(el.dataset.id);
    state.relevant.has(id) ? state.relevant.delete(id) : state.relevant.add(id);
    el.classList.toggle('relevant', state.relevant.has(id));
    el.setAttribute('aria-pressed', state.relevant.has(id));
    updateButtons();
  }

  function render(data) {
    state.iteration = data.iteration;
    state.retrieved = data.results.map(r => r.id);
    const dists = data.results.map(r => r.distance);
    const lo = Math.min(...dists), hi = Math.max(...dists);
    // Les images déjà jugées pertinentes restent marquées si elles réapparaissent.
    $('results').innerHTML = data.results.map(r => {
      const sim = hi > lo ? Math.round((1 - (r.distance - lo) / (hi - lo)) * 100) : 100;
      const on = state.relevant.has(r.id);
      return `<figure class="thumb result ${on ? 'relevant' : ''}" data-id="${r.id}" tabindex="0" role="button" aria-pressed="${on}" aria-label="Résultat ${r.rank}, distance ${r.distance}">
        <span class="rank">#${r.rank}</span><span class="tick">${CHECK}</span>
        <img src="${escapeHtml(r.thumb)}" alt="${escapeHtml(r.name)}">
        <div class="sim" title="Similarité relative"><i style="width:${sim}%"></i></div>
        <figcaption><span title="${escapeHtml(r.name)}">d = ${r.distance}</span>
          <a href="${escapeHtml(r.url)}" target="_blank" rel="noopener" title="Ouvrir ${escapeHtml(r.name)}" aria-label="Ouvrir ${escapeHtml(r.name)}">${EXT}</a></figcaption></figure>`;
    }).join('');
    document.querySelectorAll('.result').forEach(el => {
      el.addEventListener('click', ev => { if (!ev.target.closest('a')) toggle(el); });
      el.addEventListener('keydown', ev => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(el); }
      });
    });
    renderWeights(data.weights, data.updated);
    $('status').textContent = data.iteration === 0
      ? 'Recherche simple : distance euclidienne, poids uniformes.'
      : `Itération ${data.iteration} : ${state.relevant.size} image${state.relevant.size > 1 ? 's' : ''} pertinente${state.relevant.size > 1 ? 's' : ''} prise${state.relevant.size > 1 ? 's' : ''} en compte.`;
    updateButtons();
  }

  const run = async fn => {
    try { $('status').textContent = 'Calcul en cours…'; render(await fn()); }
    catch (e) { $('status').textContent = e.message; }
  };
  const k = () => Number($('k').value) || 24;
  const qid = Number(app.dataset.query);

  $('btnSearch').onclick = () => { state.relevant.clear(); run(() => post(app.dataset.search, { query_id: qid, k: k() })); };
  $('btnFeedback').onclick = () => run(() => post(app.dataset.feedback, {
    query_id: qid, k: k(), iteration: state.iteration,
    relevant_ids: [...state.relevant], retrieved_ids: state.retrieved }));
  $('btnReset').onclick = () => {
    state.relevant.clear(); state.retrieved = []; $('results').innerHTML = '';
    $('weights').hidden = true; $('weights').innerHTML = ''; $('status').textContent = ''; updateButtons();
  };
});
