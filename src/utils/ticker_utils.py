from asyncio.log import logger
import json
import requests
import os
import re
from turtle import pd
from typing import Set, List

def get_sec_tickers() -> Set[str]:
    """Fetch the SEC company tickers and return a set of valid ticker symbols."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    response = requests.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers=headers
    )
    if response.status_code != 200:
        raise Exception(f"SEC API returned status code {response.status_code}")
    
    data = json.loads(response.text)
    
    # Extract ticker symbols into a set
    ticker_set = {entry['ticker'] for entry in data.values()}
    return ticker_set


def get_company_name(ticker: str) -> str:
    """Fetch the SEC company tickers and return the company name for a given ticker."""
    try: 
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=headers
        )
        if response.status_code != 200:
            raise Exception(f"SEC API returned status code {response.status_code}")
        
        data = json.loads(response.text)

        # Iterate over the dictionary to find the matching ticker
        for key, value in data.items():
            if value['ticker'] == ticker:
                return value['title']

        # If no match is found
        return "Unknown"

    except Exception as e:
        print("Error:", e)
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