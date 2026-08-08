import os
import logging
from typing import Optional
import httpx

logger = logging.getLogger("uvicorn")

async def scrape_article_content_firecrawl(client: httpx.AsyncClient, url: str) -> tuple[str, Optional[str]]:
    """
    Fetches the article URL using Firecrawl API and returns the markdown content and metadata image.
    """
    api_key = os.getenv("FIRECRAWL_API_KEY")
    if not api_key:
        logger.error("FIRECRAWL_API_KEY is not set.")
        return "", None

    firecrawl_url = "https://api.firecrawl.dev/v1/scrape"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "url": url,
        "formats": ["markdown"]
    }
    try:
        response = await client.post(firecrawl_url, headers=headers, json=payload, timeout=30.0)
        if response.status_code != 200:
            logger.error(f"Firecrawl returned status {response.status_code} for {url}. Details: {response.text}")
            return "", None
        
        data = response.json()
        if not data.get("success"):
            logger.error(f"Firecrawl returned success=False for {url}. Details: {data}")
            return "", None
            
        content_data = data.get("data", {})
        markdown_text = content_data.get("markdown", "")
        metadata = content_data.get("metadata", {})
        
        # Extract image from metadata
        image_url = metadata.get("og:image") or metadata.get("image") or metadata.get("twitter:image")
        
        # Firecrawl returns markdown. We could strip some markdown, but since it's an article, it should be fine.
        return markdown_text, image_url
        
    except Exception as e:
        logger.error(f"Error scraping {url} with Firecrawl: {e}")
        return "", None
