import json
import traceback
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

def print_debug(msg):
    return
    print(f"$$$$$ {msg}")

def calculate_signal_confidence(signals: dict) -> tuple[float, str]:
    """
    Calculate weighted confidence score from signals.
    Handles any combination of available agents flexibly.
    Returns (confidence_score, dominant_direction)
    """
    # Base weights if all agents are present
    base_weights = {
        'fundamentals': 0.24,
        'technical_analysis': 0.23,
        'valuation': 0.23,
        'warren_buffett': 0.15,
        'sentiment': 0.15
    }
    
    print_debug("Starting signal confidence calculation")
    print_debug(f"Input signals: {signals}")
    
    # Get active agents (exclude risk management)
    active_agents = {k: v for k, v in signals.items() if k.lower() != 'risk_management_agent'}
    
    # Dynamically adjust weights based on which agents are present
    total_weight = sum(base_weights[k.lower().replace('_agent', '').replace('analyst', 'analysis')] 
                      for k in active_agents.keys() 
                      if k.lower().replace('_agent', '').replace('analyst', 'analysis') in base_weights)
    
    weights = {k: v/total_weight for k, v in base_weights.items()} if total_weight > 0 else base_weights
    print_debug(f"Adjusted weights for available agents: {weights}")
    
    weighted_bullish = 0.0
    weighted_bearish = 0.0
    active_signals = 0  # Only count non-neutral signals
    available_signals = len(active_agents)  # Total available agents
    
    print_debug("Processing each signal:")
    for signal_type, signal_data in active_agents.items():
        print_debug(f"\nProcessing signal: {signal_type}")
        print_debug(f"Signal data: {signal_data}")
        
        # Extract signal and confidence
        direction = signal_data.get('signal', '').upper()
        print_debug(f"Extracted direction: {direction}")
        
        try:
            confidence = float(signal_data.get('confidence', 0))
            print_debug(f"Parsed confidence: {confidence}")
        except (ValueError, AttributeError) as e:
            print_debug(f"Error parsing confidence: {e}")
            confidence = 0.0
        
        # Process non-neutral signals
        if direction and direction != 'NEUTRAL':
            active_signals += 1
            # Normalize agent name to match weight keys
            normalized_type = (signal_type.lower()
                             .replace('_agent', '')
                             .replace('analyst', 'analysis')
                             .replace(' ', '_'))
            weight = weights.get(normalized_type, 0)
            print_debug(f"Signal type '{signal_type}' normalized to '{normalized_type}', weight: {weight}")
            
            weighted_value = confidence * weight
            if direction == 'BULLISH':
                weighted_bullish += weighted_value
                print_debug(f"Added to bullish: {confidence}% * {weight} = {weighted_value}%")
            elif direction == 'BEARISH':
                weighted_bearish += weighted_value
                print_debug(f"Added to bearish: {confidence}% * {weight} = {weighted_value}%")
        else:
            print_debug(f"Skipping neutral or empty signal")
    
    print_debug(f"\nSignal summary:")
    print_debug(f"Active (non-neutral) signals: {active_signals}")
    print_debug(f"Total available signals: {available_signals}")
    print_debug(f"Total weighted bullish: {weighted_bullish}%")
    print_debug(f"Total weighted bearish: {weighted_bearish}%")
    
    # Determine dominant direction
    if weighted_bearish > weighted_bullish:
        confidence = weighted_bearish
        direction = 'bearish'
    else:
        confidence = weighted_bullish
        direction = 'bullish'
    
    print_debug(f"Dominant direction: {direction}")
    print_debug(f"Base confidence: {confidence}%")
    
    # Scale confidence based on signal participation
    # Instead of requiring 3 signals, we scale based on what proportion of available signals are active
    if active_signals < available_signals:
        original_confidence = confidence
        confidence *= (active_signals / available_signals)
        print_debug(f"Adjusted confidence based on signal participation: {original_confidence}% * ({active_signals}/{available_signals}) = {confidence}%")
    
    print_debug(f"Final output - Direction: {direction}, Confidence: {confidence}%")
    return confidence, direction

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
    """Generates trading decisions with optional Alpaca orders"""
    try:
        print_debug("Starting trading decision generation")
        print_debug(f"Processing tickers: {tickers}")
        print_debug(f"Current prices: {current_prices}")
        print_debug(f"Max shares: {max_shares}")
        print_debug(f"Portfolio: {portfolio}")
        
        # Pre-calculate confidence scores and create analysis summary
        analysis_by_ticker = {}
        for ticker, signals in signals_by_ticker.items():
            print_debug(f"\nAnalyzing ticker: {ticker}")
            print_debug(f"Signals for {ticker}: {signals}")
            
            confidence, direction = calculate_signal_confidence(signals)
            current_position = portfolio["positions"].get(ticker, 0)
            
            analysis = {
                "confidence": confidence,
                "direction": direction,
                "current_position": current_position,
                "current_price": current_prices[ticker],
                "max_shares": max_shares[ticker]
            }
            analysis_by_ticker[ticker] = analysis
            print_debug(f"Analysis for {ticker}: {analysis}")

        print_debug("Preparing LLM prompt")
        template = ChatPromptTemplate.from_messages([
            (
                "system",
                """You are a sophisticated portfolio manager making final trading decisions based on pre-calculated signal analysis.

                Trading Rules:
                IMPORTANT: USE THE HIGHER OF BULLISH OR BEARISH CONFIDENCE!
                
                - For new long positions (bullish direction):
                  * Require minimum 60% bullish confidence
                  * 60-70%: Buy 25% of max position
                  * 70-80%: Buy 50% of max position
                  * 80-90%: Buy 75% of max position
                  * >90%: Buy full position

                - For selling existing positions (bearish direction):
                  * Require minimum 70% bearish confidence
                  * 70-80%: Sell 25% of position
                  * 80-90%: Sell 50% of position
                  * 90-95%: Sell 75% of position
                  * >95%: Sell full position

                - For new short positions (bearish direction with no current position):
                  * Require minimum 80% bearish confidence
                  * 80-85%: Short 25% of max size
                  * 85-90%: Short 50% of max size
                  * 90-95%: Short 75% of max size
                  * >95%: Short full size

                Return decisions in JSON matching exactly this structure:
                {{
                    "decisions": {{
                        "TICKER": {{
                            "action": "buy/sell/hold",
                            "quantity": integer,
                            "confidence": float,
                            "reasoning": "string"
                        }}
                    }}
                }}
                """
            ),
            (
                "human",
                """Make trading decisions based on the pre-calculated analysis:
                {analysis_by_ticker}

                Portfolio Cash: {portfolio_cash}
                """
            )
        ])

        prompt = template.invoke({
            "analysis_by_ticker": json.dumps(analysis_by_ticker, indent=2),
            "portfolio_cash": f"{portfolio['cash']:.2f}"
        })
        print_debug(f"Generated prompt: {prompt}")

        print_debug("Calling LLM")
        result = call_llm(
            prompt=prompt,
            model_name=model_name,
            model_provider=model_provider,
            pydantic_model=PortfolioManagerOutput,
            agent_name="portfolio_management_agent"
        )
        print_debug(f"LLM response: {result}")

        # Add order details if executing trades
        if execute_trades:
            print_debug("Processing trade execution details")
            for ticker, decision in result.decisions.items():
                print_debug(f"Processing order for {ticker}: {decision}")
                if decision.action in ["buy", "sell"] and decision.quantity > 0:
                    current_price = current_prices.get(ticker, 0)
                    
                    # Determine order type based on confidence
                    order_type = "market" if decision.confidence >= 80 else "limit"
                    print_debug(f"Selected order type: {order_type}")
                    
                    # Create order
                    decision.order = {
                        "type": order_type,
                        "symbol": ticker,
                        "qty": decision.quantity,
                        "side": decision.action,
                        "time_in_force": "day"
                    }
                    
                    if order_type == "limit":
                        limit_price = (
                            round(current_price * 0.99, 2) if decision.action == "buy"
                            else round(current_price * 1.01, 2)
                        )
                        decision.order["limit_price"] = limit_price
                        print_debug(f"Added limit price: {limit_price}")
                else:
                    decision.order = None
                    print_debug("No order needed")

        print_debug("Trading decision generation complete")
        return result
        
    except Exception as e:
        print_debug(f"ERROR: {str(e)}")
        print_debug(f"ERROR TRACEBACK: {traceback.format_exc()}")
        raise ValueError(f"Error generating trading decisions: {e}")