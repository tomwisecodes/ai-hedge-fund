from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from colorama import Fore, Back, Style, init
import questionary
import os
from supabase import create_client, Client
from agents.fundamentals import fundamentals_agent
from agents.portfolio_manager import portfolio_management_agent
from agents.technicals import technical_analyst_agent
from agents.risk_manager import risk_management_agent
from agents.sentiment import sentiment_agent
from agents.warren_buffett import warren_buffett_agent
from graph.state import AgentState
from agents.valuation import valuation_agent
from utils.display import print_trading_output
from utils.analysts import ANALYST_ORDER
from utils.progress import progress
from db.functions import store_backtest_record, store_analyst_signals
from traders.alpaca_cfd import execute_trades

import argparse
from datetime import datetime
from dateutil.relativedelta import relativedelta
from tabulate import tabulate

# Load environment variables from .env file
load_dotenv()

# Retrieve Supabase URL and Key from environment variables
url = os.getenv("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")

if not url or not key:
    raise ValueError("Please set SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables.")


# Initialize Supabase client
supabase: Client = create_client(url, key)
supabase.postgrest.auth(token=key)

init(autoreset=True)


def parse_hedge_fund_response(response):
    import json

    try:
        return json.loads(response)
    except:
        print(f"Error parsing response: {response}")
        return None


##### Run the Hedge Fund #####
def run_hedge_fund(
    tickers: list[str],
    start_date: str,
    end_date: str,
    portfolio: dict,
    show_reasoning: bool = False,
    selected_analysts: list = None,
    supabase=None
):
    progress.start()
    try:
        if selected_analysts is not None:
            workflow = create_workflow(selected_analysts)
            agent = workflow.compile()
        else:
            agent = app

        final_state = agent.invoke({
            "messages": [HumanMessage(content="Make trading decisions based on the provided data.")],
            "data": {
                "tickers": tickers,
                "portfolio": portfolio,
                "start_date": start_date,
                "end_date": end_date,
                "analyst_signals": {},
            },
            "metadata": {"show_reasoning": show_reasoning},
        })

        decisions = parse_hedge_fund_response(final_state["messages"][-1].content)
        analyst_signals = final_state["data"]["analyst_signals"]

        # # Store data if supabase client is provided
        # if supabase:
        #     for ticker in tickers:
        #         store_analyst_signals(supabase, end_date, ticker, analyst_signals)
        #         if ticker in decisions:
        #             record = {
        #                 'date': end_date,
        #                 'ticker': ticker,
        #                 'action': decisions[ticker].get('action', 'hold'),
        #                 'quantity': decisions[ticker].get('quantity', 0),
        #                 'price': portfolio.get('last_price', {}).get(ticker, 0),
        #                 'shares_owned': portfolio['positions'].get(ticker, 0),
        #                 'position_value': portfolio['positions'].get(ticker, 0) * portfolio.get('last_price', {}).get(ticker, 0),
        #                 'bullish_count': len([s for s in analyst_signals.values() if s.get(ticker, {}).get('signal') == 'bullish']),
        #                 'bearish_count': len([s for s in analyst_signals.values() if s.get(ticker, {}).get('signal') == 'bearish']),
        #                 'neutral_count': len([s for s in analyst_signals.values() if s.get(ticker, {}).get('signal') == 'neutral']),
        #                 'total_value': portfolio['cash'] + sum(portfolio['positions'].get(t, 0) * portfolio.get('last_price', {}).get(t, 0) for t in tickers),
        #                 'return_pct': 0,  # Calculate if needed
        #                 'cash_balance': portfolio['cash'],
        #                 'total_position_value': sum(portfolio['positions'].get(t, 0) * portfolio.get('last_price', {}).get(t, 0) for t in tickers)
        #             }
        #             store_backtest_record(supabase, record)

        return {
            "decisions": decisions,
            "analyst_signals": analyst_signals,
        }
    finally:
        progress.stop()

def start(state: AgentState):
    """Initialize the workflow with the input message."""
    return state


