/* glossary-page.js — Search and category filtering for the standalone glossary */

(function () {
  'use strict';

  var searchInput = document.getElementById('glossary-search');
  var categoryButtons = Array.prototype.slice.call(document.querySelectorAll('[data-category-filter]'));
  var termItems = Array.prototype.slice.call(document.querySelectorAll('[data-glossary-term]'));
  var categorySections = Array.prototype.slice.call(document.querySelectorAll('[data-category-section]'));
  var resultCount = document.getElementById('glossary-result-count');
  var noResults = document.getElementById('glossary-no-results');
  var activeCategory = 'all';

  if (!searchInput || !termItems.length) return;

  function normalize(value) {
    return (value || '').toLocaleLowerCase().trim();
  }

  function updateCategoryButtons() {
    categoryButtons.forEach(function (button) {
      var isActive = button.getAttribute('data-category-filter') === activeCategory;
      button.classList.toggle('active', isActive);
      button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
  }

  function filterTerms() {
    var query = normalize(searchInput.value);
    var visibleCount = 0;

    termItems.forEach(function (item) {
      var matchesCategory = activeCategory === 'all' || item.getAttribute('data-category') === activeCategory;
      var haystack = normalize(item.getAttribute('data-search'));
      var matchesSearch = !query || haystack.indexOf(query) !== -1;
      var isVisible = matchesCategory && matchesSearch;
      item.hidden = !isVisible;
      if (isVisible) visibleCount += 1;
    });

    categorySections.forEach(function (section) {
      var hasVisibleTerm = !!section.querySelector('[data-glossary-term]:not([hidden])');
      section.hidden = !hasVisibleTerm;
    });

    if (resultCount) {
      resultCount.textContent = visibleCount + (visibleCount === 1 ? ' term shown' : ' terms shown');
    }
    if (noResults) {
      noResults.hidden = visibleCount !== 0;
    }
    updateCategoryButtons();
  }

  categoryButtons.forEach(function (button) {
    button.addEventListener('click', function () {
      activeCategory = button.getAttribute('data-category-filter') || 'all';
      filterTerms();
      searchInput.focus({ preventScroll: true });
    });
  });

  searchInput.addEventListener('input', filterTerms);
  filterTerms();
})();
