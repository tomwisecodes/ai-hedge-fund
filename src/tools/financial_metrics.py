import os
import requests
from typing import Dict, Any, List
from datetime import datetime
from pydantic import BaseModel
from data.cache import get_cache

# Global cache instance
_cache = get_cache()

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