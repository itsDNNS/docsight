# Quick Test Guide - Phase 4.5

**URL:** http://localhost:8767  
**Container:** docsight-v2-dev (port 8767)

---

## Pre-Test Checklist

- [x] Container running: `docker ps | grep docsight-v2-dev`
- [x] App accessible: `curl -I http://localhost:8767`
- [x] CSS file served: `/static/css/main.css` (72KB)
- [x] No Flask errors in logs

---

## 1-Minute Smoke Test

### Channel Timeline (30 seconds)
1. Navigate to "Channel Timeline" in sidebar
2. Select any channel from dropdown
3. **VERIFY:**
   - [ ] 3 charts display in grid
   - [ ] Each chart has icon header (⚡, ⚠️, 📈)
   - [ ] Charts have purple gradient fills
   - [ ] Cards glow purple on hover
   - [ ] Expand buttons work

**Expected:** Purple gradient area charts with modern card design

---

### BQM Graphs (10 seconds)
1. Navigate to "BQM Graphs" in sidebar
2. Select a date with data
3. **VERIFY:**
   - [ ] Image wrapped in card with header
   - [ ] Header shows chart icon + "Broadband Quality Monitor"
   - [ ] Card glows purple on hover
   - [ ] Image centered and responsive

**Expected:** Single card wrapping BQM image with purple accents

---

### Incident Journal (20 seconds)
1. Navigate to "Incident Journal" in sidebar
2. **VERIFY:**
   - [ ] "New Entry" button is purple pill style
   - [ ] Table wrapped in card with calendar icon header
   - [ ] Table rows glow purple on hover
3. Click "New Entry"
4. **VERIFY:**
   - [ ] Modal opens with purple title
   - [ ] Input borders turn purple on focus
   - [ ] "Save" button is purple
   - [ ] "Cancel" button is gray outline

**Expected:** Modern table card + purple pill button + styled modal

---

## 5-Minute Full Test

### Channel Timeline - Detailed
- [ ] Select different channels (DS/US)
- [ ] Change time range (1d, 3d, 7d, 30d)
- [ ] Verify power chart shows gradient
- [ ] Verify errors chart (DS only) displays
- [ ] Verify modulation chart displays
- [ ] Click expand button → modal opens
- [ ] Modal shows same gradient chart
- [ ] Close modal → back to view
- [ ] Hover each card → purple glow
- [ ] Check mobile view (resize browser)

### BQM - Detailed
- [ ] Navigate to different dates
- [ ] Verify card appears when image loads
- [ ] Verify "no data" message when empty
- [ ] Hover card → purple glow
- [ ] Refresh image (if refresh button exists)
- [ ] Check responsive behavior

### Journal - Detailed
- [ ] Verify table displays in card
- [ ] Click table headers → sort works
- [ ] Click rows → edit modal opens
- [ ] "New Entry" button → modal opens
- [ ] Fill in form fields
- [ ] Tab through inputs → purple focus
- [ ] Click "Save" → incident created
- [ ] Edit existing incident
- [ ] Delete incident (if applicable)
- [ ] Verify attachments display (if any)
- [ ] Check mobile view (description column hides)

---

## Console Error Check

Open browser console (F12):

```javascript
// Should be no errors
console.log("Checking for errors...");

// Verify elements exist
console.log("BQM card:", document.getElementById('bqm-card'));
console.log("Journal card:", document.getElementById('journal-table-card'));
console.log("Channel charts:", document.getElementById('channel-charts'));
```

**Expected:** All elements found, no errors

---

## Visual Inspection Checklist

