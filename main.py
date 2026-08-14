import os
import asyncio
import urllib.parse
import json
import logging
from typing import List, Optional, Callable, Awaitable, Tuple
import httpx
import feedparser
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from googlenewsdecoder import gnewsdecoder
from dotenv import load_dotenv
import re

# Load environment variables (API keys) from .env
load_dotenv()

# Import the new scrapers
from scrapers.native import scrape_article_content_native
from scrapers.scraperapi import scrape_article_content_scraperapi
from scrapers.firecrawl import scrape_article_content_firecrawl
from scrapers.apify import scrape_article_content_apify

# Initialize logging to show up in Uvicorn container logs
logger = logging.getLogger("uvicorn")

app = FastAPI(
    title="News Article Link & Content Fetcher API",
    description="An API that searches news, decodes redirects, and scrapes article text and top image content using multiple backends.",
    version="2.0.0"
)

# Enable CORS for easy cross-origin integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request and Response schemas

class HeadlinesRequest(BaseModel):
    query: str = Field(..., example="artificial intelligence news", description="The search term to find articles for.")
    num_articles: int = Field(default=30, ge=1, le=50, description="Number of news headlines to fetch.")

class HeadlineItem(BaseModel):
    title: str
    url: str
    source: str
    published: str

class HeadlinesResponse(BaseModel):
    query: str
    articles: List[HeadlineItem]

class NewsRequest(BaseModel):
    query: str = Field(..., example="SpaceX AI guidance system", description="The search term to find articles for.")
    num_articles: int = Field(default=10, ge=1, le=20, description="Number of news articles to fetch.")

class NewsItem(BaseModel):
    title: str
    url: str
    source: str
    published: str

class NewsResponse(BaseModel):
    query: str
    articles: List[NewsItem]

class NewsItemWithContent(BaseModel):
    title: str
    url: str
    source: str
    published: str
    content: str
    image_url: Optional[str] = None
    scraped_successfully: bool

class NewsContentResponse(BaseModel):
    query: str
    articles: List[NewsItemWithContent]

class ScrapeRequest(BaseModel):
    url: str = Field(..., example="https://www.bbc.com/news/articles/c4gy0x0j5deo", description="The URL of the page to scrape.")

class ScrapeResponse(BaseModel):
    url: str
    image_url: Optional[str] = None
    scraped_successfully: bool
    content: str


# Headers mimicking a normal browser to bypass simple crawler blocks for native scraping
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Upgrade-Insecure-Requests": "1"
}

CATEGORY_FEEDS = {
    "world": "https://news.google.com/rss/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx1YlY4U0JXVnVMVWRDR2dKSlRpZ0FQAQ?hl=en-IN&gl=IN&ceid=IN%3Aen",
    "india": "https://news.google.com/rss/topics/CAAqJQgKIh9DQkFTRVFvSUwyMHZNRE55YXpBU0JXVnVMVWRDS0FBUAE?hl=en-IN&gl=IN&ceid=IN%3Aen",
    "business": "https://news.google.com/rss/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx6TVdZU0JXVnVMVWRDR2dKSlRpZ0FQAQ?hl=en-IN&gl=IN&ceid=IN%3Aen",
    "technology": "https://news.google.com/rss/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRGRqTVhZU0JXVnVMVWRDR2dKSlRpZ0FQAQ?hl=en-IN&gl=IN&ceid=IN%3Aen",
    "entertainment": "https://news.google.com/rss/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNREpxYW5RU0JXVnVMVWRDR2dKSlRpZ0FQAQ?hl=en-IN&gl=IN&ceid=IN%3Aen",
    "sports": "https://news.google.com/rss/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRFp1ZEdvU0JXVnVMVWRDR2dKSlRpZ0FQAQ?hl=en-IN&gl=IN&ceid=IN%3Aen",
    "science": "https://news.google.com/rss/topics/CAAqKggKIiRDQkFTRlFvSUwyMHZNRFp0Y1RjU0JXVnVMVWRDR2dKSlRpZ0FQAQ?hl=en-IN&gl=IN&ceid=IN%3Aen",
    "health": "https://news.google.com/rss/topics/CAAqJQgKIh9DQkFTRVFvSUwyMHZNR3QwTlRFU0JXVnVMVWRDS0FBUAE?hl=en-IN&gl=IN&ceid=IN%3Aen"
}


