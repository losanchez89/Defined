from supabase import create_client
import streamlit as st
import os

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Compatibilidad para ejecutar localmente con .streamlit/secrets.toml
if not SUPABASE_URL:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]

if not SUPABASE_SERVICE_ROLE_KEY:
    SUPABASE_SERVICE_ROLE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)