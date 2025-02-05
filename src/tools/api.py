import os
import traceback
import pandas as pd
import requests
from pydantic import BaseModel
from data.cache import get_cache
from typing import Dict, Any, List, Optional
from datetime import datetime
from data.models import (
    CompanyNews,
    CompanyNewsResponse,
    FinancialMetrics,
    FinancialMetricsResponse,
    Price,
    PriceResponse,
    LineItem,
    LineItemResponse,
    InsiderTrade,
    InsiderTradeResponse,
)

# Global cache instance
_cache = get_cache()


def get_prices(ticker: str, start_date: str, end_date: str) -> list[Price]:
    """Fetch price data from Alpha Vantage API."""
    # Check cache first
    if cached_data := _cache.get_prices(ticker):
        # Filter cached data by date range and convert to Price objects
        filtered_data = [Price(**price) for price in cached_data if start_date <= price["time"] <= end_date]
        if filtered_data:
            return filtered_data

    # If not in cache or no data in range, fetch from Alpha Vantage
    alpha_vantage_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not alpha_vantage_key:
        raise Exception("ALPHA_VANTAGE_API_KEY environment variable not set")

    url = (
        f"https://www.alphavantage.co/query?"
        f"function=TIME_SERIES_DAILY"
        f"&symbol={ticker}"
        f"&outputsize=full"  # This gets the full history
        f"&apikey={alpha_vantage_key}"
    )

    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Error fetching data: {response.status_code} - {response.text}")

    data = response.json()
    
    # Handle Alpha Vantage error responses
    if "Error Message" in data:
        raise Exception(f"Alpha Vantage API error: {data['Error Message']}")
    
    # Extract time series data
    time_series = data.get("Time Series (Daily)")
    if not time_series:
        return []

    # Convert Alpha Vantage format to our Price format
    prices = []
    for date, values in time_series.items():
        if start_date <= date <= end_date:
            price = Price(
                time=date,
                open=float(values["1. open"]),
                high=float(values["2. high"]),
                low=float(values["3. low"]),
                close=float(values["4. close"]),
                volume=int(values["5. volume"])
            )
            prices.append(price)

    # Sort prices by date (newest first)
    prices.sort(key=lambda x: x.time, reverse=True)

    # Cache the results as dicts
    _cache.set_prices(ticker, [p.model_dump() for p in prices])
    
    return prices


class LineItem(BaseModel):
    ticker: str
    report_period: str
    period: str
    currency: str

    # Allow additional fields dynamically
    model_config = {"extra": "allow"}

class LineItemResponse(BaseModel):
    search_results: list[LineItem]

def _fetch_alpha_vantage_data(endpoint: str, ticker: str) -> Dict[str, Any]:
    """Helper function to fetch data from Alpha Vantage API."""
    alpha_vantage_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not alpha_vantage_key:
        raise Exception("ALPHA_VANTAGE_API_KEY environment variable not set")

    url = (
        f"https://www.alphavantage.co/query?"
        f"function={endpoint}"
        f"&symbol={ticker}"
        f"&apikey={alpha_vantage_key}"
    )

    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Error fetching data: {response.status_code} - {response.text}")

    data = response.json()
    if "Error Message" in data:
        raise Exception(f"Alpha Vantage API error: {data['Error Message']}")
    
    return data

def _safe_float(value: Any) -> float | None:
    """Safely convert value to float, returning None if conversion fails."""
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None

# Mapping of common line item names to their Alpha Vantage locations
LINE_ITEM_MAPPING = {
    # Income Statement items
    "revenue": ("INCOME_STATEMENT", "totalRevenue"),
    "gross_profit": ("INCOME_STATEMENT", "grossProfit"),
    "operating_income": ("INCOME_STATEMENT", "operatingIncome"),
    "net_income": ("INCOME_STATEMENT", "netIncome"),
    "ebit": ("INCOME_STATEMENT", "ebit"),
    "ebitda": ("INCOME_STATEMENT", "ebitda"),
    
    # Balance Sheet items
    "total_assets": ("BALANCE_SHEET", "totalAssets"),
    "total_current_assets": ("BALANCE_SHEET", "totalCurrentAssets"),
    "cash_and_equivalents": ("BALANCE_SHEET", "cashAndCashEquivalentsAtCarryingValue"),
    "inventory": ("BALANCE_SHEET", "inventory"),
    "total_liabilities": ("BALANCE_SHEET", "totalLiabilities"),
    "total_current_liabilities": ("BALANCE_SHEET", "totalCurrentLiabilities"),
    "total_shareholder_equity": ("BALANCE_SHEET", "totalShareholderEquity"),
    "working_capital": ("BALANCE_SHEET", "special_working_capital"),  # Special handling
    
    # Cash Flow items
    "operating_cash_flow": ("CASH_FLOW", "operatingCashflow"),
    "capital_expenditure": ("CASH_FLOW", "capitalExpenditures"),
    "free_cash_flow": ("CASH_FLOW", "operatingCashflow"),  # Will need to calculate
    "dividend_payments": ("CASH_FLOW", "dividendPayout"),
    "depreciation_and_amortization": ("CASH_FLOW", "depreciation"),
}

