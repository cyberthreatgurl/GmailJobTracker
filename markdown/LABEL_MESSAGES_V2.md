# Label Messages 2.0 - Enhanced UI

## Overview
Completely redesigned the message labeling interface to make manual labeling more efficient and user-friendly. The new interface focuses on **one message at a time** with rich context and smart filtering.

## Key Improvements

### 🎯 One-at-a-Time Workflow
- **Focused view**: Shows only ONE message at a time to reduce cognitive load
- **Full context**: Subject, sender, domain, date, current label, confidence, company, thread ID
- **Expandable body**: Preview first 100 words, click to expand full message
- **Auto-advance**: After labeling, automatically loads next message in queue

### 📊 Smart Prioritization
Messages are ordered by:
1. **Confidence level** (lowest first) - Fix uncertain predictions first
2. **Timestamp** (oldest first) - Handle backlog systematically

### 🔍 Advanced Filtering
Three-dimensional filtering system:

#### 1. Label Filter
- All Labels
- Specific label (interview_invite, rejection, etc.)
- Focus on one message type at a time

#### 2. Confidence Filter
- **Low** (< 50%) - Prioritize uncertain predictions
- **Medium** (50-75%) - Review moderately confident
- **High** (> 75%) - Verify high-confidence predictions
- **All** - No filtering

#### 3. Company Filter
- **All** - All messages
- **Missing** - Only messages without company assignment
- **Resolved** - Only messages with assigned company

### 📈 Progress Tracking
- **Real-time stats**: Remaining, Labeled, Total counts
- **Visual progress banner**: Prominent display of labeling progress
- **Label distribution table**: Shows count per label type (helps identify rare classes)

### ⚡ User Experience
- **Django messages integration**: Success/error/info notifications after each action
- **Company name field**: Optional field to assign/update company during labeling
- **Skip button**: Skip difficult messages and come back later
- **Auto-retrain**: Triggers model retraining every 20 labels (background process)

### 🎨 Visual Design
- **Color-coded confidence badges**:
  - Green (High: ≥75%)
  - Yellow (Medium: 50-75%)
  - Red (Low: <50%)
- **Gradient progress banner**: Visually appealing purple gradient
- **Clean card-based layout**: Modern, professional appearance
- **Responsive meta grid**: Key metadata in 2-column grid

## Technical Changes

### Backend (`tracker/views.py`)

#### Updated `label_messages()` function:
```python
def label_messages(request):
    """Enhanced one-at-a-time message labeling interface"""
```

**POST Handler:**
- Simplified to handle single message at a time
- Accepts `message_id`, `ml_label`, `company_name` (optional)
- Marks message as `reviewed=True` automatically
- Triggers model retraining every 20 labels (background via `subprocess.Popen`)
- Django messages for user feedback

**Query Builder:**
- Three filter dimensions: label, confidence, company
- Confidence filters using database queries (`confidence__lt`, `confidence__gte`)
- Company filters using `company__isnull`
- Orders by `F("confidence").asc(nulls_first=True)` for prioritization

**Context Data:**
- `current_message` - Single message to display (`.first()`)
- `sender_domain` - Extracted from sender email
- `rendered_body` - HTML-safe body content
- `distinct_labels` - Available labels for filter dropdown
- `label_choices` - All valid message types
- `label_counts` - Distribution of labeled messages (for insights)

**Added Import:**
```python
from django.db.models import F, Q, Count  # Added Count
```

### Frontend (`tracker/templates/tracker/label_messages.html`)

**Structure:**
1. **Progress Banner** - Shows remaining/labeled/total counts
2. **Django Messages** - Success/error alerts
3. **Filter Bar** - Three dropdowns (label, confidence, company)
4. **Message Viewer** - Single message display
   - Header with metadata (6 fields in grid)
   - Body with snippet + expandable full view
   - Label form with submit/skip buttons
5. **Label Distribution Table** - Shows training data breakdown
6. **Empty State** - When no messages match filters

**JavaScript Functions:**
- `toggleFullBody()` - Show/hide full message content
- `applyFilters()` - Reload page with selected filters
- `skipMessage()` - Reload to get next message

**Styling:**
- CSS-only (no external frameworks)
- Responsive grid layouts
- Color-coded confidence badges
- Hover effects on buttons
- Smooth transitions

## Usage Workflow

### Standard Labeling Session:
1. **Navigate** to `/tracker/label_messages/`
2. **Apply filters** (e.g., "Low confidence" + "Missing company")
3. **Review message** - Read subject, sender, body snippet
4. **Expand full body** if needed
5. **Select label** from dropdown (or keep predicted label)
6. **Enter company** if missing/incorrect (optional)
7. **Click "Save & Next"** - Automatically loads next message
8. **Repeat** until queue is empty

