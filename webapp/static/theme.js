// Appliqué avant le rendu (chargé dans <head>) pour éviter un flash de mauvais thème.
(() => {
  let theme = null;
  try { theme = localStorage.getItem('vs-theme'); } catch (e) { /* stockage indisponible */ }
  if (!theme) theme = window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  document.documentElement.dataset.theme = theme;
})();