# **************************************

class ValuationLineItem(BaseModel):
    ticker: str
    report_period: str
    period: str = "ttm"
    currency: str = "USD"
    free_cash_flow: Optional[float]
    net_income: Optional[float]
    depreciation_and_amortization: Optional[float]
    capital_expenditure: Optional[float]
    working_capital: Optional[float]

def safe_float_convert(value: Any) -> Optional[float]:
    """Safely convert a value to float, returning None if conversion fails."""
    if value is None or value == 'None' or value == '':
        return None
    try:
        float_val = float(value)
        return float_val if float_val != 0 else None
    except (ValueError, TypeError):
        return None

def get_alpha_vantage_data(endpoint: str, ticker: str, api_key: str) -> Dict[str, Any]:
    """Fetch data from Alpha Vantage API."""
    base_url = "https://www.alphavantage.co/query"
    params = {
        "function": endpoint,
        "symbol": ticker,
        "apikey": api_key
    }
    
    response = requests.get(base_url, params=params)
    if response.status_code != 200:
        raise Exception(f"Error fetching {endpoint}: {response.status_code} - {response.text}")
    
    data = response.json()
    if "Error Message" in data:
        raise Exception(f"Alpha Vantage API error: {data['Error Message']}")
    
    if not data or (
        "annualReports" not in data 
        and "quarterlyReports" not in data 
        and endpoint not in ["OVERVIEW"]
    ):
        raise Exception(f"Invalid or empty response for {endpoint}")
        
    return data

def calculate_ttm_value(quarterly_data: List[dict], field_name: str) -> Optional[float]:
    """Calculate TTM value by summing last 4 quarters with special handling for capital expenditures."""
    try:
        if not quarterly_data or len(quarterly_data) < 4:
            return None
        
        values = []
        for quarter in quarterly_data[:4]:
            value = safe_float_convert(quarter.get(field_name))
            
            # Special handling for different fields
            if value is None:
                if field_name == 'depreciationAndAmortization':
                    # Existing depreciation fallback logic
                    depreciation_value = safe_float_convert(quarter.get('depreciation'))
                    if depreciation_value is not None:
                        print(f"Using depreciation value {depreciation_value} for {quarter['fiscalDateEnding']}")
                        value = depreciation_value
                    else:
                        print(f"Warning: No valid depreciation data for {quarter['fiscalDateEnding']}")
                        return None
                elif field_name == 'capitalExpenditures':
                    # Treat None as 0 for capital expenditures
                    print(f"Treating None capitalExpenditures as 0 for {quarter['fiscalDateEnding']}")
                    value = 0
                else:
                    print(f"Error: No valid {field_name} for {quarter['fiscalDateEnding']}")
                    return None
                
            values.append(value)

        return sum(values) if len(values) == 4 else None
        
    except Exception as e:
        print(f"Error calculating TTM value: {e}")
        return None

def calculate_working_capital(balance_data: dict) -> Optional[float]:
    """Calculate working capital from current assets and current liabilities."""
    current_assets = safe_float_convert(balance_data.get("totalCurrentAssets"))
    current_liabilities = safe_float_convert(balance_data.get("totalCurrentLiabilities"))
    
    if current_assets is None or current_liabilities is None:
        return None
        
    return current_assets - current_liabilities

