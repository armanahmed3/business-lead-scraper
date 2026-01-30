import streamlit as st

st.set_page_config(
    page_title="Test App",
    page_icon="🧪",
    layout="wide"
)

st.title("🧪 Test Application")
st.write("This is a simple test to check if Streamlit is working.")

if st.button("Click me"):
    st.success("Button clicked! Streamlit is working properly.")

st.write("Current time:", st.datetime_input("Select time"))
