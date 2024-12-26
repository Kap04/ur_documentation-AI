import streamlit as st
import snowflake.connector
from bs4 import BeautifulSoup
import requests
from urllib.parse import urljoin, urlparse
import time
import queue
from snowflake.snowpark import Session
import threading
from mistralai.client import MistralClient

from mistralai.client import MistralClient

from mistralai import Mistral

from mistralai.async_client import MistralAsyncClient
import asyncio

from snowflake.core import Root

import os

# Configure Streamlit page
st.set_page_config(
    page_title="Documentation Scraper",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state variables
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'username' not in st.session_state:
    st.session_state['username'] = ""
if 'scrape_queue' not in st.session_state:
    st.session_state['scrape_queue'] = queue.Queue()
if 'scraped_pages' not in st.session_state:
    st.session_state['scraped_pages'] = []


class DocSearchService:
    def __init__(self, connection_params):
        self.session = Session.builder.configs(connection_params).create()

    def search_documentation(self, query, documentation_id, limit=5):
        try:
            cortex_search_service = (
                Root(self.session)
                .databases["ASK_DOC"]
                .schemas["PUBLIC"]
                .cortex_search_services["doc_search_service"]
            )
            
            # Use PAGE_ID attribute since that's what we defined in the search service
            search_results = cortex_search_service.search(
                query=query,
                columns=["CONTENT", "PAGE_ID", "DOCUMENTATION_ID"],
                limit=limit
            )
            
            # Filter results after search since DOCUMENTATION_ID isn't an attribute
            filtered_results = [
                result for result in search_results.results 
                if result.get("DOCUMENTATION_ID") == documentation_id
            ]
            
            return filtered_results[:limit]
        except Exception as e:
            st.error(f"Search error: {str(e)}")
            return []

class LLMService:
    def __init__(self, api_key):
        self.client = Mistral(api_key=api_key)

    def get_response(self, prompt, context):
        try:
            messages = [
                {
                    "role": "system",
                    "content": "You are a helpful documentation assistant. Use the provided context to answer questions. If the answer isn't in the context, say so."
                },
                {
                    "role": "user",
                    "content": f"Context: {context}\n\nQuestion: {prompt}"
                }
            ]

            response = self.client.chat.complete(
                model="mistral-medium",
                messages=messages
            )
            return response.choices[0].message.content
        except Exception as e:
            st.error(f"LLM error: {str(e)}")
            return "Sorry, I encountered an error processing your request."
            
def initialize_services():
    if 'doc_search' not in st.session_state:
        connection_params = {
            "user": 'KAP',
            "password": '9714044400K@p',
            "account": 'YEB46881',
            "warehouse": 'COMPUTE_WH',
            "database": 'ASK_DOC',
            "schema": 'ask_doc_schema'
        }
        st.session_state.doc_search = DocSearchService(connection_params)
    
    if 'llm_service' not in st.session_state:
        # Hardcoded API key instead of using secrets
        mistral_api_key = "lrverkbFAwCgjROS1McgRmJmuJIiJMpA"  # Replace with your actual API key
        st.session_state.llm_service = LLMService(mistral_api_key)


def get_snowflake_connection():
    """Create and return a Snowflake connection"""
    return snowflake.connector.connect(
        user='KAP',
        password='9714044400K@p',
        account='YEB46881',
        warehouse='COMPUTE_WH',
        database='ASK_DOC',
        schema='ask_doc_schema'
    )

def safe_scrape_page(url, domain):
    """Safely scrape a single page with error handling"""
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return None, []

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'footer']):
            element.decompose()
        
        # Extract text content
        content = ' '.join(soup.get_text().split())
        
        # Find links
        links = []
        for a_tag in soup.find_all('a', href=True):
            href = urljoin(url, a_tag['href'])
            parsed = urlparse(href)
            if parsed.netloc == domain and href not in st.session_state['scraped_pages']:
                links.append(href)
        
        return content, links
    except Exception as e:
        st.error(f"Error scraping {url}: {str(e)}")
        return None, []


def authenticate_user(username, password):
    try:
        conn = get_snowflake_connection()
        cursor = conn.cursor()
        # Use parameterized query to prevent SQL injection
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE username = %s AND password = %s",
            (username, password)
        )
        result = cursor.fetchone()
        return result[0] == 1
    except Exception as e:
        st.error(f"Authentication error: {str(e)}")
        return False
    finally:
        if conn:
            conn.close()

def signup_user(username, password):
    try:
        conn = get_snowflake_connection()
        cursor = conn.cursor()
        # Use parameterized query to prevent SQL injection
        cursor.execute(
            "INSERT INTO users (username, password) VALUES (%s, %s)",
            (username, password)
        )
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Signup error: {str(e)}")
        return False
    finally:
        if conn:
            conn.close()


