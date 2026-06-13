/**
 * Q3OS / SpyLink — shared frontend utilities
 */

(function () {
  'use strict';

  /** Initialize background audio controls */
  function initAudioControls() {
    const audio = document.getElementById('bg-audio');
    const btn = document.getElementById('mute-btn');
    const slider = document.getElementById('volume-slider');
    if (!audio || !btn || !slider) return;

    audio.volume = parseFloat(slider.value) || 1;
    btn.textContent = audio.muted ? '🔇' : '🔊';

    const kickstart = () => {
      audio.play().catch(() => {});
    };
    document.body.addEventListener('click', kickstart, { once: true });

    btn.addEventListener('click', () => {
      audio.muted = !audio.muted;
      btn.textContent = audio.muted ? '🔇' : '🔊';
      if (!audio.muted) audio.play().catch(() => {});
    });

    slider.addEventListener('input', (e) => {
      audio.volume = parseFloat(e.target.value);
      if (audio.muted && audio.volume > 0) {
        audio.muted = false;
        btn.textContent = '🔊';
        audio.play().catch(() => {});
      }
    });
  }

  /** Options modal for capture settings */
  function initOptionsModal() {
    const modal = document.getElementById('optionsModal');
    const openBtn = document.getElementById('openOptions');
    if (!modal || !openBtn) return;

    const closeBtn = document.getElementById('closeOptions');
    const doneBtn = document.getElementById('doneOptions');
    const selectAllBtn = document.getElementById('selectAll');

    const open = () => {
      modal.classList.add('is-open');
      modal.setAttribute('aria-hidden', 'false');
    };

    const close = () => {
      modal.classList.remove('is-open');
      modal.setAttribute('aria-hidden', 'true');
    };

    openBtn.addEventListener('click', open);
    if (closeBtn) closeBtn.addEventListener('click', close);
    if (doneBtn) doneBtn.addEventListener('click', close);

    if (selectAllBtn) {
      selectAllBtn.addEventListener('click', () => {
        modal.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
          cb.checked = true;
        });
      });
    }

    modal.addEventListener('click', (e) => {
      if (e.target === modal) close();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && modal.classList.contains('is-open')) close();
    });
  }

  /** Keep service alive ping */
  function initHealthPing() {
    if (!document.querySelector('[data-health-ping]')) return;
    setInterval(() => fetch('/ping').catch(() => {}), 10000);
  }

  /** Visit dashboard: selector + naming */
  function initVisitDashboard() {
    const select = document.getElementById('visitSelect');
    const panels = document.querySelectorAll('.visit-detail-panel');
    if (!select || !panels.length) return;

    const nameInput = document.getElementById('visitNameInput');
    const setNameBtn = document.getElementById('setVisitNameBtn');
    const names = {};

    function showPanel(idx) {
      panels.forEach((panel) => {
        panel.classList.toggle('is-active', panel.dataset.index === String(idx));
      });
    }

    select.value = '0';
    showPanel('0');

    select.addEventListener('change', () => {
      showPanel(select.value);
      if (nameInput) nameInput.value = names[select.value] || '';
    });

    if (setNameBtn && nameInput) {
      setNameBtn.addEventListener('click', () => {
        const idx = select.value;
        const custom = nameInput.value.trim();
        if (custom) {
          names[idx] = custom;
          select.options[idx].text = custom;
        }
      });
    }

    const code = document.body.dataset.trackCode;
    if (code) {
      setInterval(async () => {
        try {
          const res = await fetch(`/api/visit-metadata/${code}`);
          if (!res.ok) return;
          const { count } = await res.json();
          if (count > panels.length) window.location.reload();
        } catch (_) {}
      }, 5000);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    initAudioControls();
    initOptionsModal();
    initHealthPing();
    initVisitDashboard();
  });
})();
