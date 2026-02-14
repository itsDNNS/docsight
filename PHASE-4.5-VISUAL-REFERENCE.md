# DOCSight v2.0 Phase 4.5: Visual Reference Guide

This document describes the expected visual appearance of the 3 modernized views.

---

## 1. Channel Timeline View

### Layout Structure:
```
┌─────────────────────────────────────────────────────────┐
│ 📊 Channel Timeline                                     │
│                                                         │
│ [Select Channel ▼] [7 Days ▼]                         │
└─────────────────────────────────────────────────────────┘

┌──────────────────────┐ ┌──────────────────────┐ ┌──────────────────────┐
│ ⚡ Power (dBmV) & SNR│ │ ⚠️ Error History     │ │ 📈 Modulation       │
│        [↗️ Expand]   │ │        [↗️ Expand]   │ │        [↗️ Expand]  │
│ ┌──────────────────┐ │ │ ┌──────────────────┐ │ │ ┌──────────────────┐│
│ │                  │ │ │ │                  │ │ │ │                  ││
│ │  [Purple         │ │ │ │  [Bar chart      │ │ │ │  [Stepped line   ││
│ │   gradient       │ │ │ │   red/blue]      │ │ │ │   chart]         ││
│ │   area chart]    │ │ │ │                  │ │ │ │                  ││
│ │                  │ │ │ │                  │ │ │ │                  ││
│ └──────────────────┘ │ │ └──────────────────┘ │ │ └──────────────────┘│
└──────────────────────┘ └──────────────────────┘ └──────────────────────┘
   [Purple glow on hover]   [Purple glow on hover]   [Purple glow on hover]
```

### Visual Details:
- **Header:** Large purple "Channel Timeline" title
- **Filters:** Dropdowns for channel + time range
- **Charts:** 3-column grid (responsive: stacks on mobile)
- **Icons:** 
  - ⚡ Lightning (power)
  - ⚠️ Alert circle (errors)
  - 📈 Line graph (modulation)
- **Gradients:** Purple fill from top (50% opacity) to bottom (0%)
- **Hover:** Purple border glow (0 4px 12px rgba(168,85,247,0.15))

---

## 2. BQM Graphs View

### Layout Structure:
```
┌─────────────────────────────────────────────────────────┐
│ 📊 BQM Graphs                                           │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ 📈 Broadband Quality Monitor                            │
│                                                         │
│  ┌───────────────────────────────────────────────────┐ │
│  │                                                   │ │
│  │         [BQM Graph Image]                        │ │
│  │         (Full width, centered)                    │ │
│  │                                                   │ │
│  └───────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
   [Purple glow on hover]
```

### Visual Details:
- **Header:** Large purple "BQM Graphs" title
- **Card:** Single card wrapping the image
- **Icon:** 📈 Chart icon (purple)
- **Title:** "Broadband Quality Monitor"
- **Image:** Centered, max-width 100%, rounded corners
- **Hover:** Purple border glow
- **No Data:** Card hidden, message shown instead

---

## 3. Incident Journal View

### Layout Structure:
```
┌─────────────────────────────────────────────────────────┐
│ 📊 Incident Journal               [+ New Entry] ←Purple │
│                                        Pill Button      │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ 📅 Incident Journal                                      │
├─────────────────────────────────────────────────────────┤
│ Date       │ Title          │ Description        │ 📎  │
├────────────┼────────────────┼────────────────────┼─────┤
│ 2026-02-14 │ Connection...  │ Modem rebooted...  │ 📎 2│
│ 2026-02-13 │ Slow speeds... │ Speed test fail... │     │
│ 2026-02-12 │ Packet loss... │ High latency...    │ 📎 1│
└─────────────────────────────────────────────────────────┘
   [Purple hover on rows]
```

### New Entry Modal:
```
┌─────────────────────────────────────────────────┐
│ ✏️ New Incident Entry                      [X] │
├─────────────────────────────────────────────────┤
│                                                 │
│  Date                                           │
│  [2026-02-14      ]  ←Purple focus border      │
│                                                 │
│  Title                                          │
│  [Connection dropped...   ]  ←Purple on focus  │
│                                                 │
│  Description                                    │
│  ┌─────────────────────────────────────────┐  │
│  │ Modem lost connection...                │  │
│  │                                          │  │
│  │                                          │  │
│  └─────────────────────────────────────────┘  │
│                                                 │
│               [Cancel] [Save] ←Purple button   │
└─────────────────────────────────────────────────┘
```

### Visual Details:

**Header:**
- Large purple "Incident Journal" title
- Purple pill button: "+ New Entry"
  - White text on purple gradient
  - Border-radius: 50px
  - Box shadow on hover
  - Plus icon (SVG)

