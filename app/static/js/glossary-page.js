/* glossary-page.js — Simple glossary search and mobile term picker */

(function () {
  'use strict';

  var panels = Array.prototype.slice.call(document.querySelectorAll('[data-glossary-panel]'));
  var picker = document.querySelector('[data-glossary-picker]');
  var openButton = document.querySelector('[data-glossary-picker-open]');
  var closeButtons = Array.prototype.slice.call(document.querySelectorAll('[data-glossary-picker-close]'));
  var lastFocused = null;

  function normalize(value) {
    return (value || '').toLocaleLowerCase().trim();
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
    if (!picker) return;
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

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && picker && !picker.hidden) {
      closePicker();
    }
  });
})();