def search_valuation_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 2,
) -> list[ValuationLineItem]:
    """Fetch financial line items specifically for valuation analysis."""
    if period != "ttm":
        raise ValueError("Currently only TTM period is supported")

    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        raise ValueError("ALPHA_VANTAGE_API_KEY environment variable is required")

    try:
        # Fetch required data
        income_stmt = get_alpha_vantage_data("INCOME_STATEMENT", ticker, api_key)
        balance_sheet = get_alpha_vantage_data("BALANCE_SHEET", ticker, api_key)
        cash_flow = get_alpha_vantage_data("CASH_FLOW", ticker, api_key)

        # Get quarterly data
        quarterly_income = income_stmt.get("quarterlyReports", [])
        quarterly_cash_flow = cash_flow.get("quarterlyReports", [])
        quarterly_balance = balance_sheet.get("quarterlyReports", [])

        if len(quarterly_balance) < 8:  # Need at least 8 quarters for 2 TTM periods
            return []

        results = []
        
        # Process two TTM periods
        for i in range(2):
            try:
                period_start_idx = i * 4
                period_end_idx = period_start_idx + 4
                
                period_quarters_income = quarterly_income[period_start_idx:]
                period_quarters_cash = quarterly_cash_flow[period_start_idx:]
                period_balance = quarterly_balance[period_start_idx]

                period_end = period_balance.get("fiscalDateEnding")
                
                print(f"Processing period {i} starting from {period_end}")
                print(f"First quarter depreciation value: {period_quarters_income[0].get('depreciationAndAmortization')}")
                
                # Calculate values for this period
                free_cash_flow = calculate_ttm_value(period_quarters_cash, "operatingCashflow")
                net_income = calculate_ttm_value(period_quarters_income, "netIncome")
                capital_expenditure = calculate_ttm_value(period_quarters_cash, "capitalExpenditures")
                working_capital = calculate_working_capital(period_balance)
                
                # Special handling for depreciation
                depreciation_and_amortization = None
                if period_quarters_income[0].get('depreciationAndAmortization') == 'None':
                    # Try to interpolate
                    depreciation_and_amortization = interpolate_depreciation(period_quarters_income)
                else:
                    # Calculate normally if we have the value
                    depreciation_and_amortization = calculate_ttm_value(period_quarters_income, "depreciationAndAmortization")
                
                # Validate all required values are present
                if any(v is None for v in [free_cash_flow, net_income, capital_expenditure, working_capital]):
                    print(f"Missing required values for period {period_end}")
                    continue
                
                # Create line item even if depreciation is interpolated or missing
                line_item = ValuationLineItem(
                    ticker=ticker,
                    report_period=period_end,
                    free_cash_flow=free_cash_flow,
                    net_income=net_income,
                    depreciation_and_amortization=depreciation_and_amortization,
                    capital_expenditure=capital_expenditure,
                    working_capital=working_capital
                )
                
                results.append(line_item)
                
            except Exception as e:
                print(f"Error processing period {i}: {str(e)}")
                continue

        return results[:limit]
        
    except Exception as e:
        print(f"Error processing valuation data for {ticker}: {str(e)}")
        return []


# **************************************

class LineItem(BaseModel):
    ticker: str
    report_period: str
    period: str = "ttm"
    currency: str = "USD"
    capital_expenditure: Optional[float]
    depreciation_and_amortization: Optional[float]
    net_income: Optional[float]
    outstanding_shares: Optional[float]
    total_assets: Optional[float]
    total_liabilities: Optional[float]

def safe_float_convert(value: Any) -> Optional[float]:
    """Safely convert a value to float, returning None if conversion fails."""
    if value is None or value == 'None' or value == '':
        return None
    try:
        float_val = float(value)
        return float_val if float_val != 0 else None
    except (ValueError, TypeError):
        return None

def get_alpha_vantage_data(endpoint: str, ticker: str, api_key: str) -> Dict[str, Any]:
    """Fetch data from Alpha Vantage API."""
    base_url = "https://www.alphavantage.co/query"
    params = {
        "function": endpoint,
        "symbol": ticker,
        "apikey": api_key
    }
    
    response = requests.get(base_url, params=params)
    if response.status_code != 200:
        raise Exception(f"Error fetching {endpoint}: {response.status_code} - {response.text}")
    
    data = response.json()
    if "Error Message" in data:
        raise Exception(f"Alpha Vantage API error: {data['Error Message']}")
    
    # Add basic validation for empty or invalid responses
    if not data or (
        "annualReports" not in data 
        and "quarterlyReports" not in data 
        and endpoint not in ["OVERVIEW"]
    ):
        raise Exception(f"Invalid or empty response for {endpoint}")
        
    return data