### Colors
- [ ] Purple accents throughout (#a855f7)
- [ ] No cyan/teal colors remaining (#00adb5)
- [ ] Charts use purple gradients
- [ ] Buttons use purple
- [ ] Icons are purple

### Typography
- [ ] Headers are 1.5em, bold, purple
- [ ] Buttons are 0.9em, semi-bold
- [ ] Table text readable
- [ ] Form labels clear

### Spacing
- [ ] Cards have consistent padding
- [ ] Gaps between elements even
- [ ] No overlapping elements
- [ ] Responsive stacking works

### Hover/Focus
- [ ] Cards glow purple on hover
- [ ] Buttons lift on hover
- [ ] Table rows tint purple
- [ ] Inputs show purple border on focus

---

## Browser Testing

### Chrome/Edge
- [ ] All views render correctly
- [ ] Gradients display smoothly
- [ ] Hover effects work
- [ ] No console errors

### Firefox
- [ ] Same as Chrome
- [ ] SVG icons display
- [ ] CSS grid works

### Safari (if available)
- [ ] Gradients work
- [ ] Flex/grid layout correct
- [ ] Hover states work

---

## Responsive Testing

### Desktop (> 1200px)
- [ ] Channel Timeline: 3 columns
- [ ] Cards have proper width
- [ ] Text readable

### Tablet (768px - 1200px)
- [ ] Channel Timeline: 2-3 columns
- [ ] BQM card full width
- [ ] Journal table scrollable

### Mobile (< 768px)
- [ ] Channel Timeline: 1 column stack
- [ ] Journal description column hidden
- [ ] Buttons full width
- [ ] Modal fits screen

---

## Functional Testing

### Channel Timeline
- [ ] Data loads correctly
- [ ] Charts update when filters change
- [ ] Zoom modal works
- [ ] No JavaScript errors

### BQM
- [ ] Image loads from API
- [ ] Card shows/hides correctly
- [ ] No broken images
- [ ] No JavaScript errors

### Journal
- [ ] Incidents load from API
- [ ] Create new incident works
- [ ] Edit incident works
- [ ] Delete incident works (if applicable)
- [ ] Sort by columns works
- [ ] No JavaScript errors

---

## Quick Command Tests

```bash
# Check if container is running
docker ps | grep docsight-v2-dev

# Check app logs for errors
docker logs docsight-v2-dev --tail 50 | grep -i error

# Verify CSS file size (should be ~72KB)
curl -s http://localhost:8767/static/css/main.css | wc -c

# Check HTML contains new elements
curl -s http://localhost:8767 | grep -c "bqm-card"
curl -s http://localhost:8767 | grep -c "journal-table-card"
curl -s http://localhost:8767 | grep -c "chart-card-header"

# Verify API endpoints work
curl -s http://localhost:8767/api/incidents | jq '.' | head -20
```

---

## Pass/Fail Criteria

### PASS ✅
- All 3 views display correctly
- Purple accents throughout
- Charts have gradients
- No console errors
- All functionality works
- Responsive on mobile

### FAIL ❌
- Views don't display
- Console errors present
- Missing purple accents
- Charts lack gradients
- Functionality broken
- Layout broken on mobile

---

## If Tests Fail

### Common Issues:

**Charts don't show gradients:**
- Check renderChart function uses purple colors
- Verify chart canvas elements exist
- Check browser console for Chart.js errors

**BQM card doesn't appear:**
- Verify image loads from API
- Check JavaScript show/hide logic
- Ensure card element exists in HTML

**Journal table not in card:**
- Verify `journal-table-card` element exists
- Check JavaScript displays card (not just table)
- Ensure CSS for `.table-card` loaded

**CSS not loading:**
- Hard refresh browser (Ctrl+Shift+R)
- Check `/static/css/main.css` endpoint
- Verify CSS file size (~72KB)

**Purple accents missing:**
- Check CSS variables defined
- Verify `var(--accent-purple)` used
- Check theme (dark/light) active

---

## Success Criteria

If all these are ✅, Phase 4.5 is complete:

- [x] Channel Timeline has gradient charts in cards
- [x] BQM has image wrapped in card
- [x] Journal has table in card + purple button
- [ ] No console errors (test manually)
- [ ] All filters/sorting work (test manually)
- [ ] Responsive design works (test manually)
- [x] Code changes minimal and clean
- [x] All functionality preserved

---

## Next Steps After Passing

1. **Screenshot views** for documentation
2. **Commit changes** to Git
3. **Update main README** if needed
4. **Mark Phase 4.5 complete** in project tracker
5. **Plan Phase 5** (if applicable)

---

**Testing Time:** ~5-10 minutes  
**Expected Result:** All views modernized, purple accents, no errors
