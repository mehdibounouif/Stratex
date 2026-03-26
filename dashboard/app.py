"""
Quant_firm Performance Dashboard.
Full implementation of Portfolio, Risk, Signals, and Backtest views.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import os
import sys
import json
from streamlit_autorefresh import st_autorefresh
from decimal import Decimal

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import singletons
from risk.portfolio.portfolio_tracker import position_tracker
from strategies.strategy_researcher import strategy_engine

st.set_page_config(page_title="Quant_firm Dashboard", layout="wide", page_icon="📈")

page = st.sidebar.radio("Navigation", ["Portfolio", "Risk", "Signals & Trades", "Backtest"])

def _to_float(val):
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, dict):
        return {k: _to_float(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_to_float(i) for i in val]
    return val

def load_reports():
    reports = []
    dir_path = 'risk/reports'
    if os.path.exists(dir_path):
        files = sorted([f for f in os.listdir(dir_path) if f.startswith('risk_') and f.endswith('.json')])
        for f in files:
            try:
                with open(os.path.join(dir_path, f), 'r') as file:
                    data = json.load(file)
                    # Extract date from filename if not in JSON
                    date_val = data.get('date')
                    if not date_val:
                        # Extract YYYYMMDD from risk_YYYYMMDD.json
                        date_str = f.split('_')[1].split('.')[0]
                        try:
                            date_val = datetime.strptime(date_str, '%Y%m%d').strftime('%Y-%m-%d')
                        except:
                            date_val = date_str
                    
                    # Flatten portfolio data
                    portfolio = data.get('portfolio', {})
                    flat_data = {
                        'date': date_val,
                        'portfolio_value': float(portfolio.get('portfolio_value', 0)),
                        'cash': float(portfolio.get('cash', 0)),
                        'return_pct': float(portfolio.get('return_pct', 0)),
                    }
                    reports.append(flat_data)
            except Exception as e:
                st.sidebar.warning(f"Failed to load report {f}: {e}")
                continue
    
    if not reports:
        return pd.DataFrame(columns=['date', 'portfolio_value', 'cash', 'return_pct'])
        
    df = pd.DataFrame(reports)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    return df

if page == "Portfolio":
    st_autorefresh(interval=60000)
    st.title("Portfolio Status")
    
    summary = _to_float(position_tracker.get_portfolio_summary())
    reports_df = load_reports()
    
    # KPI Row
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Value", f"${summary['portfolio_value']:,.2f}")
    c2.metric("Cash", f"${summary['cash']:,.2f}")
    
    pnl = summary.get('total_unrealized_pnl', 0) + summary.get('total_realized_pnl', 0)
    c3.metric("Total P&L", f"${pnl:,.2f}", delta=f"{pnl:,.2f}")
    
    daily_chg = 0
    if not reports_df.empty and len(reports_df) > 1:
        daily_chg = reports_df.iloc[-1]['portfolio_value'] - reports_df.iloc[-2]['portfolio_value']
    c4.metric("Daily Change", f"${daily_chg:,.2f}", delta=f"{daily_chg:,.2f}")

    # Value Chart
    st.subheader("Equity Curve")
    if not reports_df.empty and len(reports_df) > 0:
        try:
            # Ensure we have at least 2 points for an area chart to look good
            if len(reports_df) < 2:
                st.info("Insufficient data history to render equity curve area. Showing single point.")
                st.metric("Latest Value", f"${reports_df.iloc[-1]['portfolio_value']:,.2f}")
            else:
                fig = px.area(reports_df, x='date', y='portfolio_value', template='plotly_dark', title="Portfolio Value Over Time")
                st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"Error rendering equity curve: {e}")
            # Fallback to simple line chart or metric
            try:
                st.line_chart(reports_df.set_index('date')['portfolio_value'])
            except:
                st.info("Insufficient data to render chart.")
    else: 
        st.info("No report data yet. Run the system to generate reports (risk/reports/risk_YYYYMMDD.json).")

    # Positions
    st.subheader("Open Positions")
    pos = _to_float(position_tracker.get_all_positions())
    if pos:
        df_pos = pd.DataFrame(pos)
        st.dataframe(df_pos.style.background_gradient(subset=['unrealized_pnl'], cmap='RdYlGn'))
        
        fig_pie = px.pie(df_pos, values='market_value', names='ticker', hole=0.4)
        st.plotly_chart(fig_pie)
    else: st.info("No open positions.")

elif page == "Risk":
    st.title("Risk Analysis")
    reports_df = load_reports()
    
    if not reports_df.empty:
        vals = reports_df['portfolio_value']
        rets = vals.pct_change().dropna()
        sharpe = (rets.mean() / rets.std() * (252**0.5)) if len(rets) > 1 and rets.std() > 0 else 0
        mdd = ((vals - vals.cummax()) / vals.cummax()).min()
        
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Sharpe Ratio", f"{sharpe:.2f}")
        r2.metric("Max Drawdown", f"{mdd:.2%}")
        r3.metric("Daily Return Std", f"{rets.std():.2%}")
        r4.metric("Volatility (Ann)", f"{rets.std() * (252**0.5):.2%}")
        
        # Drawdown Chart
        st.subheader("Drawdown History")
        dd = (vals - vals.cummax()) / vals.cummax()
        fig_dd = px.area(x=reports_df['date'], y=dd, title="Drawdown %", template='plotly_dark')
        fig_dd.update_traces(fillcolor='rgba(255,0,0,0.3)', line_color='red')
        st.plotly_chart(fig_dd, use_container_width=True)
    else: st.info("No data available.")

elif page == "Signals & Trades":
    st.title("Activity Feed")
    
    st.subheader("Recent Signals")
    sig_dir = 'strategies/signals'
    if os.path.exists(sig_dir):
        files = sorted(os.listdir(sig_dir), reverse=True)[:50]
        sigs = []
        for f in files:
            with open(os.path.join(sig_dir, f), 'r') as file:
                sigs.append(json.load(file))
        df_sig = pd.DataFrame(sigs)
        if not df_sig.empty:
            st.dataframe(df_sig[['timestamp', 'ticker', 'strategy', 'action', 'confidence', 'reasoning']])
    
    st.subheader("Order Log")
    if os.path.exists('execution/order_log.jsonl'):
        with open('execution/order_log.jsonl', 'r') as f:
            orders = [json.loads(line) for line in f.readlines()][-50:]
        st.dataframe(pd.DataFrame(orders))

elif page == "Backtest":
    st.title("Backtest Sandbox")
    with st.sidebar:
        t = st.text_input("Ticker", "AAPL")
        s = st.date_input("Start", value=date(2024,1,1))
        e = st.date_input("End", value=date(2024,12,31))
        strat = st.selectbox("Strategy", strategy_engine.list_strategies())
        cap = st.number_input("Capital", value=20000)
        run = st.button("Execute Backtest")

    if run:
        from system.backtest_engine import BacktestEngine
        strategy = strategy_engine.strategies[strat]
        engine = BacktestEngine(strategy, initial_capital=cap)
        res = engine.run(t, str(s), str(e))
        
        if res:
            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Return", f"{res['total_return']}%")
            b2.metric("Sharpe", f"{res['sharpe_ratio']}")
            b3.metric("MDD", f"{res['max_drawdown']}%")
            b4.metric("Trades", res['total_trades'])
            
            st.plotly_chart(px.line(y=res['daily_values'], title="Equity Curve"), use_container_width=True)
            st.subheader("Trade History")
            st.dataframe(pd.DataFrame(res['trades']))