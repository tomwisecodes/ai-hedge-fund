def initialize_portfolio(trading_client, initial_cash=100000.0):
    """Initialize portfolio with real Alpaca data if available"""
    try:
        # Get account information
        account = trading_client.get_account()
        current_cash = float(account.cash)
        buying_power = float(account.buying_power)
        
        # Get current positions
        positions = trading_client.get_all_positions()
        position_data = {}
        cost_basis = {}
        
        for position in positions:
            position_data[position.symbol] = int(position.qty)
            cost_basis[position.symbol] = float(position.cost_basis)
            
        portfolio = {
            "cash": current_cash,
            "buying_power": buying_power,
            "positions": position_data,
            "cost_basis": cost_basis
        }
        
        return portfolio
        
    except Exception as e:
        print(f"Error initializing Alpaca portfolio: {e}")
        return {
            "cash": initial_cash,
            "buying_power": initial_cash,
            "positions": {},
            "cost_basis": {}
        }