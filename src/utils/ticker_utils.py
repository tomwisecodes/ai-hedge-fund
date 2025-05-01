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
    """Filter out common false positives while allowing legitimate tickers"""
    # Legitimate single-letter tickers (major companies)
    valid_single_letters = {'V'}
    
    # Common words, acronyms, and abbreviations that get mistaken for tickers
    common_words = {
        # Original common words
        'A', 'I', 'AM', 'BE', 'DO', 'GO', 'IN', 'IS', 'IT', 'ME', 'MY', 
        'NO', 'OF', 'ON', 'OR', 'PM', 'SO', 'TO', 'UP', 'US', 'WE', 'DD', 'DTE', 'EOD', 'API', 'DTE', 'DD',
        
        # Common English words
        'ALL', 'AN', 'ANY', 'ARE', 'AS', 'AT', 'BY', 'CAN', 'DAY', 'FOR', 
        'HAS', 'HE', 'LOT', 'NOW', 'OPEN', 'REAL', 'SAY', 'WAY', 'EDIT', 'OP'
        
        # Internet/chat abbreviations and slang
        'IMO', 'WTF', 'EOD', 'API', 'DTE', 'DD',
        
        # Countries and regions
        'USA', 'EU', 'UK',
        
        # Finance/trading terms
        'IRS', 'RSI', 'IP', 'VC', 'HR', 'VS', 'TFSA',
        
        # Two letter combinations commonly mistaken
        'CC', 'TV', 'WH', 'WM',
    }

        
    # Check if it's a valid single letter ticker
    if len(ticker) == 1:
        return ticker in valid_single_letters
        
    # Filter out common words
    if ticker in common_words:
        return False
        
    return True

def find_tickers(text: str, ticker_set: Set[str]) -> List[str]:
    """
    Find stock tickers in text using pattern matching and validation against known tickers.
    
    Improvements:
    - Enforces proper word boundaries with whitespace
    - Excludes tickers found within URLs, email addresses, or other non-ticker contexts
    - Uses existing is_likely_ticker() function as a secondary filter
    """
    # First, exclude URLs and email addresses from consideration
    # This will temporarily replace URLs with spaces to prevent false matches
    url_pattern = r'https?://\S+|www\.\S+|\S+\.\S+/\S+|\S+@\S+\.\S+'
    clean_text = re.sub(url_pattern, ' ', text)
    
    # Pattern for tickers - requires whitespace or string boundaries on both sides
    # Format: either $TICKER or TICKER with 1-5 uppercase letters
    ticker_pattern = r'(?:^|\s)(\$?[A-Z]{1,5})(?=\s|$)'
    potential_tickers = re.findall(ticker_pattern, clean_text)

    valid_tickers = []
    for ticker in potential_tickers:
        clean_ticker = ticker.replace('$', '')
        
        # Skip if it's not a valid ticker in our set
        if clean_ticker not in ticker_set:
            continue
            
        # Apply the existing filtering logic
        if not is_likely_ticker(clean_ticker):
            continue
            
        # Optional: Check for stock-related context for single-letter tickers
        if len(clean_ticker) == 1:
            # Look for stock context near single-letter tickers to reduce false positives
            context_pattern = rf'(?:stock|share|ticker|symbol|buy|sell|long|short)(?:\s+\w+){{0,3}}\s+(?:\$?{clean_ticker}\b|\b{clean_ticker}(?:\$|\s))'
            alt_context_pattern = rf'\b{clean_ticker}(?:\$|\s)(?:\s+\w+){{0,3}}\s+(?:stock|share|price|dip|moon|gain|loss)'
            
            has_context = re.search(context_pattern, clean_text, re.IGNORECASE) or \
                          re.search(alt_context_pattern, clean_text, re.IGNORECASE) or \
                          f'${clean_ticker}' in clean_text  # $-prefixed tickers are almost always actual tickers
                          
            if not has_context:
                continue
        
        valid_tickers.append(clean_ticker)
    
    return valid_tickers