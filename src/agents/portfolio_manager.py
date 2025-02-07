import json
from typing import Optional
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from graph.state import AgentState, show_agent_reasoning
from pydantic import BaseModel, Field
from typing_extensions import Literal
from utils.progress import progress
from utils.llm import call_llm

class AlpacaOrder(BaseModel):
    symbol: str
    qty: int
    side: Literal["buy", "sell"]
    type: Literal["market", "limit"] = "market"
    time_in_force: Literal["day", "gtc"] = "day"
    limit_price: Optional[float] = None

class PortfolioDecision(BaseModel):
    action: Literal["buy", "sell", "hold"]
    quantity: int = Field(description="Number of shares to trade")
    confidence: float = Field(description="Confidence in the decision, between 0.0 and 100.0")
    reasoning: str = Field(description="Reasoning for the decision")
    order: Optional[AlpacaOrder] = None

class PortfolioManagerOutput(BaseModel):
    decisions: dict[str, PortfolioDecision] = Field(description="Dictionary of ticker to trading decisions")

def portfolio_management_agent(state: AgentState):
    """Makes final trading decisions and generates orders for multiple tickers"""
    portfolio = state["data"]["portfolio"]
    analyst_signals = state["data"]["analyst_signals"]
    tickers = state["data"]["tickers"]
    execute_trades = state["data"].get("execute_trades", False)
    


    progress.update_status("portfolio_management_agent", None, "Analyzing signals")

    position_limits = {}
    current_prices = {}
    max_shares = {}
    signals_by_ticker = {}
    
    for ticker in tickers:
        progress.update_status("portfolio_management_agent", ticker, "Processing analyst signals")
        risk_data = analyst_signals.get("risk_management_agent", {}).get(ticker, {})
        position_limits[ticker] = risk_data.get("remaining_position_limit", 0)
        current_prices[ticker] = risk_data.get("current_price", 0)

        if current_prices[ticker] > 0:
            max_shares[ticker] = int(position_limits[ticker] / current_prices[ticker])
        else:
            max_shares[ticker] = 0

        ticker_signals = {}
        for agent, signals in analyst_signals.items():
            if agent != "risk_management_agent" and ticker in signals:
                ticker_signals[agent] = {
                    "signal": signals[ticker]["signal"], 
                    "confidence": signals[ticker]["confidence"]
                }
        signals_by_ticker[ticker] = ticker_signals

    progress.update_status("portfolio_management_agent", None, "Making trading decisions")

    result = generate_trading_decision(
        tickers=tickers,
        signals_by_ticker=signals_by_ticker,
        current_prices=current_prices,
        max_shares=max_shares,
        portfolio=portfolio,
        model_name=state["metadata"]["model_name"],
        model_provider=state["metadata"]["model_provider"],
        execute_trades=execute_trades
    )


    message = HumanMessage(
        content=json.dumps({ticker: decision.model_dump() for ticker, decision in result.decisions.items()}),
        name="portfolio_management",
    )

    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning({ticker: decision.model_dump() for ticker, decision in result.decisions.items()}, "Portfolio Management Agent")

    progress.update_status("portfolio_management_agent", None, "Done")

    decisions = result.decisions

    state["data"]["trading_decisions"] = decisions

    return {
        "messages": state["messages"] + [message],
        "data": state["data"],
        "metadata": state["metadata"]
    }

def generate_trading_decision(
    tickers: list[str],
    signals_by_ticker: dict[str, dict],
    current_prices: dict[str, float],
    max_shares: dict[str, int],
    portfolio: dict[str, float],
    model_name: str,
    model_provider: str,
    execute_trades: bool = False
) -> PortfolioManagerOutput:
    """Generates trading decisions with optional Alpaca orders, including short positions"""
    try:     
        template = ChatPromptTemplate.from_messages([
            (
                "system",
                """You are a portfolio manager making final trading decisions based on multiple tickers.

                Trading Rules:
                - Only execute buy orders if confidence > 60%
                - Only execute sell orders if confidence > 70%
                - For buys, scale position size with confidence:
                * 60-70%: Use 25% of max position size
                * 70-80%: Use 50% of max position size
                * 80-90%: Use 75% of max position size
                * >90%: Use full position size
                - Only buy if you have available cash
                - Only sell if you currently hold shares or to take a short position
                - Sell quantity must be ≤ current position shares (unless shorting)
                - Buy quantity must be ≤ max_shares for that ticker
                """ + ("""
                Live Trading Rules:
                - Use market orders for confidence >= 80%
                - Use limit orders for confidence < 80%
                - Set buy limits 1% below market
                - Set sell limits 1% above market
                """ if execute_trades else "")
            ),
            (
                "human",
                """Based on the team's analysis, make your trading decisions for each ticker.

                Here are the signals by ticker:
                {signals_by_ticker}

                Current Prices:
                {current_prices}

                Maximum Shares Allowed For Purchases:
                {max_shares}

                Portfolio Cash: {portfolio_cash}
                Current Positions: {portfolio_positions}

                Output strictly in JSON with the following structure:
                {{
                    "decisions": {{
                        "TICKER1": {{
                            "action": "buy/sell/hold",
                            "quantity": integer,
                            "confidence": float,
                            "reasoning": "string"
                        }}
                    }}
                }}
                """
            )
        ])

        prompt = template.invoke({
            "signals_by_ticker": json.dumps(signals_by_ticker, indent=2),
            "current_prices": json.dumps(current_prices, indent=2),
            "max_shares": json.dumps(max_shares, indent=2),
            "portfolio_cash": f"{portfolio['cash']:.2f}",
            "portfolio_positions": json.dumps(portfolio["positions"], indent=2)
        })

        result = call_llm(
            prompt=prompt,
            model_name=model_name,
            model_provider=model_provider,
            pydantic_model=PortfolioManagerOutput,
            agent_name="portfolio_management_agent"
        )

        for ticker, decision in result.decisions.items():
            current_position = portfolio["positions"].get(ticker, 0)

            # Handle position closures
            if current_position > 0:
                if decision.action == "sell" or decision.confidence <= 40:  # Force sell if confidence very low
                    decision.quantity = min(decision.quantity, current_position)
                    continue

            # Enable shorting if no current position exists
            if current_position == 0 and decision.action == "sell":
                max_quantity = max_shares.get(ticker, 0)
                confidence = decision.confidence

                if confidence >= 70:  # Only allow shorting with high confidence
                    if 70 <= confidence < 80:
                        short_quantity = int(max_quantity * 0.25)
                    elif 80 <= confidence < 90:
                        short_quantity = int(max_quantity * 0.50)
                    elif 90 <= confidence <= 100:
                        short_quantity = int(max_quantity * 0.75)
                    else:
                        short_quantity = max_quantity

                    decision.quantity = short_quantity
                else:
                    decision.action = "hold"
                    decision.quantity = 0
                    continue

            # Regular trading logic for buys
            if (decision.action == "buy" and decision.confidence <= 60) or \
               (decision.action == "sell" and decision.confidence <= 70):
                decision.action = "hold"
                decision.quantity = 0

        return result
    except Exception as e:
        raise ValueError(f"Error generating trading decisions: {e}")