def create_workflow(selected_analysts=None):
    """Create the workflow with selected analysts."""
    workflow = StateGraph(AgentState)
    workflow.add_node("start_node", start)

    # Default to all analysts if none selected
    if selected_analysts is None:
        selected_analysts = ["technical_analyst", "fundamentals_analyst", "sentiment_analyst", "valuation_analyst"]

    # Dictionary of all available analysts
    analyst_nodes = {
        "technical_analyst": ("technical_analyst_agent", technical_analyst_agent),
        "fundamentals_analyst": ("fundamentals_agent", fundamentals_agent),
        "sentiment_analyst": ("sentiment_agent", sentiment_agent),
        "valuation_analyst": ("valuation_agent", valuation_agent),
        "warren_buffett": ("warren_buffett_agent", warren_buffett_agent),
    }

    # Add selected analyst nodes
    for analyst_key in selected_analysts:
        node_name, node_func = analyst_nodes[analyst_key]
        workflow.add_node(node_name, node_func)
        workflow.add_edge("start_node", node_name)

    # Always add risk and portfolio management
    workflow.add_node("risk_management_agent", risk_management_agent)
    workflow.add_node("portfolio_management_agent", portfolio_management_agent)

    # Connect selected analysts to risk management
    for analyst_key in selected_analysts:
        node_name = analyst_nodes[analyst_key][0]
        workflow.add_edge(node_name, "risk_management_agent")

    workflow.add_edge("risk_management_agent", "portfolio_management_agent")
    workflow.add_edge("portfolio_management_agent", END)

    workflow.set_entry_point("start_node")
    return workflow


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the hedge fund trading system")
    parser.add_argument(
        "--initial-cash",
        type=float,
        default=100000.0,
        help="Initial cash position. Defaults to 100000.0)"
    )
    parser.add_argument("--tickers", type=str, required=True, help="Comma-separated list of stock ticker symbols")
    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date (YYYY-MM-DD). Defaults to 3 months before end date",
    )
    parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD). Defaults to today")
    parser.add_argument("--show-reasoning", action="store_true", help="Show reasoning from each agent")

    parser.add_argument(
    "--execute-trades",
    action="store_true",
    help="Execute trades through Alpaca"
    )
    parser.add_argument(
        "--trade-amount",
        type=float,
        default=100000.0,
        help="Amount to invest per buy order (default: 100000.0)"
    )

    parser.add_argument(
    "--leverage",
    type=int,
    default=5,
    help="Leverage ratio for CFD trading (default: 5)"
    )

    args = parser.parse_args()

    # Parse tickers from comma-separated string
    tickers = [ticker.strip() for ticker in args.tickers.split(",")]

    selected_analysts = None
    choices = questionary.checkbox(
        "Select your AI analysts.",
        choices=[questionary.Choice(display, value=value) for display, value in ANALYST_ORDER],
        instruction="\n\nInstructions: \n1. Press Space to select/unselect analysts.\n2. Press 'a' to select/unselect all.\n3. Press Enter when done to run the hedge fund.\n",
        validate=lambda x: len(x) > 0 or "You must select at least one analyst.",
        style=questionary.Style(
            [
                ("checkbox-selected", "fg:green"),
                ("selected", "fg:green noinherit"),
                ("highlighted", "noinherit"),
                ("pointer", "noinherit"),
            ]
        ),
    ).ask()

    if not choices:
        print("You must select at least one analyst. Using all analysts by default.")
        selected_analysts = None
    else:
        selected_analysts = choices
        print(f"\nSelected analysts: {', '.join(Fore.GREEN + choice.title().replace('_', ' ') + Style.RESET_ALL for choice in choices)}\n")

    # Create the workflow with selected analysts
    workflow = create_workflow(selected_analysts)
    app = workflow.compile()

    # Validate dates if provided
    if args.start_date:
        try:
            datetime.strptime(args.start_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Start date must be in YYYY-MM-DD format")

    if args.end_date:
        try:
            datetime.strptime(args.end_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("End date must be in YYYY-MM-DD format")

    # Set the start and end dates
    end_date = args.end_date or datetime.now().strftime("%Y-%m-%d")
    if not args.start_date:
        # Calculate 3 months before end_date
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        start_date = (end_date_obj - relativedelta(months=3)).strftime("%Y-%m-%d")
    else:
        start_date = args.start_date

    # Initialize portfolio with cash amount and stock positions
    portfolio = {
        "cash": args.initial_cash,  # Initial cash amount
        "positions": {ticker: 0 for ticker in tickers}  # Initial stock positions
    }

    # Run the hedge fund
    result = run_hedge_fund(
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        portfolio=portfolio,
        show_reasoning=args.show_reasoning,
        selected_analysts=selected_analysts,
        supabase=supabase
    )
    print_trading_output(result)

    print("\n")
    print("***************")
    print(args.execute_trades)
    print("args.execute_trades")
    print("***************")
    print(result.get('decisions'))
    # CFD trading
    if args.execute_trades and result.get('decisions'):
        print("\nExecuting trades through Alpaca...")
        trade_results = execute_trades(
            result['decisions'],
            fixed_amount=args.trade_amount,
            leverage=args.leverage  
        )



# HPE
# KNOP
# ZIM