**Table Card:**
- Card wrapper with header
- 📅 Calendar icon (purple)
- Table inside card
- Header row: Subtle dark background
- Row hover: Purple tint (rgba(168,85,247,0.1))
- Click row to edit

**Modal:**
- Purple title "New/Edit Incident Entry"
- Purple close button (X) on hover
- Form inputs:
  - Date picker
  - Text input (title)
  - Textarea (description)
  - All have purple focus border + glow
- Buttons:
  - **Save:** Purple gradient, white text, shadow
  - **Cancel:** Transparent, gray border, purple on hover
  - **Delete:** Red (if editing)

---

## Color Palette Reference

### Purple Accents:
- Primary: `#a855f7` (var(--accent-purple))
- Hover: `#9333ea` (var(--accent-hover))
- Muted: `rgba(168,85,247,0.15)` (var(--accent-muted))

### Gradients (Charts):
```
Top:    rgba(168,85,247,0.5)  - 50% opacity
Middle: rgba(168,85,247,0.1)  - 10% opacity (at 70%)
Bottom: rgba(168,85,247,0)    - 0% opacity
```

### Borders:
- Default: `var(--card-border)` - rgba(255,255,255,0.08)
- Hover: `var(--accent-purple)` - #a855f7

### Shadows:
- Card hover: `0 4px 12px rgba(168,85,247,0.15)`
- Button: `0 2px 8px rgba(168,85,247,0.3)`
- Button hover: `0 4px 12px rgba(168,85,247,0.4)`

---

## Typography

### Headers:
- View title: 1.5em, bold, purple
- Card title: 1.1em, semi-bold, purple icon

### Buttons:
- Font-size: 0.9em
- Font-weight: 600
- Icon + text alignment: center

### Tables:
- Header: 0.85em, semi-bold
- Body: 0.92em, regular
- Muted text: 0.88em

---

## Responsive Behavior

### Desktop (> 768px):
- Channel Timeline: 3-column grid
- BQM: Single centered card
- Journal: Full table with all columns

### Mobile (< 768px):
- Channel Timeline: Single column stack
- BQM: Full width card
- Journal: 
  - Description column hidden
  - 📎 column shown
  - Vertical stack

---

## Hover/Focus States

### Cards:
- Default: Border rgba(255,255,255,0.08)
- Hover: Purple border + glow + translateY(-2px)

### Buttons:
- Default: Purple solid
- Hover: Darker purple + translateY(-1px) + stronger shadow

### Table Rows:
- Default: Transparent
- Hover: Purple tint (10% opacity)

### Form Inputs:
- Default: Gray border
- Focus: Purple border + 3px purple glow (10% opacity)

---

## Dark/Light Theme Compatibility

All views use CSS variables, so they automatically adapt:

**Dark Theme (default):**
- Background: #1f2937 (charcoal)
- Text: #f0f0f0 (near-white)
- Cards: Same as background with subtle borders

**Light Theme:**
- Background: #ffffff (white)
- Text: #111827 (dark gray)
- Cards: #f9fafb (light gray)

Purple accent stays consistent across both themes.

---

## Icon Reference

All icons are inline SVG (24x24 viewBox):

**Channel Timeline:**
- ⚡ Lightning: `<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>`
- ⚠️ Alert: `<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>`
- 📈 Graph: `<path d="M3 3v18h18"/><path d="M7 12l4-4 4 4 4-4"/>`

**BQM:**
- 📈 Chart: `<path d="M3 3v18h18"/><path d="M7 12l4-4 4 4 4-4"/>`

**Journal:**
- 📅 Calendar: `<path d="M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2z"/><path d="M16 2v4M8 2v4M3 10h18"/>`
- ➕ Plus: `<path d="M12 5v14m-7-7h14"/>`

---

## Comparison to Previous Phases

Phase 4.5 completes the visual language established in:

| Phase   | View              | Status |
|---------|-------------------|--------|
| Phase 3 | Live Dashboard    | ✅     |
| Phase 4.1 | Trends          | ✅     |
| Phase 4.2 | Speedtest       | ✅     |
| Phase 4.3 | Events          | ✅     |
| Phase 4.4 | Correlation     | ✅     |
| **Phase 4.5** | **Channel Timeline** | ✅ |
| **Phase 4.5** | **BQM**         | ✅     |
| **Phase 4.5** | **Journal**     | ✅     |

All views now share:
- ✅ Purple accent palette
- ✅ Modern card wrappers
- ✅ Gradient charts (where applicable)
- ✅ Consistent typography
- ✅ Responsive design
- ✅ Hover/focus states

---

**Visual consistency achieved across entire application!** 🎨
