def store_analyst_signals(supabase, date, ticker, signals):
    """Store analyst signals"""
    for analyst, signal_data in signals.items():
        record = {
            'date': date,
            'ticker': ticker,
            'analyst': analyst,
            'signal': signal_data.get('signal', 'unknown'),
            'confidence': signal_data.get('confidence', 0)
        }
        try:
            supabase.table('analyst_signals').upsert(record).execute()
        except Exception as e:
            print(f"Error storing analyst signal: {e}")
