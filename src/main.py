import json
import sys
from typing import List

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from colorama import Fore, Back, Style, init
import questionary
import os
from src.agents.execution_agent import execution_agent
from src.db.functions_files.store_stock_record import get_hot_stocks
from src.reddit.getDailyDiscussion import send_slack_message
from src.traders.initialize_portfolio import initialize_portfolio
from src.traders.trading_decisions import enhance_trading_decisions
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
from llm.models import LLM_ORDER, get_model_info

import argparse
from datetime import datetime
from dateutil.relativedelta import relativedelta
from tabulate import tabulate
from utils.visualize import save_graph_as_png
from alpaca.trading.client import TradingClient

# Load environment variables from .env file
load_dotenv()

# Retrieve Supabase URL and Key from environment variables
url = os.getenv("SUPABASE_URL") or os.environ.get("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")

if not url or not key:
    raise ValueError("Please set SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables.")


# Debug environment variables
print("\nDebugging Environment Variables:")
print(f"ALPACA_API_KEY exists: {'ALPACA_API_KEY' in os.environ}")
print(f"ALPACA_API_SECRET exists: {'ALPACA_API_SECRET' in os.environ}")
        
        
ALPACA_API_KEY = (
    os.getenv('ALPACA_API_KEY') or 
    os.environ.get('ALPACA_API_KEY') or 
    os.getenv('APCA_API_KEY_ID')
    )
ALPACA_API_SECRET = (
    os.getenv('ALPACA_API_SECRET') or 
    os.environ.get('ALPACA_API_SECRET') or 
    os.getenv('APCA_API_SECRET_KEY')
    )
        
# Print diagnostic information
print("\nAPI Key Status:")
print(f"API Key length: {len(ALPACA_API_KEY) if ALPACA_API_KEY else 0}")
print(f"API Secret length: {len(ALPACA_API_SECRET) if ALPACA_API_SECRET else 0}")
trading_client = TradingClient(ALPACA_API_KEY, ALPACA_API_SECRET, paper=True)

# Initialize Supabase client
supabase: Client = create_client(url, key)
supabase.postgrest.auth(token=key)

init(autoreset=True)

class StockEntry:
    ticker: str
    created_at: datetime
    updated_at: datetime
    name: str


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
    selected_analysts: list[str] = [],
    model_name: str = "gpt-4o",
    model_provider: str = "OpenAI",
    execute_trades: bool = False,
    trading_client = None
):
    progress.start()
    successful_tickers = []
    failed_tickers = {}
    
    try:
        if selected_analysts:
            workflow = create_workflow(selected_analysts, execute_trades)
            agent = workflow.compile()
        else:
            agent = app

        # Process each ticker individually
        combined_decisions = {}
        combined_signals = {}
        combined_executions = {}

        for ticker in tickers:
            try:
                final_state = agent.invoke({
                    "messages": [HumanMessage(content="Make trading decisions based on the provided data.")],
                    "data": {
                        "tickers": [ticker],  # Process single ticker
                        "portfolio": {
                            "cash": portfolio["cash"],
                            "positions": {ticker: portfolio["positions"].get(ticker, 0)}
                        },
                        "start_date": start_date,
                        "end_date": end_date,
                        "analyst_signals": {},
                        "execute_trades": execute_trades,
                        "trading_client": trading_client
                    },
                    "metadata": {
                        "show_reasoning": show_reasoning,
                        "model_name": model_name,
                        "model_provider": model_provider,
                    },
                })
                
                # Collect successful results
                if "trading_decisions" in final_state["data"]:
                    combined_decisions.update(final_state["data"]["trading_decisions"])
                    combined_signals.update(final_state["data"]["analyst_signals"])
                    if execute_trades and "execution_results" in final_state["data"]:
                        combined_executions.update(final_state["data"].get("execution_results", {}))
                    successful_tickers.append(ticker)
                
            except Exception as e:
                failed_tickers[ticker] = str(e)
                print(f"Error processing ticker {ticker}: {str(e)}")
                continue

        # Log results
        if failed_tickers:
            print("\nFailed tickers:")
            for ticker, error in failed_tickers.items():
                print(f"{ticker}: {error}")
            
        print(f"\nSuccessfully processed {len(successful_tickers)} out of {len(tickers)} tickers")

        return {
            "decisions": {
                ticker: decision.model_dump() 
                for ticker, decision in combined_decisions.items()
            },
            "analyst_signals": combined_signals,
            "execution_results": combined_executions,
            "failed_tickers": failed_tickers
        }
    finally:
        progress.stop()

