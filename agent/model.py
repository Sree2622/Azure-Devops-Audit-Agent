"""Gemini model configuration for the Azure DevOps AI Agent."""

from __future__ import annotations

import os

from langchain_google_genai import ChatGoogleGenerativeAI

from .config import GOOGLE_API_KEY


# ============================================================
# MODEL CONFIGURATION
# ============================================================

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.5-flash",
)


# ============================================================
# MODEL
# ============================================================

model = ChatGoogleGenerativeAI(
    model=GEMINI_MODEL,
    google_api_key=GOOGLE_API_KEY,
    include_thoughts=False,
)