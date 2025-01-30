import os
import pandas as pd
import requests

from data.cache import get_cache
from data.models import (
    CompanyNews,
    FinancialMetrics,
    Price,
    LineItem,
    InsiderTrade,
)

# Global cache instance
_cache = get_cache()


def get_prices(ticker: str, start_date: str, end_date: str) -> list[Price]:
    """Fetch price data from cache or API."""
    # Check cache first
    if cached_data := _cache.get_prices(ticker):
        filtered_data = [Price(**price) for price in cached_data if start_date <= price["time"] <= end_date]
        if filtered_data:
            return filtered_data

    # If not in cache or no data in range, fetch from Alpha Vantage
    if not (api_key := os.environ.get("ALPHA_VANTAGE_API_KEY")):
        raise Exception("ALPHA_VANTAGE_API_KEY not found in environment variables")

    url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={ticker}&outputsize=full&apikey={api_key}"
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Error fetching data: {response.status_code} - {response.text}")

    data = response.json()
    print("API Response Keys:", data.keys())  # Debug print
    
    if "Time Series (Daily)" not in data:
        print("Full API Response:", data)  # Debug print
        if "Note" in data:
            raise Exception(f"Alpha Vantage API limit message: {data['Note']}")
        if "Error Message" in data:
            raise Exception(f"Alpha Vantage error: {data['Error Message']}")
        return []

    time_series = data["Time Series (Daily)"]
    print(f"First date in data: {list(time_series.keys())[0]}")  # Debug print
    print(f"Date range requested: {start_date} to {end_date}")  # Debug print

    # Transform Alpha Vantage data to match our Price model
    prices = []
    for date, values in time_series.items():
        if start_date <= date <= end_date:
            try:
                price = Price(
                    open=float(values["1. open"]),
                    close=float(values["4. close"]),
                    high=float(values["2. high"]),
                    low=float(values["3. low"]),
                    volume=int(float(values["5. volume"])),
                    time=date
                )
                prices.append(price)
            except (KeyError, ValueError) as e:
                print(f"Error processing data for {date}: {e}")  # Debug print
                print(f"Values: {values}")  # Debug print
                continue

    print(f"Found {len(prices)} prices in date range")  # Debug print

    if not prices:
        return []

    # Sort prices by date (newest first)
    prices.sort(key=lambda x: x.time, reverse=True)

    # Cache the results as dicts
    _cache.set_prices(ticker, [p.model_dump() for p in prices])
    return prices


def calculate_growth_rate(current: float | None, previous: float | None) -> float | None:
    """Calculate year-over-year growth rate."""
    if current and previous and previous != 0:
        return ((current - previous) / abs(previous)) * 100
    return None

def calculate_enterprise_value(market_cap: float | None, total_debt: float | None, cash_and_equivalents: float | None) -> float | None:
    """Calculate enterprise value."""
    if all(v is not None for v in [market_cap, total_debt, cash_and_equivalents]):
        return market_cap + total_debt - cash_and_equivalents
    return None

