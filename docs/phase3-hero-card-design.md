# Phase 3 Task 3.1: Hero Card Design

**Ziel:** Prominentes Hero-Element mit Health Status + inline Trend Chart

## Struktur

```html
<div class="hero-card health-{{ s.health }}">
  <div class="hero-header">
    <div class="hero-status">
      <i data-lucide="activity" class="hero-icon"></i>
      <div class="hero-status-text">
        <h1 class="hero-title">{{ health_label }}</h1>
        <p class="hero-subtitle">{{ health_msgs.get(s.health, '') }}</p>
      </div>
    </div>
    <div class="hero-meta">
      <span class="hero-channels">{{ s.ds_total }} DS / {{ s.us_total }} US</span>
      {% if isp_name %}<span class="hero-isp">{{ isp_name }}</span>{% endif %}
    </div>
  </div>
  
  {% if s.health_issues %}
  <div class="hero-issues">
    {% for issue in s.health_issues %}
    <span class="issue-badge">{{ issue_labels.get(issue, issue) }}</span>
    {% endfor %}
  </div>
  {% endif %}
  
  <div class="hero-chart-container">
    <canvas id="hero-trend-chart"></canvas>
  </div>
</div>
```

## Chart Spec (Chart.js)

- **Type:** Line Chart (2 Y-Achsen)
- **Left Y:** DS Power (dBmV), Bereich: -15 bis +25
- **Right Y:** SNR (dB), Bereich: 10 bis 50
- **X-Achse:** Zeit (letzte 24h, 1h Schritte)
- **Datasets:**
  - DS Power (lila, left Y)
  - SNR (blau, right Y)
- **Reference Zones:**
  - DS Power: good (-4 bis +13), warn/crit außerhalb
  - SNR: good (>33), warn (25-33), crit (<25)
- **Responsive:** true, maintainAspectRatio: false
- **Height:** 200px (CSS)

## CSS Variablen

```css
.hero-card {
  background: linear-gradient(135deg, var(--card-bg), rgba(168,85,247,0.03));
  border: 1px solid var(--card-border);
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 24px;
}

.hero-card.health-good { border-left: 4px solid var(--color-good); }
.hero-card.health-warn { border-left: 4px solid var(--color-warn); }
.hero-card.health-crit { border-left: 4px solid var(--color-crit); }

.hero-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.hero-status {
  display: flex;
  align-items: center;
  gap: 16px;
}

.hero-icon {
  width: 48px;
  height: 48px;
  color: var(--accent-purple);
}

.hero-title {
  font-size: 28px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
}

.hero-subtitle {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 4px 0 0 0;
}

.hero-meta {
  text-align: right;
  color: var(--text-secondary);
  font-size: 13px;
}

.hero-issues {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

.issue-badge {
  background: rgba(251,191,36,0.15);
  color: var(--color-warn);
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}

.hero-chart-container {
  height: 200px;
  margin-top: 16px;
}
```

## JavaScript (hero-chart.js)

```javascript
// Init Hero Trend Chart nach DOM ready
document.addEventListener('DOMContentLoaded', () => {
  const ctx = document.getElementById('hero-trend-chart');
  if (!ctx) return;
  
  // Fetch last 24h data from API
  fetch('/api/history?hours=24')
    .then(r => r.json())
    .then(data => {
      const labels = data.map(d => new Date(d.timestamp * 1000));
      const dsPower = data.map(d => d.ds_power_avg);
      const snr = data.map(d => d.ds_snr_avg);
      
      new Chart(ctx, {
        type: 'line',
        data: {
          labels: labels,
          datasets: [{
            label: 'DS Power (dBmV)',
            data: dsPower,
            borderColor: 'rgba(168,85,247,0.8)',
            backgroundColor: 'rgba(168,85,247,0.1)',
            yAxisID: 'y-power',
            tension: 0.3,
            pointRadius: 0,
            borderWidth: 2
          }, {
            label: 'SNR (dB)',
            data: snr,
            borderColor: 'rgba(59,130,246,0.8)',
            backgroundColor: 'rgba(59,130,246,0.1)',
            yAxisID: 'y-snr',
            tension: 0.3,
            pointRadius: 0,
            borderWidth: 2
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { display: true, position: 'top' },
            tooltip: { mode: 'index' }
          },
          scales: {
            x: {
              type: 'time',
              time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
              grid: { color: 'rgba(255,255,255,0.05)' }
            },
            'y-power': {
              type: 'linear',
              position: 'left',
              min: -15,
              max: 25,
              title: { display: true, text: 'Power (dBmV)' },
              grid: { color: 'rgba(255,255,255,0.05)' }
            },
            'y-snr': {
              type: 'linear',
              position: 'right',
              min: 10,
              max: 50,
              title: { display: true, text: 'SNR (dB)' },
              grid: { display: false }
            }
          }
        }
      });
    });
});
```

## Integration Steps

1. ✅ Design Doc erstellt
2. ⏳ HTML in index.html einfügen (nach {% set %} Variablen, vor alten Cards)
3. ⏳ CSS in main.css hinzufügen
4. ⏳ JavaScript als `static/js/hero-chart.js` erstellen
5. ⏳ Script-Tag in index.html einbinden
6. ⏳ Altes Health Banner auskommentieren
7. ⏳ Container rebuild + Test

**Status:** Design definiert, bereit für Implementation