def scrape_documentation(base_url):
    """Scrape documentation pages"""
    domain = urlparse(base_url).netloc
    pages_data = []
    visited = set()
    to_visit = [base_url]
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    while to_visit and len(visited) < 100:  # Limit to 100 pages for safety
        current_url = to_visit.pop(0)
        if current_url in visited:
            continue
            
        status_text.text(f"Scraping: {current_url}")
        content, new_links = safe_scrape_page(current_url, domain)
        
        if content:
            pages_data.append({
                'url': current_url,
                'content': content
            })
            visited.add(current_url)
            
            # Add new links to visit
            to_visit.extend([link for link in new_links if link not in visited])
            
        # Update progress
        progress = min(len(visited) / 100, 1.0)
        progress_bar.progress(progress)
        time.sleep(0.1)  # Prevent overwhelming the server
        
    status_text.empty()
    progress_bar.empty()
    return pages_data

def store_documentation_data(username, doc_name, base_url, pages_data):
    """Store scraped documentation in Snowflake"""
    try:
        conn = get_snowflake_connection()
        cur = conn.cursor()
        
        # Get user ID
        cur.execute("SELECT USER_ID FROM USERS WHERE USERNAME = %s", (username,))
        user_id = cur.fetchone()[0]
        
        # Insert documentation and get ID using RETURNING clause
        cur.execute("""
            INSERT INTO DOCUMENTATIONS (USER_ID, DOCUMENTATION_NAME, DOCUMENTATION_LINK)
            VALUES (%s, %s, %s)
            //RETURNING DOCUMENTATION_ID
        """, (user_id, doc_name, base_url))
        
        doc_id = cur.fetchone()[0]
        
        # Store current documentation ID in session state
        st.session_state.current_documentation_id = doc_id
        
        # Store pages and content using batch insert for better performance
        for page in pages_data:
            # Insert page and get its ID
            cur.execute("""
                INSERT INTO PAGES (DOCUMENTATION_ID, PAGE_LINK)
                VALUES (%s, %s)
                //RETURNING PAGE_ID
            """, (doc_id, page['url']))
            
            page_id = cur.fetchone()[0]
            
            # Insert content
            cur.execute("""
                INSERT INTO PAGE_CONTENT (PAGE_ID, CONTENT)
                VALUES (%s, %s)
            """, (page_id, page['content']))
        
        conn.commit()
        return True
    except Exception as e:
        st.error(f"Database error: {str(e)}")
        return False
    finally:
        if conn:
            conn.close()

            
def dashboard():
    """Main dashboard UI"""
    st.title("Documentation Scraper")

    initialize_services()
    
    with st.form("scrape_form"):    
        doc_name = st.text_input("Documentation Name")
        doc_url = st.text_input("Documentation URL")
        submitted = st.form_submit_button("Scrape Documentation")
        
        if submitted and doc_name and doc_url:
            with st.spinner("Scraping documentation..."):
                pages_data = scrape_documentation(doc_url)
                
                if pages_data:
                    st.info(f"Found {len(pages_data)} pages")
                    
                    with st.spinner("Storing in database..."):
                        if store_documentation_data(
                            st.session_state['username'],
                            doc_name,
                            doc_url,
                            pages_data
                        ):
                            st.success("Documentation stored successfully!")
                        else:
                            st.error("Failed to store documentation.")
                else:
                    st.warning("No content found to scrape.")
     # Chat interface
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat input
    if prompt := st.chat_input("Ask about the documentation"):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        current_doc_id = st.session_state.get('current_documentation_id')
        if not current_doc_id:
            response = "Please scrape a documentation first before asking questions."
        else:
            # Get relevant context from Cortex Search
            with st.spinner("Searching documentation..."):
                search_results = st.session_state.doc_search.search_documentation(
                    prompt, 
                    current_doc_id
                )
                context = "\n".join([result["CONTENT"] for result in search_results])

            # Get LLM response
            with st.spinner("Generating response..."):
                response = st.session_state.llm_service.get_response(prompt, context)

        # Add assistant message
        st.session_state.messages.append({"role": "assistant", "content": response})
        with st.chat_message("assistant"):
            st.markdown(response)


def main():
    st.sidebar.title("Menu")
    menu = st.sidebar.radio("Navigation", ["Login", "Sign Up", "Dashboard"])

    if menu == "Login":
        st.title("Login")
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            login_button = st.form_submit_button("Log In")

            if login_button:
                if authenticate_user(username, password):
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = username
                    st.success("Logged in successfully!")
                else:
                    st.error("Invalid credentials. Please try again.")
    
    elif menu == "Sign Up":
        st.title("Sign Up")
        with st.form("signup_form"):
            username = st.text_input("Choose a Username")
            password = st.text_input("Choose a Password", type="password")
            signup_button = st.form_submit_button("Sign Up")

            if signup_button:
                signup_user(username, password)
    
    elif menu == "Dashboard":
        if st.session_state['logged_in']:
            dashboard()
        else:
            st.warning("Please log in to access the dashboard.")


if __name__ == "__main__":
    main()