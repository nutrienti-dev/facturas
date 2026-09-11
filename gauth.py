"""
Autenticacion con Google via OAuth de usuario (reutilizando el mismo
client_id/client_secret/refresh_token que ya usa la app de pedidos de
Nutrienti). No se usa cuenta de servicio porque la organizacion bloquea la
creacion de llaves de cuenta de servicio (politica
iam.disableServiceAccountKeyCreation).
"""
import streamlit as st
import gspread
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


@st.cache_resource(show_spinner=False)
def get_credentials():
    if "gcp_oauth" not in st.secrets:
        return None
    cfg = st.secrets["gcp_oauth"]
    return UserCredentials(
        token=None,
        refresh_token=cfg["refresh_token"],
        client_id=cfg["client_id"],
        client_secret=cfg["client_secret"],
        token_uri=cfg.get("token_uri", "https://oauth2.googleapis.com/token"),
        scopes=SCOPES,
    )


@st.cache_resource(show_spinner=False)
def get_gspread_client():
    creds = get_credentials()
    if creds is None:
        return None
    return gspread.authorize(creds)


@st.cache_resource(show_spinner=False)
def get_drive_service():
    creds = get_credentials()
    if creds is None:
        return None
    return build("drive", "v3", credentials=creds, cache_discovery=False)
