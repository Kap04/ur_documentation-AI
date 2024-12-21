import streamlit as st
import snowflake.connector
from bs4 import BeautifulSoup
import requests
from urllib.parse import urljoin, urlparse
import time
import queue
import threading

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
        
        # Insert documentation
        cur.execute("""
            INSERT INTO DOCUMENTATIONS (USER_ID, DOCUMENTATION_NAME, DOCUMENTATION_LINK)
            VALUES (%s, %s, %s)
            //RETURNING DOCUMENTATION_ID
        """, (user_id, doc_name, base_url))
        doc_id = cur.fetchone()[0]
        
        # Store pages and content
        for page in pages_data:
            # Insert page
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

def main():
    """Main application entry point"""
    if not st.session_state['logged_in']:
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Login")
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                login_submitted = st.form_submit_button("Login")
                
                if login_submitted:
                    if authenticate_user(username, password):
                        st.session_state['logged_in'] = True
                        st.session_state['username'] = username
                        #st.experimental_rerun()
        
        with col2:
            st.subheader("Sign Up")
            with st.form("signup_form"):
                new_username = st.text_input("Choose Username")
                new_password = st.text_input("Choose Password", type="password")
                confirm_password = st.text_input("Confirm Password", type="password")
                signup_submitted = st.form_submit_button("Sign Up")
                
                if signup_submitted:
                    if new_password != confirm_password:
                        st.error("Passwords don't match")
                    else:
                        signup_user(new_username, new_password)
    else:
        dashboard()

if __name__ == "__main__":
    main()