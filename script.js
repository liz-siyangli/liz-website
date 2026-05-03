/* ============================================================
   NAV — transparent → cream on scroll
   ============================================================ */
const nav = document.getElementById('nav');
const NAV_THRESHOLD = 60;

function updateNav() {
  if (window.scrollY > NAV_THRESHOLD) {
    nav.classList.add('scrolled');
  } else {
    nav.classList.remove('scrolled');
  }
}
window.addEventListener('scroll', updateNav, { passive: true });
updateNav();

/* ============================================================
   HAMBURGER MENU
   ============================================================ */
const hamburger = document.getElementById('hamburger');
const mobileMenu = document.getElementById('mobileMenu');

hamburger.addEventListener('click', () => {
  hamburger.classList.toggle('open');
  mobileMenu.classList.toggle('open');
});

document.querySelectorAll('.mobile-link').forEach(link => {
  link.addEventListener('click', () => {
    hamburger.classList.remove('open');
    mobileMenu.classList.remove('open');
  });
});

/* ============================================================
   SCROLL REVEAL — IntersectionObserver
   ============================================================ */
const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
      revealObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.12 });

document.querySelectorAll('.reveal').forEach(el => {
  revealObserver.observe(el);
});

/* ============================================================
   COUNT-UP — hero stat numbers
   ============================================================ */
function countUp(el) {
  const target = parseInt(el.dataset.target, 10);
  const suffix = el.dataset.suffix || '';
  const duration = 1400;
  const start = performance.now();

  function tick(now) {
    const elapsed = now - start;
    const progress = Math.min(elapsed / duration, 1);
    // ease out cubic
    const eased = 1 - Math.pow(1 - progress, 3);
    const current = Math.floor(eased * target);

    if (target >= 1000) {
      el.textContent = current.toLocaleString() + suffix;
    } else {
      el.textContent = current + suffix;
    }

    if (progress < 1) {
      requestAnimationFrame(tick);
    } else {
      if (target >= 1000) {
        el.textContent = target.toLocaleString() + suffix;
      } else {
        el.textContent = target + suffix;
      }
    }
  }
  requestAnimationFrame(tick);
}

// Trigger count-up when stat card enters view
const statCard = document.querySelector('.stat-card');
if (statCard) {
  const countObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        document.querySelectorAll('.count-up').forEach(el => countUp(el));
        countObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.5 });
  countObserver.observe(statCard);
}

/* ============================================================
   SMOOTH SCROLL OFFSET — account for fixed nav height
   ============================================================ */
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', function (e) {
    const targetId = this.getAttribute('href');
    if (targetId === '#') return;
    const target = document.querySelector(targetId);
    if (!target) return;
    e.preventDefault();
    const navH = nav.offsetHeight;
    const targetTop = target.getBoundingClientRect().top + window.scrollY - navH;
    window.scrollTo({ top: targetTop, behavior: 'smooth' });
  });
});

/* ============================================================
   CUSTOM CURSOR
   ============================================================ */
(function () {
  if (!window.matchMedia('(pointer:fine)').matches) return;

  const html = document.documentElement;
  html.classList.add('has-cursor');

  const ring = document.createElement('div');
  ring.className = 'c-cursor';
  const dot = document.createElement('div');
  dot.className = 'c-cursor-dot';
  document.body.appendChild(ring);
  document.body.appendChild(dot);

  let mx = window.innerWidth / 2, my = window.innerHeight / 2;
  let rx = mx, ry = my;
  let started = false;

  document.addEventListener('mousemove', e => {
    mx = e.clientX; my = e.clientY;
    // Exact dot follows immediately
    dot.style.left = mx + 'px';
    dot.style.top  = my + 'px';
    if (!started) {
      rx = mx; ry = my;
      ring.classList.add('visible');
      dot.classList.add('visible');
      started = true;
    }
  }, { passive: true });

  document.addEventListener('mouseleave', () => {
    ring.classList.remove('visible');
    dot.classList.remove('visible');
  });
  document.addEventListener('mouseenter', () => {
    if (started) {
      ring.classList.add('visible');
      dot.classList.add('visible');
    }
  });

  (function animRing() {
    rx += (mx - rx) * 0.11;
    ry += (my - ry) * 0.11;
    ring.style.left = rx + 'px';
    ring.style.top  = ry + 'px';
    requestAnimationFrame(animRing);
  })();

  const hoverSel = 'a, button, [role="button"], .door-card, .project-card, .edu-card, .contact-card, .story-card';
  document.querySelectorAll(hoverSel).forEach(el => {
    el.addEventListener('mouseenter', () => ring.classList.add('hover'));
    el.addEventListener('mouseleave', () => ring.classList.remove('hover'));
  });
})();

/* ============================================================
   DOOR PARALLAX on mousemove
   ============================================================ */
document.querySelectorAll('.door-card').forEach(card => {
  const bg = card.querySelector('.door-bg');
  if (!bg) return;
  card.addEventListener('mousemove', e => {
    const r = card.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5;
    const y = (e.clientY - r.top)  / r.height - 0.5;
    bg.style.transform = `scale(1.06) translate(${x * 18}px,${y * 12}px)`;
  });
  card.addEventListener('mouseleave', () => {
    bg.style.transform = '';
  });
});

/* ============================================================
   PAGE TRANSITIONS
   ============================================================ */
document.querySelectorAll('a[href]').forEach(link => {
  const href = link.getAttribute('href');
  if (!href || href.startsWith('#') || href.startsWith('mailto:') ||
      href.startsWith('tel:') || link.target === '_blank') return;
  link.addEventListener('click', e => {
    e.preventDefault();
    document.body.classList.add('page-out');
    setTimeout(() => { window.location.href = href; }, 260);
  });
});
