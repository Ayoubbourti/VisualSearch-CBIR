// Page de détail : champs de transformation + histogrammes (Chart.js) colorés avec les vraies teintes.
document.addEventListener('DOMContentLoaded', () => {
  const op = document.getElementById('op');
  if (op) {
    const sync = () => document.querySelectorAll('.params').forEach(p => {
      p.style.display = p.dataset.for.split(' ').includes(op.value) ? '' : 'none';
    });
    op.addEventListener('change', sync);
    sync();
  }

  const node = document.getElementById('descriptors-data');
  if (!node || typeof Chart === 'undefined') return;
  const D = JSON.parse(node.textContent);
  const css = getComputedStyle(document.documentElement);
  const ink = css.getPropertyValue('--muted').trim() || '#A8A4D6';
  const grid = css.getPropertyValue('--line').trim() || 'rgba(167,155,255,.16)';
  Chart.defaults.color = ink;
  Chart.defaults.font.family = "'DM Sans', system-ui, sans-serif";

  let tick = function (value, i) { return this.getLabelForValue(value).startsWith('P') ? (i % 2 ? '' : this.getLabelForValue(value)) : (i % 9 === 4 ? HUES[(i / 9) | 0] : ''); };
  const HUES = ['Orange', 'Jaune', 'Vert', 'Turquoise', 'Azur', 'Bleu', 'Violet', 'Rose'];
  const bar = (id, labels, data, colors) => new Chart(document.getElementById(id), {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: colors, borderRadius: 3, borderSkipped: false }] },
    options: { maintainAspectRatio: false, animation: { duration: 500 },
      plugins: { legend: { display: false } },
      scales: { x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: false, callback: tick } },
                y: { beginAtZero: true, grid: { color: grid } } } },
  });

  // 72 bins (teinte × saturation × valeur) dans l'ordre d'aplatissement de numpy.histogramdd :
  // chaque barre prend la couleur HSV qu'elle représente.
  const labels = [], colors = [];
  for (let h = 0; h < 8; h++) for (let s = 0; s < 3; s++) for (let v = 0; v < 3; v++) {
    labels.push(`H${h} S${s} V${v}`);
    colors.push(`hsl(${(h + 0.5) * 45}, ${Math.round(((s + 0.5) / 3) * 100)}%, ${Math.round(18 + ((v + 0.5) / 3) * 55)}%)`);
  }
  bar('chHist', labels, D.color.histogram.values, colors);

  const lbp = D.texture.lbp_histogram;
  bar('chLbp', lbp.map((_, i) => 'P' + i), lbp,
      lbp.map((_, i) => `hsl(${190 + i * 14}, 85%, 62%)`));
});
