import json
import logging
from typing import Optional
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger("uvicorn")

def extract_image_url(soup: BeautifulSoup, data: Optional[dict] = None) -> Optional[str]:
    """
    Heuristically extracts the top/hero image URL from JSON-LD or meta tags or img tags.
    """
    # 1. Try JSON-LD first
    if data and isinstance(data, dict):
        image_data = data.get("image")
        if image_data:
            if isinstance(image_data, str):
                return image_data.strip()
            elif isinstance(image_data, dict) and image_data.get("url"):
                return image_data.get("url").strip()
            elif isinstance(image_data, list) and len(image_data) > 0:
                item = image_data[0]
                if isinstance(item, str):
                    return item.strip()
                elif isinstance(item, dict) and item.get("url"):
                    return item.get("url").strip()

    # 2. Try Open Graph og:image meta tag
    og_image = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
    if og_image and og_image.get("content"):
        return og_image.get("content").strip()

    # 3. Try Twitter image tag
    twitter_image = soup.find("meta", property="twitter:image") or soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", attrs={"name": "twitter:image:src"})
    if twitter_image and twitter_image.get("content"):
        return twitter_image.get("content").strip()

    # 4. Try to find the first large-looking image tag in the body
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src and src.startswith("http"):
            src_lower = src.lower()
            # Exclude common icon/logo keywords to target real images
            if not any(x in src_lower for x in ["icon", "logo", "avatar", "spacer", "ad-", "/ads/", "sprite"]):
                return src.strip()
                
    return None

async def scrape_article_content_native(client: httpx.AsyncClient, url: str, headers: dict) -> tuple[str, Optional[str]]:
    """
    Fetches the article URL and extracts the main text body and top image URL using multiple fallbacks.
    """
    try:
        response = await client.get(url, headers=headers, follow_redirects=True, timeout=10.0)
        if response.status_code != 200:
            return "", None
        
        soup = BeautifulSoup(response.text, "html.parser")
        image_url = None
        
        # --- Fallback 1: Extract from JSON-LD metadata ---
        json_ld_scripts = soup.find_all("script", type="application/ld+json")
        for script in json_ld_scripts:
            try:
                if not script.string:
                    continue
                data = json.loads(script.string.strip())
                if isinstance(data, dict):
                    if data.get("@type") in ["NewsArticle", "ReportageNewsArticle", "Article", "BlogPosting"]:
                        image_url = extract_image_url(soup, data)
                        body = data.get("articleBody") or data.get("description")
                        if body and len(body.strip()) > 100:
                            return body.strip(), image_url
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") in ["NewsArticle", "ReportageNewsArticle", "Article"]:
                            image_url = extract_image_url(soup, item)
                            body = item.get("articleBody") or item.get("description")
                            if body and len(body.strip()) > 100:
                                return body.strip(), image_url
            except Exception:
                continue

        # Extract standard fallback image URL if JSON-LD parsing didn't find one
        if not image_url:
            image_url = extract_image_url(soup)

        # Remove noisy tags
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
            element.extract()
            
        # --- Fallback 2: Look for article content tags ---
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
            
        # --- Fallback 3: Text Density Heuristics ---
        candidate_divs = []
        for div in soup.find_all("div"):
            p_tags = div.find_all("p", recursive=False)
            if len(p_tags) >= 2:
                div_text = "\n\n".join([p.get_text().strip() for p in p_tags if len(p.get_text().strip()) > 40])
                if len(div_text) > 150:
                    candidate_divs.append((len(div_text), div_text))
                    
        if candidate_divs:
            candidate_divs.sort(key=lambda x: x[0], reverse=True)
            return candidate_divs[0][1], image_url

        # --- Fallback 4: Raw Text Extraction ---
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 50]
        return "\n\n".join(lines[:15]), image_url
        
    except Exception as e:
        logger.error(f"Error scraping natively {url}: {e}")
        return "", None
