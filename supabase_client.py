from supabase import create_client
import os
import streamlit as st

# Primero intenta leer las variables de Railway
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Si no existen (ejecución local), usa secrets.toml
if not SUPABASE_URL:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]

if not SUPABASE_SERVICE_ROLE_KEY:
    SUPABASE_SERVICE_ROLE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY
)