def interpolate_depreciation(quarterly_data: List[dict]) -> Optional[float]:
    """
    Interpolate missing depreciation value based on the trend from previous quarters.
    Only used when the most recent quarter has missing depreciation data.
    """
    if len(quarterly_data) < 4:
        return None
    
    # Get the previous 4 quarters' depreciation values
    values = []
    for i in range(1, 5):  # Start from index 1 to get previous quarters
        if i >= len(quarterly_data):
            return None
        value = safe_float_convert(quarterly_data[i].get('depreciationAndAmortization'))
        if value is None:
            return None
        values.append(value)
    
    # Calculate the average quarter-over-quarter change
    qoq_changes = []
    for i in range(len(values)-1):
        change = values[i] - values[i+1]
        qoq_changes.append(change)
    
    # Use the trend to project forward
    if qoq_changes:
        avg_change = sum(qoq_changes) / len(qoq_changes)
        interpolated_value = values[0] + avg_change
        # Round to nearest thousand to match data format
        return round(interpolated_value / 1000) * 1000
    
    return None

def calculate_ttm_value_buff(quarterly_data: List[dict], field_name: str) -> Optional[float]:
    """Calculate TTM value by summing last 4 quarters, with special handling for depreciation."""
    if not quarterly_data or len(quarterly_data) < 4:
        return None
        
    # Special handling for depreciation and amortization
    if field_name == 'depreciationAndAmortization':
        values = []
        first_quarter_value = safe_float_convert(quarterly_data[0].get(field_name))
        
        # Only interpolate if first quarter is None
        if first_quarter_value is None:
            interpolated_value = interpolate_depreciation(quarterly_data)
            if interpolated_value is not None:
                values.append(interpolated_value)
                # Add the other quarters
                for quarter in quarterly_data[1:4]:
                    value = safe_float_convert(quarter.get(field_name))
                    if value is None:
                        return None
                    values.append(value)
                return sum(values)
        return None
    
    # Standard handling for all other fields
    values = []
    for quarter in quarterly_data[:4]:
        value = safe_float_convert(quarter.get(field_name))
        if value is None:
            return None
        values.append(value)
    
    return sum(values) if len(values) == 4 else None

def search_line_items_warren_buff(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
) -> list[LineItem]:
    """Fetch financial line items from Alpha Vantage."""
    if period != "ttm":
        raise ValueError("Currently only TTM period is supported")

    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not api_key:
        raise ValueError("ALPHA_VANTAGE_API_KEY environment variable is required")

    try:
        # Fetch data from required endpoints
        income_stmt = get_alpha_vantage_data("INCOME_STATEMENT", ticker, api_key)
        balance_sheet = get_alpha_vantage_data("BALANCE_SHEET", ticker, api_key)
        cash_flow = get_alpha_vantage_data("CASH_FLOW", ticker, api_key)
        overview = get_alpha_vantage_data("OVERVIEW", ticker, api_key)

        # Get quarterly data for TTM calculations
        quarterly_income = income_stmt.get("quarterlyReports", [])
        quarterly_cash_flow = cash_flow.get("quarterlyReports", [])
        
        # Get annual data for historical comparison
        annual_balance = balance_sheet.get("annualReports", [])

        if not annual_balance:
            return []

        results = []
        
        # Process the most recent 5 periods (or less if not available)
        for i in range(min(limit, len(annual_balance))):
            period_data = annual_balance[i]
            period_end = period_data.get("fiscalDateEnding")

            # Create LineItem for each period
            line_item = LineItem(
                ticker=ticker,
                report_period=period_end,
                capital_expenditure=calculate_ttm_value_buff(
                    quarterly_cash_flow, "capitalExpenditures"
                ),
                depreciation_and_amortization=calculate_ttm_value_buff(
                    quarterly_income, "depreciationAndAmortization"
                ),
                net_income=calculate_ttm_value_buff(
                    quarterly_income, "netIncome"
                ),
                outstanding_shares=safe_float_convert(
                    overview.get("SharesOutstanding")
                ),
                total_assets=safe_float_convert(
                    period_data.get("totalAssets")
                ),
                total_liabilities=safe_float_convert(
                    period_data.get("totalLiabilities")
                )
            )
            
            results.append(line_item)

        return results[:limit]
        
    except Exception as e:
        print(f"Error processing data for {ticker}: {str(e)}")
        return []




