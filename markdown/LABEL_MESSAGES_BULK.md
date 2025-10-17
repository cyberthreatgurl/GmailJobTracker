# Label Messages - Bulk Labeling Mode

## Overview
The message labeling interface has been redesigned as a **bulk labeling system** with checkboxes, allowing you to label multiple messages at once efficiently.

## Key Features

### ✅ **Checkbox Selection**
- **Individual selection**: Check/uncheck specific messages
- **Select All checkbox**: Toggle all messages on current page
- **Visual feedback**: Selected count displayed in real-time

### 📊 **Flexible Pagination**
- **10, 50, or 100 messages per page** (selectable dropdown)
- **Previous/Next navigation**
- **Page info**: "Showing X of Y messages (Page N of M)"

### 🎯 **Bulk Actions**
- **Single action bar** at top of table
- **Select label from dropdown** (all available labels)
- **Apply to all selected** messages with one click
- **Confirmation prompt** before applying

### 🔍 **Advanced Filtering** (Same as before)
- **Label**: All or specific type
- **Confidence**: Low (<50%), Medium (50-75%), High (>75%), All
- **Company**: All, Missing, Resolved

### 📈 **Progress Tracking**
- **Progress banner**: Remaining, Labeled, Total counts
- **Purple gradient design**: Modern, eye-catching

### 📋 **Table Display**
Columns:
1. **Checkbox** - Select message
2. **Subject** - Email subject line
3. **Company** - Linked to company detail (or "Missing")
4. **Current Label** - Color-coded badge
5. **Confidence** - Color-coded badge (High/Medium/Low)
6. **Sender Domain** - Extracted domain
7. **Date** - Formatted as "Mon DD"
8. **Snippet** - First 80 chars of body

## Usage Workflow

### Standard Bulk Labeling:
1. **Apply filters** (e.g., "Low confidence" + "50 per page")
2. **Review messages** in table
3. **Check boxes** for messages to label
   - Use "Select All" for entire page
   - Or individually select specific messages
4. **Select label** from dropdown at top
5. **Click "Apply Label to Selected"**
6. **Confirm** the action
7. System labels all selected messages and marks them as reviewed

### Example Scenarios:

**Scenario 1: Bulk Mark as Noise**
- Filter: Confidence = "Low", Label = "noise"
- Select All (50 messages)
- Choose label: "noise"
- Apply → 50 messages labeled instantly

**Scenario 2: Selective Labeling**
- Filter: Label = "interview_invite", Confidence = "Medium"
- Review each message
- Check only true interviews (skip false positives)
- Choose label: "interview_invite"
- Apply → Only selected messages updated

**Scenario 3: Fix Misclassified**
- Filter: Label = "rejection"
- Per page: 10
- Review each carefully
- Check incorrect labels
- Choose correct label: "job_application"
- Apply → Corrections made

## UI Components

### Bulk Actions Bar
```
[0] messages selected    [-- Select Label --]    [Apply Label to Selected]
```
- **Counter updates** as you select/deselect
- **Button disabled** until messages selected
- **Dropdown required** before submission

### Checkbox Behaviors
- **Click checkbox** → Toggle individual message
- **Click "Select All"** → Toggle all on page
- **Partial selection** → "Select All" shows indeterminate state
- **Change page** → Selections reset (page-specific)

### Confidence Badges
- 🟢 **High** (≥75%): Green background
- 🟡 **Medium** (50-75%): Yellow background
- 🔴 **Low** (<50%): Red background

### Pagination Controls
```
Showing 50 of 150 messages (Page 1 of 3)    [← Previous] [Next →]
```
- **Previous button** disabled on page 1
- **Next button** disabled on last page
- **Per page dropdown** resets to page 1 when changed

## Backend Changes

### View Function (`label_messages`)
**POST Handler:**
- Accepts `action=bulk_label`
- Gets list of `selected_messages` IDs
- Gets `bulk_label` value
- Updates all selected messages in loop
- Triggers retraining every 20 labels
- Shows success message with count

**GET Handler:**
- Reads pagination params (`per_page`, `page`)
- Applies filters (label, confidence, company)
- Slices queryset for current page
- Calculates pagination info (has_previous, has_next, total_pages)
- Extracts body snippets for table display

