import streamlit as st # type: ignore
import snowflake.connector
from snowflake.snowpark import Session
from bs4 import BeautifulSoup
import requests
from urllib.parse import urljoin, urlparse
import time
from langchain.text_splitter import RecursiveCharacterTextSplitter
from snowflake.core import Root
from mistralai import Mistral

# Page config
st.set_page_config(
    page_title="AskDoc - Chat with Your Documentation",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Constants
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200
MAX_PAGES = 100
SEARCH_RESULT_LIMIT = 5

class SnowflakeConnection:
    @staticmethod
    def get_connection():
        return snowflake.connector.connect(
            user='KAP',
            password='9714044400K@p',
            account='YEB46881',
            warehouse='COMPUTE_WH',
            database='ASK_DOC',
            schema='ask_doc_schema'
        )

class DocumentProcessor:
    def __init__(self):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            length_function=len
        )

    def scrape_and_chunk_content(self, url, domain):
        """Scrape content and split into chunks"""
        try:
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                return None

            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'footer']):
                element.decompose()
            
            # Get text content
            content = ' '.join(soup.get_text().split())
            
            # Split content into chunks
            chunks = self.text_splitter.split_text(content)
            
            # Find links
            links = []
            for a_tag in soup.find_all('a', href=True):
                href = urljoin(url, a_tag['href'])
                if urlparse(href).netloc == domain:
                    links.append(href)
            
            return chunks, links
        except Exception as e:
            st.error(f"Error processing {url}: {str(e)}")
            return None, []

class Auth:
    @staticmethod
    def authenticate(username, password):
        conn = SnowflakeConnection.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT USER_ID FROM users WHERE username = %s AND password = %s", 
                   (username, password))
        result = cur.fetchone()
        conn.close()
        return result[0] if result else None

    @staticmethod
    def signup(username, password):
        conn = SnowflakeConnection.get_connection()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", 
                       (username, password))
            conn.commit()
            cur.execute("SELECT USER_ID FROM users WHERE username = %s", (username,))
            user_id = cur.fetchone()[0]
            return user_id
        except Exception as e:
            st.error(f"Signup failed: {str(e)}")
            return None
        finally:
            conn.close()

class DocumentStore:
    def store_documentation(self, user_id, doc_name, base_url, chunks):
        conn = SnowflakeConnection.get_connection()
        try:
            cur = conn.cursor()
            
            # Insert documentation
            cur.execute("""
                INSERT INTO DOCUMENTATIONS (USER_ID, DOCUMENTATION_NAME, DOCUMENTATION_LINK)
                VALUES (%s, %s, %s)
            """, (user_id, doc_name, base_url))
            
            # Get the inserted ID
            cur.execute("SELECT MAX(DOCUMENTATION_ID) FROM DOCUMENTATIONS WHERE USER_ID = %s AND DOCUMENTATION_NAME = %s", 
                       (user_id, doc_name))
            doc_id = cur.fetchone()[0]
            
            # Insert pages and content
            for i, chunk in enumerate(chunks):
                # Insert page
                cur.execute("""
                    INSERT INTO PAGES (DOCUMENTATION_ID, PAGE_LINK)
                    VALUES (%s, %s)
                """, (doc_id, f"{base_url}#chunk{i}"))
                
                # Get the inserted page ID
                cur.execute("SELECT MAX(PAGE_ID) FROM PAGES WHERE DOCUMENTATION_ID = %s AND PAGE_LINK = %s",
                           (doc_id, f"{base_url}#chunk{i}"))
                page_id = cur.fetchone()[0]
                
                # Insert page content
                cur.execute("""
                    INSERT INTO PAGE_CONTENT (PAGE_ID, CONTENT)
                    VALUES (%s, %s)
                """, (page_id, chunk))
            
            conn.commit()
            return doc_id
        except Exception as e:
            st.error(f"Database error: {str(e)}")
            conn.rollback()
            return None
        finally:
            conn.close()
            
def login_page():
    st.title("Login")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
        
        if submitted:
            user_id = Auth.authenticate(username, password)
            if user_id:
                st.session_state['user_id'] = user_id
                st.session_state['username'] = username
                st.session_state['logged_in'] = True
                st.rerun()
            else:
                st.error("Invalid credentials")