### Filter Strategies:

**Strategy 1: Fix Low Confidence**
- Confidence: Low
- Label: All
- Company: All
- **Goal**: Improve model on uncertain predictions

**Strategy 2: Label Rare Classes**
- Confidence: All
- Label: rejection (or other rare class)
- Company: All
- **Goal**: Add more training data for underrepresented classes

**Strategy 3: Resolve Missing Companies**
- Confidence: All
- Label: All
- Company: Missing
- **Goal**: Clean up company resolution issues

## Comparison: Old vs New

| Feature | Old Interface | New Interface |
|---------|--------------|---------------|
| **Messages per page** | 50 at once | 1 at a time |
| **Body preview** | ❌ None | ✅ Snippet + expandable |
| **Filtering** | Label only | Label + Confidence + Company |
| **Company editing** | ❌ Separate page | ✅ Inline field |
| **Progress tracking** | Basic count | ✅ Prominent banner |
| **Auto-retrain** | After every submit | ✅ Every 20 labels |
| **User feedback** | ❌ None | ✅ Django messages |
| **Confidence display** | Text only | ✅ Color-coded badges |
| **Sender domain** | ❌ Not shown | ✅ Extracted |
| **Label distribution** | ❌ None | ✅ Table at bottom |

## Benefits

### For User:
- **Less overwhelming**: One message at a time vs 50
- **Better context**: Full metadata + expandable body
- **Faster workflow**: Auto-advance + inline company editing
- **Clearer priorities**: Smart ordering + filters
- **Real-time feedback**: Django messages + progress stats

### For Model:
- **Higher quality labels**: Better context = better decisions
- **Targeted improvement**: Filter by confidence/label to focus on weak areas
- **Automatic retraining**: Background process every 20 labels
- **Data insights**: Label distribution table shows where to focus

### For System:
- **Reduced cognitive load**: Focused interface = fewer mistakes
- **Flexible filtering**: Handle different labeling scenarios
- **Scalable**: Works well with 10 or 10,000 unlabeled messages
- **Maintainable**: Clean separation of concerns (backend/frontend)

## Configuration

### Auto-Retrain Frequency
Change `if labeled_count % 20 == 0:` in `label_messages()` to adjust retraining frequency:
- **10** - Retrain every 10 labels (more responsive)
- **50** - Retrain every 50 labels (less overhead)
- **100** - Retrain every 100 labels (bulk labeling)

### Label Choices
Edit `label_choices` list in `label_messages()` to add/remove available labels:
```python
label_choices = [
    'interview_invite', 'job_application', 'rejection', 'offer',
    'noise', 'job_alert', 'head_hunter', 'referral', 
    'ghosted', 'follow_up', 'response', 'other'
]
```

### Filter Defaults
Change default filter in view:
```python
filter_confidence = request.GET.get("confidence", "low")  # Default to "low"
```

## Future Enhancements

### Potential Additions:
- [ ] **Keyboard shortcuts** - Number keys (1-9) for quick labeling
- [ ] **Bulk actions** - Label multiple messages at once
- [ ] **Thread view** - Show related messages in same thread
- [ ] **Undo button** - Revert last label
- [ ] **Notes field** - Add comments to messages
- [ ] **Search** - Find specific messages by subject/sender
- [ ] **Confidence threshold** - Only show messages below X% confidence
- [ ] **Session stats** - Track how many labeled this session
- [ ] **Export** - Download labeled messages as CSV

## Troubleshooting

### No messages showing:
- Check filters - may be too restrictive
- Click "Reset filters" link in empty state
- Verify `reviewed=False` messages exist in database

### Auto-retrain not working:
- Check `python_path` variable in settings
- Verify `train_model.py` exists in project root
- Check console for subprocess errors

### Confidence not displaying:
- Some messages may not have confidence values (imported data)
- Re-run `reclassify_messages` command to populate

### Company not saving:
- Check that company name is valid (not in `invalid_company_prefixes`)
- Verify `Company` model has proper constraints
- Check Django messages for error feedback

## Related Files

- `tracker/views.py` - Backend logic
- `tracker/templates/tracker/label_messages.html` - Frontend template
- `tracker/templates/tracker/_sidebar.html` - Reusable sidebar
- `tracker/models.py` - Message, Company models
- `train_model.py` - Model retraining script
- `db.py` - `load_training_data()` function

---

**Created**: October 17, 2025  
**Version**: 2.0  
**Status**: ✅ Production Ready
