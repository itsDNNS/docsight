/* glossary-page.js — Simple glossary search and mobile term picker */

(function () {
  'use strict';

  var panels = Array.prototype.slice.call(document.querySelectorAll('[data-glossary-panel]'));
  var picker = document.querySelector('[data-glossary-picker]');
  var openButton = document.querySelector('[data-glossary-picker-open]');
  var closeButtons = Array.prototype.slice.call(document.querySelectorAll('[data-glossary-picker-close]'));
  var articles = Array.prototype.slice.call(document.querySelectorAll('[data-glossary-article]'));
  var missingState = document.querySelector('[data-glossary-missing]');
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
    return (value || '')
      .toString()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLocaleLowerCase()
      .trim();
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

  function glossaryHashForTerm(termId, level) {
    var hash = '#glossary?term=' + encodeURIComponent(termId);
    if (level) hash += '&level=' + encodeURIComponent(level);
    return hash;
  }

  function findArticle(termId) {
    if (!termId) return null;
    return articles.find(function (article) {
      return article.getAttribute('data-term-id') === termId;
    }) || null;
  }

  function resolveTermId(value) {
    var normalized = normalize(value);
    if (!normalized) return '';
    var exact = findArticle(value);
    if (exact) return exact.getAttribute('data-term-id');

    var links = Array.prototype.slice.call(document.querySelectorAll('[data-glossary-term]'));
    var match = links.find(function (link) {
      if (normalize(link.getAttribute('data-term-id')) === normalized) return true;
      if (normalize(link.getAttribute('data-search-title')) === normalized) return true;
      var aliases = (link.getAttribute('data-search-alias-values') || '')
        .split('|||')
        .map(normalize)
        .filter(Boolean);
      return aliases.indexOf(normalized) !== -1;
    });
    return match ? match.getAttribute('data-term-id') : value;
  }

  function setMissingTerm(termId) {
    articles.forEach(function (item) { item.hidden = true; });
    document.querySelectorAll('[data-glossary-term]').forEach(function (link) {
      link.classList.remove('active');
      link.setAttribute('aria-current', 'false');
    });
    if (missingState) missingState.hidden = false;
    if (selectedLabel) {
      var prefix = openButton ? openButton.getAttribute('data-glossary-selected-prefix') : '';
      selectedLabel.textContent = (prefix || 'Selected term') + ': ' + termId;
    }
    panels.forEach(function (panel) {
      var input = panel.querySelector('[data-glossary-search]');
      if (input && termId) {
        input.value = termId;
        filterPanel(panel);
      }
    });
  }

  function setActiveTerm(termId, options) {
    options = options || {};
    var requestedLevel = /^(eli5|basic|advanced|technician)$/.test(options.level || '') ? options.level : '';
    var resolvedTermId = resolveTermId(termId);
    var article = findArticle(resolvedTermId) || (!termId ? articles[0] : null);
    if (!article) {
      setMissingTerm(termId || resolvedTermId);
      return;
    }
    if (missingState) missingState.hidden = true;
    var activeTermId = article.getAttribute('data-term-id');

    articles.forEach(function (item) {
      item.hidden = item !== article;
      Array.prototype.slice.call(item.querySelectorAll('[data-glossary-detail-level]')).forEach(function (detail) {
        detail.open = false;
      });
    });

    document.querySelectorAll('[data-glossary-term]').forEach(function (link) {
      var isActive = link.getAttribute('data-term-id') === activeTermId;
      link.classList.toggle('active', isActive);
      link.setAttribute('aria-current', isActive ? 'page' : 'false');
    });

    if (selectedLabel) {
      var selectedPrefix = openButton ? openButton.getAttribute('data-glossary-selected-prefix') : '';
      selectedLabel.textContent = (selectedPrefix || 'Selected term') + ': ' + (article.getAttribute('data-title') || activeTermId);
    }

    var targetDetail = null;
    if (requestedLevel === 'advanced' || requestedLevel === 'technician') {
      targetDetail = article.querySelector('[data-glossary-detail-level="' + requestedLevel + '"]');
      if (targetDetail) targetDetail.open = true;
    }

    if (options.updateHash && window.location.hash !== glossaryHashForTerm(activeTermId, requestedLevel)) {
      window.location.hash = glossaryHashForTerm(activeTermId, requestedLevel);
    }

    if (options.scroll && targetDetail) {
      window.requestAnimationFrame(function () {
        targetDetail.scrollIntoView({ block: 'start', behavior: 'smooth' });
      });
    }
  }

  function setCount(resultCount, visibleCount) {
    if (!resultCount) return;
    var template = visibleCount === 1
      ? resultCount.getAttribute('data-singular-template')
      : resultCount.getAttribute('data-plural-template');
    resultCount.textContent = (template || '{count} terms shown').replace('{count}', String(visibleCount));
  }

  function searchScore(item, query) {
    if (!query) return 0;
    var title = normalize(item.getAttribute('data-search-title'));
    var aliases = normalize(item.getAttribute('data-search-aliases'));
    var id = normalize(item.getAttribute('data-search-id'));
    var metadata = normalize(item.getAttribute('data-search-metadata'));
    if (title.indexOf(query) === 0) return 100;
    if (title.indexOf(query) !== -1) return 90;
    if (aliases.indexOf(query) !== -1) return 80;
    if (id.indexOf(query) !== -1) return 70;
    if (metadata.indexOf(query) !== -1) return 50;
    return -1;
  }

  function filterPanel(panel) {
    var input = panel.querySelector('[data-glossary-search]');
    var list = panel.querySelector('.glossary-term-list');
    var terms = Array.prototype.slice.call(panel.querySelectorAll('[data-glossary-term]'));
    var resultCount = panel.querySelector('.glossary-result-count');
    var noResults = panel.querySelector('.glossary-no-results');
    if (!input || !terms.length) return;

    var query = normalize(input.value);
    var visibleCount = 0;
    var ranked = terms.map(function (item, index) {
      var storedIndex = item.getAttribute('data-glossary-original-index');
      if (storedIndex === null) {
        storedIndex = String(index);
        item.setAttribute('data-glossary-original-index', storedIndex);
      }
      return {
        item: item,
        score: searchScore(item, query),
        index: Number(storedIndex)
      };
    });

    ranked.forEach(function (entry) {
      var isVisible = !query || entry.score >= 0;
      entry.item.hidden = !isVisible;
      if (isVisible) visibleCount += 1;
    });

    ranked.sort(function (a, b) {
      if (!query) return a.index - b.index;
      if (b.score !== a.score) return b.score - a.score;
      return a.index - b.index;
    });
    if (list) ranked.forEach(function (entry) { list.appendChild(entry.item); });

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
    input.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter') return;
      var firstVisible = Array.prototype.slice.call(panel.querySelectorAll('[data-glossary-term]')).find(function (term) {
        return !term.hidden;
      });
      if (!firstVisible) return;
      event.preventDefault();
      setActiveTerm(firstVisible.getAttribute('data-term-id'), { updateHash: true });
      closePicker();
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
    var relatedLink = event.target.closest('[data-glossary-related-term]');
    var link = event.target.closest('[data-glossary-term]') || relatedLink;
    if (!link) return;
    var termId = link.getAttribute('data-term-id');
    if (!termId && link.getAttribute('href')) {
      var href = link.getAttribute('href');
      var query = href.split('#glossary?', 2)[1] || '';
      termId = new URLSearchParams(query).get('term') || '';
    }
    if (!findArticle(resolveTermId(termId))) return;
    event.preventDefault();
    setActiveTerm(termId, { updateHash: true });
    closePicker();
  });

  window.addEventListener('hashchange', function () {
    var parsed = parseGlossaryHash();
    if (parsed) setActiveTerm(parsed.term, { level: parsed.level, scroll: true });
  });

  var parsed = parseGlossaryHash();
  if (parsed) setActiveTerm(parsed.term, { level: parsed.level });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && picker && !picker.hidden) {
      closePicker();
      return;
    }
    trapPickerFocus(event);
  });
})();
