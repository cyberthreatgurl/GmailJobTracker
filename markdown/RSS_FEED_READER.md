# RSS Feed Reader

The **RSS Feed Reader** is a built-in feature of GmailJobTracker that allows you to aggregate, read, and link industry news directly to companies in your database.

## Features

- **Dashboard**: Centralized view of all articles from subscribed feeds.
- **Search & Filter**: 
  - Search by headline/description.
  - Filter by specific Feed.
  - Filter by Category (folders from your OPML file).
- **Company Linking**:
  - Quickly link an article to a tracked Company.
  - Useful for tracking news about companies you are applying to.
  - Uses the same company database as the rest of the application.
- **Feed Management**:
  - Add new feeds via URL.
  - Delete feeds.
  - Auto-updates the local OPML file (`feedbro-subscriptions-...opml`).
- **Import/Export**:
  - Uses standard OPML format compatible with FeedBro and other readers.

## Usage

### 1. Importing Feeds

If you have an existing OPML file (e.g., from FeedBro), place it in the root directory and run:

```bash
python manage.py import_opml [filename.opml]
```

By default, it looks for `feedbro-subscriptions-20260310-110531.opml`.

### 2. Fetching Articles

To pull the latest articles from all active feeds:

```bash
python manage.py fetch_rss
```

This command:
- Connects to each feed URL.
- Parses the XML/RSS content.
- Saves new articles to the database.
- Skips duplicates (based on GUID/Link).
- Logs any errors to the console.

**Recommendation**: Set up a cron job or scheduled task to run this periodically.

### 3. Using the Dashboard

Navigate to **News / RSS** in the sidebar (or `/news/`).

- **Read**: Browse headlines and descriptions. Click the title to open the original article.
- **Link**: Click "🔗 Link to Company" to associate an article with a company.
  - Type to search your company database.
  - Select the company to link.
  - The article will now appear with a "✅ Linked" badge.
- **Filter**: Use the dropdowns to focus on specific categories (e.g., "Tech", "Defense", "GovCon").

## Data Model

- **RSSFeed**: Stores the feed URL, title, category, and active status.
- **RSSArticle**: Stores the article title, link, description, publication date, and GUID.
- **Relationship**: An Article belongs to a Feed. An Article can optionally belong to a Company.

## Troubleshooting

- **"Feed might be invalid"**: Some feeds use non-standard XML. The parser attempts to handle this, but if a feed fails repeatedly, check the URL in a browser.
- **Missing Articles**: The fetcher respects the `pubDate` provided by the feed. Ensure the feed is actually updating.
- **OPML Sync**: Adding/Deleting feeds via the UI updates the local OPML file immediately. If you manually edit the OPML file, run `import_opml` again to sync the database.