def fetch_google_news_rss(query: str, limit: int = 10) -> List[dict]:
    query_clean = query.strip().lower()
    
    if not query_clean or query_clean in ["top", "top-stories", "breaking", "news"]:
        feed_url = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
    elif query_clean in CATEGORY_FEEDS:
        feed_url = CATEGORY_FEEDS[query_clean]
    else:
        encoded_query = urllib.parse.quote(query)
        feed_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
        
    try:
        with httpx.Client(timeout=10.0) as sync_client:
            resp = sync_client.get(feed_url, headers=HEADERS)
            if resp.status_code == 200:
                feed = feedparser.parse(resp.text)
            else:
                feed = feedparser.parse(feed_url)
    except Exception as e:
        logger.error(f"Error fetching RSS feed via httpx: {e}")
        feed = feedparser.parse(feed_url)
    
    articles = []
    for entry in feed.entries[:limit]:
        source_name = "News Source"
        if hasattr(entry, "source") and hasattr(entry.source, "title"):
            source_name = entry.source.title
        elif " - " in entry.title:
            source_name = entry.title.split(" - ")[-1]
            
        snippet = ""
        if hasattr(entry, "summary"):
            try:
                soup_summary = BeautifulSoup(entry.summary, "html.parser")
                snippet = soup_summary.get_text().strip()
            except Exception:
                pass
            
        articles.append({
            "title": entry.title,
            "link": entry.link,
            "published": entry.published if hasattr(entry, "published") else "",
            "source": source_name,
            "snippet": snippet
        })
    return articles


def clean_for_llm(text: str) -> str:
    """Cleans markdown links, images, newlines, and common boilerplate for LLMs."""
    if not text:
        return ""
        
    # 1. Flatten newlines first so cross-line regexes work easily
    # This handles actual newline characters
    text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    # This handles literal encoded string representations like '\n' that scrapers sometimes return
    text = text.replace('\\n', ' ').replace('\\r', ' ').replace('\\t', ' ')
    
    # 2. Remove markdown images
    text = re.sub(r'!\[.*?\]\(.*?\)', ' ', text)
    
    # 3. Replace markdown links with just their text
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    
    # 4. Remove Markdown formatting (Headers, Bold, Tables, Slashes)
    text = re.sub(r'#+\s*', '', text)
    text = text.replace('**', '').replace('__', '').replace('\\', '').replace('|', '').replace('---', '')
    
    # 5. Remove common boilerplate words (case-insensitive)
    boilerplates = [
        r'(?i)advertisement',
        r'(?i)read more',
        r'(?i)related topics',
        r'(?i)follow us on: facebook twitter instagram google news',
        r'(?i)follow us on:'
    ]
    for bp in boilerplates:
        text = re.sub(bp, ' ', text)
        
    # 6. Collapse multiple spaces and trim
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    return text

# Global semaphore to prevent Google News from blocking the server due to burst requests.
# Initialized lazily to avoid 'no current event loop' errors during module import.
URL_RESOLVE_SEM = None

async def resolve_url(item: dict) -> NewsItem:
    global URL_RESOLVE_SEM
    if URL_RESOLVE_SEM is None:
        URL_RESOLVE_SEM = asyncio.Semaphore(2)
        
    target_url = item["link"]
    
    async with URL_RESOLVE_SEM:
        try:
            decoded = await asyncio.wait_for(asyncio.to_thread(gnewsdecoder, target_url), timeout=10.0)
            if decoded.get("status"):
                target_url = decoded["decoded_url"]
        except Exception as e:
            logger.error(f"Error decoding Google News link {target_url}: {e}")
            # Manual fallback
            try:
                async with httpx.AsyncClient(headers=HEADERS) as client:
                    # Use GET instead of HEAD as Google often blocks HEAD requests, and follow redirects
                    resp = await client.get(target_url, follow_redirects=True, timeout=10.0)
                    target_url = str(resp.url)
            except Exception as fallback_e:
                logger.error(f"Manual fallback failed for {target_url}: {fallback_e}")
        
    return NewsItem(
        title=item["title"],
        url=target_url,
        source=item["source"],
        published=item["published"]
    )


async def execute_news_content_fetch(payload: NewsRequest, scrape_func: Callable, concurrent: bool = False) -> NewsContentResponse:
    news_items = fetch_google_news_rss(payload.query, limit=payload.num_articles)
    if not news_items:
        raise HTTPException(status_code=404, detail=f"No news articles found for query: {payload.query}")
        
    # Step 1: Concurrently resolve all URLs (fast, just gets the clean links)
    resolve_tasks = [resolve_url(item) for item in news_items]
    resolved_articles = await asyncio.gather(*resolve_tasks)
    
    scraped_articles = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        if concurrent:
            # Limit concurrent requests to avoid API rate limits (HTTP 429)
            sem = asyncio.Semaphore(2)
            
            # Scrape all articles simultaneously
            async def _scrape_single(article):
                async with sem:
                    target_url = article.url
                    content, image_url = await scrape_func(client, target_url)
                scraped_successfully = bool(content and len(content.strip()) > 100)
                if not content or not scraped_successfully:
                    content = "[Full article text could not be scraped due to paywall or connection blocks.]"
                
                # Clean content for LLM
                content = clean_for_llm(content)
                
                return NewsItemWithContent(
                    title=article.title,
                    url=target_url,
                    source=article.source,
                    published=article.published,
                    content=content,
                    image_url=image_url,
                    scraped_successfully=scraped_successfully
                )
            
            tasks = [_scrape_single(article) for article in resolved_articles]
            scraped_articles = await asyncio.gather(*tasks)
        else:
            # Step 2: Sequentially scrape the content one by one
            for article in resolved_articles:
                target_url = article.url
                
                # Scrape one by one
                content, image_url = await scrape_func(client, target_url)
                scraped_successfully = bool(content and len(content.strip()) > 100)
                
                if not content or not scraped_successfully:
                    content = "[Full article text could not be scraped due to paywall or connection blocks.]"
                    
                # Clean content for LLM
                content = clean_for_llm(content)
                
                scraped_articles.append(NewsItemWithContent(
                    title=article.title,
                    url=target_url,
                    source=article.source,
                    published=article.published,
                    content=content,
                    image_url=image_url,
                    scraped_successfully=scraped_successfully
                ))
            
    return NewsContentResponse(
        query=payload.query,
        articles=scraped_articles
    )

