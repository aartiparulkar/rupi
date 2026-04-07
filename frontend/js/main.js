/* ============================================================
   RuPi — Main JavaScript
   ============================================================ */

'use strict';

// ── Utility ──────────────────────────────────────────────────
const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

// ── Navigation ───────────────────────────────────────────────
function initNav() {
  const nav = $('.nav');
  if (!nav) return;

  // Scroll behavior
  const onScroll = () => {
    nav.classList.toggle('scrolled', window.scrollY > 20);
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();

  // Hamburger toggle
  const hamburger = $('.nav-hamburger');
  const mobileMenu = $('.nav-mobile');
  if (hamburger && mobileMenu) {
    hamburger.addEventListener('click', () => {
      const open = hamburger.classList.toggle('open');
      mobileMenu.classList.toggle('open', open);
      document.body.style.overflow = open ? 'hidden' : '';
    });

    // Close on link click
    $$('.nav-mobile .nav-link').forEach(link => {
      link.addEventListener('click', () => {
        hamburger.classList.remove('open');
        mobileMenu.classList.remove('open');
        document.body.style.overflow = '';
      });
    });
  }

  // Active link highlight
  const currentPath = window.location.pathname.split('/').pop() || 'index.html';
  $$('.nav-link').forEach(link => {
    const href = link.getAttribute('href') || '';
    if (href === currentPath || href.endsWith(currentPath)) {
      link.classList.add('active');
    }
  });
}

// ── Scroll & Storytelling Reveal ──────────────────────────────
function initScrollObserver() {
  const elements = $$('.fade-in, .slide-up, [data-stagger]');
  if (!elements.length) return;

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry, i) => {
      if (entry.isIntersecting) {
        const delay = entry.target.dataset.delay || (entry.target.dataset.stagger ? entry.target.dataset.stagger * 100 : 0);
        setTimeout(() => {
          entry.target.classList.add('visible');
        }, delay);
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15, rootMargin: '0px 0px -50px 0px' });

  elements.forEach((el, i) => {
    observer.observe(el);
  });
}

