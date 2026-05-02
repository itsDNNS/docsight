/* DOCSight local maintainer notices. No remote feed or telemetry. */
(function() {
  'use strict';

  function removeNoticeElement(noticeId) {
    document.querySelectorAll('[data-notice-id]').forEach(function(el) {
      if (el.getAttribute('data-notice-id') === noticeId) el.remove();
    });
  }

  window.dismissMaintainerNotice = function(noticeId) {
    if (!noticeId) return;
    fetch('/api/notices/' + encodeURIComponent(noticeId) + '/dismiss', {
      method: 'POST',
      headers: {'Accept': 'application/json'}
    }).then(function(response) {
      if (!response.ok) throw new Error('dismiss failed');
      return response.json();
    }).then(function(data) {
      if (data && data.success) {
        removeNoticeElement(noticeId);
      }
    }).catch(function() {
      if (typeof showToast === 'function') {
        showToast((window.T && (T.notice_dismiss_error || T.error_prefix)) || 'Could not dismiss notice', false);
      }
    });
  };
})();