async def execute_single_scrape(payload: ScrapeRequest, scrape_func: Callable) -> ScrapeResponse:
    target_url = payload.url
    
    # If it's a Google News link, decode it first so we don't send a Google domain to 
    # third-party scrapers (which automatically trigger a 10-credit premium charge)
    if "news.google.com" in target_url:
        try:
            decoded = await asyncio.wait_for(asyncio.to_thread(gnewsdecoder, target_url), timeout=5.0)
            if decoded.get("status"):
                target_url = decoded["decoded_url"]
        except Exception as e:
            logger.error(f"Error decoding Google News link {target_url}: {e}")

    async with httpx.AsyncClient(timeout=10.0) as client:
        content, image_url = await scrape_func(client, target_url)
        
    scraped_successfully = bool(content and len(content.strip()) > 100)
    if not content:
        content = "[Could not scrape page content due to paywall or connection blocks.]"
        
    return ScrapeResponse(
        url=target_url,
        image_url=image_url,
        scraped_successfully=scraped_successfully,
        content=content
    )

# ----------------- FastAPI Endpoints -----------------

@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.post("/headlines", response_model=HeadlinesResponse)
def fetch_headlines(payload: HeadlinesRequest):
    news_items = fetch_google_news_rss(payload.query, limit=payload.num_articles)
    if not news_items:
        raise HTTPException(status_code=404, detail=f"No news articles found for query: {payload.query}")
        
    articles = [
        HeadlineItem(
            title=item["title"],
            url=item["link"],
            source=item["source"],
            published=item["published"]
        )
        for item in news_items
    ]
    
    return HeadlinesResponse(query=payload.query, articles=articles)


@app.post("/news", response_model=NewsResponse)
async def fetch_news_articles(payload: NewsRequest):
    news_items = fetch_google_news_rss(payload.query, limit=payload.num_articles)
    if not news_items:
        raise HTTPException(status_code=404, detail=f"No news articles found for query: {payload.query}")
        
    tasks = [resolve_url(item) for item in news_items]
    resolved_articles = await asyncio.gather(*tasks)
    
    return NewsResponse(query=payload.query, articles=resolved_articles)


# ---- NATIVE ROUTES ----
async def native_wrapper(client, url): return await scrape_article_content_native(client, url, HEADERS)

@app.post("/news-content", response_model=NewsContentResponse)
async def fetch_news_content_native_default(payload: NewsRequest):
    return await execute_news_content_fetch(payload, native_wrapper)

@app.post("/scrape", response_model=ScrapeResponse)
async def scrape_single_native_default(payload: ScrapeRequest):
    return await execute_single_scrape(payload, native_wrapper)

@app.post("/news-content-native", response_model=NewsContentResponse)
async def fetch_news_content_native(payload: NewsRequest):
    return await execute_news_content_fetch(payload, native_wrapper)

@app.post("/scrape-native", response_model=ScrapeResponse)
async def scrape_single_native(payload: ScrapeRequest):
    return await execute_single_scrape(payload, native_wrapper)

# ---- APIFY ROUTES ----
@app.post("/news-content-apify", response_model=NewsContentResponse)
async def fetch_news_content_apify(payload: NewsRequest):
    return await execute_news_content_fetch(payload, scrape_article_content_apify)

@app.post("/scrape-apify", response_model=ScrapeResponse)
async def scrape_single_apify(payload: ScrapeRequest):
    return await execute_single_scrape(payload, scrape_article_content_apify)

# ---- FIRECRAWL ROUTES ----
@app.post("/news-content-firecrawl", response_model=NewsContentResponse)
async def fetch_news_content_firecrawl(payload: NewsRequest):
    return await execute_news_content_fetch(payload, scrape_article_content_firecrawl, concurrent=True)

@app.post("/scrape-firecrawl", response_model=ScrapeResponse)
async def scrape_single_firecrawl(payload: ScrapeRequest):
    return await execute_single_scrape(payload, scrape_article_content_firecrawl)

# ---- SCRAPERAPI ROUTES ----
@app.post("/news-content-scraperapi", response_model=NewsContentResponse)
async def fetch_news_content_scraperapi(payload: NewsRequest):
    return await execute_news_content_fetch(payload, scrape_article_content_scraperapi)

@app.post("/scrape-scraperapi", response_model=ScrapeResponse)
async def scrape_single_scraperapi(payload: ScrapeRequest):
    return await execute_single_scrape(payload, scrape_article_content_scraperapi)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
