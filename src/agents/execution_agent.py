from alpaca.trading.requests import OrderRequest
from alpaca.trading.requests import LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType
from langchain_core.messages import HumanMessage
from graph.state import AgentState, show_agent_reasoning
from utils.progress import progress
import json

def execution_agent(state: AgentState):
    """Execute trades through Alpaca based on portfolio decisions"""
    if not state["data"].get("execute_trades"):
        return state
    trading_decisions = state["data"].get("trading_decisions", {})
    trading_client = state["data"].get("trading_client")
    execution_results = {}

    progress.update_status("execution_agent", None, "Executing trades")

    try:
        for ticker, decision in trading_decisions.items():
            
            if not decision.order or decision.action == "hold":
                continue

            if decision.order.type == "limit" and decision.order.limit_price is None:
                raise ValueError(f"Limit order for {decision.order.symbol} is missing a limit price.")

            try:
                progress.update_status("execution_agent", ticker, "Placing order")

                order_request = LimitOrderRequest(
                    symbol=decision.order.symbol,
                    qty=decision.order.qty,
                    side=OrderSide(decision.order.side),
                    time_in_force=TimeInForce(decision.order.time_in_force),
                    limit_price=round(float(decision.order.limit_price), 2)
                )

                order = trading_client.submit_order(order_request)
                
                execution_results[ticker] = {
                    "status": "success",
                    "order_id": str(order.id),
                    "filled_qty": order.filled_qty,
                    "filled_avg_price": order.filled_avg_price
                }
                
            except Exception as e:
                print(f"Error executing trade for {ticker}: {e}")
                execution_results[ticker] = {
                    "status": "failed",
                    "error": str(e)
                }
    except Exception as e:
        print(f"Execution error: {e}")
        
    message = HumanMessage(
        content=json.dumps(execution_results),
        name="execution_agent",
    )

    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(execution_results, "Execution Agent")

    state["data"]["execution_results"] = execution_results
    
    return {
        "messages": state["messages"] + [message],
        "data": state["data"],
        "metadata": state["metadata"]
    }