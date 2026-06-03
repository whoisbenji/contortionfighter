# Contortion Space — Monthly Performance Review Agent

An automated agent that researches global contortion performances for a given
month, writes an editorial article, saves everything to Notion, and publishes
a draft to Webflow for your review.

## What it does

1. **Research** — runs 6+ targeted web searches for contortion performances,
   circus shows, and performer schedules for the target month.

2. **Saves raw research** — creates a page in the *Monthly research* Notion
   database so you can see the source material.

3. **Writes the article** — produces a 1,500–3,000 word editorial roundup
   organised by region, with Instagram links for every named performer.

4. **Saves to Notion** — creates the article in the *Monthly performance posts*
   database and links it to matching performers in the ICPDB.

5. **Publishes a Webflow draft** — creates a `isDraft = true` Blog Post in
   Webflow CMS with the article, meta description, and featured performer
   references pre-populated.

6. **Tells you it's ready** — prints a summary with all URLs and asks you to
   review the draft in Webflow.

## Setup

### 1. Install dependencies

```bash
pip install -r agent/requirements.txt
```

### 2. Set environment variables

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `NOTION_API_KEY` | notion.so → Settings → Integrations → New integration |
| `WEBFLOW_API_KEY` | webflow.com → Account → Integrations → API token (v2) |
| `TAVILY_API_KEY` | app.tavily.com *(recommended)* |
| `SERPER_API_KEY` | serper.dev *(alternative to Tavily)* |

You only need one of Tavily or Serper.

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export NOTION_API_KEY="secret_..."
export WEBFLOW_API_KEY="..."
export TAVILY_API_KEY="tvly-..."
```

Or use a `.env` file and `python-dotenv`.

### 3. Make sure the Notion integration has access

In Notion, share these databases with your integration:
- **Monthly performance posts**
- **Monthly research**
- **International Contortion Performers Database (ICPDB)**

### 4. Run it

```bash
# Review for the current month
python -m agent.run

# Review for a specific month
python -m agent.run --month "July 2026"

# Quiet mode (no tool-call logging)
python -m agent.run --month "July 2026" --quiet
```

## Reviewing the output

After the agent runs:

1. Open Webflow → **CMS → Blog Posts** — find the new draft (marked as Draft)
2. Check the article body, add a hero image, and adjust any details
3. Click **Publish** when happy

The Notion pages are created in draft state too — you can edit them before
or after the Webflow publish.

## Customising

- **Tone & structure**: edit `agent/prompts.py`
- **IDs** (if you change Notion/Webflow setup): edit `agent/config.py`
- **Search depth**: in `agent/prompts.py`, add more search queries to Phase 1
