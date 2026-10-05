# Boxing Match Information Assistant

Cloud-ready Streamlit prototype for post-match professional boxing research.

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

The current build runs in **Demo mode** with the 13 supplied matches. It is deliberately evidence-first: market settlement is not automated.

## Free source discovery

Select **Free source discovery** in the sidebar and enter both boxers, the event/offered date and an optional event name. The app builds search links (DuckDuckGo, Google, BoxRec and Tapology lookups, official/promoter reports, round-by-round/knockdown evidence) that open in a new browser tab.

Every link is labelled *Unverified manual source link*. The app makes no network requests, needs no account, API key or card, does no scraping or extraction, and never confirms a result or settles a market.

## Deploy

Create a new private GitHub repository from this folder, then create a new Streamlit Cloud application with `app.py` as the entry point.

## Next implementation stages

1. Fight-identity normalisation and aliases.
2. Search/discovery connector and source evidence collector.
3. Official PDF and scorecard extraction.
4. Knockdown evidence conflict handling.
