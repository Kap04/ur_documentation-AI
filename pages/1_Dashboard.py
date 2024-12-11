import streamlit as st
import snowflake.connector
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import crochet
from scrapy import Spider
from scrapy.crawler import CrawlerRunner
from scrapy.utils.project import get_project_settings

# Snowflake Authentication
def authenticate_user(username, password):
    try:
        conn = snowflake.connector.connect(
            user='KAP',  # Replace with your Snowflake username
            password='9714044400K@p',  # Replace with your Snowflake password
            account='YEB46881',  # Replace with your Snowflake account name
            warehouse='COMPUTE_WH',  # Replace with your Snowflake warehouse
            database='ASK_DOC',  # Replace with your database
            schema='ask_doc_schema'  # Replace with your schema
        )

        cursor = conn.cursor()
        query = f"SELECT COUNT(*) FROM users WHERE username = '{username}' AND password = '{password}'"
        cursor.execute(query)
        result = cursor.fetchone()

        if result[0] == 1:
            st.success(f"Welcome back, {username}!")
            return True
        else:
            st.error("Invalid username or password.")
            return False
    except Exception as e:
        st.error(f"Error in Snowflake authentication: {e}")
        return False

# User Sign-Up Function
def signup_user(username, password):
    try:
        conn = snowflake.connector.connect(
            user='KAP',  # Replace with your Snowflake username
            password='9714044400K@p',  # Replace with your Snowflake password
            account='YEB46881',  # Replace with your Snowflake account name
            warehouse='COMPUTE_WH',  # Replace with your Snowflake warehouse
            database='ASK_DOC',  # Replace with your database
            schema='ask_doc_schema'  # Replace with your schema
        )

        cursor = conn.cursor()
        query = f"INSERT INTO users (username, password) VALUES ('{username}', '{password}')"
        cursor.execute(query)
        conn.commit()
        st.success("Sign-up successful! You can now log in.")
    except Exception as e:
        st.error(f"Error in Sign-Up: {e}")

# Scraping Class and Functions
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
    # User Authentication Logic
    if 'logged_in' not in st.session_state:
        # Show login or sign-up options
        menu = ["Login", "Sign Up"]
        choice = st.sidebar.selectbox("Select an option", menu)

        if choice == "Login":
            username = st.text_input("Username")
            password = st.text_input("Password", type='password')

            if st.button("Login"):
                logged_in = authenticate_user(username, password)
                if logged_in:
                    st.session_state.logged_in = True
                    dashboard()

        elif choice == "Sign Up":
            username = st.text_input("Choose a username")
            password = st.text_input("Choose a password", type='password')
            confirm_password = st.text_input("Confirm password", type='password')

            if password != confirm_password:
                st.error("Passwords do not match!")
            elif st.button("Sign Up"):
                signup_user(username, password)

    else:
        dashboard()

def dashboard():
    # Dashboard content after successful login
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
