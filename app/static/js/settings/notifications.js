'use strict';
DOCSightSettings.notifications = function({showToast, saveInstantly, syncCard}) {
function expandNotificationChannelCard(controlEl) {
    if (!controlEl || !controlEl.checked) return;
    var card = controlEl.closest('.notification-channel-card');
    if (card && card.classList.contains('collapsed')) {
        card.classList.remove('collapsed');
        syncCard(card);
    }
}

function _notificationLabel(key, fallback) {
    return (typeof T !== 'undefined' && T[key]) ? T[key] : fallback;
}

function _setNotificationChannelBadge(channel, enabled, label) {
    var badge = document.querySelector('[data-channel-badge="' + channel + '"]');
    if (!badge) return;
    badge.textContent = label;
    badge.classList.toggle('status-enabled', enabled);
    badge.classList.toggle('status-disabled', !enabled && channel !== 'webhook');
    badge.classList.toggle('status-muted', !enabled && channel === 'webhook');
}

function updateNotificationChannelSummaries() {
    var webhook = document.getElementById('notify_webhook_url');
    var webhookConfigured = !!(webhook && webhook.value.trim() !== '');
    _setNotificationChannelBadge(
        'webhook',
        webhookConfigured,
        webhookConfigured ? _notificationLabel('enabled', 'Enabled') : _notificationLabel('not_configured', 'Not configured')
    );

    var apprise = document.getElementById('notify_apprise_enabled');
    var appriseEnabled = !!(apprise && apprise.checked);
    _setNotificationChannelBadge(
        'apprise',
        appriseEnabled,
        appriseEnabled ? _notificationLabel('enabled', 'Enabled') : _notificationLabel('disabled', 'Disabled')
    );

    var pwa = document.getElementById('notify_pwa_push_enabled');
    var pwaEnabled = !!(pwa && pwa.checked);
    _setNotificationChannelBadge(
        'pwa',
        pwaEnabled,
        pwaEnabled ? _notificationLabel('enabled', 'Enabled') : _notificationLabel('disabled', 'Disabled')
    );
}

/* ── PWA Web Push ── */
var _pwaPushStatus = null;

function _setPwaPushStatus(message, ok) {
    var el = document.getElementById('pwa-push-status');
    if (!el) return;
    el.className = 'test-result ' + (ok ? 'test-ok' : 'test-fail');
    el.style.display = 'flex';
    el.textContent = message;
}

function _urlBase64ToUint8Array(base64String) {
    var padding = '='.repeat((4 - base64String.length % 4) % 4);
    var base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
    var rawData = atob(base64);
    var outputArray = new Uint8Array(rawData.length);
    for (var i = 0; i < rawData.length; ++i) outputArray[i] = rawData.charCodeAt(i);
    return outputArray;
}

function _getCurrentPwaSubscription() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return Promise.resolve(null);
    return navigator.serviceWorker.ready
        .then(function(registration) { return registration.pushManager.getSubscription(); })
        .catch(function() { return null; });
}

function refreshPwaPushStatus() {
    if (!document.getElementById('pwa-push-status')) return Promise.resolve(null);
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
        _setPwaPushStatus(T.notify_pwa_push_unsupported || 'Web Push is not supported in this browser.', false);
        return Promise.resolve(null);
    }
    return Promise.all([
        fetch(docsightUrl('/api/notifications/pwa/status')).then(function(r) { return r.json(); }),
        _getCurrentPwaSubscription()
    ])
        .then(function(values) {
            var status = values[0];
            var currentSubscription = values[1];
            _pwaPushStatus = status;
            var permission = Notification.permission;
            if (!status.configured) {
                _setPwaPushStatus(T.notify_pwa_push_not_configured || 'Web Push is not configured yet.', false);
            } else if (permission === 'granted' && currentSubscription) {
                _setPwaPushStatus((T.notify_pwa_push_ready || 'This browser is subscribed.') + ' ' + (status.subscription_count || 0) + ' ' + (T.notify_pwa_push_devices || 'device(s)'), true);
            } else if (permission === 'granted') {
                _setPwaPushStatus(T.notify_pwa_push_not_subscribed || 'This browser is not subscribed yet.', false);
            } else {
                _setPwaPushStatus(T.notify_pwa_push_permission_needed || 'Browser permission is needed for this device.', false);
            }
            return status;
        })
        .catch(function() {
            _setPwaPushStatus(T.network_error || 'Network error', false);
            return null;
        });
}

