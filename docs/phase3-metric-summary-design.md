# Phase 3 Task 3.2: Metric Summary Row Design

**Ziel:** Kompakte Metric Cards unterhalb der Hero Card – nur Key Metrics, kein expandable Detail.

## Struktur

```html
<div class="metric-summary-row">
  <!-- Card 1: Downstream Signal -->
  <div class="metric-summary-card health-{{ signal_health }}">
    <div class="metric-summary-header">
      <i data-lucide="radio" class="metric-icon"></i>
      <span class="metric-label">Downstream</span>
    </div>
    <div class="metric-summary-values">
      <div class="metric-value-item">
        <span class="value val-{{ ds_pwr_health }}">{{ s.ds_power_avg }}</span>
        <span class="unit">dBmV</span>
        <span class="sublabel">Power</span>
      </div>
      <div class="metric-value-divider"></div>
      <div class="metric-value-item">
        <span class="value val-{{ snr_health }}">{{ s.ds_snr_avg }}</span>
        <span class="unit">dB</span>
        <span class="sublabel">SNR</span>
      </div>
    </div>
  </div>

  <!-- Card 2: Upstream Signal -->
  <div class="metric-summary-card health-{{ us_health }}">
    <div class="metric-summary-header">
      <i data-lucide="radio" class="metric-icon"></i>
      <span class="metric-label">Upstream</span>
    </div>
    <div class="metric-summary-values">
      <div class="metric-value-item">
        <span class="value val-{{ us_health }}">{{ s.us_power_avg }}</span>
        <span class="unit">dBmV</span>
        <span class="sublabel">Power</span>
      </div>
    </div>
  </div>

  <!-- Card 3: Errors -->
  <div class="metric-summary-card health-{{ error_health }}">
    <div class="metric-summary-header">
      <i data-lucide="alert-triangle" class="metric-icon"></i>
      <span class="metric-label">Errors</span>
    </div>
    <div class="metric-summary-values">
      <div class="metric-value-item">
        <span class="value val-{{ error_health }}">{{ s.ds_uncorrectable_errors|fmt_k }}</span>
        <span class="unit">uncorr</span>
        <span class="sublabel">{{ s.ds_correctable_errors|fmt_k }} corr</span>
      </div>
    </div>
  </div>

  <!-- Card 4: Speedtest (conditional) -->
  {% if speedtest_configured and speedtest_latest %}
  <div class="metric-summary-card {{ speed_health }}">
    <div class="metric-summary-header">
      <i data-lucide="zap" class="metric-icon"></i>
      <span class="metric-label">Speed</span>
    </div>
    <div class="metric-summary-values">
      <div class="metric-value-item">
        <span class="value {{ dl_val_class }}">{{ speedtest_latest.download_human or (speedtest_latest.download_mbps ~ ' Mbps') }}</span>
        <span class="sublabel">↓ Download</span>
      </div>
      <div class="metric-value-divider"></div>
      <div class="metric-value-item">
        <span class="value {{ ul_val_class }}">{{ speedtest_latest.upload_human or (speedtest_latest.upload_mbps ~ ' Mbps') }}</span>
        <span class="sublabel">↑ Upload</span>
      </div>
    </div>
  </div>
  {% endif %}
</div>
```

## CSS

```css
.metric-summary-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--space-md, 16px);
  margin-bottom: var(--space-xl, 24px);
}

.metric-summary-card {
  background: var(--card-bg, var(--card));
  border: 1px solid var(--card-border, var(--input-border));
  border-radius: var(--radius-md, 8px);
  padding: var(--space-md, 16px);
  transition: all 0.2s ease;
}

.metric-summary-card:hover {
  border-color: var(--accent-purple, var(--purple-500));
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(168,85,247,0.15);
}

.metric-summary-card.health-good { border-left: 3px solid var(--color-good, var(--good)); }
.metric-summary-card.health-warn { border-left: 3px solid var(--color-warn, var(--warn)); }
.metric-summary-card.health-crit { border-left: 3px solid var(--color-crit, var(--crit)); }

.metric-summary-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: var(--space-sm, 12px);
}

.metric-icon {
  width: 20px;
  height: 20px;
  color: var(--text-secondary, var(--muted));
}

.metric-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary, var(--muted));
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.metric-summary-values {
  display: flex;
  justify-content: space-around;
  align-items: center;
  gap: var(--space-sm, 12px);
}

.metric-value-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  flex: 1;
}

.metric-value-item .value {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-primary, var(--text));
  line-height: 1;
  margin-bottom: 4px;
}

.metric-value-item .unit {
  font-size: 11px;
  color: var(--text-secondary, var(--muted));
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.metric-value-item .sublabel {
  font-size: 11px;
  color: var(--text-secondary, var(--muted));
  margin-top: 4px;
}

.metric-value-divider {
  width: 1px;
  height: 40px;
  background: var(--input-border, rgba(255,255,255,0.15));
}

/* Value color classes */
.val-good { color: var(--color-good, var(--good)) !important; }
.val-warn { color: var(--color-warn, var(--warn)) !important; }
.val-bad, .val-crit { color: var(--color-crit, var(--crit)) !important; }

/* Mobile: 2x2 Grid */
@media (max-width: 600px) {
  .metric-summary-row {
    grid-template-columns: repeat(2, 1fr);
    gap: var(--space-sm, 12px);
  }
  
  .metric-summary-card {
    padding: var(--space-sm, 12px);
  }
  
  .metric-value-item .value {
    font-size: 20px;
  }
}
```

## Icon Mapping

- **Downstream:** `radio` (signal waves)
- **Upstream:** `radio` (same, consistent)
- **Errors:** `alert-triangle` (warning symbol)
- **Speed:** `zap` (lightning bolt)

## Integration Steps

1. ✅ Design Doc erstellt
2. ⏳ HTML nach Hero Card einfügen (vor alten metric-cards)
3. ⏳ CSS in main.css hinzufügen
4. ⏳ Alte metric-cards auskommentieren
5. ⏳ Container rebuild + Test
6. ⏳ Commit + Push

**Status:** Design definiert, bereit für Implementation
