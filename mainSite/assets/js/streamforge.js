/**
 * StreamForge product page — scoped JS
 * All state is local to this IIFE. No globals polluted.
 * Safe to drop into loonlabs.io alongside other scripts.
 */
(function () {
  'use strict';

  /* ── Particle canvas in hero ──────────────────────────────────────────── */
  function initCanvas() {
    const canvas = document.getElementById('sfCanvas');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    let W, H, particles, animId;

    function resize() {
      const hero = canvas.closest('.sf-hero');
      W = canvas.width  = hero.offsetWidth;
      H = canvas.height = hero.offsetHeight;
    }

    function mkParticle() {
      return {
        x: Math.random() * W,
        y: Math.random() * H,
        r: Math.random() * 1.5 + 0.3,
        vx: (Math.random() - 0.5) * 0.25,
        vy: (Math.random() - 0.5) * 0.25,
        alpha: Math.random() * 0.5 + 0.1,
      };
    }

    function init() {
      resize();
      particles = Array.from({ length: 120 }, mkParticle);
    }

    function draw() {
      ctx.clearRect(0, 0, W, H);

      // Draw connections
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const a = particles[i], b = particles[j];
          const dx = a.x - b.x, dy = a.y - b.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 120) {
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.strokeStyle = `rgba(99,102,241,${(1 - dist / 120) * 0.12})`;
            ctx.lineWidth = 1;
            ctx.stroke();
          }
        }
      }

      // Draw particles
      particles.forEach(p => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(139,92,246,${p.alpha})`;
        ctx.fill();

        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0 || p.x > W) p.vx *= -1;
        if (p.y < 0 || p.y > H) p.vy *= -1;
      });

      animId = requestAnimationFrame(draw);
    }

    init();
    draw();

    let resizeTimer;
    window.addEventListener('resize', () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => { resize(); }, 150);
    });

    // Stop animation when page is hidden (perf)
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        cancelAnimationFrame(animId);
      } else {
        animId = requestAnimationFrame(draw);
      }
    });
  }

  /* ── Smooth scroll for anchor links inside #sf-page ──────────────────── */
  function initSmoothScroll() {
    const page = document.getElementById('sf-page');
    if (!page) return;

    page.querySelectorAll('a[href^="#sf-"]').forEach(link => {
      link.addEventListener('click', e => {
        const target = document.querySelector(link.getAttribute('href'));
        if (!target) return;
        e.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  }

  /* ── Scroll-reveal: fade elements in on scroll ────────────────────────── */
  function initReveal() {
    const page = document.getElementById('sf-page');
    if (!page || !('IntersectionObserver' in window)) return;

    const targets = page.querySelectorAll(
      '.sf-step, .sf-feat, .sf-why-card, .sf-inv-card, .sf-perf, .sf-comp, .sf-tier'
    );

    targets.forEach(el => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(20px)';
      el.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
    });

    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.style.opacity = '1';
          entry.target.style.transform = 'translateY(0)';
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });

    targets.forEach(el => observer.observe(el));
  }

  /* ── Typed terminal effect on code blocks ─────────────────────────────── */
  function initTypedCode() {
    const page = document.getElementById('sf-page');
    if (!page || !('IntersectionObserver' in window)) return;

    const codeBlocks = page.querySelectorAll('.sf-code pre code');

    codeBlocks.forEach(block => {
      const original = block.innerHTML;
      let played = false;

      const observer = new IntersectionObserver(entries => {
        if (entries[0].isIntersecting && !played) {
          played = true;
          observer.disconnect();

          block.innerHTML = '';
          block.style.opacity = '1';

          // Strip HTML tags to get plain text, then replay with original HTML
          const lines = original.split('\n');
          let lineIdx = 0;

          function showNextLine() {
            if (lineIdx >= lines.length) return;
            const existing = block.innerHTML;
            block.innerHTML = existing + (lineIdx > 0 ? '\n' : '') + lines[lineIdx];
            lineIdx++;
            setTimeout(showNextLine, lineIdx === 1 ? 0 : 60 + Math.random() * 40);
          }

          showNextLine();
        }
      }, { threshold: 0.5 });

      observer.observe(block.closest('.sf-code'));
    });
  }

  /* ── Counter animation for traction numbers ────────────────────────────── */
  function initCounters() {
    const page = document.getElementById('sf-page');
    if (!page || !('IntersectionObserver' in window)) return;

    const items = page.querySelectorAll('.sf-traction__num, .sf-hero .sf-stat__num');

    function animateCounter(el) {
      const raw = el.textContent.trim();
      // Only animate pure numbers (skip "$0.02", "<100ms", etc.)
      if (!/^\d[\d,+k]*$/.test(raw.replace(/,/g, ''))) return;

      const numStr = raw.replace(/[k+]/g, '');
      const target = parseInt(numStr.replace(/,/g, ''), 10);
      if (isNaN(target)) return;

      const suffix = raw.replace(/[\d,]/g, ''); // "k+", "+", ""
      const duration = 1000;
      const start = performance.now();

      function tick(now) {
        const t = Math.min((now - start) / duration, 1);
        const ease = 1 - Math.pow(1 - t, 3);
        const current = Math.round(ease * target);
        el.textContent = current.toLocaleString() + suffix;
        if (t < 1) requestAnimationFrame(tick);
      }

      requestAnimationFrame(tick);
    }

    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          animateCounter(entry.target);
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.5 });

    items.forEach(el => observer.observe(el));
  }

  /* ── Boot ─────────────────────────────────────────────────────────────── */
  function boot() {
    initCanvas();
    initSmoothScroll();
    initReveal();
    initTypedCode();
    initCounters();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

})();