function subscribePwaPush() {
    refreshPwaPushStatus().then(function(status) {
        if (!status || !status.configured || !status.public_key) return;
        return navigator.serviceWorker.ready
            .then(function(registration) { return Notification.requestPermission().then(function(permission) { return {registration: registration, permission: permission}; }); })
            .then(function(ctx) {
                if (ctx.permission !== 'granted') throw new Error(T.notify_pwa_push_permission_denied || 'Notification permission was denied.');
                return ctx.registration.pushManager.getSubscription().then(function(existing) {
                    if (existing) return existing;
                    return ctx.registration.pushManager.subscribe({
                        userVisibleOnly: true,
                        applicationServerKey: _urlBase64ToUint8Array(status.public_key)
                    });
                });
            })
            .then(function(subscription) {
                return fetch(docsightUrl('/api/notifications/pwa/subscribe'), {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({subscription: subscription.toJSON()})
                });
            })
            .then(function(r) { return r.json(); })
            .then(function(res) {
                if (!res.success) throw new Error(res.error || T.unknown_error || 'Unknown error');
                showToast(T.notify_pwa_push_subscribed || 'This browser is subscribed.', true);
                refreshPwaPushStatus();
            })
            .catch(function(err) {
                showToast(err.message || (T.notify_pwa_push_subscribe_failed || 'Subscription failed'), false);
            });
    });
}

function unsubscribePwaPush() {
    if (!('serviceWorker' in navigator)) return;
    navigator.serviceWorker.ready
        .then(function(registration) { return registration.pushManager.getSubscription(); })
        .then(function(subscription) {
            if (!subscription) return null;
            var endpoint = subscription.endpoint;
            return subscription.unsubscribe().then(function() {
                return fetch(docsightUrl('/api/notifications/pwa/unsubscribe'), {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({endpoint: endpoint})
                });
            });
        })
        .then(function(r) { return r ? r.json() : {success: true}; })
        .then(function(res) {
            if (!res.success) throw new Error(res.error || T.unknown_error || 'Unknown error');
            showToast(T.notify_pwa_push_unsubscribed || 'This browser is unsubscribed.', true);
            refreshPwaPushStatus();
        })
        .catch(function(err) {
            showToast(err.message || (T.notify_pwa_push_unsubscribe_failed || 'Unsubscribe failed'), false);
        });
}

function initNotificationCooldownControls() {
    try {
        var saved = typeof savedCooldowns !== 'undefined' ? savedCooldowns : {};
        document.querySelectorAll('.notify-event-row').forEach(function(row) {
            var eventKey = row.getAttribute('data-event');
            var severity = row.getAttribute('data-severity') || '';
            var key = severity ? eventKey + ':' + severity : eventKey;
            var toggle = row.querySelector('.notify-toggle');
            var inp = row.querySelector('.notify-cooldown-input');
            if (!toggle || !inp) return;
            var savedValue = saved[key];
            if (savedValue === undefined && severity) {
                savedValue = saved[eventKey];
            }
            if (savedValue !== undefined) {
                if (savedValue === 0) {
                    toggle.checked = false;
                    inp.disabled = true;
                    inp.style.opacity = '0.4';
                } else {
                    inp.value = savedValue;
                }
            }
            toggle.addEventListener('change', function() {
                inp.disabled = !toggle.checked;
                inp.style.opacity = toggle.checked ? '1' : '0.4';
                saveInstantly();
            });
            inp.addEventListener('change', function() {
                saveInstantly();
            });
        });
    } catch(e) {}
}

function init() {
    initNotificationCooldownControls();
    refreshPwaPushStatus();
    updateNotificationChannelSummaries();
    var webhook = document.getElementById('notify_webhook_url');
    if (webhook) webhook.addEventListener('input', updateNotificationChannelSummaries);
    ['notify_apprise_enabled', 'notify_pwa_push_enabled'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.addEventListener('change', function() {
            updateNotificationChannelSummaries();
            expandNotificationChannelCard(el);
        });
    });
}
return {init, subscribePwaPush, unsubscribePwaPush};
};
