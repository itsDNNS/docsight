# Phase 3 Task 3.5: Channel Tables in Card Containers

**Ziel:** Channel-Tabellen in moderne Card-Container wrappen, konsistent mit Hero/Metric Cards.

## Current Structure

```html
<h2 class="section-title">Downstream (32 Channels)</h2>
<details class="channel-group">
  <summary>DOCSIS 3.1 (2 channels) ✓</summary>
  <table class="sortable">...</table>
</details>
<details class="channel-group">
  <summary>DOCSIS 3.0 (30 channels) ✓</summary>
  <table class="sortable">...</table>
</details>

<h2 class="section-title">Upstream (8 Channels)</h2>
<details class="channel-group">...</details>
```

## New Structure

```html
<div class="channel-section">
  <div class="channel-section-header">
    <i data-lucide="radio-tower" class="section-icon"></i>
    <h2 class="section-title">Downstream</h2>
    <span class="section-badge">{{ ds|length }} {{ t.channels }}</span>
  </div>
  
  <div class="channel-card">
    <details class="channel-group" open>
      <summary>
        <div class="channel-group-summary">
          <span class="channel-group-label">DOCSIS {{ group.grouper }}</span>
          <span class="channel-group-count">({{ group.list|length }} {{ t.channels }})</span>
          <div class="channel-group-badges">
            {% if g_crit %}<span class="badge badge-crit">{{ g_crit }} {{ t.health_critical|lower }}</span>{% endif %}
            {% if g_warn %}<span class="badge badge-warn">{{ g_warn }} {{ t.health_warning|lower }}</span>{% endif %}
            {% if not g_crit and not g_warn %}<span class="badge badge-good">✓</span>{% endif %}
          </div>
        </div>
      </summary>
      <div class="channel-table-wrapper">
        <table class="sortable">...</table>
      </div>
    </details>
  </div>
</div>
```

## CSS

```css
.channel-section {
  margin-bottom: var(--space-xl, 24px);
}

.channel-section-header {
  display: flex;
  align-items: center;
  gap: var(--space-sm, 12px);
  margin-bottom: var(--space-md, 16px);
}

.section-icon {
  width: 24px;
  height: 24px;
  color: var(--accent-purple, var(--purple-500));
}

.section-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary, var(--text));
  margin: 0;
}

.section-badge {
  background: rgba(168,85,247,0.15);
  color: var(--accent-purple, var(--purple-500));
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.channel-card {
  background: var(--card-bg, var(--card));
  border: 1px solid var(--card-border, var(--input-border));
  border-radius: var(--radius-md, 8px);
  overflow: hidden;
  margin-bottom: var(--space-md, 16px);
}

.channel-group {
  border: none;
  margin: 0;
}

.channel-group summary {
  cursor: pointer;
  padding: var(--space-md, 16px);
  background: rgba(0,0,0,0.1);
  border-bottom: 1px solid var(--card-border, var(--input-border));
  user-select: none;
  transition: background 0.2s ease;
  list-style: none; /* Remove default arrow */
}

.channel-group summary::-webkit-details-marker {
  display: none; /* Remove default arrow in WebKit */
}

.channel-group summary:hover {
  background: rgba(168,85,247,0.08);
}

.channel-group-summary {
  display: flex;
  align-items: center;
  gap: var(--space-sm, 12px);
  flex-wrap: wrap;
}

.channel-group-label {
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary, var(--text));
}

.channel-group-count {
  font-size: 13px;
  color: var(--text-secondary, var(--muted));
}

.channel-group-badges {
  display: flex;
  gap: 6px;
  margin-left: auto;
}

.channel-table-wrapper {
  padding: var(--space-md, 16px);
  overflow-x: auto;
}

/* Add chevron indicator for collapsed state */
.channel-group summary::before {
  content: '▶';
  display: inline-block;
  margin-right: 8px;
  transition: transform 0.2s ease;
  color: var(--text-secondary, var(--muted));
  font-size: 10px;
}

.channel-group[open] summary::before {
  transform: rotate(90deg);
}

/* Mobile: Stack badges below */
@media (max-width: 600px) {
  .channel-section-header {
    flex-wrap: wrap;
  }
  
  .channel-group-summary {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }
  
  .channel-group-badges {
    margin-left: 0;
  }
}
```

## Icon Mapping

- **Downstream Section:** `radio-tower` (broadcast tower)
- **Upstream Section:** `radio-tower` (same, consistent)

## Changes to Existing Elements

- Remove old `.section-title` standalone styles (now in `.channel-section-header`)
- Keep existing `.channel-group` table styles
- `.sortable` table styles unchanged
- Badge styles (`.badge-good`, `.badge-warn`, `.badge-crit`) unchanged

## Integration Steps

1. ✅ Design Doc erstellt
2. ⏳ HTML: Wrap Downstream section in new structure
3. ⏳ HTML: Wrap Upstream section in new structure
4. ⏳ CSS: Add new channel card styles
5. ⏳ CSS: Update old section-title styles
6. ⏳ Container rebuild + Test
7. ⏳ Commit + Push

**Status:** Design definiert, bereit für Implementation