def start(state: AgentState):
    """Initialize the workflow with the input message."""
    return state


def create_workflow(selected_analysts=None, execute_trades=False):
    workflow = StateGraph(AgentState)
    workflow.add_node("start_node", start)

    if not selected_analysts:
        selected_analysts = ["technical_analyst"]

    analyst_nodes = {
        "technical_analyst": ("technical_analyst_agent", technical_analyst_agent),
        "fundamentals_analyst": ("fundamentals_agent", fundamentals_agent),
        "sentiment_analyst": ("sentiment_agent", sentiment_agent),
        "valuation_analyst": ("valuation_agent", valuation_agent),
        "warren_buffett": ("warren_buffett_agent", warren_buffett_agent),
    }

    for analyst_key in selected_analysts:
        if analyst_key in analyst_nodes:
            node_name, node_func = analyst_nodes[analyst_key]
            workflow.add_node(node_name, node_func)
            workflow.add_edge("start_node", node_name)

    workflow.add_node("risk_management_agent", risk_management_agent)
    workflow.add_node("portfolio_management_agent", portfolio_management_agent)

    for analyst_key in selected_analysts:
        if analyst_key in analyst_nodes:
            node_name = analyst_nodes[analyst_key][0]
            workflow.add_edge(node_name, "risk_management_agent")

    workflow.add_edge("risk_management_agent", "portfolio_management_agent")
    
    if execute_trades:
        workflow.add_node("execution_agent", execution_agent)
        workflow.add_edge("portfolio_management_agent", "execution_agent")
        workflow.add_edge("execution_agent", END)
    else:
        workflow.add_edge("portfolio_management_agent", END)

    workflow.set_entry_point("start_node")
    return workflow


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the hedge fund trading system")
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    parser.add_argument("--tickers", type=str)
    parser.add_argument("--start-date", type=str)
    parser.add_argument("--end-date", type=str)
    parser.add_argument("--show-reasoning", action="store_true")
    parser.add_argument("--show-agent-graph", action="store_true")
    parser.add_argument("--execute-trades", action="store_true")
    parser.add_argument("--trade-amount", type=float, default=100000.0)
    parser.add_argument("--leverage", type=int, default=1)

    args = parser.parse_args()

    if not args.tickers and not args.execute_trades:
        print("You must provide a list of tickers to process.")
        raise ValueError("No tickers provided")

    if args.execute_trades:
        try:
            owned_positions = trading_client.get_all_positions()
            owned_tickers = [position.symbol for position in owned_positions]
            print(f"Currently owned stocks: {', '.join(owned_tickers)}")
            
            response = supabase.table("stocks").select("*").execute()
            response_data: List[StockEntry] = response.data
            db_tickers_hot = get_hot_stocks(supabase)

            print("Hot stocks: ", db_tickers_hot)
            print("Owned stocks: ", owned_tickers)    


            tickers = owned_tickers.copy() 
            for ticker in db_tickers_hot:
                if ticker not in owned_tickers:
                    tickers.append(ticker)
    
                    
            portfolio = initialize_portfolio(trading_client, args.initial_cash)
        except Exception as e:
            print(f"Error fetching positions: {e}")
            sys.exit(1)
    else:
        tickers = [ticker.strip() for ticker in args.tickers.split(",")]
        print(f"Processing tickers: {', '.join(tickers)}")
        portfolio = {
            "cash": args.initial_cash,
            "positions": {ticker: 0 for ticker in tickers}
        }

    # starting_msg = f":bar_chart: :alien: Starting hedge fund bot for {len(tickers)} tickers: {', '.join(tickers)}"
    # send_slack_message(starting_msg)

    print(f"Portfolio: ${portfolio}")
    print("tickers: ", tickers)
    
    selected_analysts = None
    choices = questionary.checkbox(
        "Select your AI analysts.",
        choices=[questionary.Choice(display, value=value) for display, value in ANALYST_ORDER],
        instruction="\n\nInstructions: \n1. Press Space to select/unselect analysts.\n2. Press 'a' to select/unselect all.\n3. Press Enter when done to run the hedge fund.\n",
        validate=lambda x: len(x) > 0 or "You must select at least one analyst.",
        style=questionary.Style([
            ("checkbox-selected", "fg:green"),
            ("selected", "fg:green noinherit"),
            ("highlighted", "noinherit"),
            ("pointer", "noinherit"),
        ]),
    ).ask()

    if not choices:
        print("\n\nInterrupt received. Exiting...")
        sys.exit(0)
    else:
        selected_analysts = choices
        print(f"\nSelected analysts: {', '.join(Fore.GREEN + choice.title().replace('_', ' ') + Style.RESET_ALL for choice in choices)}\n")

    # model_choice = questionary.select(
    #     "Select your LLM model:",
    #     choices=[questionary.Choice(display, value=value) for display, value, _ in LLM_ORDER],
    #     style=questionary.Style([
    #         ("selected", "fg:green bold"),
    #         ("pointer", "fg:green bold"),
    #         ("highlighted", "fg:green"),
    #         ("answer", "fg:green bold"),
    #     ])
    # ).ask()

    # if not model_choice:
    #     print("\n\nInterrupt received. Exiting...")
    #     sys.exit(0)
    # else:
    #     model_info = get_model_info(model_choice)
    #     if model_info:
    #         model_provider = model_info.provider.value
    #         print(f"\nSelected {Fore.CYAN}{model_provider}{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{model_choice}{Style.RESET_ALL}\n")
    #     else:
    #         model_provider = "Unknown"
    #         print(f"\nSelected model: {Fore.GREEN + Style.BRIGHT}{model_choice}{Style.RESET_ALL}\n")

    model_choice = "gpt-4o"  # Hardcoded model

    model_info = get_model_info(model_choice)
    if model_info:
        model_provider = model_info.provider.value
        print(f"\nSelected {Fore.CYAN}{model_provider}{Style.RESET_ALL} model: {Fore.GREEN + Style.BRIGHT}{model_choice}{Style.RESET_ALL}\n")
    else:
        model_provider = "Unknown"
        print(f"\nSelected model: {Fore.GREEN + Style.BRIGHT}{model_choice}{Style.RESET_ALL}\n")

    workflow = create_workflow(selected_analysts, args.execute_trades)
    app = workflow.compile()

    if args.show_agent_graph:
        file_path = ""
        if selected_analysts is not None:
            for selected_analyst in selected_analysts:
                file_path += selected_analyst + "_"
            file_path += "graph.png"
        save_graph_as_png(app, file_path)

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

    end_date = args.end_date or datetime.now().strftime("%Y-%m-%d")
    if not args.start_date:
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
        start_date = (end_date_obj - relativedelta(months=3)).strftime("%Y-%m-%d")
    else:
        start_date = args.start_date

    result = run_hedge_fund(
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        portfolio=portfolio,
        show_reasoning=args.show_reasoning,
        selected_analysts=selected_analysts,
        model_name=model_choice,
        model_provider=model_provider,
        execute_trades=args.execute_trades,
        trading_client=trading_client if args.execute_trades else None
    )
    
    
    print_trading_output(result)

    # sucess_msg = f":bar_chart: :alien: Hedge fund bot completed for {len(tickers)} tickers: {', '.join(tickers)}"
    # send_slack_message(sucess_msg)

    if args.execute_trades and result.get('execution_results'):
        print("\nExecution Results:")
        for ticker, exec_result in result['execution_results'].items():
            status = exec_result['status']
            if status == 'success':
                order_success_message = f"{ticker}: Order {exec_result['order_id']} filled {exec_result['filled_qty']} @ ${exec_result.get('filled_avg_price', 'N/A')}"
                # print(order_success_message)
                # send_slack_message(order_success_message)
            else:
                print(f"{ticker}: Failed - {exec_result.get('error', 'Unknown error')}")