# *************************


def _safe_float(value: Any) -> float | None:
    """Safely convert value to float, returning None if conversion fails."""
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None

def _parse_date(date_str: str | None) -> str | None:
    """Convert Alpha Vantage date format to our date format."""
    if not date_str:
        return None
    try:
        # Parse the date and convert to ISO format (YYYY-MM-DD)
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%Y-%m-%d')
    except ValueError:
        return None

def _is_board_director(title: str | None) -> bool | None:
    """Determine if the person is a board director based on their title."""
    if not title:
        return None
    title_lower = title.lower()
    director_keywords = ['director', 'board member', 'chairman', 'vice chairman']
    return any(keyword in title_lower for keyword in director_keywords)

def get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
) -> list[InsiderTrade]:
    """Fetch insider trades from Alpha Vantage API."""
    # Check cache first
    if cached_data := _cache.get_insider_trades(ticker):
        # Filter cached data by date range
        filtered_data = [InsiderTrade(**trade) for trade in cached_data 
                        if (start_date is None or (trade.get("transaction_date") or trade["filing_date"]) >= start_date)
                        and (trade.get("transaction_date") or trade["filing_date"]) <= end_date]
        filtered_data.sort(key=lambda x: x.transaction_date or x.filing_date, reverse=True)
        if filtered_data:
            return filtered_data

    # If not in cache, fetch from Alpha Vantage
    alpha_vantage_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not alpha_vantage_key:
        raise Exception("ALPHA_VANTAGE_API_KEY environment variable not set")

    url = (
        f"https://www.alphavantage.co/query?"
        f"function=INSIDER_TRANSACTIONS"
        f"&symbol={ticker}"
        f"&apikey={alpha_vantage_key}"
    )

    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Error fetching data: {response.status_code} - {response.text}")

    data = response.json()
    if "Error Message" in data:
        raise Exception(f"Alpha Vantage API error: {data['Error Message']}")

    # Extract trades from Alpha Vantage response
    trades_data = data.get("transactions", [])
    
    # Transform Alpha Vantage data into our InsiderTrade model
    all_trades = []
    for trade in trades_data:
        # Get the transaction date and check if it's within our date range
        transaction_date = _parse_date(trade.get("transactionDate"))
        if transaction_date:
            if start_date and transaction_date < start_date:
                continue
            if transaction_date > end_date:
                continue

        # Calculate transaction value
        shares = _safe_float(trade.get("numberOfShares"))
        price = _safe_float(trade.get("transactionPrice"))
        value = shares * price if shares is not None and price is not None else None

        insider_trade = InsiderTrade(
            ticker=ticker,
            issuer=trade.get("issuerName"),
            name=trade.get("insiderName"),
            title=trade.get("insiderTitle"),
            is_board_director=_is_board_director(trade.get("insiderTitle")),
            transaction_date=transaction_date,
            transaction_shares=shares,
            transaction_price_per_share=price,
            transaction_value=value,
            shares_owned_before_transaction=_safe_float(trade.get("sharesOwnedBeforeTransaction")),
            shares_owned_after_transaction=_safe_float(trade.get("sharesOwnedAfterTransaction")),
            security_title=trade.get("securityType"),
            filing_date=_parse_date(trade.get("filingDate")) or end_date  # Fallback to end_date if no filing date
        )
        all_trades.append(insider_trade)

    # Sort trades by date (newest first) and apply limit
    all_trades.sort(key=lambda x: x.transaction_date or x.filing_date, reverse=True)
    all_trades = all_trades[:limit]

    if not all_trades:
        return []

    # Cache the results
    _cache.set_insider_trades(ticker, [trade.model_dump() for trade in all_trades])
    return all_trades

# *************************


def _parse_time_string(time_str: str) -> str:
    """Convert Alpha Vantage time format to our date format."""
    try:
        # Alpha Vantage uses a format like "20240130T0130"
        dt = datetime.strptime(time_str, "%Y%m%dT%H%M")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        try:
            # Fallback for other possible formats
            dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return time_str

