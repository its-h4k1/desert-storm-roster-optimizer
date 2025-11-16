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
