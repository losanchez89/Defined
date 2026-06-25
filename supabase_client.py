from supabase import create_client
import os
import streamlit as st

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

st.write("SUPABASE_URL =", repr(SUPABASE_URL))
st.write("SUPABASE_SERVICE_ROLE_KEY exists =", SUPABASE_SERVICE_ROLE_KEY is not None)

if not SUPABASE_URL:
    st.stop()

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)