def get_company_news(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
) -> list[CompanyNews]:
    """Fetch company news from Alpha Vantage API."""
    # Check cache first
    if cached_data := _cache.get_company_news(ticker):
        # Filter cached data by date range
        filtered_data = [CompanyNews(**news) for news in cached_data 
                        if (start_date is None or news["date"] >= start_date)
                        and news["date"] <= end_date]
        filtered_data.sort(key=lambda x: x.date, reverse=True)
        if filtered_data:
            return filtered_data

    # If not in cache, fetch from Alpha Vantage
    alpha_vantage_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not alpha_vantage_key:
        raise Exception("ALPHA_VANTAGE_API_KEY environment variable not set")

    all_news = []
    
    url = (
        f"https://www.alphavantage.co/query?"
        f"function=NEWS_SENTIMENT"
        f"&tickers={ticker}"
        f"&sort=LATEST"
        f"&limit=200"  # Max limit for Alpha Vantage
        f"&apikey={alpha_vantage_key}"
    )

    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Error fetching data: {response.status_code} - {response.text}")

    data = response.json()
    if "Error Message" in data:
        raise Exception(f"Alpha Vantage API error: {data['Error Message']}")

    feed = data.get("feed", [])
    if not feed:
        return []

    # Process each news item
    for item in feed:
        # Check if this news item mentions our ticker
        ticker_sentiments = item.get("ticker_sentiment", [])
        if not any(ts.get("ticker") == ticker for ts in ticker_sentiments):
            continue

        # Get the date and check if it's within our range
        news_date = _parse_time_string(item.get("time_published", ""))
        if start_date and news_date < start_date:
            continue
        if news_date > end_date:
            continue

        # Get the sentiment for our specific ticker
        ticker_sentiment = next(
            (ts.get("ticker_sentiment_score") 
             for ts in ticker_sentiments if ts.get("ticker") == ticker),
            None
        )
        
        # Convert sentiment score to label
        sentiment = None
        if ticker_sentiment is not None:
            score = float(ticker_sentiment)
            if score > 0.25:
                sentiment = "positive"
            elif score < -0.25:
                sentiment = "negative"
            else:
                sentiment = "neutral"

        # Safely get the author
        authors = item.get("authors", [])
        author = authors[0] if authors else "Unknown"

        news = CompanyNews(
            ticker=ticker,
            title=item.get("title", ""),
            author=author,
            source=item.get("source", ""),
            date=news_date,
            url=item.get("url", ""),
            sentiment=sentiment
        )
        all_news.append(news)

        # Check if we've reached our limit
        if len(all_news) >= limit:
            break

    if not all_news:
        return []

    # Sort by date (newest first)
    all_news.sort(key=lambda x: x.date, reverse=True)
    
    # Apply limit
    all_news = all_news[:limit]

    # Cache the results
    _cache.set_company_news(ticker, [news.model_dump() for news in all_news])
    return all_news


# *****************************

def get_market_cap(
    ticker: str,
    end_date: str,
) -> float | None:
    """Fetch market cap directly from Alpha Vantage OVERVIEW endpoint."""
    try:
        # Fetch directly from OVERVIEW endpoint since we only need market cap
        overview = _fetch_alpha_vantage_data("OVERVIEW", ticker)
        return _safe_float(overview.get('MarketCapitalization'))
    except Exception as e:
        return None


