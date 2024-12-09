import streamlit as st
from scrapy import Spider, signals
from scrapy.crawler import CrawlerRunner
from scrapy.utils.project import get_project_settings
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from twisted.internet import reactor
from threading import Thread
import crochet
crochet.setup()

class DocSpider(Spider):
    name = 'doc_spider'
    text_content = []
    
    def __init__(self, url=None):
        self.start_urls = [url]
        self.allowed_domains = [urlparse(url).netloc]
        self.visited_urls = set()

    def parse(self, response):
        if response.url in self.visited_urls:
            return
        
        self.visited_urls.add(response.url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for script in soup(["script", "style"]):
            script.decompose()
            
        text = ' '.join(chunk.strip() for chunk in soup.get_text().splitlines() if chunk.strip())
        
        if text:
            self.text_content.append({
                'url': response.url,
                'content': text
            })

        for href in response.css('a::attr(href)').getall():
            url = urljoin(response.url, href)
            if urlparse(url).netloc in self.allowed_domains:
                yield response.follow(url, self.parse)

@crochet.run_in_reactor
def scrape_url(url):
    runner = CrawlerRunner(get_project_settings())
    d = runner.crawl(DocSpider, url=url)
    return d

def main():
    st.title("Documentation Scraper")
    url = st.text_input("Enter documentation URL:")
    
    if st.button("Scrape"):
        if url:
            try:
                with st.spinner('Scraping documentation...'):
                    deferred = scrape_url(url)
                    deferred.wait(timeout=180)
                    spider = DocSpider(url)
                    
                    if spider.text_content:
                        st.success(f"Scraped {len(spider.text_content)} pages")
                        for idx, page in enumerate(spider.text_content, 1):
                            with st.expander(f"Page {idx}: {page['url']}"):
                                st.text_area("Content", page['content'], height=200)
                    else:
                        st.warning("No content found")
            except Exception as e:
                st.error(f"Error: {str(e)}")
        else:
            st.warning("Please enter a URL")

if __name__ == "__main__":
    main()


