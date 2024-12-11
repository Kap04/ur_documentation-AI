import streamlit as st

def main():
    st.set_page_config(page_title="AskDocs - Chat with Documentation", page_icon="📚", layout="centered")

    st.title("AskDocs 📚")
    st.subheader("Your AI-powered documentation assistant")

    st.write("""
    Tired of spending hours reading through documentation? 
    AskDocs is here to help! Our AI-powered tool allows you to chat 
    with any documentation, getting quick and accurate answers to your questions.
    """)

    st.markdown("### How it works")
    col1, col2, col3 = st.columns(3)

    with col1:
        st.image("https://placeholder.svg?height=100&width=100", caption="1. Paste Doc Link")
        st.write("Simply paste the link to your documentation.")

    with col2:
        st.image("https://placeholder.svg?height=100&width=100", caption="2. Ask Questions")
        st.write("Ask questions in natural language.")

    with col3:
        st.image("https://placeholder.svg?height=100&width=100", caption="3. Get Answers")
        st.write("Receive accurate answers from our AI.")

    st.markdown("### Benefits")
    st.write("✅ Save time on reading extensive documentation")
    st.write("✅ Get precise answers to your questions")
    st.write("✅ Improve productivity and understanding")

    if st.button("Get Started", key="get_started"):
        st.success("Great! Redirecting you to the dashboard...")
        st.switch_page("pages/1_Dashboard.py")

    st.markdown("---")
    st.write("© 2023 AskDocs. All rights reserved.")

if __name__ == "__main__":
    main()