// ── Toast Notifications ───────────────────────────────────────
function showToast(message, type = 'info', duration = 3500) {
  let container = $('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const icons = { success: '&#10003;', error: '&#10005;', info: '&#9432;', warning: '&#9888;' };
  const colors = {
    success: 'var(--accent)',
    error: 'var(--error)',
    info: 'var(--info)',
    warning: 'var(--warning)'
  };

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `
    <span style="color: ${colors[type]}; font-size: 1rem; flex-shrink:0;">${icons[type]}</span>
    <span>${message}</span>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.animation = 'toast-in 0.3s ease reverse';
    setTimeout(() => toast.remove(), 280);
  }, duration);
}

window.showToast = showToast;

// ── Animated Counter ──────────────────────────────────────────
function animateCounter(el) {
  const target = parseFloat(el.dataset.target);
  const prefix = el.dataset.prefix || '';
  const suffix = el.dataset.suffix || '';
  const duration = parseInt(el.dataset.duration || '1800');
  const decimals = el.dataset.decimals ? parseInt(el.dataset.decimals) : 0;

  const start = performance.now();

  const tick = (now) => {
    const elapsed = now - start;
    const progress = Math.min(elapsed / duration, 1);
    // Ease out quart
    const eased = 1 - Math.pow(1 - progress, 4);
    const value = eased * target;
    el.textContent = prefix + value.toFixed(decimals) + suffix;
    if (progress < 1) requestAnimationFrame(tick);
  };

  requestAnimationFrame(tick);
}

function initCounters() {
  const counters = $$('.stat-number, [data-target]');
  if (!counters.length) return;

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        if (!entry.target.dataset.target) {
          // Auto setup target if not set but is stat-number
          const val = entry.target.textContent.replace(/[^0-9.]/g, '');
          if (val) {
            entry.target.dataset.target = val;
            entry.target.dataset.prefix = entry.target.textContent.charAt(0) === '$' ? '$' : '';
            entry.target.dataset.suffix = entry.target.textContent.charAt(entry.target.textContent.length - 1) === '%' ? '%' : '';
          }
        }
        if (entry.target.dataset.target) animateCounter(entry.target);
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.5 });

  counters.forEach(c => observer.observe(c));
}

// ── Bar Chart Animation ───────────────────────────────────────
function initChartBars() {
  $$('.hcard-bar').forEach((bar, i) => {
    // don't replay animation if we've already initialised this bar
    if (bar.dataset.animated === 'true') return;
    const h = bar.dataset.height || Math.random() * 70 + 20;
    bar.dataset.animated = 'true';
    bar.style.height = '0%';
    setTimeout(() => {
      bar.style.transition = `height 0.6s cubic-bezier(0.34, 1.56, 0.64, 1)`;
      bar.style.height = h + '%';
    }, 400 + i * 80);
  });
}

// ── File Drop Zone ────────────────────────────────────────────
function initFileDropZones() {
  $$('.file-drop-zone').forEach(zone => {
    if (zone.dataset.apiUpload === 'true') return;
    const input = zone.querySelector('input[type="file"]');
    const fileList = zone.closest('.file-upload-wrapper')?.querySelector('.file-list');

    const handleFiles = (files) => {
      if (!files || !files.length) return;
      Array.from(files).forEach(file => {
        addFileItem(file, fileList);
      });
    };

    // Click to open
    zone.addEventListener('click', () => input && input.click());

    // Input change
    if (input) {
      input.addEventListener('change', (e) => {
        handleFiles(e.target.files);
      });
    }

    // Drag & drop
    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('drag-over');
    });

    zone.addEventListener('dragleave', () => {
      zone.classList.remove('drag-over');
    });

    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('drag-over');
      handleFiles(e.dataTransfer.files);
    });
  });
}

function addFileItem(file, container) {
  if (!container) return;

  const size = file.size < 1024 * 1024
    ? (file.size / 1024).toFixed(1) + ' KB'
    : (file.size / 1024 / 1024).toFixed(1) + ' MB';

  const ext = file.name.split('.').pop().toUpperCase();

  const item = document.createElement('div');
  item.className = 'file-item';
  item.innerHTML = `
    <span class="badge badge-green" style="font-size:0.7rem;padding:2px 8px;">${ext}</span>
    <span class="file-item-name">${file.name}</span>
    <span class="file-item-size">${size}</span>
    <button class="file-remove-btn" title="Remove" aria-label="Remove file">&times;</button>
  `;

  item.querySelector('.file-remove-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    item.remove();
  });

  container.appendChild(item);
  showToast(`Added: ${file.name}`, 'success', 2000);
}

// ── Progress Steps ────────────────────────────────────────────
function initProgressSteps() {
  $$('.progress-steps[data-active]').forEach(stepsEl => {
    const activeIdx = parseInt(stepsEl.dataset.active || '0');
    $$('.progress-step', stepsEl).forEach((step, i) => {
      if (i < activeIdx) step.classList.add('completed');
      else if (i === activeIdx) step.classList.add('active');
    });
  });
}

// ── Tabs ─────────────────────────────────────────────────────
function initTabs() {
  $$('[data-tabs]').forEach(tabGroup => {
    const tabButtons = $$('[data-tab-btn]', tabGroup);
    const tabPanels = $$('[data-tab-panel]', tabGroup);

    const switchTab = (targetId) => {
      tabButtons.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tabBtn === targetId);
        btn.setAttribute('aria-selected', btn.dataset.tabBtn === targetId);
      });
      tabPanels.forEach(panel => {
        const visible = panel.dataset.tabPanel === targetId;
        panel.style.display = visible ? '' : 'none';
        if (visible) {
          panel.style.animation = 'none';
          panel.offsetHeight; // reflow
          panel.style.animation = 'tab-fade 0.25s ease';
        }
      });
    };

    tabButtons.forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tabBtn));
    });

    // Activate first
    if (tabButtons.length) switchTab(tabButtons[0].dataset.tabBtn);
  });
}

// ── Tooltip ───────────────────────────────────────────────────
function initTooltips() {
  $$('[data-tooltip]').forEach(el => {
    const tip = document.createElement('div');
    tip.className = 'tooltip';
    tip.textContent = el.dataset.tooltip;
    tip.style.cssText = `
      position:absolute; background:var(--bg-card); border:1px solid var(--border-default);
      padding:6px 10px; border-radius:var(--radius-sm); font-size:0.78rem; color:var(--text-secondary);
      white-space:nowrap; pointer-events:none; z-index:9999; opacity:0;
      transition:opacity 0.15s ease; box-shadow:var(--shadow-card);
    `;
    document.body.appendChild(tip);

    const show = (e) => {
      const rect = el.getBoundingClientRect();
      tip.style.left = rect.left + rect.width / 2 - tip.offsetWidth / 2 + 'px';
      tip.style.top = rect.top - tip.offsetHeight - 8 + window.scrollY + 'px';
      tip.style.opacity = '1';
    };
    const hide = () => { tip.style.opacity = '0'; };

    el.addEventListener('mouseenter', show);
    el.addEventListener('mouseleave', hide);
  });
}

// ── Mini Sparkline ────────────────────────────────────────────
function drawSparkline(canvas, data, color = '#3ddc52') {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width, h = canvas.height;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;

  const pts = data.map((v, i) => ({
    x: (i / (data.length - 1)) * w,
    y: h - ((v - min) / range) * (h - 8) - 4
  }));

  ctx.clearRect(0, 0, w, h);

  // Fill
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, color + '33');
  grad.addColorStop(1, color + '00');

  ctx.beginPath();
  ctx.moveTo(pts[0].x, h);
  pts.forEach(p => ctx.lineTo(p.x, p.y));
  ctx.lineTo(pts[pts.length - 1].x, h);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // Line
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  pts.forEach(p => ctx.lineTo(p.x, p.y));
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.stroke();
}

window.drawSparkline = drawSparkline;

// ── Smooth Scroll ─────────────────────────────────────────────
function initSmoothScroll() {
  $$('a[href^="#"]').forEach(link => {
    link.addEventListener('click', (e) => {
      const id = link.getAttribute('href').slice(1);
      const target = document.getElementById(id);
      if (target) {
        e.preventDefault();
        const top = target.getBoundingClientRect().top + window.scrollY - 90;
        window.scrollTo({ top, behavior: 'smooth' });
      }
    });
  });
}

// ── Typing animation ──────────────────────────────────────────
function initTypingEffect() {
  $$('[data-typewriter]').forEach(el => {
    const words = el.dataset.typewriter.split('|');
    let wordIndex = 0, charIndex = 0, deleting = false;

    const tick = () => {
      const word = words[wordIndex];
      if (deleting) {
        el.textContent = word.slice(0, --charIndex);
        if (charIndex === 0) {
          deleting = false;
          wordIndex = (wordIndex + 1) % words.length;
          setTimeout(tick, 400);
          return;
        }
      } else {
        el.textContent = word.slice(0, ++charIndex);
        if (charIndex === word.length) {
          setTimeout(() => { deleting = true; tick(); }, 2200);
          return;
        }
      }
      setTimeout(tick, deleting ? 40 : 70);
    };

    tick();
  });
}

// ── Copy to Clipboard ─────────────────────────────────────────
function initCopyBtns() {
  $$('[data-copy]').forEach(btn => {
    btn.addEventListener('click', () => {
      const text = btn.dataset.copy;
      navigator.clipboard.writeText(text).then(() => {
        const orig = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = orig; }, 1500);
      });
    });
  });
}

// ── 3D Card Tilt Effect ───────────────────────────────────────
function initTiltCards() {
  $$('.tilt-card').forEach(card => {
    card.addEventListener('mousemove', (e) => {
      const rect = card.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      const centerX = rect.width / 2;
      const centerY = rect.height / 2;

      const rotateX = ((y - centerY) / centerY) * -5; // max 5 deg
      const rotateY = ((x - centerX) / centerX) * 5;

      card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateY(-4px)`;
    });

    card.addEventListener('mouseleave', () => {
      card.style.transform = `perspective(1000px) rotateX(0deg) rotateY(0deg) translateY(0)`;
      card.style.transition = 'transform 0.5s ease';
    });

    card.addEventListener('mouseenter', () => {
      card.style.transition = 'transform 0.1s ease'; // quick follow
    });
  });
}

