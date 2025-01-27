from langchain_openai import ChatOpenAI
from graph.state import AgentState, show_agent_reasoning
from tools.api import (
    get_financial_metrics,
    get_market_cap,
    search_line_items
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
import json
from typing_extensions import Literal
from utils.progress import progress


class BuffettSignal(BaseModel):
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float
    reasoning: str

def warren_buffett_agent(state: AgentState):
    """Analyzes stocks using Buffett's principles and LLM reasoning."""
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    
    # Collect all analysis for LLM reasoning
    analysis_data = {}
    buffett_analysis = {}
    
    for ticker in tickers:
        progress.update_status("warren_buffett_agent", ticker, "Fetching financial metrics")
        # Fetch required data
        metrics = get_financial_metrics(ticker, end_date, period="ttm", limit=5)
        
        progress.update_status("warren_buffett_agent", ticker, "Gathering financial line items")
        financial_line_items = search_line_items(
            ticker,
            [
                "capital_expenditure", 
                "depreciation_and_amortization", 
                "net_income",
                "outstanding_shares",
                "total_assets", 
                "total_liabilities", 
            ],
            end_date,
            period="ttm",
            limit=5
        )
        
        progress.update_status("warren_buffett_agent", ticker, "Getting market cap")
        # Get current market cap
        market_cap = get_market_cap(ticker, end_date)
        
        progress.update_status("warren_buffett_agent", ticker, "Analyzing fundamentals")
        # Analyze fundamentals
        fundamental_analysis = analyze_fundamentals(metrics)
        
        progress.update_status("warren_buffett_agent", ticker, "Analyzing consistency")
        consistency_analysis = analyze_consistency(financial_line_items)
        
        progress.update_status("warren_buffett_agent", ticker, "Calculating intrinsic value")
        intrinsic_value_analysis = calculate_intrinsic_value(financial_line_items)
        
        # Calculate total score
        total_score = fundamental_analysis["score"] + consistency_analysis["score"]
        max_possible_score = 10
        
        # Add margin of safety analysis if we have both intrinsic value and current price
        margin_of_safety = None
        intrinsic_value = intrinsic_value_analysis["intrinsic_value"]
        if intrinsic_value and market_cap:
            margin_of_safety = (intrinsic_value - market_cap) / market_cap
            
            # Add to score if there's a good margin of safety (>30%)
            if margin_of_safety > 0.3:
                total_score += 2
                max_possible_score += 2
        
        # Generate trading signal
        if total_score >= 0.7 * max_possible_score:
            signal = "bullish"
        elif total_score <= 0.3 * max_possible_score:
            signal = "bearish"
        else:
            signal = "neutral"
        
        # Combine all analysis results
        analysis_data[ticker] = {
            "signal": signal,
            "score": total_score,
            "max_score": max_possible_score,
            "fundamental_analysis": fundamental_analysis,
            "consistency_analysis": consistency_analysis,
            "intrinsic_value_analysis": intrinsic_value_analysis,
            "market_cap": market_cap,
            "margin_of_safety": margin_of_safety
        }

        progress.update_status("warren_buffett_agent", ticker, "Generating Buffett analysis")
        buffett_output = generate_buffett_output(ticker, analysis_data)
        
        # Store analysis in consistent format with other agents
        buffett_analysis[ticker] = {
            "signal": buffett_output.signal,
            "confidence": buffett_output.confidence,
            "reasoning": buffett_output.reasoning,
        }
        
        progress.update_status("warren_buffett_agent", ticker, "Done")

    # Create the message
    message = HumanMessage(
        content=json.dumps(buffett_analysis),
        name="warren_buffett_agent"
    )

    # Show reasoning if requested
    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(buffett_analysis, "Warren Buffett Agent")

    # Add the signal to the analyst_signals list
    state["data"]["analyst_signals"]["warren_buffett_agent"] = buffett_analysis

    return {
        "messages": [message],
        "data": state["data"]
    }

def analyze_fundamentals(metrics: list) -> dict[str, any]:
    """Analyze company fundamentals based on Buffett's criteria."""
    if not metrics:
        return {"score": 0, "details": "Insufficient fundamental data"}
    
    latest_metrics = metrics[0]
    
    score = 0
    reasoning = []
    
    # Check ROE (Return on Equity)
    if latest_metrics.return_on_equity and latest_metrics.return_on_equity > 0.15:  # 15% ROE threshold
        score += 2
        reasoning.append(f"Strong ROE of {latest_metrics.return_on_equity:.1%}")
    elif latest_metrics.return_on_equity:
        reasoning.append(f"Weak ROE of {latest_metrics.return_on_equity:.1%}")
    else:
        reasoning.append("ROE data not available")
    
    # Check Debt to Equity
    if latest_metrics.debt_to_equity and latest_metrics.debt_to_equity < 0.5:
        score += 2
        reasoning.append("Conservative debt levels")
    elif latest_metrics.debt_to_equity:
        reasoning.append(f"High debt to equity ratio of {latest_metrics.debt_to_equity:.1f}")
    else:
        reasoning.append("Debt to equity data not available")
    
    # Check Operating Margin
    if latest_metrics.operating_margin and latest_metrics.operating_margin > 0.15:
        score += 2
        reasoning.append("Strong operating margins")
    elif latest_metrics.operating_margin:
        reasoning.append(f"Weak operating margin of {latest_metrics.operating_margin:.1%}")
    else:
        reasoning.append("Operating margin data not available")
    
    # Check Current Ratio
    if latest_metrics.current_ratio and latest_metrics.current_ratio > 1.5:
        score += 1
        reasoning.append("Good liquidity position")
    elif latest_metrics.current_ratio:
        reasoning.append(f"Weak liquidity with current ratio of {latest_metrics.current_ratio:.1f}")
    else:
        reasoning.append("Current ratio data not available")
    
    return {
        "score": score,
        "details": "; ".join(reasoning),
        "metrics": latest_metrics.model_dump()
    }


def analyze_consistency(financial_line_items: list) -> dict[str, any]:
    """Analyze earnings consistency and growth."""
    if len(financial_line_items) < 4:  # Need at least 4 periods for trend analysis
        return {"score": 0, "details": "Insufficient historical data"}
    
    score = 0
    reasoning = []
    
    # Check earnings growth trend
    earnings_values = [item.net_income for item in financial_line_items if item.net_income]
    if len(earnings_values) >= 4:
        earnings_growth = all(
            earnings_values[i] > earnings_values[i+1]
            for i in range(len(earnings_values)-1)
        )
        
        if earnings_growth:
            score += 3
            reasoning.append("Consistent earnings growth over past periods")
        else:
            reasoning.append("Inconsistent earnings growth pattern")
            
        # Calculate growth rate
        if len(earnings_values) >= 2:
            growth_rate = (earnings_values[0] - earnings_values[-1]) / abs(earnings_values[-1])
            reasoning.append(f"Total earnings growth of {growth_rate:.1%} over past {len(earnings_values)} periods")
    else:
        reasoning.append("Insufficient earnings data for trend analysis")
    
    return {
        "score": score,
        "details": "; ".join(reasoning),
    }


def calculate_owner_earnings(financial_line_items: list) -> dict[str, any]:
    """Calculate owner earnings (Buffett's preferred measure of true earnings power).
    Owner Earnings = Net Income + Depreciation - Maintenance CapEx"""
    if not financial_line_items or len(financial_line_items) < 1:
        return {"owner_earnings": None, "details": ["Insufficient data for owner earnings calculation"]}
    
    latest = financial_line_items[0]
    
    # Get required components
    net_income = latest.net_income
    depreciation = latest.depreciation_and_amortization
    capex = latest.capital_expenditure
    
    if not all([net_income, depreciation, capex]):
        return {"owner_earnings": None, "details": ["Missing components for owner earnings calculation"]}
    
    # Estimate maintenance capex (typically 70-80% of total capex)
    maintenance_capex = capex * 0.75
    
    owner_earnings = net_income + depreciation - maintenance_capex
    
    return {
        "owner_earnings": owner_earnings,
        "components": {
            "net_income": net_income,
            "depreciation": depreciation,
            "maintenance_capex": maintenance_capex
        },
        "details": ["Owner earnings calculated successfully"]
    }


def calculate_intrinsic_value(financial_line_items: list) -> dict[str, any]:
    """Calculate intrinsic value using DCF with owner earnings."""
    if not financial_line_items:
        return {"intrinsic_value": None, "details": ["Insufficient data for valuation"]}
    
    earnings_data = calculate_owner_earnings(financial_line_items)
    if not earnings_data["owner_earnings"]:
        return {"intrinsic_value": None, "details": earnings_data["details"]}
    
    owner_earnings = earnings_data["owner_earnings"]
    
    # Buffett's DCF assumptions
    growth_rate = 0.05  
    discount_rate = 0.09
    terminal_multiple = 12
    projection_years = 10
    
    # Calculate future value
    future_value = 0
    for year in range(1, projection_years + 1):
        future_earnings = owner_earnings * (1 + growth_rate) ** year
        present_value = future_earnings / (1 + discount_rate) ** year
        future_value += present_value
    
    # Add terminal value
    terminal_value = (owner_earnings * (1 + growth_rate) ** projection_years * terminal_multiple) / (1 + discount_rate) ** projection_years
    intrinsic_value = future_value + terminal_value
    
    return {
        "intrinsic_value": intrinsic_value,
        "owner_earnings": owner_earnings,
        "assumptions": {
            "growth_rate": growth_rate,
            "discount_rate": discount_rate,
            "terminal_multiple": terminal_multiple,
            "projection_years": projection_years
        },
        "details": ["Intrinsic value calculated using DCF model with owner earnings"]
    }

def generate_buffett_output(ticker: str, analysis_data: dict[str, any]) -> BuffettSignal:
    """Get investment decision from LLM with Buffett's principles"""
    template = ChatPromptTemplate.from_messages([
        (
            "system",
            """You are a Warren Buffett AI agent, making investment decisions using his principles:

            1. Circle of Competence: Only invest in understandable businesses
            2. Margin of Safety: Buy well below intrinsic value
            3. Economic Moat: Look for competitive advantages
            4. Quality Management: Conservative, shareholder-oriented
            5. Financial Strength: Low debt, high returns on equity
            6. Long-term Perspective: Invest in businesses, not stocks
            
            Rules:
            - Only buy when there's a significant margin of safety (>30%)
            - Focus on owner earnings and intrinsic value
            - Prefer companies with consistent earnings growth
            - Avoid companies with high debt or poor management
            - Hold good businesses for very long periods
            - Sell when fundamentals deteriorate or valuation becomes excessive"""
        ),
        (
            "human",
            """Based on the following analysis, create investment signals as Warren Buffett would.

            Analysis Data for {ticker}:
            {analysis_data}

            Return signals for this ticker in this format:
            {{
                "signal": "bullish/bearish/neutral",
                "confidence": float (0-100),
                "reasoning": "Buffett-style explanation"
            }}"""
        )
    ])

    # Generate the prompt
    prompt = template.invoke({
        "analysis_data": json.dumps(analysis_data, indent=2),
        "ticker": ticker
    })


    llm = ChatOpenAI(model="gpt-4o").with_structured_output(
        BuffettSignal,
        method="function_calling",
    )

    max_retries = 3
    for attempt in range(max_retries):
        try:
            result = llm.invoke(prompt)
            return result
        except Exception as e:
            if attempt == max_retries - 1:
                # On final attempt, return a safe default
                return BuffettSignal(
                    signal="hold",
                    confidence=0.0,
                    reasoning="Error in analysis, defaulting to hold"
                )
