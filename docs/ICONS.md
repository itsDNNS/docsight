# DOCSight Icon Migration Plan

## Overview

Migrate from Unicode emoji to [Lucide Icons](https://lucide.dev/) for consistent,
scalable, theme-aware iconography across the dashboard.

## Why Lucide?

- Lightweight (~200 icons used, tree-shakeable)
- Consistent 24x24 stroke style
- CSS-customizable (color, size, stroke-width)
- Active maintenance, MIT licensed
- Works with vanilla JS (no framework dependency)

## CDN Setup

```html
<script src="https://unpkg.com/lucide@latest"></script>
```

Initialization: call `lucide.createIcons()` after DOM ready.

## Icon Mapping

### Sidebar Navigation — Monitoring

| Location | Current (Unicode) | Lucide Icon | Lucide Name |
|---|---|---|---|
| Live Dashboard | ● `&#9679;` | `<i data-lucide="radio">` | `Radio` |
| Event Log | 📔 `&#128276;` | `<i data-lucide="bell">` | `Bell` |
| Signal Trends | 📈 `&#128200;` | `<i data-lucide="trending-up">` | `TrendingUp` |
| Channel Timeline | 🕐 `&#128336;` | `<i data-lucide="clock">` | `Clock` |
| Correlation Analysis | 📊 `&#128202;` | `<i data-lucide="bar-chart-3">` | `BarChart3` |

### Sidebar Navigation — Tools

| Location | Current (Unicode) | Lucide Icon | Lucide Name |
|---|---|---|---|
| Speedtest | ⚡ `&#9889;` | `<i data-lucide="zap">` | `Zap` |
| Speedtest Setup | ⚙ `&#9881;` | `<i data-lucide="settings">` | `Settings` |
| BQM | 📹 `&#128225;` | `<i data-lucide="activity">` | `Activity` |
| BQM Setup | ⚙ `&#9881;` | `<i data-lucide="settings">` | `Settings` |
| Incident Journal | 📋 `&#128203;` | `<i data-lucide="clipboard-list">` | `ClipboardList` |
| Export LLM | 📾 `&#128190;` | `<i data-lucide="file-output">` | `FileOutput` |
| Incident Report | 🗢 `&#128226;` | `<i data-lucide="file-text">` | `FileText` |

### Sidebar Navigation — Account

| Location | Current (Unicode) | Lucide Icon | Lucide Name |
|---|---|---|---|
| Settings | ⚙ `&#9881;` | `<i data-lucide="settings">` | `Settings` |
| Logout | 🚪 `&#128682;` | `<i data-lucide="log-out">` | `LogOut` |

### Toolbar / Header

| Location | Current (Unicode) | Lucide Icon | Lucide Name |
|---|---|---|---|
| Hamburger menu | ☰ `&#9776;` | `<i data-lucide="menu">` | `Menu` |
| Refresh | 🔄 `&#x1F504;` | `<i data-lucide="refresh-cw">` | `RefreshCw` |
| Theme toggle (dark) | ☾ `&#9790;` | `<i data-lucide="moon">` | `Moon` |
| Theme toggle (light) | ☀ `&#9788;` | `<i data-lucide="sun">` | `Sun` |
| Collapse sidebar | ◀ `&#10094;` | `<i data-lucide="panel-left-close">` | `PanelLeftClose` |

### Status Indicators

| Location | Current (Unicode) | Lucide Icon | Lucide Name |
|---|---|---|---|
| Good / OK | ✔ `&#10004;` | `<i data-lucide="check-circle">` | `CheckCircle` |
| Poor / Error | ✖ `&#10006;` | `<i data-lucide="x-circle">` | `XCircle` |
| Warning | ⚠ `&#9888;` | `<i data-lucide="alert-triangle">` | `AlertTriangle` |
| Info tooltip | Ⓘ `&#9432;` | `<i data-lucide="info">` | `Info` |

### Directional / Navigation

| Location | Current (Unicode) | Lucide Icon | Lucide Name |
|---|---|---|---|
| Downstream | ↓ `&#8595;` | `<i data-lucide="arrow-down">` | `ArrowDown` |
| Upstream | ↑ `&#8593;` | `<i data-lucide="arrow-up">` | `ArrowUp` |
| Previous date | ‹ `&#8249;` | `<i data-lucide="chevron-left">` | `ChevronLeft` |
| Next date | › `&#8250;` | `<i data-lucide="chevron-right">` | `ChevronRight` |
| Expand section | ▶ `&#9654;` | `<i data-lucide="chevron-down">` | `ChevronDown` |

### Actions

| Location | Current (Unicode) | Lucide Icon | Lucide Name |
|---|---|---|---|
| Delete | 🗑 `&#128465;` | `<i data-lucide="trash-2">` | `Trash2` |
| Download | ⬏ `&#11015;` | `<i data-lucide="download">` | `Download` |
| Generate report | ✎ `&#9998;` | `<i data-lucide="pen-line">` | `PenLine` |
| Attachment | 📎 `&#128206;` | `<i data-lucide="paperclip">` | `Paperclip` |
| PDF document | 📄 `&#128196;` | `<i data-lucide="file">` | `File` |
| Uptime | ⏱ `&#9201;` | `<i data-lucide="timer">` | `Timer` |

### Chart / Data

| Location | Current (Unicode) | Lucide Icon | Lucide Name |
|---|---|---|---|
| Expand chart | ⛶ `&#x26F6;` | `<i data-lucide="maximize-2">` | `Maximize2` |
| Download indicator | ▼ `&#9660;` | `<i data-lucide="arrow-down">` | `ArrowDown` |
| Upload indicator | ▲ `&#9650;` | `<i data-lucide="arrow-up">` | `ArrowUp` |

## Migration Notes

- Replace HTML entities with `<i data-lucide="icon-name"></i>` elements
- Call `lucide.createIcons()` after DOM updates (tab switches, dynamic content)
- Icons inherit `color` from parent CSS (`currentColor`)
- Default size: 18px for inline, 20px for sidebar, 24px for headers
- Add `.lucide` class styling in `main.css` for consistent sizing