### Template Variables
- `messages` - List of messages for current page
- `per_page` - Current pagination setting (10/50/100)
- `page` - Current page number
- `total_pages` - Total number of pages
- `total_count` - Total messages matching filters
- `has_previous` / `has_next` - Navigation flags

## JavaScript Functions

### `updateSelection()`
- Called on every checkbox change
- Counts checked boxes
- Updates selected count display
- Enables/disables submit button
- Updates "Select All" checkbox state (checked/indeterminate/unchecked)

### `toggleSelectAll()`
- Called when "Select All" clicked
- Sets all checkboxes to same state
- Calls `updateSelection()` to update UI

### `applyFilters()`
- Reads all filter dropdown values
- Constructs URL with query params
- Navigates to filtered page (resets to page 1)

### `changePerPage()`
- Wrapper for `applyFilters()`
- Called when per-page dropdown changes

### `goToPage(pageNum)`
- Preserves current filters
- Changes only page parameter
- Navigates to specified page

### Form Submission Handler
- Prevents submission if no label selected
- Shows confirmation dialog: "Label N message(s) as 'X'?"
- Allows user to cancel

## Comparison: Old vs New

| Feature | Old (One-at-a-Time) | New (Bulk Mode) |
|---------|-------------------|-----------------|
| **Messages visible** | 1 | 10/50/100 |
| **Selection** | N/A | Checkboxes |
| **Bulk actions** | ❌ | ✅ |
| **Select all** | ❌ | ✅ |
| **Pagination** | ❌ | ✅ |
| **Per page control** | ❌ | ✅ (10/50/100) |
| **Table view** | ❌ | ✅ |
| **Body preview** | Full expandable | 80-char snippet |
| **Speed** | 1 per submit | Up to 100 per submit |
| **Use case** | Detailed review | Bulk corrections |

## Performance

### Efficiency Gains:
- **10 messages at once** = 10x faster than one-at-a-time
- **50 messages at once** = 50x faster
- **100 messages at once** = 100x faster (for obvious cases)

### Recommended Strategy:
1. **First pass**: Use 100/page for obvious cases (noise, alerts)
2. **Second pass**: Use 50/page for confident predictions
3. **Final pass**: Use 10/page for uncertain cases (low confidence)

## Auto-Retraining

Model retrains automatically **every 20 labels** (same as before):
- Triggers in background via `subprocess.Popen()`
- Doesn't block labeling workflow
- Shows Django messages notification

## Tips for Efficient Labeling

### 1. **Filter Aggressively**
- Start with "Low confidence" + specific label
- This surfaces uncertain predictions first
- Label in batches of similar messages

### 2. **Use Select All Wisely**
- Good for: All messages clearly same label
- Bad for: Mixed content on page
- Better to: Select subset if unsure

### 3. **Leverage Pagination**
- **100/page**: Quick scan for noise/alerts
- **50/page**: Standard review speed
- **10/page**: Detailed analysis

### 4. **Check Confidence Badges**
- Green (High): Usually correct, quick verify
- Yellow (Medium): Review more carefully
- Red (Low): Highest priority for manual review

### 5. **Use Snippets**
- Scan snippet column quickly
- Keywords often visible in first 80 chars
- Click company link for more context if needed

## Keyboard Shortcuts (Future Enhancement)

Potential additions:
- **Space** - Toggle current row checkbox
- **Ctrl+A** - Select all visible
- **Enter** - Submit form
- **Arrow keys** - Navigate rows

## Troubleshooting

### "Apply Label" button disabled:
- **Cause**: No messages selected
- **Solution**: Check at least one checkbox

### No confirmation dialog appears:
- **Cause**: JavaScript disabled or error
- **Solution**: Check browser console, ensure JS enabled

### Selections disappear when changing page:
- **Expected behavior**: Selections are page-specific
- **Workaround**: Label current page before navigating

### Pagination shows wrong count:
- **Cause**: Filters applied after count calculation
- **Solution**: Refresh page or re-apply filters

## Related Files

- `tracker/views.py` - `label_messages()` function
- `tracker/templates/tracker/label_messages.html` - Bulk UI template
- `tracker/models.py` - Message model
- `train_model.py` - Auto-retraining script

---

**Created**: October 17, 2025  
**Version**: 3.0 - Bulk Mode  
**Status**: ✅ Production Ready
