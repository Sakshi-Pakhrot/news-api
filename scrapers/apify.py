import os
import logging
from typing import Optional
import httpx

logger = logging.getLogger("uvicorn")

async def scrape_article_content_apify(client: httpx.AsyncClient, url: str) -> tuple[str, Optional[str]]:
    """
    Fetches the article using Apify's lukaskrivka/article-extractor-smart actor.
    Uses the synchronous get-dataset-items endpoint.
    """
    api_key = os.getenv("APIFY_API_KEY")
    if not api_key:
        logger.error("APIFY_API_KEY is not set.")
        return "", None

    # Using the Apify API to run the actor and synchronously get the dataset
    apify_url = f"https://api.apify.com/v2/acts/lukaskrivka~article-extractor-smart/run-sync-get-dataset-items?token={api_key}"
    
    payload = {
        "articleUrls": [{"url": url}]
    }
    
    try:
        # Increase timeout because running an actor can take some time
        response = await client.post(apify_url, json=payload, timeout=60.0)
        
        if response.status_code not in (200, 201):
            logger.error(f"Apify returned status {response.status_code} for {url}. Details: {response.text}")
            return "", None
            
        data = response.json()
        if not data or not isinstance(data, list) or len(data) == 0:
            logger.error(f"Apify returned empty dataset for {url}.")
            return "", None
            
        item = data[0]
        content = item.get("text") or item.get("html") or ""
        image_url = item.get("image") or item.get("image_url")
        
        return content, image_url
        
    except httpx.ReadTimeout:
        logger.error(f"Apify actor run timed out for {url}.")
        return "", None
    except Exception as e:
        logger.error(f"Error scraping {url} with Apify: {e}")
        return "", None