// ── Floating AI Orb ───────────────────────────────────────────
function attachAIOrb() {
  if (document.getElementById('aiGlobalOrb')) return;
  const orb = document.createElement('div');
  orb.id = 'aiGlobalOrb';
  orb.innerHTML = `
    <div style="width:50px; height:50px; border-radius:50%; background:radial-gradient(circle at 30% 30%, rgba(79, 195, 247, 0.9), rgba(13, 26, 51, 0.9)); box-shadow: 0 0 20px rgba(79, 195, 247, 0.6); display:flex; align-items:center; justify-content:center; cursor:pointer; position:fixed; bottom:30px; right:30px; z-index:9999; animation: orbFloat 4s ease-in-out infinite, pulseGlow 2s infinite alternate;">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#e8f4fd" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
    </div>
    <style>
      @keyframes orbFloat { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-10px); } }
      @keyframes pulseGlow { from { box-shadow: 0 0 10px rgba(79, 195, 247, 0.4); } to { box-shadow: 0 0 25px rgba(79, 195, 247, 0.8); } }
    </style>
  `;
  document.body.appendChild(orb);

  orb.addEventListener('click', () => {
    showToast('RuPi AI Agent is analyzing your current view...', 'info');
  });
}

// ── Theme Toggle ──────────────────────────────────────────────
function initThemeToggle() {
  // remove toggle buttons entirely for now (demo requires consistent styling)
  const toggleBtn = document.getElementById('themeToggleBtn');
  const mobileToggleBtn = document.getElementById('themeToggleMobileBtn');
  if (toggleBtn) toggleBtn.style.display = 'none';
  if (mobileToggleBtn) mobileToggleBtn.style.display = 'none';

  // always use dark theme while preparing the presentation
  document.documentElement.setAttribute('data-theme', 'dark');
}

