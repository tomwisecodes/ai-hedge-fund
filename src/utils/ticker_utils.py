
import json
import logging
import requests
import os
import re
from turtle import pd
from typing import Set, List

# This file was manually added as a fall back on 31st of Jan 2025 and should be updated if its used
SEC_JSON_PATH = "src/data/sec.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_local_sec_data() -> dict:
    """Load SEC company tickers from the local JSON file."""
    try:
        with open(SEC_JSON_PATH, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as e:
        print(f"Failed to load local SEC data: {e}")
        return {}

def get_sec_tickers() -> Set[str]:
    """Fetch the SEC company tickers, falling back to local file if the API fails."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    try:
        response = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=headers
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        # print(f"SEC API request failed: {e}. Falling back to local file.")
        data = load_local_sec_data()

    return {entry['ticker'] for entry in data.values()}

def get_company_name(ticker: str) -> str:
    """Fetch the company name for a given ticker, falling back to local file if the API fails."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    try:
        response = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=headers
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        # print(f"SEC API request failed: {e}. Falling back to local file.")
        data = load_local_sec_data()

    for value in data.values():
        if value['ticker'] == ticker:
            return value['title']

    return "Unknown"
    
def is_likely_ticker(ticker: str) -> bool:
    """Filter out common false positives"""
    common_words = {
        'A', 'I', 'AM', 'BE', 'DO', 'GO', 'IN', 'IS', 'IT', 'ME', 'MY', 
        'NO', 'OF', 'ON', 'OR', 'PM', 'SO', 'TO', 'UP', 'US', 'WE'
    }
    return ticker not in common_words

def find_tickers(text: str, ticker_set: Set[str]) -> List[str]:
    """
    Find stock tickers in text using pattern matching and validation against known tickers.
    """
    pattern = r'\$?[A-Z]{1,5}\b'
    potential_tickers = re.findall(pattern, text)

    valid_tickers = []
    for ticker in potential_tickers:
        clean_ticker = ticker.replace('$', '')
        if clean_ticker in ticker_set and is_likely_ticker(clean_ticker):
            valid_tickers.append(clean_ticker)
    
    return valid_tickers