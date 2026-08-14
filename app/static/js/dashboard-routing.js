  // Apply deferred hash-based view routing (all scripts including modules are now loaded)
  if (window._pendingView) {
    window.switchView(window._pendingView, true);
    delete window._pendingView;
  }
  // Initialize Lucide icons after DOM is ready
  document.addEventListener('DOMContentLoaded', function() {
    lucide.createIcons();
  });