// ── Custom Fintech Canvas Background ──────────────────────────
function initFintechCanvas() {
  const canvas = document.getElementById('fintech-bg');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  let w, h;
  const resize = () => {
    w = canvas.width = window.innerWidth;
    h = canvas.height = window.innerHeight;
  };
  window.addEventListener('resize', resize);
  resize();

  const particles = [];
  const particleCount = Math.min(window.innerWidth / 15, 75); // Responsive nodes

  for (let i = 0; i < particleCount; i++) {
    particles.push({
      x: Math.random() * w,
      y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.4,
      vy: (Math.random() - 0.5) * 0.4,
      r: Math.random() * 2 + 1,
      isSymbol: Math.random() > 0.88 // Occasional Rupees
    });
  }

  const getThemeColors = () => {
    const isLight = document.documentElement.getAttribute('data-theme') === 'light';
    return {
      line: isLight ? 'rgba(79, 195, 247, 0.18)' : 'rgba(79, 195, 247, 0.1)',
      node: isLight ? 'rgba(13, 26, 51, 0.4)' : 'rgba(79, 195, 247, 0.4)',
      symbol: isLight ? 'rgba(13, 26, 51, 0.3)' : 'rgba(79, 195, 247, 0.25)'
    };
  };

  // Only animate if intersecting to save performance
  let ticking = true;
  const draw = () => {
    if (!ticking) return;
    ctx.clearRect(0, 0, w, h);
    const colors = getThemeColors();

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      p.x += p.vx;
      p.y += p.vy;

      if (p.x < 0 || p.x > w) p.vx *= -1;
      if (p.y < 0 || p.y > h) p.vy *= -1;

      if (p.isSymbol) {
        ctx.fillStyle = colors.symbol;
        ctx.font = '16px "DM Sans"';
        ctx.fillText('₹', p.x - 4, p.y + 4);
      } else {
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = colors.node;
        ctx.fill();
      }

      for (let j = i + 1; j < particles.length; j++) {
        const p2 = particles[j];
        const dist = (p.x - p2.x) ** 2 + (p.y - p2.y) ** 2;

        if (dist < 18000) {
          ctx.beginPath();
          ctx.moveTo(p.x, p.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.strokeStyle = colors.line;
          ctx.lineWidth = 1 - (dist / 18000);
          ctx.stroke();
        }
      }
    }
    requestAnimationFrame(draw);
  };

  // Pause animation when completely scrolled out of hero view
  const observer = new IntersectionObserver((entries) => {
    ticking = entries[0].isIntersecting;
    if (ticking) draw();
  });
  observer.observe(document.querySelector('.hero') || document.body);
}

// ── Init All ──────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initNav();
  initThemeToggle();
  initFintechCanvas();
  initScrollObserver();
  initCounters();
  initChartBars();
  initFileDropZones();
  initProgressSteps();
  initTabs();
  initTooltips();
  initSmoothScroll();
  initTypingEffect();
  initCopyBtns();
  initTiltCards();
  attachAIOrb();

  // Cinematic Video Fallback
  (function() {
    const vid = document.querySelector('.cinematic-video');
    if (!vid) return;
    vid.addEventListener('error', () => {
      vid.style.display = 'none';
      document.querySelector('.cinematic-bg').style.background =
        'radial-gradient(ellipse 80% 60% at 50% 0%, rgba(0,255,200,0.04) 0%, transparent 70%)';
    });
  })();
});

// CSS Keyframes injection for tab fade
const style = document.createElement('style');
style.textContent = `
@keyframes tab-fade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
`;
document.head.appendChild(style);
