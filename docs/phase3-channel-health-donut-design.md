# Phase 3 Task 3.4: Channel Health Donut Chart

**Ziel:** Visueller Überblick über Channel Health Distribution (good/warn/crit) als Donut Charts.

## Position

Zwischen **Metric Summary Row** und **Channel Sections** → neue "Channel Health Overview" Card.

## Structure

```html
<div class="channel-health-card">
  <div class="channel-health-header">
    <i data-lucide="pie-chart" class="channel-health-icon"></i>
    <h3 class="channel-health-title">{{ t.channel_health_overview }}</h3>
  </div>
  
  <div class="channel-health-charts">
    <!-- Downstream Donut -->
    <div class="health-chart-container">
      <canvas id="ds-health-donut"></canvas>
      <div class="chart-label">{{ t.downstream }}</div>
    </div>
    
    <!-- Upstream Donut -->
    <div class="health-chart-container">
      <canvas id="us-health-donut"></canvas>
      <div class="chart-label">{{ t.upstream }}</div>
    </div>
  </div>
  
  <div class="channel-health-legend">
    <div class="legend-item">
      <span class="legend-dot legend-good"></span>
      <span class="legend-label">{{ t.health_good }}</span>
    </div>
    <div class="legend-item">
      <span class="legend-dot legend-warn"></span>
      <span class="legend-label">{{ t.health_warning }}</span>
    </div>
    <div class="legend-item">
      <span class="legend-dot legend-crit"></span>
      <span class="legend-label">{{ t.health_critical }}</span>
    </div>
  </div>
</div>
```

## CSS

```css
.channel-health-card {
  background: var(--card-bg, var(--card));
  border: 1px solid var(--card-border, var(--input-border));
  border-radius: var(--radius-md, 8px);
  padding: var(--space-lg, 20px);
  margin-bottom: var(--space-xl, 24px);
}

.channel-health-header {
  display: flex;
  align-items: center;
  gap: var(--space-sm, 12px);
  margin-bottom: var(--space-lg, 20px);
}

.channel-health-icon {
  width: 24px;
  height: 24px;
  color: var(--accent-purple, var(--purple-500));
}

.channel-health-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary, var(--text));
  margin: 0;
}

.channel-health-charts {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-xl, 24px);
  margin-bottom: var(--space-lg, 20px);
}

.health-chart-container {
  position: relative;
  height: 200px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.health-chart-container canvas {
  max-height: 180px;
}

.chart-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary, var(--muted));
  margin-top: var(--space-sm, 8px);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.channel-health-legend {
  display: flex;
  justify-content: center;
  gap: var(--space-lg, 24px);
  padding-top: var(--space-md, 16px);
  border-top: 1px solid var(--card-border, var(--input-border));
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.legend-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.legend-dot.legend-good { background: var(--color-good, var(--good)); }
.legend-dot.legend-warn { background: var(--color-warn, var(--warn)); }
.legend-dot.legend-crit { background: var(--color-crit, var(--crit)); }

.legend-label {
  font-size: 13px;
  color: var(--text-secondary, var(--muted));
}

/* Mobile: Stack donuts vertically */
@media (max-width: 600px) {
  .channel-health-charts {
    grid-template-columns: 1fr;
    gap: var(--space-md, 16px);
  }
  
  .health-chart-container {
    height: 180px;
  }
  
  .channel-health-legend {
    gap: var(--space-md, 16px);
    flex-wrap: wrap;
  }
}
```

## Chart.js Configuration

```javascript
// Data preparation from template variables
const dsHealthCounts = {
  good: {{ ds|selectattr('health', 'equalto', 'good')|list|length }},
  warn: {{ ds|rejectattr('health', 'equalto', 'good')|rejectattr('health', 'equalto', 'critical')|list|length }},
  crit: {{ ds|selectattr('health', 'equalto', 'critical')|list|length }}
};

const usHealthCounts = {
  good: {{ us|selectattr('health', 'equalto', 'good')|list|length }},
  warn: {{ us|rejectattr('health', 'equalto', 'good')|rejectattr('health', 'equalto', 'critical')|list|length }},
  crit: {{ us|selectattr('health', 'equalto', 'critical')|list|length }}
};

// Donut chart config
const donutConfig = {
  type: 'doughnut',
  data: {
    labels: ['Good', 'Warning', 'Critical'],
    datasets: [{
      data: [counts.good, counts.warn, counts.crit],
      backgroundColor: [
        'rgba(76, 175, 80, 0.8)',   // good
        'rgba(255, 152, 0, 0.8)',   // warn
        'rgba(244, 67, 54, 0.8)'    // crit
      ],
      borderColor: [
        'rgba(76, 175, 80, 1)',
        'rgba(255, 152, 0, 1)',
        'rgba(244, 67, 54, 1)'
      ],
      borderWidth: 2
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: true,
    cutout: '65%',  // Donut hole size
    plugins: {
      legend: { display: false },  // Custom legend below
      tooltip: {
        backgroundColor: 'rgba(15,20,25,0.95)',
        titleColor: 'rgba(224,224,224,0.9)',
        bodyColor: 'rgba(224,224,224,0.8)',
        borderColor: 'rgba(168,85,247,0.3)',
        borderWidth: 1,
        padding: 12,
        displayColors: true,
        callbacks: {
          label: function(context) {
            const label = context.label || '';
            const value = context.parsed || 0;
            const total = context.dataset.data.reduce((a, b) => a + b, 0);
            const percentage = total > 0 ? ((value / total) * 100).toFixed(1) : 0;
            return `${label}: ${value} (${percentage}%)`;
          }
        }
      }
    }
  }
};
```

## Icon Mapping

- **Channel Health Overview:** `pie-chart` (Lucide)

## Integration Steps

1. ✅ Design Doc erstellt
2. ⏳ HTML: Channel Health Card nach Metric Summary Row einfügen
3. ⏳ JavaScript: Inline script für Donut Chart Rendering (in index.html)
4. ⏳ CSS: Channel Health Card Styles hinzufügen
5. ⏳ Container rebuild + Test
6. ⏳ Commit + Push

## Translation Keys (may need to add)

- `channel_health_overview`: "Channel Health Overview" (EN) / "Kanal-Status Übersicht" (DE)
- Existing: `health_good`, `health_warning`, `health_critical`, `downstream`, `upstream`

**Status:** Design definiert, bereit für Implementation
