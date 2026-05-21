/* glossary.js — Click-to-open popovers for DOCSIS term explanations */

(function () {
  'use strict';

  // Single shared popover appended to body (escapes overflow:hidden + transform)
  var overlay = document.createElement('div');
  overlay.className = 'glossary-popover';
  overlay.id = 'glossary-popover-overlay';
  overlay.setAttribute('role', 'tooltip');
  document.body.appendChild(overlay);

  var activeHint = null;
  var activeOpenedByFocus = false;

  function closeAll() {
    overlay.style.display = 'none';
    overlay.classList.remove('above', 'dashboard-meta-popover');
    overlay.style.removeProperty('--glossary-arrow-left');
    activeOpenedByFocus = false;
    if (activeHint) {
      activeHint.classList.remove('open');
      activeHint.removeAttribute('aria-describedby');
      activeHint.setAttribute('aria-expanded', 'false');
      activeHint = null;
    }
  }

  function showPopover(hint) {
    var source = hint.querySelector('.glossary-popover');
    if (!source) return;
    var isDashboardMeta = hint.matches('.dashboard-view .insights-meta .hero-meta-item');
    overlay.textContent = source.textContent;
    overlay.style.display = 'block';
    overlay.classList.remove('above');
    overlay.classList.toggle('dashboard-meta-popover', isDashboardMeta);
    overlay.style.removeProperty('--glossary-arrow-left');
    hint.setAttribute('aria-describedby', 'glossary-popover-overlay');
    hint.setAttribute('aria-expanded', 'true');

    function clamp(value, min, max) {
      return Math.min(Math.max(value, min), max);
    }

    var r = hint.getBoundingClientRect();
    var viewportWidth = document.documentElement.clientWidth || window.innerWidth;
    var viewportHeight = window.innerHeight;
    var margin = 12;
    var gap = 8;
    var top = r.bottom + gap;
    var center = r.left + r.width / 2;
    var popRect = overlay.getBoundingClientRect();
    var maxLeft = Math.max(margin, viewportWidth - popRect.width - margin);
    var left = clamp(center - popRect.width / 2, margin, maxLeft);
    overlay.style.left = left + 'px';
    overlay.style.top = top + 'px';
    overlay.style.removeProperty('right');
    overlay.style.removeProperty('bottom');
    overlay.style.transform = 'none';
    overlay.style.setProperty(
      '--glossary-arrow-left',
      clamp(center - left, 16, Math.max(16, popRect.width - 16)) + 'px'
    );

    // Flip above if near bottom
    popRect = overlay.getBoundingClientRect();
    if (popRect.bottom > viewportHeight - 20) {
      overlay.classList.add('above');
      overlay.style.top = Math.max(margin, r.top - gap - popRect.height) + 'px';
    }
  }

  // Make hints keyboard-accessible (re-runnable after innerHTML refresh)
  function initHints() {
    document.querySelectorAll('.glossary-hint').forEach(function (hint) {
      if (hint.hasAttribute('data-glossary-init')) return;
      hint.setAttribute('data-glossary-init', '1');
      hint.setAttribute('tabindex', '0');
      hint.setAttribute('role', 'button');
      // Use the popover text as aria-label for i18n, skip empty hints
      var source = hint.querySelector('.glossary-popover');
      var label = source ? source.textContent.trim() : '';
      if (!label) {
        // Empty glossary text — don't make it focusable
        hint.removeAttribute('tabindex');
        hint.removeAttribute('role');
        return;
      }
      hint.setAttribute('aria-label', label);
      hint.setAttribute('aria-expanded', 'false');
    });
  }
  initHints();

  // Expose for dashboard refresh cycle
  window.initGlossaryHints = initHints;

  // Toggle on Enter/Space for keyboard users (capture phase to intercept before inline handlers)
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ' ') {
      var hint = e.target.closest('.glossary-hint');
      if (hint) {
        e.preventDefault();
        e.stopImmediatePropagation();
        hint.click();
      }
    }
  }, true);

  document.addEventListener('click', function (e) {
    // Ignore clicks on the overlay itself
    if (e.target === overlay) return;

    var hint = e.target.closest('.glossary-hint');
    if (hint) {
      e.preventDefault();
      e.stopPropagation();
      var wasOpen = hint === activeHint;
      if (wasOpen && activeOpenedByFocus) {
        activeOpenedByFocus = false;
        return;
      }
      closeAll();
      if (!wasOpen) {
        activeHint = hint;
        hint.classList.add('open');
        showPopover(hint);
      }
      return;
    }
    closeAll();
  });

  document.addEventListener('focusin', function (e) {
    var hint = e.target.closest('.glossary-hint');
    if (!hint) return;
    var source = hint.querySelector('.glossary-popover');
    if (!source || !source.textContent.trim()) return;
    closeAll();
    activeHint = hint;
    activeOpenedByFocus = true;
    hint.classList.add('open');
    showPopover(hint);
  });

  document.addEventListener('focusout', function (e) {
    var hint = e.target.closest('.glossary-hint');
    if (hint && hint === activeHint) closeAll();
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeAll();
  });
})();
