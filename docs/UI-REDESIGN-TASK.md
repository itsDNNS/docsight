# DOCSight v2.0 Web UI Redesign

## 1. Design Concept Analysis

### 1.1 Mockup Overview

The reference design (`docs/ui-redesign-concept.jpg`) presents a **modern, premium dark dashboard** with a polished SaaS aesthetic. While the mockup originates from a finance/order management context, its design language translates directly to DOCSight's monitoring use case.

### 1.2 Layout Structure

```
┌──────────────────────────────────────────────────────────────┐
│ ┌──────────┐ ┌──────────────────────────────────────────────┐│
│ │          │ │  Top Bar: Search │ Action Button │ Icons     ││
│ │          │ ├──────────────────────────────────────────────┤│
│ │ Sidebar  │ │  Welcome Header + Time Range Toggles        ││
│ │ (fixed)  │ ├──────────────────────────────────────────────┤│
│ │          │ │  Hero Card: Primary metric + area chart      ││
│ │  Nav     │ │  ┌──────┬──────┬──────┬──────┐              ││
│ │  items   │ │  │ Sub  │ Sub  │ Sub  │ Sub  │ Summary row  ││
│ │          │ │  └──────┴──────┴──────┴──────┘              ││
│ │          │ ├──────────────────────────────────────────────┤│
│ │ Help     │ │  ┌────────────┐ ┌────────────┐              ││
│ │ Dark mode│ │  │ Donut card │ │ Table card │ Bottom row   ││
│ │          │ │  └────────────┘ └────────────┘              ││
│ └──────────┘ └──────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

**Sidebar (~240px fixed)**:
- Logo + app icon in header, collapse toggle button
- Navigation items with leading icons, text labels
- Active state: rounded highlight background (subtle, not full-width)
- Grouped sections (main nav, secondary tools)
- Bottom: "Help & information" link, Dark Mode toggle
- Optional: promotional/info card at bottom (for DOCSight: version info, collector status)

**Top Bar (sticky)**:
- Left: Search input (rounded, dark background, magnifying glass icon)
- Right: Primary CTA button (rounded pill, accent color), icon buttons (notifications, chat/info), user avatar

**Main Content Area**:
- Welcome header with greeting text
- Time range toggle (pill buttons: Today / Week / custom calendar icon)
- Hero card: large metric + inline area chart (gradient fill, purple/violet palette)
- Summary row: 4 sub metric cards (compact, label + value + trend arrow)
- Bottom cards: 2 column layout (donut chart card + data table card)

### 1.3 Visual Design Language

| Element | Mockup Style |
|---------|-------------|
| **Background** | Deep charcoal/near-black (#111827 range) |
| **Card surface** | Dark elevated (#1e2330 range), subtle border or shadow |
| **Card corners** | Large border-radius (12-16px) |
| **Accent color** | Purple/violet gradient (#7c3aed → #a855f7) for charts, CTAs |
| **Secondary accent** | Cyan/teal for active nav, links |
| **Text primary** | White/near-white (#f0f0f0) |
| **Text secondary** | Muted gray (#9ca3af) |
| **Trend indicators** | Green arrows (up/positive), Red/pink arrows (down/negative) |
| **Charts** | Area charts with gradient fills, smooth curves |
| **Donut charts** | Thick rings, color-coded segments, center hollow |
| **Typography** | Clean sans-serif (Inter/System), generous spacing |
| **Spacing** | Generous padding (20-24px cards), 16-20px gaps between cards |
| **Shadows** | Minimal, rely on surface color elevation instead |
| **Transitions** | Smooth 0.2-0.3s for hover, active states |

### 1.4 Interactive Elements

- **Pill toggle buttons**: Segmented controls with rounded edges (Today/Week)
- **Tooltip on chart**: Hover card with date + value, connected via dot on line
- **Dark mode toggle**: Slide switch in sidebar footer
- **Active nav item**: Rounded background highlight with subtle opacity
- **Icon buttons**: Circular, subtle background on hover
- **Search bar**: Rounded input with search icon prefix
- **Cards**: No explicit borders, differentiated by background shade

---

## 2. Key Differences from Current DOCSight UI

### 2.1 Visual/Aesthetic Changes

| Aspect | Current UI | Target Design |
|--------|-----------|---------------|
| **Card style** | Flat, thin border, 6-10px radius | Elevated surface, no border, 12-16px radius |
| **Color palette** | Cyan (#00adb5) accent, navy (#0f3460) cards | Purple/violet accent gradient, charcoal cards |
| **Chart style** | Basic Chart.js lines | Gradient-fill area charts, smooth curves |
| **Spacing** | Compact, dense data | Generous whitespace, breathing room |
| **Typography** | System fonts, compact | Clean sans-serif (Inter), larger headings |
| **Shadows** | Box-shadow on cards | Minimal shadows, surface elevation |
| **Icons** | Unicode/text emoji (☀/☾, ⓘ, ⏳) | SVG or icon font (Lucide, Phosphor) |
| **Status badges** | Simple colored backgrounds | Refined with trend arrows + subtle background |
| **Dark theme** | Navy-blue tones | Charcoal/slate tones |
| **Light theme** | Light gray background | Needs full redesign with matching palette |

### 2.2 Layout Changes

| Aspect | Current UI | Target Design |
|--------|-----------|---------------|
| **Sidebar header** | Logo + text + collapse button | Cleaner branding, icon-only collapse state |
| **Top bar** | Title + refresh + language + theme | Search + action button + notifications + avatar |
| **Dashboard hero** | 4 equal metric cards in grid | 1 large hero card with embedded chart |
| **Sub metrics** | Expandable detail cards | Compact summary row (4 cards) |
| **Channel tables** | Inline expandable below cards | Separate table card with clean styling |
| **Health banner** | Full-width banner at top | Integrated into hero card or sidebar indicator |
| **Bottom section** | None (all cards are equal) | 2 column layout (chart + table) |

### 2.3 Component Changes

| Component | Current | Target |
|-----------|---------|--------|
| **Time filter** | Date navigator (< date >) with calendar popup | Pill toggle (Today/Week/Month) + calendar icon |
| **Theme toggle** | Sun/Moon icon in topbar | Slide switch in sidebar footer |
| **Language selector** | Dropdown in topbar | Move to settings (reduce topbar clutter) |
| **Refresh button** | Icon in topbar | Either auto-refresh indicator or subtle icon |
| **Chart expansion** | ↗ button opens fullscreen modal | Keep, but restyle modal to match new design |
| **Tables** | Dense, sortable inline tables | Card-wrapped tables with cleaner row styling |
| **Status indicators** | Color-coded text badges | Color-coded pills with rounded backgrounds |

### 2.4 What Stays the Same

- Sidebar navigation pattern (but visually refreshed)
- View-switching via hash routing
- Chart.js for data visualization (but with new styling)
- All existing views (Live, Trends, Events, Channels, Correlation, Speedtest, BQM, Journal)
- All existing API endpoints (no backend changes required)
- Responsive behavior (sidebar collapses on mobile)
- i18n system (Jinja2 translations)
- Auto-refresh mechanism on live dashboard

---

## 3. Implementation Requirements

### 3.1 CSS Architecture Overhaul

**Extract CSS from inline `<style>` to external file(s):**
```
app/static/css/
├── variables.css      # CSS custom properties (themes, spacing, colors)
├── base.css           # Reset, typography, body
├── layout.css         # Sidebar, topbar, main content grid
├── components.css     # Cards, badges, buttons, toggles, modals
├── charts.css         # Chart wrappers, canvas styling
├── tables.css         # Table styling
├── views.css          # View-specific overrides
├── responsive.css     # Media queries
└── main.css           # Import aggregator (@import all above)
```

**New CSS Custom Properties:**
```css
:root {
  /* Surface elevation system */
  --surface-0: #0f1117;     /* page background */
  --surface-1: #1a1d28;     /* card background */
  --surface-2: #242836;     /* elevated card / hover */
  --surface-3: #2e3345;     /* active / selected */

  /* Accent palette */
  --accent-primary: #7c3aed;    /* purple */
  --accent-secondary: #a855f7;  /* lighter purple */
  --accent-gradient: linear-gradient(135deg, #7c3aed, #a855f7);
  --accent-cyan: #06b6d4;       /* links, active nav */

  /* Status colors */
  --status-good: #22c55e;
  --status-warn: #f59e0b;
  --status-crit: #ef4444;
  --status-info: #3b82f6;

  /* Spacing system */
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 16px;
  --space-lg: 24px;
  --space-xl: 32px;

  /* Border radius */
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-full: 9999px;

  /* Typography */
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
}
```

### 3.2 Font Loading

Add Inter font (self-hosted or Google Fonts CDN):
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
```

Or use `@font-face` with self-hosted woff2 files in `app/static/fonts/`.

### 3.3 Icon System

Replace Unicode/emoji icons with a proper icon library:

**Recommended: Lucide Icons (SVG, tree-shakeable)**
- Open source, MIT licensed
- Consistent 24x24 grid, 2px stroke
- CDN or self-hosted SVG sprite
- Usage: `<svg class="icon"><use href="#icon-name"/></svg>`

Alternatively: Phosphor Icons or Tabler Icons (both open source, similar quality).

### 3.4 Component Redesign

**Cards:**
```css
.card {
  background: var(--surface-1);
  border-radius: var(--radius-lg);
  padding: var(--space-lg);
  transition: background 0.2s ease;
}
.card:hover {
  background: var(--surface-2);
}
```

**Hero Card (new component):**
- Large card spanning full content width
- Contains: primary metric (e.g., overall health status), trend arrow, inline area chart
- Sub-heading with descriptive text
- For DOCSight: Overall Health with SNR trend chart

**Metric Summary Row (new component):**
- 4 compact cards in a row (flex or grid)
- Each shows: label, value, trend indicator (arrow + percentage)
- For DOCSight: DS Power avg, US Power avg, Error rate, Speed (if configured)

**Pill Toggle (new component):**
```html
<div class="pill-toggle">
  <button class="pill-toggle-btn active">Today</button>
  <button class="pill-toggle-btn">Week</button>
  <button class="pill-toggle-btn">Month</button>
</div>
```

**Donut Chart Card (new component):**
- For channel health distribution (Good/Marginal/Poor/Critical counts)
- Chart.js doughnut with thick rings
- Legend with colored dots beside chart

**Sidebar Redesign:**
- Cleaner nav items with SVG icons
- Grouped sections with subtle dividers
- Active item: rounded background, accent left border or fill
- Collapse: icon-only mode with tooltips
- Footer: Help link + dark/light toggle switch

**Top Bar Redesign:**
- Search input (decorative or functional; could filter events/logs)
- Primary action button: "Run Poll" or "Export Report"
- Notification bell (unacknowledged events count)
- User/modem info avatar area

### 3.5 Chart Styling Overhaul

**Chart.js configuration updates:**
```javascript
const chartDefaults = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor: 'rgba(30, 35, 48, 0.95)',
      titleFont: { family: 'Inter', size: 13 },
      bodyFont: { family: 'Inter', size: 12 },
      padding: 12,
      cornerRadius: 8,
      borderColor: 'rgba(124, 58, 237, 0.3)',
      borderWidth: 1,
    }
  },
  scales: {
    x: {
      grid: { color: 'rgba(255,255,255,0.05)' },
      ticks: { color: '#9ca3af', font: { family: 'Inter' } }
    },
    y: {
      grid: { color: 'rgba(255,255,255,0.05)' },
      ticks: { color: '#9ca3af', font: { family: 'Inter' } }
    }
  }
};
```

**Gradient fills for area charts:**
```javascript
const gradient = ctx.createLinearGradient(0, 0, 0, height);
gradient.addColorStop(0, 'rgba(124, 58, 237, 0.4)');
gradient.addColorStop(1, 'rgba(124, 58, 237, 0.0)');
dataset.backgroundColor = gradient;
dataset.borderColor = '#a855f7';
dataset.fill = true;
dataset.tension = 0.4; // smooth curves
```

### 3.6 Table Redesign

```css
.table-card {
  background: var(--surface-1);
  border-radius: var(--radius-lg);
  overflow: hidden;
}
.table-card table {
  width: 100%;
  border-collapse: collapse;
}
.table-card th {
  background: var(--surface-2);
  padding: var(--space-sm) var(--space-md);
  text-align: left;
  font-weight: 600;
  color: var(--text-secondary);
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.table-card td {
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid rgba(255,255,255,0.05);
}
.table-card tr:hover {
  background: var(--surface-2);
}
```

### 3.7 Responsive Design Updates

**Breakpoints (align with modern standards):**
```css
/* Mobile first approach */
@media (min-width: 640px)  { /* sm: tablets */ }
@media (min-width: 1024px) { /* lg: desktop */ }
@media (min-width: 1280px) { /* xl: wide desktop */ }
```

**Mobile sidebar:**
- Transform: translateX(-100%) → translateX(0) with backdrop
- Touch-swipe gesture support (optional enhancement)

**Mobile dashboard:**
- Hero card: chart below metric instead of beside it
- Summary row: 2x2 grid instead of 4 columns
- Bottom cards: stack vertically
- Tables: horizontal scroll with sticky first column

### 3.8 Animation & Transitions

```css
/* Consistent transition timing */
--transition-fast: 150ms ease;
--transition-base: 200ms ease;
--transition-slow: 300ms ease;

/* View transitions */
.view { opacity: 0; transition: opacity var(--transition-base); }
.view.active { opacity: 1; }

/* Card hover */
.card { transition: background var(--transition-fast), transform var(--transition-fast); }
.card:hover { transform: translateY(-1px); }

/* Sidebar collapse */
.sidebar { transition: width var(--transition-slow); }
.sidebar.collapsed { width: 64px; }
```

### 3.9 Light Theme Adaptation

The mockup is dark-only, but DOCSight supports dual themes. The light theme needs:

```css
[data-theme="light"] {
  --surface-0: #f8fafc;
  --surface-1: #ffffff;
  --surface-2: #f1f5f9;
  --surface-3: #e2e8f0;
  --text-primary: #1e293b;
  --text-secondary: #64748b;
  /* Accent colors stay the same (purple works on both) */
}
```

---

## 4. Implementation Phases

### Phase 1: Foundation (CSS Architecture + Design Tokens)
**Scope:** Extract CSS, establish design system, no visual changes yet

- [ ] Extract all inline `<style>` from `index.html` to `app/static/css/` files
- [ ] Define CSS custom properties (colors, spacing, typography, radius)
- [ ] Add Inter font loading
- [ ] Add icon library (Lucide CDN or self-hosted SVG sprite)
- [ ] Verify no visual regressions (existing styles preserved in new files)
- [ ] Update `settings.html` and `setup.html` to use shared CSS
- [ ] Add all new i18n keys to all 4 language files (EN/DE/FR/ES)

**Estimated scope:** ~15 files touched, medium complexity
**Risk:** Low (pure refactor, no behavior change)

### Phase 2: Sidebar + Top Bar Redesign
**Scope:** New navigation chrome, keeping content views untouched

- [ ] Redesign sidebar: new colors, icon library, active states, section grouping
- [ ] Implement sidebar collapsed (icon-only) state with tooltips
- [ ] Redesign top bar: search input, action button, notification bell, avatar area
- [ ] Move language selector from topbar to settings
- [ ] Move dark mode toggle from topbar to sidebar footer (slide switch)
- [ ] Mobile sidebar: improve slide-in animation, touch backdrop
- [ ] Ensure all existing nav items work (view switching unchanged)

**Estimated scope:** Sidebar + topbar HTML/CSS, ~3-5 files
**Risk:** Low-medium (navigation must stay functional)

### Phase 3: Live Dashboard Redesign
**Scope:** Complete redesign of the primary dashboard view

- [ ] Hero card: overall health status + inline SNR/power trend chart
- [ ] Metric summary row: 4 compact cards (DS power, US power, errors, speed)
- [ ] Pill toggle for time range (replaces date navigator on dashboard)
- [ ] Channel health donut chart card
- [ ] Channel tables: wrapped in card containers, cleaner styling
- [ ] Health banner: integrate into hero card design
- [ ] Connection info bar: cleaner layout within hero card or as subtitle
- [ ] Range indicators: visual refresh with new color palette
- [ ] Status badges: pill-shaped with new colors

**Estimated scope:** Major HTML restructure of live view, new components
**Risk:** Medium (most complex view, must not break data binding)

### Phase 4: Secondary Views Redesign
**Scope:** Apply new design language to all other views

- [ ] **Trends view:** Area charts with gradient fills, new tab styling, card wrappers
- [ ] **Events view:** Card-wrapped table, severity filters as pill toggles
- [ ] **Channel Timeline:** Chart card wrappers, new chart colors
- [ ] **Correlation Analysis:** Unified card layout, source toggles as pills
- [ ] **Speedtest Tracker:** Custom canvas chart with new colors, table card
- [ ] **BQM Graphs:** Card wrapper for embedded image
- [ ] **Incident Journal:** Card table, modal redesign
- [ ] **Export/Report modals:** Match new modal design

**Estimated scope:** All secondary views, ~7 view sections
**Risk:** Medium (many views, but changes are primarily visual)

### Phase 5: Settings + Setup Wizard
**Scope:** Apply design to configuration screens

- [ ] Settings page: new card-based tab layout, form styling
- [ ] Setup wizard: restyle stepper, form cards, transition animations
- [ ] Integration cards: match new card component style
- [ ] Test connection buttons: new button styling
- [ ] Toast notifications: match new design language

**Estimated scope:** `settings.html`, `setup.html`
**Risk:** Low (isolated pages)

### Phase 6: Polish + Responsive QA
**Scope:** Cross-browser, responsive, performance, accessibility

- [ ] Responsive testing: mobile (360px), tablet (768px), desktop (1280px+)
- [ ] Cross-browser: Chrome, Firefox, Safari (latest)
- [ ] Performance: ensure CSS files are cached, minimize render-blocking
- [ ] Accessibility: focus states, keyboard navigation, contrast ratios (WCAG AA)
- [ ] Animation: verify smooth transitions, no jank
- [ ] Print stylesheet (optional, for reports)
- [ ] Final visual QA against mockup reference

**Estimated scope:** Testing, fixes, tweaks
**Risk:** Low

---

## 5. Technical Notes

### 5.1 No Build System Required
DOCSight uses vanilla JS/CSS with no bundler. The CSS can be split into files and loaded via `<link>` tags or a single concatenated file. No Sass/PostCSS/Tailwind needed.

### 5.2 Template Size Consideration
`index.html` is ~174 KB. Extracting CSS (~30-40 KB) to external files will:
- Reduce template size significantly
- Enable browser CSS caching (styles won't re-download on each page load)
- Make styling maintainable and diff-friendly

### 5.3 Backward Compatibility
- All existing JS functions must continue working
- All API endpoints remain unchanged
- Hash-based routing preserved
- i18n keys: add new ones, do not remove existing
- Docker image size impact: minimal (few KB of CSS files + font)

### 5.4 CDN vs Self-hosted Assets
- **Inter font:** Google Fonts CDN (simplest) or self-hosted woff2 (for offline/air-gapped deployments)
- **Icon library:** CDN preferred, self-hosted SVG sprite as fallback
- **Chart.js:** Already CDN, keep as-is

### 5.5 Testing
- Visual changes are hard to unit test; manual QA is primary
- Existing pytest suite (196 tests) should pass unchanged (no backend changes)
- Consider screenshots comparison (optional tooling)

---

## 6. Acceptance Criteria

1. **Dark theme** matches the design concept's visual language (charcoal surfaces, purple accents, gradient charts)
2. **Light theme** adapts the same design language with appropriate light colors
3. **All existing functionality** works identically (views, navigation, data loading, auto-refresh)
4. **Responsive design** works on mobile (360px+), tablet, and desktop
5. **Performance:** Page load time not significantly impacted (CSS caching helps)
6. **Accessibility:** WCAG AA contrast ratios, keyboard navigable
7. **i18n:** All 4 languages display correctly with new layout
8. **No backend changes** required
9. **CSS externalized** from templates into maintainable files
10. **Browser support:** Chrome, Firefox, Safari (latest 2 versions)

---

## 7. Reference

- **Mockup:** `docs/ui-redesign-concept.jpg`
- **Current template:** `app/templates/index.html` (~174 KB)
- **Current settings:** `app/templates/settings.html`
- **Current setup:** `app/templates/setup.html`
- **Milestone:** DOCSight v2.0 (https://github.com/itsDNNS/docsight/milestone/1)
