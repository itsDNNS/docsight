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
    return { term: params.get('term') || '' };
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
    document.querySelectorAll('#view-glossary [data-glossary-term]').forEach(function (link) {
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
    });

    document.querySelectorAll('#view-glossary [data-glossary-term]').forEach(function (link) {
      var isActive = link.getAttribute('data-term-id') === activeTermId;
      link.classList.toggle('active', isActive);
      link.setAttribute('aria-current', isActive ? 'page' : 'false');
    });

    if (selectedLabel) {
      var selectedPrefix = openButton ? openButton.getAttribute('data-glossary-selected-prefix') : '';
      selectedLabel.textContent = (selectedPrefix || 'Selected term') + ': ' + (article.getAttribute('data-title') || activeTermId);
    }

    if (options.updateHash && window.location.hash !== glossaryHashForTerm(activeTermId)) {
      window.location.hash = glossaryHashForTerm(activeTermId);
    }

    if (options.scroll) {
      window.requestAnimationFrame(function () {
        // Only bring the article back when its title has left the viewport, so
        // opening the view or picking a nearby term keeps the page header in place.
        var top = article.getBoundingClientRect().top;
        var marginTop = parseFloat(getComputedStyle(article).scrollMarginTop) || 0;
        if (top < marginTop || top > window.innerHeight) {
          article.scrollIntoView({ block: 'start', behavior: 'smooth' });
        }
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
    var letters = Array.prototype.slice.call(panel.querySelectorAll('[data-glossary-letter]'));
    if (!input || !terms.length) return;
    if (list && !list.hasAttribute('data-glossary-ordered')) {
      Array.prototype.forEach.call(list.children, function (child, index) {
        child.setAttribute('data-glossary-order', String(index));
      });
      list.setAttribute('data-glossary-ordered', '');
    }

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

    // Without a query the list is A–Z under its letters; with one, ranked by match and without them.
    letters.forEach(function (letter) { letter.hidden = !!query; });
    if (list && !query) {
      Array.prototype.slice.call(list.children)
        .sort(function (a, b) { return Number(a.getAttribute('data-glossary-order')) - Number(b.getAttribute('data-glossary-order')); })
        .forEach(function (child) { list.appendChild(child); });
    } else if (list) {
      ranked.sort(function (a, b) {
        if (b.score !== a.score) return b.score - a.score;
        return a.index - b.index;
      });
      ranked.forEach(function (entry) { list.appendChild(entry.item); });
    }

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

  /* "Where you see this": the navigation names each view as the user sees it there, and
     only lists views this instance offers, so links appear only for those. */
  function revealWhereLinks(root) {
    root.querySelectorAll('[data-glossary-where]').forEach(function (section) {
      var shown = 0;
      section.querySelectorAll('[data-glossary-where-view]').forEach(function (link) {
        var view = link.getAttribute('data-glossary-where-view');
        var nav = document.querySelector('#topnav .nav-item[data-view="' + view + '"]');
        var label = nav && (nav.querySelector('.topnav-label') || nav).textContent.trim();
        var title = label || (nav && nav.getAttribute('data-nav-title'));
        link.hidden = !title;
        if (title) {
          link.querySelector('span').textContent = title;
          shown += 1;
        }
      });
      section.hidden = shown === 0;
    });
  }
  revealWhereLinks(document);

  /* ── Help panel: in-context glossary links open the article over the current view ── */
  var helpPanel = document.querySelector('[data-glossary-help-panel]');
  var helpList = helpPanel && helpPanel.querySelector('[data-glossary-panel-list]');
  var helpArticle = helpPanel && helpPanel.querySelector('[data-glossary-panel-article]');
  var helpSlot = helpPanel && helpPanel.querySelector('[data-glossary-panel-slot]');
  var helpSearch = helpPanel && helpPanel.querySelector('[data-glossary-search]');
  var helpPageLink = helpPanel && helpPanel.querySelector('[data-glossary-panel-page]');
  var helpOpener = null;

  function termFromHref(href) {
    var query = (href || '').split('#glossary?', 2)[1];
    return query === undefined ? '' : (new URLSearchParams(query).get('term') || '');
  }

  // The clone sits next to its original, so its ids and the references to them get a prefix.
  function prefixIds(root, prefix) {
    root.querySelectorAll('[id]').forEach(function (node) { node.id = prefix + node.id; });
    ['aria-labelledby', 'aria-describedby', 'aria-controls'].forEach(function (attr) {
      root.querySelectorAll('[' + attr + ']').forEach(function (node) {
        node.setAttribute(attr, node.getAttribute(attr).split(/\s+/).map(function (id) { return prefix + id; }).join(' '));
      });
    });
  }

  function showPanelList() {
    if (!helpPanel) return;
    helpList.hidden = false;
    helpArticle.hidden = true;
    helpPageLink.setAttribute('href', '#glossary');
  }

  function showPanelArticle(termId) {
    var resolved = resolveTermId(termId);
    var source = findArticle(resolved);
    if (!source) {
      helpSearch.value = termId || '';
      filterPanel(helpPanel);
      showPanelList();
      return;
    }
    var clone = source.cloneNode(true);
    clone.hidden = false;
    prefixIds(clone, 'glossary-panel-');
    helpSlot.textContent = '';
    helpSlot.appendChild(clone);
    helpList.hidden = true;
    helpArticle.hidden = false;
    helpPageLink.setAttribute('href', glossaryHashForTerm(resolved));
    helpPanel.querySelector('.glossary-panel-body').scrollTop = 0;
  }

  function openGlossaryPanel(termId) {
    if (!helpPanel) return false;
    if (helpPanel.hidden) {
      helpOpener = document.activeElement;
      // A popover link disappears with its popover; focus returns to the hint instead.
      if (helpOpener && helpOpener.closest('#glossary-popover-overlay')) {
        helpOpener = document.querySelector('.glossary-hint.open') || helpOpener;
      }
    }
    if (typeof window.closeGlossaryPopover === 'function') window.closeGlossaryPopover();
    helpPanel.hidden = false;
    helpSearch.value = '';
    filterPanel(helpPanel);
    if (termId) showPanelArticle(termId);
    else showPanelList();
    document.getElementById('glossary-panel-title').focus({ preventScroll: true });
    return true;
  }
  window.openGlossaryPanel = openGlossaryPanel;

  function closeGlossaryPanel() {
    if (!helpPanel || helpPanel.hidden) return;
    helpPanel.hidden = true;
    if (helpOpener && helpOpener.isConnected && isVisible(helpOpener)) helpOpener.focus({ preventScroll: true });
    helpOpener = null;
  }

  if (helpPanel) {
    helpPanel.addEventListener('click', function (event) {
      if (event.target.closest('[data-glossary-panel-close]')) {
        closeGlossaryPanel();
        return;
      }
      if (event.target.closest('[data-glossary-panel-back]')) {
        showPanelList();
        helpSearch.focus({ preventScroll: true });
        return;
      }
      if (event.target.closest('[data-glossary-panel-page]')) {
        closeGlossaryPanel();
        return;
      }
      var termLink = event.target.closest('[data-glossary-term], [data-glossary-related-term]');
      if (termLink) {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        // The new article replaces the link, so the page's handlers must not see this click.
        event.stopPropagation();
        showPanelArticle(termLink.getAttribute('data-term-id') || termFromHref(termLink.getAttribute('href')));
      }
    });

    // Hints, empty states and other links into the glossary open the panel and keep the view.
    document.addEventListener('click', function (event) {
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      var link = event.target.closest('a[href*="#glossary?"]');
      if (!link || link.closest('#view-glossary') || link.closest('[data-glossary-help-panel]')) return;
      var termId = termFromHref(link.getAttribute('href'));
      if (!termId) return;
      event.preventDefault();
      openGlossaryPanel(termId);
    });
  }

  panels.forEach(function (panel) {
    var input = panel.querySelector('[data-glossary-search]');
    if (!input) return;
    var inHelpPanel = panel.hasAttribute('data-glossary-help-panel');
    input.addEventListener('input', function () {
      if (inHelpPanel) showPanelList();
      filterPanel(panel);
    });
    input.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter') return;
      var firstVisible = Array.prototype.slice.call(panel.querySelectorAll('[data-glossary-term]')).find(function (term) {
        return !term.hidden;
      });
      if (!firstVisible) return;
      event.preventDefault();
      if (inHelpPanel) {
        showPanelArticle(firstVisible.getAttribute('data-term-id'));
        return;
      }
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
    if (event.target.closest('[data-glossary-help-panel]')) return;
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
    if (parsed) setActiveTerm(parsed.term, { scroll: true });
    // On phones the panel covers the view the user just went to.
    if (helpPanel && !helpPanel.hidden && window.matchMedia('(max-width: 640px)').matches) closeGlossaryPanel();
  });

  var parsed = parseGlossaryHash();
  if (parsed) setActiveTerm(parsed.term);

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && picker && !picker.hidden) {
      closePicker();
      return;
    }
    if (event.key === 'Escape' && helpPanel && !helpPanel.hidden) {
      closeGlossaryPanel();
      return;
    }
    trapPickerFocus(event);
  });
})();
