(function(){
  const navLinks = document.querySelectorAll('.admin-nav a');
  if (!navLinks.length) return;
  const current = location.pathname.split('/').pop() || 'index.html';
  navLinks.forEach((link) => {
    const href = link.getAttribute('href');
    if (!href) return;
    if (href === current || (href.endsWith('index.html') && current === '')) {
      link.classList.add('active');
    }
  });
})();

(function(){
  if (!window.dsroShared || typeof window.dsroShared.initAdminLayout !== 'function') return;
  window.dsroShared.initAdminLayout();
})();

// Admin-Key / Worker-Secret zentral aus shared.js lesen und aktualisieren
(function(){
  if (!window.dsroShared) return;
  const inputs = Array.from(document.querySelectorAll('#adminKey, #admin-key'));
  if (!inputs.length) return;
  inputs.forEach(input => {
    window.dsroShared.applyAdminKeyInput(input);
    window.addEventListener('load', () => window.dsroShared.saveAdminKey(input.value));
  });
})();
