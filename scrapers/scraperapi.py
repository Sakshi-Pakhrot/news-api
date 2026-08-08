import os
import logging
from typing import Optional
import httpx
from bs4 import BeautifulSoup
from .native import extract_image_url

logger = logging.getLogger("uvicorn")

async def scrape_article_content_scraperapi(client: httpx.AsyncClient, url: str) -> tuple[str, Optional[str]]:
    """
    Fetches the article URL using ScraperAPI and extracts the main text body and top image URL.
    """
    api_key = os.getenv("SCRAPER_API_KEY")
    if not api_key:
        logger.error("SCRAPER_API_KEY is not set.")
        return "", None

    scraper_url = f"http://api.scraperapi.com?api_key={api_key}&url={url}"
    try:
        response = await client.get(scraper_url, timeout=30.0)
        if response.status_code != 200:
            logger.error(f"ScraperAPI returned status {response.status_code} for {url}")
            return "", None
        
        soup = BeautifulSoup(response.text, "html.parser")
        image_url = extract_image_url(soup)

        # Remove noisy tags
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
            element.extract()
            
        # Try to find article content tags
        content_div = soup.find("article") or soup.find("div", class_="article-body") or soup.find("div", class_="story-content") or soup.find("div", class_="post-content")
        
        paragraphs = []
        if content_div:
            paragraphs = content_div.find_all("p")
        else:
            paragraphs = soup.find_all("p")
            
        text_blocks = []
        for p in paragraphs:
            text = p.get_text().strip()
            if len(text) > 50:
                text_blocks.append(text)
                
        if len(text_blocks) >= 2:
            return "\n\n".join(text_blocks[:20]), image_url
            
        # Raw Text Extraction fallback
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 50]
        return "\n\n".join(lines[:15]), image_url
        
    except Exception as e:
        logger.error(f"Error scraping {url} with ScraperAPI: {e}")
        return "", None