def signup_page():
    st.title("Sign Up")
    with st.form("signup"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign Up")
        
        if submitted:
            user_id = Auth.signup(username, password)
            if user_id:
                st.session_state['user_id'] = user_id
                st.session_state['username'] = username
                st.session_state['logged_in'] = True
                st.rerun()


class SearchService:
    def __init__(self, session):
        self.root = Root(session)
        self.search_service = (
            self.root.databases["ASK_DOC"]
            .schemas["PUBLIC"]
            .cortex_search_services["doc_search_service"]
        )

    def search(self, query, documentation_id):
        """Search for relevant chunks using Cortex Search"""
        try:
            # Convert documentation_id to string for Cortex Search
            doc_id = str(documentation_id)
            
            filter_obj = {"@eq": {"documentation_id": doc_id}}
            
            results = self.search_service.search(
                query=query,
                columns=["content", "page_id", "documentation_id"],
                filter=filter_obj,
                limit=SEARCH_RESULT_LIMIT
            )
            return results
        except Exception as e:
            st.error(f"Search error: {str(e)}")
            return None     
        
class ChatBot:
    def __init__(self, api_key):
        self.client = Mistral(api_key=api_key)
        self.search_service = None
        self.session = None

    def initialize_session(self, connection_params):
        self.session = Session.builder.configs(connection_params).create()
        self.search_service = SearchService(self.session)

    def generate_response(self, query, context):
        """Generate response using Mistral AI"""
        prompt = f"""You are a helpful documentation assistant. Use the provided context to answer questions.
        Always base your answers on the context provided. If you cannot find the answer in the context, say so.
        
        Context:
        {context}
        
        Question: {query}
        
        Answer:"""

        try:
            response = self.client.chat.complete(
                model="mistral-medium",
                messages=[
                    {"role": "system", "content": "You are a documentation assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            st.error(f"LLM error: {str(e)}")
            return None

def main():
     # Initialize all session states
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
    if 'messages' not in st.session_state:
        st.session_state['messages'] = []
    if 'user_id' not in st.session_state:
        st.session_state['user_id'] = None
    if 'username' not in st.session_state:
        st.session_state['username'] = None
    if 'current_doc_id' not in st.session_state:
        st.session_state['current_doc_id'] = None

    if not st.session_state['logged_in']:
        tab1, tab2 = st.tabs(["Login", "Sign Up"])
        with tab1:
            login_page()
        with tab2:
            signup_page()
        return
    
    st.title("🤖 AskDoc - Chat with Your Documentation")
    
    # Initialize services
    connection_params = {
        "user": 'KAP',
        "password": '9714044400K@p',
        "account": 'YEB46881',
        "warehouse": 'COMPUTE_WH',
        "database": 'ASK_DOC',
        "schema": 'ask_doc_schema'
    }
    
    chatbot = ChatBot(api_key="lrverkbFAwCgjROS1McgRmJmuJIiJMpA")
    chatbot.initialize_session(connection_params)
    
    # Sidebar for documentation upload
    with st.sidebar:
        st.header("📚 Add Documentation")
        doc_name = st.text_input("Documentation Name")
        doc_url = st.text_input("Documentation URL")
        
        if st.button("Add Documentation"):
            if doc_name and doc_url:
                processor = DocumentProcessor()
                store = DocumentStore()
                
                with st.spinner("Processing documentation..."):
                    domain = urlparse(doc_url).netloc
                    chunks, _ = processor.scrape_and_chunk_content(doc_url, domain)
                    
                    if chunks:
                        doc_id = store.store_documentation(1, doc_name, doc_url, chunks)
                        if doc_id:
                            st.success("Documentation added successfully!")
                            st.session_state['current_doc_id'] = doc_id
    
    # Main chat interface
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    if query := st.chat_input("Ask about your documentation"):
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)
        
        if 'current_doc_id' in st.session_state:
            # Get relevant context
            search_results = chatbot.search_service.search(query, st.session_state['current_doc_id'])
            if search_results:
                context = "\n".join([result["content"] for result in search_results.results])
                
                # Generate response
                response = chatbot.generate_response(query, context)
                
                if response:
                    st.session_state.messages.append({"role": "assistant", "content": response})
                    with st.chat_message("assistant"):
                        st.markdown(response)
        else:
            st.warning("Please add documentation first!")

if __name__ == "__main__":
    main()