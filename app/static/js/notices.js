/* DOCSight local maintainer notices. No remote feed or telemetry. */
(function() {
  'use strict';

  /* A read notice leaves the pages but stays in the notice center, so it remains reachable. */
  function markNoticeRead(noticeId) {
    document.querySelectorAll('[data-notice-id]').forEach(function(el) {
      if (el.getAttribute('data-notice-id') === noticeId) el.remove();
    });
    document.querySelectorAll('[data-notice-center-item]').forEach(function(item) {
      if (item.getAttribute('data-notice-center-item') !== noticeId) return;
      item.classList.add('read');
      var button = item.querySelector('[data-action="dismissMaintainerNotice"]');
      if (button) button.remove();
    });
    updateUnreadCount();
  }

  function unreadNoticeIds() {
    return Array.prototype.map.call(
      document.querySelectorAll('[data-notice-center-item]:not(.read)'),
      function(item) { return item.getAttribute('data-notice-center-item'); }
    );
  }

  function updateUnreadCount() {
    var count = unreadNoticeIds().length;
    var badge = document.querySelector('[data-notice-unread-count]');
    var toggle = document.getElementById('nav-toggle-notices');
    var markAll = document.querySelector('[data-action="markAllNoticesRead"]');
    if (badge) {
      badge.textContent = String(count);
      badge.hidden = count === 0;
    }
    if (markAll) markAll.hidden = count === 0;
    if (toggle) {
      var title = toggle.getAttribute('title') || '';
      var unread = (toggle.getAttribute('data-unread-label') || '{count} unread').replace('{count}', String(count));
      toggle.setAttribute('aria-label', count ? title + ', ' + unread : title);
    }
  }

  function dismiss(noticeId) {
    return fetch(docsightUrl('/api/notices/' + encodeURIComponent(noticeId) + '/dismiss'), {
      method: 'POST',
      headers: {'Accept': 'application/json'}
    }).then(function(response) {
      if (!response.ok) throw new Error('dismiss failed');
      return response.json();
    }).then(function(data) {
      if (!data || !data.success) throw new Error('dismiss failed');
      markNoticeRead(noticeId);
    });
  }

  function reportFailure() {
    if (typeof showToast === 'function') {
      showToast((window.T && (T.notice_dismiss_error || T.error_prefix)) || 'Could not dismiss notice', false);
    }
  }

  window.dismissMaintainerNotice = function(noticeId) {
    if (!noticeId) return;
    dismiss(noticeId).catch(reportFailure);
  };

  window.markAllNoticesRead = function() {
    unreadNoticeIds().reduce(function(chain, noticeId) {
      return chain.then(function() { return dismiss(noticeId); });
    }, Promise.resolve()).catch(reportFailure);
  };

  /* The overview's notice line opens the center in the top bar. */
  window.openNoticeCenter = function() {
    var toggle = document.getElementById('nav-toggle-notices');
    if (!toggle) return;
    window.scrollTo({top: 0});
    // After this click has finished: the top bar closes its panels on clicks outside them.
    window.setTimeout(function() {
      if (toggle.getAttribute('aria-expanded') !== 'true') toggle.click();
      toggle.focus({preventScroll: true});
    }, 0);
  };

  updateUnreadCount();
})();
