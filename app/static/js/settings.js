/* Settings composition and the explicit boundary for template/module handlers. */
(function(S) {
    'use strict';
    var navigation;
    var form = S.form({state: S.state, showsSaveFooter: function() { return navigation.showsSaveFooter(); }});
    var tokens = S.tokens({showToast: form.showToast});
    var connections = S.connections({getFormData: form.getFormData});
    var backups = S.backups({showToast: form.showToast});
    var themes = S.themes({showToast: form.showToast, guardUnsaved: form.guardUnsaved});
    var smartCapture = S.smart_capture({showToast: form.showToast});
    var registry = S.module_registry({showToast: form.showToast});
    navigation = S.navigation({syncSaveFooter: form.syncSaveFooter, onSection: function(id, panel) {
        if (id === 'security') tokens.loadApiTokens();
        if (panel && panel.querySelector('#backup-list')) backups.loadBackupList();
        if (id === 'appearance') themes.loadThemeRegistryIfNeeded();
        if (id === 'smart_capture') smartCapture.loadSmartCaptureHistory();
        if (id === 'extensions') registry.refreshModuleRegistry();
    }});
    var notifications = S.notifications({showToast: form.showToast, saveInstantly: form.saveInstantly, syncCard: navigation.syncCard});
    function expose(owner, names) {
        names.split(' ').forEach(function(name) { window[name] = owner[name]; });
    }
    expose(form, 'getFormData showToast');
    expose(navigation, 'switchSection openMobileSidebar closeMobileSidebar toggleCardCollapse');
    expose(tokens, 'createApiToken copyToken');
    expose(connections, 'onIspChange testModem testMqtt testSpeedtest clearSpeedtestCache testNotifications');
    expose(backups, 'downloadBackup backupNow openBrowseModal closeBrowseModal selectBrowsePath');
    expose(themes, 'toggleThemeFromAppearance applyFontToggle previewTheme cancelPreview applyPreviewedTheme applyTheme refreshRegistry');
    expose(notifications, 'subscribePwaPush unsubscribePwaPush');
    expose(registry, 'refreshModuleRegistry');
    document.addEventListener('DOMContentLoaded', function() {
        if (typeof lucide !== 'undefined') lucide.createIcons();
        [themes, connections, backups, notifications, smartCapture, form, navigation].forEach(function(owner) { owner.init(); });
    });
})(DOCSightSettings);
