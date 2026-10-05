# Boxing Match Information Assistant

Cloud-ready Streamlit prototype for post-match professional boxing research.

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

The current build runs in **Demo mode** with the 13 supplied matches. It is deliberately evidence-first: market settlement is not automated.

## Live source discovery

Select **Live source discovery** in the sidebar to search the Brave Web Search API for candidate sources. Every result is labelled *Unverified source candidate*; nothing is confirmed or settled automatically.

Add the API key in Streamlit Cloud → App settings → Secrets (or locally in `.streamlit/secrets.toml`, which is git-ignored):

```toml
BRAVE_SEARCH_API_KEY = "your-brave-search-api-key"
```

## Deploy

Create a new private GitHub repository from this folder, then create a new Streamlit Cloud application with `app.py` as the entry point.

## Next implementation stages

1. Fight-identity normalisation and aliases.
2. Search/discovery connector and source evidence collector.
3. Official PDF and scorecard extraction.
4. Knockdown evidence conflict handling.