def safe_float(value) -> float | None:
    """Safely convert value to float, returning None if conversion fails."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
) -> list[FinancialMetrics]:
    """Fetch financial metrics from cache or API."""
    # Check cache first
    if cached_data := _cache.get_financial_metrics(ticker):
        filtered_data = [FinancialMetrics(**metric) for metric in cached_data if metric["report_period"] <= end_date]
        filtered_data.sort(key=lambda x: x.report_period, reverse=True)
        if filtered_data:
            return filtered_data[:limit]

    # If not in cache, fetch from Alpha Vantage
    if not (api_key := os.environ.get("ALPHA_VANTAGE_API_KEY")):
        raise Exception("ALPHA_VANTAGE_API_KEY not found in environment variables")

    # Fetch data from multiple endpoints
    endpoints = {
        "overview": f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={ticker}&apikey={api_key}",
        "income": f"https://www.alphavantage.co/query?function=INCOME_STATEMENT&symbol={ticker}&apikey={api_key}",
        "balance": f"https://www.alphavantage.co/query?function=BALANCE_SHEET&symbol={ticker}&apikey={api_key}",
        "cashflow": f"https://www.alphavantage.co/query?function=CASH_FLOW&symbol={ticker}&apikey={api_key}"
    }

    data = {}
    for name, url in endpoints.items():
        response = requests.get(url)
        if response.status_code != 200:
            raise Exception(f"Error fetching {name} data: {response.status_code} - {response.text}")
        data[name] = response.json()
        if "Error Message" in data[name]:
            raise Exception(f"Alpha Vantage API error for {name}: {data[name]['Error Message']}")

    # Helper functions (calculate_growth_rate and calculate_enterprise_value remain the same)
    
    # Transform the data into our FinancialMetrics format
    financial_metrics = []
    overview = data["overview"]
    
    # Get the dates from income statement as our base timeline
    income_dates = [report["fiscalDateEnding"] for report in data["income"].get("annualReports", [])]
    income_dates.sort(reverse=True)
    
    # Get the dates from income statement as our base timeline
    income_dates = [report["fiscalDateEnding"] for report in data["income"].get("annualReports", [])]
    income_dates.sort(reverse=True)
    
    for i, date in enumerate(income_dates[:limit]):
        # Find corresponding reports for this date
        income_report = next((r for r in data["income"].get("annualReports", []) 
                            if r["fiscalDateEnding"] == date), {})
        balance_report = next((r for r in data["balance"].get("annualReports", []) 
                            if r["fiscalDateEnding"] == date), {})
        cashflow_report = next((r for r in data["cashflow"].get("annualReports", []) 
                            if r["fiscalDateEnding"] == date), {})
        
        # Get previous year's reports for growth calculations
        prev_income_report = {} if i >= len(income_dates)-1 else next((r for r in data["income"].get("annualReports", []) 
                                                                      if r["fiscalDateEnding"] == income_dates[i+1]), {})
        prev_balance_report = {} if i >= len(income_dates)-1 else next((r for r in data["balance"].get("annualReports", []) 
                                                                       if r["fiscalDateEnding"] == income_dates[i+1]), {})
        prev_cashflow_report = {} if i >= len(income_dates)-1 else next((r for r in data["cashflow"].get("annualReports", []) 
                                                                        if r["fiscalDateEnding"] == income_dates[i+1]), {})

        if date > end_date:
            continue

        # Calculate base metrics
        total_assets = float(balance_report.get("totalAssets", 0)) or None
        total_revenue = float(income_report.get("totalRevenue", 0)) or None
        net_income = float(income_report.get("netIncome", 0)) or None
        total_current_assets = float(balance_report.get("totalCurrentAssets", 0)) or None
        total_current_liabilities = float(balance_report.get("totalCurrentLiabilities", 0)) or None
        inventory = float(balance_report.get("inventory", 0)) or None
        cash_and_equivalents = float(balance_report.get("cashAndCashEquivalentsAtCarryingValue", 0)) or None
        accounts_receivable = float(balance_report.get("currentNetReceivables", 0)) or None
        operating_income = float(income_report.get("operatingIncome", 0)) or None
        interest_expense = float(income_report.get("interestExpense", 0)) or None
        total_debt = (float(balance_report.get("shortTermDebt", 0)) or 0) + (float(balance_report.get("longTermDebt", 0)) or 0)
        operating_cashflow = float(cashflow_report.get("operatingCashflow", 0)) or None
        capital_expenditure = float(cashflow_report.get("capitalExpenditures", 0)) or None
        
        # Calculate derived metrics
        free_cash_flow = (operating_cashflow + capital_expenditure) if operating_cashflow and capital_expenditure else None
        working_capital = (total_current_assets - total_current_liabilities) if total_current_assets and total_current_liabilities else None
        market_cap = float(overview.get("MarketCapitalization")) if date == income_dates[0] else None
        enterprise_value = calculate_enterprise_value(market_cap, total_debt, cash_and_equivalents)
        
        # Previous year values for growth calculations
        prev_total_revenue = float(prev_income_report.get("totalRevenue", 0)) or None
        prev_net_income = float(prev_income_report.get("netIncome", 0)) or None
        prev_book_value = float(prev_balance_report.get("totalShareholderEquity", 0)) or None
        prev_operating_income = float(prev_income_report.get("operatingIncome", 0)) or None
        prev_free_cash_flow = ((float(prev_cashflow_report.get("operatingCashflow", 0)) or 0) + 
                              (float(prev_cashflow_report.get("capitalExpenditures", 0)) or 0)) or None

        metric = FinancialMetrics(
             ticker=ticker,
            calendar_date=date,
            report_period=date,
            period=period,
            currency="USD",
            market_cap=market_cap,
            enterprise_value=enterprise_value,
            price_to_earnings_ratio=safe_float(overview.get("PERatio")) if date == income_dates[0] else None,
            price_to_book_ratio=safe_float(overview.get("PriceToBookRatio")) if date == income_dates[0] else None,
            price_to_sales_ratio=safe_float(overview.get("PriceToSalesRatio")) if date == income_dates[0] else None,
            enterprise_value_to_ebitda_ratio=(enterprise_value / operating_income if enterprise_value and operating_income else None),
            enterprise_value_to_revenue_ratio=(enterprise_value / total_revenue if enterprise_value and total_revenue else None),
            free_cash_flow_yield=(free_cash_flow / market_cap if free_cash_flow and market_cap else None),
            peg_ratio=safe_float(overview.get("PEGRatio")) if date == income_dates[0] else None,
            gross_margin=(float(income_report.get("grossProfit", 0)) / total_revenue if total_revenue else None),
            operating_margin=(operating_income / total_revenue if operating_income and total_revenue else None),
            net_margin=(net_income / total_revenue if net_income and total_revenue else None),
            return_on_equity=float(overview.get("ReturnOnEquityTTM")) if date == income_dates[0] else None,
            return_on_assets=(net_income / total_assets if net_income and total_assets else None),
            return_on_invested_capital=(operating_income * (1 - 0.21)) / (total_assets - total_current_liabilities) 
                                     if operating_income and total_assets and total_current_liabilities else None,
            asset_turnover=(total_revenue / total_assets if total_revenue and total_assets else None),
            inventory_turnover=(total_revenue / inventory if total_revenue and inventory else None),
            receivables_turnover=(total_revenue / accounts_receivable if total_revenue and accounts_receivable else None),
            days_sales_outstanding=(accounts_receivable / (total_revenue / 365) if accounts_receivable and total_revenue else None),
            operating_cycle=(365 / (total_revenue / inventory) + 365 / (total_revenue / accounts_receivable) 
                           if total_revenue and inventory and accounts_receivable else None),
            working_capital_turnover=(total_revenue / working_capital if total_revenue and working_capital else None),
            current_ratio=(total_current_assets / total_current_liabilities 
                         if total_current_assets and total_current_liabilities else None),
            quick_ratio=((total_current_assets - inventory) / total_current_liabilities 
                        if total_current_assets and inventory and total_current_liabilities else None),
            cash_ratio=(cash_and_equivalents / total_current_liabilities 
                       if cash_and_equivalents and total_current_liabilities else None),
            operating_cash_flow_ratio=(operating_cashflow / total_current_liabilities 
                                     if operating_cashflow and total_current_liabilities else None),
            debt_to_equity=safe_float(overview.get("DebtToEquityRatio")) if date == income_dates[0] else None,
            debt_to_assets=(total_debt / total_assets if total_debt and total_assets else None),
            interest_coverage=(operating_income / interest_expense if operating_income and interest_expense else None),
            revenue_growth=calculate_growth_rate(total_revenue, prev_total_revenue),
            earnings_growth=calculate_growth_rate(net_income, prev_net_income),
            book_value_growth=calculate_growth_rate(
                float(balance_report.get("totalShareholderEquity", 0)) or None,
                prev_book_value
            ),
            earnings_per_share_growth=calculate_growth_rate(
                float(income_report.get("earningsPerShare", 0)) or None,
                float(prev_income_report.get("earningsPerShare", 0)) or None
            ),
            free_cash_flow_growth=calculate_growth_rate(free_cash_flow, prev_free_cash_flow),
            operating_income_growth=calculate_growth_rate(operating_income, prev_operating_income),
            ebitda_growth=calculate_growth_rate(operating_income, prev_operating_income),  # Using operating income as proxy
            payout_ratio=safe_float(overview.get("PayoutRatio")) if date == income_dates[0] else None,
            earnings_per_share=float(income_report.get("earningsPerShare")) if income_report.get("earningsPerShare") else None,
            book_value_per_share=(float(balance_report.get("totalShareholderEquity", 0)) / 
                                float(balance_report.get("commonSharesOutstanding", 1)) 
                                if balance_report.get("totalShareholderEquity") and 
                                balance_report.get("commonSharesOutstanding") else None),
            free_cash_flow_per_share=(free_cash_flow / float(balance_report.get("commonSharesOutstanding", 1))
                                    if free_cash_flow and balance_report.get("commonSharesOutstanding") else None)
        )
        financial_metrics.append(metric)

    if not financial_metrics:
        return []

    # Cache the results
    _cache.set_financial_metrics(ticker, [m.model_dump() for m in financial_metrics])
    return financial_metrics


def search_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
) -> list[LineItem]:
    """Fetch line items from Alpha Vantage API."""
    if not (api_key := os.environ.get("ALPHA_VANTAGE_API_KEY")):
        raise Exception("ALPHA_VANTAGE_API_KEY not found in environment variables")

    # Map standard line items to their location in Alpha Vantage endpoints and calculations
    line_item_map = {
        # Income Statement items
        "net_income": ("INCOME_STATEMENT", "netIncome"),
        "depreciation_and_amortization": ("INCOME_STATEMENT", "depreciationAndAmortization"),
        "capital_expenditure": ("CASH_FLOW", "capitalExpenditures"),
        "free_cash_flow": ("CASH_FLOW", "operatingCashflow"),  # Will need to adjust with capex
        "working_capital": ("BALANCE_SHEET", ["totalCurrentAssets", "totalCurrentLiabilities"]),  # Will need calculation
    }

    # Determine which endpoints we need based on requested line items
    needed_endpoints = set()
    for item in line_items:
        if item in line_item_map:
            endpoint, _ = line_item_map[item]
            needed_endpoints.add(endpoint)

    # Endpoint to URL mapping
    endpoint_urls = {
        "INCOME_STATEMENT": f"https://www.alphavantage.co/query?function=INCOME_STATEMENT&symbol={ticker}&apikey={api_key}",
        "BALANCE_SHEET": f"https://www.alphavantage.co/query?function=BALANCE_SHEET&symbol={ticker}&apikey={api_key}",
        "CASH_FLOW": f"https://www.alphavantage.co/query?function=CASH_FLOW&symbol={ticker}&apikey={api_key}"
    }

    # Fetch required data
    data = {}
    for endpoint in needed_endpoints:
        response = requests.get(endpoint_urls[endpoint])
        if response.status_code != 200:
            raise Exception(f"Error fetching {endpoint} data: {response.status_code} - {response.text}")
        data[endpoint] = response.json()

    # Get all available dates from the first endpoint's data
    report_type = "annualReports" if period != "quarterly" else "quarterlyReports"
    first_endpoint = next(iter(data.values()))
    dates = [report["fiscalDateEnding"] for report in first_endpoint.get(report_type, [])]
    dates.sort(reverse=True)
    dates = [d for d in dates if d <= end_date][:limit]

    results = []
    for date in dates:
        line_item = LineItem(
            ticker=ticker,
            report_period=date,
            period=period,
            currency="USD"
        )

        # Add requested line items
        for item in line_items:
            if item in line_item_map:
                endpoint, field = line_item_map[item]
                reports = data[endpoint].get(report_type, [])
                report = next((r for r in reports if r["fiscalDateEnding"] == date), {})
                
                # Handle special calculations
                if item == "working_capital":
                    current_assets = safe_float(report.get("totalCurrentAssets", 0))
                    current_liabilities = safe_float(report.get("totalCurrentLiabilities", 0))
                    if current_assets is not None and current_liabilities is not None:
                        value = current_assets - current_liabilities
                    else:
                        value = None
                elif item == "free_cash_flow":
                    operating_cash = safe_float(report.get("operatingCashflow", 0))
                    capex = safe_float(report.get("capitalExpenditures", 0))
                    if operating_cash is not None and capex is not None:
                        value = operating_cash + capex  # capex is typically negative
                    else:
                        value = None
                else:
                    value = safe_float(report.get(field, 0))
                
                setattr(line_item, item, value)

        results.append(line_item)

    return results


def get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
) -> list[InsiderTrade]:
    """Fetch insider trades from cache or API."""
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
    if not (api_key := os.environ.get("ALPHA_VANTAGE_API_KEY")):
        raise Exception("ALPHA_VANTAGE_API_KEY not found in environment variables")

    url = f"https://www.alphavantage.co/query?function=INSIDER_TRANSACTIONS&symbol={ticker}&apikey={api_key}"
    response = requests.get(url)
    
    if response.status_code != 200:
        raise Exception(f"Error fetching insider trades: {response.status_code} - {response.text}")

    data = response.json()
    if "trades" not in data:
        return []

    all_trades = []
    for trade in data["trades"]:
        # Skip if outside date range
        trade_date = trade.get("transactionDate", "").split(" ")[0]
        if (start_date and trade_date < start_date) or trade_date > end_date:
            continue

        # Map Alpha Vantage data to our InsiderTrade model
        insider_trade = InsiderTrade(
            ticker=ticker,
            issuer=trade.get("companyName"),
            name=trade.get("insiderName"),
            title=trade.get("insiderTitle"),
            is_board_director="director" in (trade.get("insiderTitle", "").lower() or ""),
            transaction_date=trade_date,
            transaction_shares=float(trade.get("transactionShares", 0)) or None,
            transaction_price_per_share=float(trade.get("transactionPrice", 0)) or None,
            transaction_value=float(trade.get("transactionValue", 0)) or None,
            shares_owned_before_transaction=float(trade.get("sharesOwnedBeforeTransaction", 0)) or None,
            shares_owned_after_transaction=float(trade.get("sharesOwnedAfterTransaction", 0)) or None,
            security_title=trade.get("securityType"),
            filing_date=trade.get("filingDate", "").split(" ")[0]
        )
        all_trades.append(insider_trade)

        if len(all_trades) >= limit:
            break

    if not all_trades:
        return []

    # Sort trades by transaction date
    all_trades.sort(key=lambda x: x.transaction_date or x.filing_date, reverse=True)

    # Cache the results
    _cache.set_insider_trades(ticker, [trade.model_dump() for trade in all_trades])
    return all_trades




def get_company_news(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
) -> list[CompanyNews]:
    """Fetch company news from cache or API."""
    # Check cache first
    if cached_data := _cache.get_company_news(ticker):
        filtered_data = [CompanyNews(**news) for news in cached_data 
                        if (start_date is None or news["date"] >= start_date)
                        and news["date"] <= end_date]
        filtered_data.sort(key=lambda x: x.date, reverse=True)
        if filtered_data:
            return filtered_data

    # If not in cache, fetch from Alpha Vantage
    if not (api_key := os.environ.get("ALPHA_VANTAGE_API_KEY")):
        raise Exception("ALPHA_VANTAGE_API_KEY not found in environment variables")

    url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={ticker}&limit={limit}&apikey={api_key}"
    response = requests.get(url)
    
    if response.status_code != 200:
        raise Exception(f"Error fetching news: {response.status_code} - {response.text}")

    data = response.json()
    if "feed" not in data:
        return []

    all_news = []
    for article in data["feed"]:
        # Extract and format the date (AV uses ISO format)
        article_date = article.get("time_published", "")[:10]  # Get YYYY-MM-DD part
        
        # Skip if outside date range
        if (start_date and article_date < start_date) or article_date > end_date:
            continue

        # Map sentiment score to string
        sentiment_score = float(article.get("overall_sentiment_score", 0))
        if sentiment_score > 0.35:
            sentiment = "positive"
        elif sentiment_score < -0.35:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        news_item = CompanyNews(
            ticker=ticker,
            title=article.get("title", ""),
            author=article.get("authors", [None])[0],  # Get first author or None
            source=article.get("source", ""),
            date=article_date,
            url=article.get("url", ""),
            sentiment=sentiment
        )
        all_news.append(news_item)

        if len(all_news) >= limit:
            break

    if not all_news:
        return []

    # Sort by date
    all_news.sort(key=lambda x: x.date, reverse=True)

    # Cache the results
    _cache.set_company_news(ticker, [news.model_dump() for news in all_news])
    return all_news



def get_market_cap(
    ticker: str,
    end_date: str,
) -> float | None:
    """Fetch market cap from the API."""
    # Try to get it directly from Overview endpoint first (more efficient)
    if not (api_key := os.environ.get("ALPHA_VANTAGE_API_KEY")):
        raise Exception("ALPHA_VANTAGE_API_KEY not found in environment variables")

    url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={ticker}&apikey={api_key}"
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        if market_cap := safe_float(data.get("MarketCapitalization")):
            return market_cap

    # Fallback to financial metrics if Overview doesn't work
    financial_metrics = get_financial_metrics(ticker, end_date)
    if not financial_metrics:  # Handle empty list case
        return None
        
    market_cap = financial_metrics[0].market_cap
    return market_cap


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
