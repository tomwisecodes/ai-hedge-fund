from langchain_core.messages import HumanMessage
from graph.state import AgentState, show_agent_reasoning
from utils.progress import progress
from src.tools.api import get_prices, prices_to_df
import json

##### Risk Management Agent #####
def risk_management_agent(state: AgentState):
    """Controls position sizing based on real-world risk factors and Alpaca account limits."""
    try:
        portfolio = state["data"]["portfolio"]
        data = state["data"]
        tickers = data["tickers"]
        execute_trades = data.get("execute_trades", False)
    except KeyError as e:
        raise ValueError(f"Missing expected key in state data: {e}")

    risk_analysis = {}
    current_prices = {}

    for ticker in tickers:
        try:
            progress.update_status("risk_management_agent", ticker, "Analyzing price data")
            
            prices = get_prices(
                ticker=ticker,
                start_date=data["start_date"],
                end_date=data["end_date"],
            )

            if not prices:
                progress.update_status("risk_management_agent", ticker, "Failed: No price data found")
                continue

            prices_df = prices_to_df(prices)
            current_price = prices_df["close"].iloc[-1]
            current_prices[ticker] = current_price

            # Enhanced position limit calculation
            current_position_value = portfolio.get("cost_basis", {}).get(ticker, 0)
            total_portfolio_value = portfolio.get("cash", 0) + sum(
                portfolio.get("cost_basis", {}).get(t, 0) for t in portfolio.get("cost_basis", {})
            )

            # Account for buying power if executing trades
            if execute_trades:
                buying_power = portfolio.get("buying_power", portfolio.get("cash", 0))
                max_position = min(
                    total_portfolio_value * 0.20,  # 20% portfolio limit
                    buying_power * 0.95,  # 95% of buying power to leave margin
                )
            else:
                max_position = total_portfolio_value * 0.20

            remaining_position_limit = max_position - current_position_value
            max_position_size = min(remaining_position_limit, portfolio.get("cash", 0))

            risk_analysis[ticker] = {
                "remaining_position_limit": float(max_position_size),
                "current_price": float(current_price),
                "max_shares": int(max_position_size / current_price) if current_price > 0 else 0,
                "reasoning": {
                    "portfolio_value": float(total_portfolio_value),
                    "current_position": float(current_position_value),
                    "position_limit": float(max_position),
                    "remaining_limit": float(remaining_position_limit),
                    "available_cash": float(portfolio.get("cash", 0)),
                    "buying_power": float(portfolio.get("buying_power", portfolio.get("cash", 0)))
                },
            }

            progress.update_status("risk_management_agent", ticker, "Done")
        
        except Exception as e:
            progress.update_status("risk_management_agent", ticker, f"Error: {e}")
            continue

    try:
        message = HumanMessage(
            content=json.dumps(risk_analysis),
            name="risk_management_agent",
        )

        if state["metadata"].get("show_reasoning", False):
            show_agent_reasoning(risk_analysis, "Risk Management Agent")

        state["data"]["analyst_signals"]["risk_management_agent"] = risk_analysis
    except Exception as e:
        raise RuntimeError(f"Failed to update state data: {e}")

    return {
        "messages": state["messages"] + [message],
        "data": data,
    }
