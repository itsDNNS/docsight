/* glossary-page.js — Simple glossary search and mobile term picker */

(function () {
  'use strict';

  var panels = Array.prototype.slice.call(document.querySelectorAll('[data-glossary-panel]'));
  var picker = document.querySelector('[data-glossary-picker]');
  var openButton = document.querySelector('[data-glossary-picker-open]');
  var closeButtons = Array.prototype.slice.call(document.querySelectorAll('[data-glossary-picker-close]'));
  var articles = Array.prototype.slice.call(document.querySelectorAll('[data-glossary-article]'));
  var selectedLabel = document.querySelector('[data-glossary-mobile-selected]');
  var focusableSelector = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])'
  ].join(',');
  var lastFocused = null;

  function normalize(value) {
    return (value || '').toLocaleLowerCase().trim();
  }

  function parseGlossaryHash() {
    var hash = window.location.hash ? window.location.hash.slice(1) : '';
    if (!hash) return null;
    var parts = hash.split('?');
    if (parts[0] !== 'glossary') return null;
    var params = new URLSearchParams(parts.slice(1).join('?'));
    return {
      term: params.get('term') || '',
      level: params.get('level') || ''
    };
  }

  function glossaryHashForTerm(termId) {
    return '#glossary?term=' + encodeURIComponent(termId);
  }

  function findArticle(termId) {
    if (!termId) return null;
    return articles.find(function (article) {
      return article.getAttribute('data-term-id') === termId;
    }) || null;
  }

  function setActiveTerm(termId, options) {
    options = options || {};
    var article = findArticle(termId) || articles[0];
    if (!article) return;
    var activeTermId = article.getAttribute('data-term-id');

    articles.forEach(function (item) {
      item.hidden = item !== article;
    });

    document.querySelectorAll('[data-glossary-term]').forEach(function (link) {
      var isActive = link.getAttribute('data-term-id') === activeTermId;
      link.classList.toggle('active', isActive);
      link.setAttribute('aria-current', isActive ? 'page' : 'false');
    });

    if (selectedLabel) {
      selectedLabel.textContent = selectedLabel.textContent.split(':')[0] + ': ' + (article.getAttribute('data-title') || activeTermId);
    }

    if (options.updateHash && window.location.hash !== glossaryHashForTerm(activeTermId)) {
      window.location.hash = glossaryHashForTerm(activeTermId);
    }
  }

  function setCount(resultCount, visibleCount) {
    if (!resultCount) return;
    var template = visibleCount === 1
      ? resultCount.getAttribute('data-singular-template')
      : resultCount.getAttribute('data-plural-template');
    resultCount.textContent = (template || '{count} terms shown').replace('{count}', String(visibleCount));
  }

  function filterPanel(panel) {
    var input = panel.querySelector('[data-glossary-search]');
    var terms = Array.prototype.slice.call(panel.querySelectorAll('[data-glossary-term]'));
    var resultCount = panel.querySelector('.glossary-result-count');
    var noResults = panel.querySelector('.glossary-no-results');
    if (!input || !terms.length) return;

    var query = normalize(input.value);
    var visibleCount = 0;
    terms.forEach(function (item) {
      var haystack = normalize(item.getAttribute('data-search'));
      var isVisible = !query || haystack.indexOf(query) !== -1;
      item.hidden = !isVisible;
      if (isVisible) visibleCount += 1;
    });
    setCount(resultCount, visibleCount);
    if (noResults) noResults.hidden = visibleCount !== 0;
  }

  function isVisible(element) {
    var style = window.getComputedStyle(element);
    var rect = element.getBoundingClientRect();
    return style.display !== 'none'
      && style.visibility !== 'hidden'
      && rect.width > 0
      && rect.height > 0;
  }

  function getPickerFocusableElements() {
    if (!picker || picker.hidden) return [];
    var dialog = picker.querySelector('[role="dialog"]') || picker;
    return Array.prototype.slice.call(dialog.querySelectorAll(focusableSelector)).filter(isVisible);
  }

  function trapPickerFocus(event) {
    if (event.key !== 'Tab' || !picker || picker.hidden) return;

    var focusableElements = getPickerFocusableElements();
    if (!focusableElements.length) {
      event.preventDefault();
      return;
    }

    var first = focusableElements[0];
    var last = focusableElements[focusableElements.length - 1];
    var active = document.activeElement;

    if (focusableElements.indexOf(active) === -1) {
      event.preventDefault();
      first.focus({ preventScroll: true });
      return;
    }

    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus({ preventScroll: true });
      return;
    }

    if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus({ preventScroll: true });
    }
  }

  panels.forEach(function (panel) {
    var input = panel.querySelector('[data-glossary-search]');
    if (!input) return;
    input.addEventListener('input', function () {
      filterPanel(panel);
    });
    filterPanel(panel);
  });

  function openPicker() {
    if (!picker) return;
    lastFocused = document.activeElement;
    picker.hidden = false;
    if (openButton) openButton.setAttribute('aria-expanded', 'true');
    var search = picker.querySelector('[data-glossary-search]');
    if (search) search.focus({ preventScroll: true });
  }

  function closePicker() {
    if (!picker || picker.hidden) return;
    picker.hidden = true;
    if (openButton) openButton.setAttribute('aria-expanded', 'false');
    if (lastFocused && typeof lastFocused.focus === 'function') {
      lastFocused.focus({ preventScroll: true });
    }
  }

  if (openButton) {
    openButton.addEventListener('click', openPicker);
  }

  closeButtons.forEach(function (button) {
    button.addEventListener('click', closePicker);
  });

  document.addEventListener('click', function (event) {
    var link = event.target.closest('[data-glossary-term]');
    if (!link) return;
    var termId = link.getAttribute('data-term-id');
    if (!findArticle(termId)) return;
    event.preventDefault();
    setActiveTerm(termId, { updateHash: true });
    closePicker();
  });

  window.addEventListener('hashchange', function () {
    var parsed = parseGlossaryHash();
    if (parsed) setActiveTerm(parsed.term);
  });

  var parsed = parseGlossaryHash();
  if (parsed) setActiveTerm(parsed.term);

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && picker && !picker.hidden) {
      closePicker();
      return;
    }
    trapPickerFocus(event);
  });
})();