def prices_to_df(prices: list[Price]) -> pd.DataFrame:
    """Convert prices to a DataFrame."""
    df = pd.DataFrame([p.model_dump() for p in prices])
    df["Date"] = pd.to_datetime(df["time"])
    df.set_index("Date", inplace=True)
    numeric_cols = ["open", "close", "high", "low", "volume"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_index(inplace=True)
    return df


# Update the get_price_data function to use the new functions
def get_price_data(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    prices = get_prices(ticker, start_date, end_date)
    return prices_to_df(prices)


class FinancialMetrics(BaseModel):
    # Required base fields
    ticker: str
    calendar_date: str
    report_period: str
    period: str
    currency: str
    
    # Critical metrics used for direct decisions
    # Profitability metrics
    return_on_equity: float | None  # Used by Buffett & Fundamentals (>15%)
    net_margin: float | None  # Used by Fundamentals (>20%)
    operating_margin: float | None  # Used by Buffett & Fundamentals (>15%)
    
    # Growth metrics
    revenue_growth: float | None  # Used by Fundamentals (>10%)
    earnings_growth: float | None  # Used by Fundamentals & Valuation (>10%)
    book_value_growth: float | None  # Used by Fundamentals (>10%)
    
    # Valuation metrics
    price_to_earnings_ratio: float | None  # Used by Fundamentals (<25)
    price_to_book_ratio: float | None  # Used by Fundamentals (<3)
    price_to_sales_ratio: float | None  # Used by Fundamentals (<5)
    market_cap: float | None  # Used for various calculations
    
    # Health metrics
    current_ratio: float | None  # Used by Buffett & Fundamentals (>1.5)
    debt_to_equity: float | None  # Used by Buffett & Fundamentals (<0.5)
    free_cash_flow_per_share: float | None  # Used by Fundamentals
    earnings_per_share: float | None  # Used by Fundamentals
    
    # Additional metrics (not directly used but kept for completeness)
    enterprise_value: float | None
    enterprise_value_to_ebitda_ratio: float | None
    enterprise_value_to_revenue_ratio: float | None
    free_cash_flow_yield: float | None
    peg_ratio: float | None
    gross_margin: float | None
    return_on_assets: float | None
    return_on_invested_capital: float | None
    asset_turnover: float | None
    inventory_turnover: float | None
    receivables_turnover: float | None
    days_sales_outstanding: float | None
    operating_cycle: float | None
    working_capital_turnover: float | None
    quick_ratio: float | None
    cash_ratio: float | None
    operating_cash_flow_ratio: float | None
    debt_to_assets: float | None
    interest_coverage: float | None
    earnings_per_share_growth: float | None
    free_cash_flow_growth: float | None
    operating_income_growth: float | None
    ebitda_growth: float | None
    payout_ratio: float | None
    book_value_per_share: float | None

def get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
) -> list[FinancialMetrics]:
    """Fetch financial metrics from cache or Alpha Vantage API."""
    # Check cache first
    if cached_data := _cache.get_financial_metrics(ticker):
        filtered_data = [FinancialMetrics(**metric) for metric in cached_data if metric["report_period"] <= end_date]
        filtered_data.sort(key=lambda x: x.report_period, reverse=True)
        if filtered_data:
            return filtered_data[:limit]

    # If not in cache, fetch from Alpha Vantage
    alpha_vantage_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    if not alpha_vantage_key:
        raise Exception("ALPHA_VANTAGE_API_KEY environment variable not set")

    # Fetch required data from multiple Alpha Vantage endpoints
    try:
        overview = _fetch_alpha_vantage_data("OVERVIEW", ticker)
        income = _fetch_alpha_vantage_data("INCOME_STATEMENT", ticker)
        balance = _fetch_alpha_vantage_data("BALANCE_SHEET", ticker)
        cashflow = _fetch_alpha_vantage_data("CASH_FLOW", ticker)
    except Exception as e:
        raise Exception(f"Error fetching data from Alpha Vantage: {str(e)}")

    # Process the data into our required format
    metrics_list = []
    report_key = "annualReports" if period == "annual" else "quarterlyReports"
    
    # Get reports and ensure they're sorted by date
    reports = income.get(report_key, [])
    reports.sort(key=lambda x: x['fiscalDateEnding'], reverse=True)
    reports = reports[:limit]  # Limit the number of reports

    for i, report in enumerate(reports):
        report_date = report['fiscalDateEnding']
        if report_date > end_date:
            continue

        # Get matching balance sheet and cashflow data
        balance_sheet = next((b for b in balance.get(report_key, []) 
                            if b['fiscalDateEnding'] == report_date), {})
        cash_flow = next((c for c in cashflow.get(report_key, [])
                         if c['fiscalDateEnding'] == report_date), {})

        # Calculate base values needed for metrics
        total_revenue = _safe_float(report.get('totalRevenue'))
        net_income = _safe_float(report.get('netIncome'))
        total_assets = _safe_float(balance_sheet.get('totalAssets'))
        shareholder_equity = _safe_float(balance_sheet.get('totalShareholderEquity'))
        
        # Previous period for growth calculations
        prev_report = reports[i + 1] if i + 1 < len(reports) else None
        prev_balance = next((b for b in balance.get(report_key, [])
                           if prev_report and b['fiscalDateEnding'] == prev_report['fiscalDateEnding']), {})

        # Calculate critical metrics
        metrics = FinancialMetrics(
            ticker=ticker,
            calendar_date=report_date,
            report_period=report_date,
            period=period,
            currency="USD",  # Alpha Vantage reports in USD

            # Profitability metrics
            return_on_equity=_calculate_ratio(net_income, shareholder_equity),
            net_margin=_calculate_ratio(net_income, total_revenue),
            operating_margin=_calculate_ratio(_safe_float(report.get('operatingIncome')), total_revenue),

            # Growth metrics
            revenue_growth=_calculate_growth(
                total_revenue,
                _safe_float(prev_report.get('totalRevenue')) if prev_report else None
            ),
            earnings_growth=_calculate_growth(
                net_income,
                _safe_float(prev_report.get('netIncome')) if prev_report else None
            ),
            book_value_growth=_calculate_growth(
                shareholder_equity,
                _safe_float(prev_balance.get('totalShareholderEquity')) if prev_balance else None
            ),

            # Valuation metrics
            market_cap=_safe_float(overview.get('MarketCapitalization')),
            price_to_earnings_ratio=_safe_float(overview.get('PERatio')),
            price_to_book_ratio=_safe_float(overview.get('PriceToBookRatio')),
            price_to_sales_ratio=_safe_float(overview.get('PriceToSalesRatioTTM')),

            # Health metrics
            current_ratio=_calculate_ratio(
                _safe_float(balance_sheet.get('totalCurrentAssets')),
                _safe_float(balance_sheet.get('totalCurrentLiabilities'))
            ),
            debt_to_equity=_calculate_ratio(
                _safe_float(balance_sheet.get('totalLiabilities')),
                shareholder_equity
            ),
            earnings_per_share=_safe_float(report.get('reportedEPS')),
            free_cash_flow_per_share=_calculate_fcf_per_share(
                cash_flow.get('operatingCashflow'),
                cash_flow.get('capitalExpenditures'),
                report.get('commonStockSharesOutstanding')
            ),

            # Set remaining fields to None as they're not critical
            enterprise_value=None,
            enterprise_value_to_ebitda_ratio=None,
            enterprise_value_to_revenue_ratio=None,
            free_cash_flow_yield=None,
            peg_ratio=None,
            gross_margin=None,
            return_on_assets=None,
            return_on_invested_capital=None,
            asset_turnover=None,
            inventory_turnover=None,
            receivables_turnover=None,
            days_sales_outstanding=None,
            operating_cycle=None,
            working_capital_turnover=None,
            quick_ratio=None,
            cash_ratio=None,
            operating_cash_flow_ratio=None,
            debt_to_assets=None,
            interest_coverage=None,
            earnings_per_share_growth=None,
            free_cash_flow_growth=None,
            operating_income_growth=None,
            ebitda_growth=None,
            payout_ratio=None,
            book_value_per_share=None
        )
        metrics_list.append(metrics)

    if not metrics_list:
        return []

    # Cache the results
    _cache.set_financial_metrics(ticker, [m.model_dump() for m in metrics_list])
    return metrics_list

def _fetch_alpha_vantage_data(endpoint: str, ticker: str) -> Dict[str, Any]:
    """Helper function to fetch data from Alpha Vantage API."""
    url = (
        f"https://www.alphavantage.co/query?"
        f"function={endpoint}"
        f"&symbol={ticker}"
        f"&apikey={os.environ['ALPHA_VANTAGE_API_KEY']}"
    )
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Error fetching data: {response.status_code} - {response.text}")

    data = response.json()
    if "Error Message" in data:
        raise Exception(f"Alpha Vantage API error: {data['Error Message']}")
    return data

def _safe_float(value: Any) -> float | None:
    """Safely convert value to float, returning None if conversion fails."""
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None

def _calculate_ratio(numerator: float | None, denominator: float | None) -> float | None:
    """Safely calculate ratio between two numbers."""
    if numerator is not None and denominator is not None and denominator != 0:
        return numerator / denominator
    return None

def _calculate_growth(current: float | None, previous: float | None) -> float | None:
    """Calculate growth rate between two periods."""
    if current is not None and previous is not None and previous != 0:
        return (current - previous) / abs(previous)
    return None

def _calculate_fcf_per_share(
    operating_cash_flow: Any,
    capital_expenditures: Any,
    shares_outstanding: Any
) -> float | None:
    """Calculate free cash flow per share."""
    ocf = _safe_float(operating_cash_flow)
    capex = _safe_float(capital_expenditures)
    shares = _safe_float(shares_outstanding)
    
    if all(v is not None for v in [ocf, capex, shares]) and shares != 0:
        return (ocf - capex) / shares
    return None