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
  const toggle = document.querySelector('.sidebar-toggle');
  const close = document.querySelector('.sidebar-close');
  const overlay = document.querySelector('.admin-overlay');
  if (!toggle && !close && !overlay) return;

  const openSidebar = () => document.body.classList.add('sidebar-open');
  const closeSidebar = () => document.body.classList.remove('sidebar-open');

  toggle?.addEventListener('click', openSidebar);
  close?.addEventListener('click', closeSidebar);
  overlay?.addEventListener('click', closeSidebar);

  window.addEventListener('resize', () => {
    if (window.innerWidth >= 1200) {
      closeSidebar();
    }
  });
})();
