
"""
Quant_firm Performance Dashboard.
Enhanced version with Real-time Monitoring, Advanced Risk, and Strategy Analytics.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import os
import sys
import json
from streamlit_autorefresh import st_autorefresh
from decimal import Decimal

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import components
from dashboard.components import (
    display_kpi_row, display_system_health, display_risk_metrics,
    display_performance_charts, display_strategy_heatmap,
    display_order_history, display_config_viewer, display_export_buttons
)

# Import singletons
from risk.portfolio.portfolio_tracker import position_tracker
from strategies.strategy_researcher import strategy_engine
from execution.alpaca_gateway import alpaca_gateway

st.set_page_config(
    page_title="Quant_firm | Dashboard", 
    layout="wide", 
    page_icon="📈",
    initial_sidebar_state="expanded"
)

# --- Data Loading Helpers ---

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
                    date_val = data.get('date')
                    if not date_val:
                        date_str = f.split('_')[1].split('.')[0]
                        try:
                            date_val = datetime.strptime(date_str, '%Y%m%d').strftime('%Y-%m-%d')
                        except:
                            date_val = date_str
                    
                    portfolio = data.get('portfolio', {})
                    flat_data = {
                        'date': date_val,
                        'portfolio_value': float(portfolio.get('portfolio_value', 0)),
                        'cash': float(portfolio.get('cash', 0)),
                        'return_pct': float(portfolio.get('return_pct', 0)),
                    }
                    reports.append(flat_data)
            except Exception as e:
                continue
    
    if not reports:
        return pd.DataFrame(columns=['date', 'portfolio_value', 'cash', 'return_pct'])
        
    df = pd.DataFrame(reports)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    return df

def get_latest_report():
    dir_path = 'risk/reports'
    if os.path.exists(dir_path):
        files = sorted([f for f in os.listdir(dir_path) if f.startswith('risk_') and f.endswith('.json')])
        if files:
            with open(os.path.join(dir_path, files[-1]), 'r') as f:
                return json.load(f)
    return {}

def load_signals():
    sig_dir = 'strategies/signals'
    sigs = []
    if os.path.exists(sig_dir):
        files = sorted(os.listdir(sig_dir), reverse=True)[:100]
        for f in files:
            try:
                with open(os.path.join(sig_dir, f), 'r') as file:
                    sigs.append(json.load(file))
            except: continue
    return pd.DataFrame(sigs)

def load_orders():
    order_file = 'execution/order_log.jsonl'
    orders = []
    if os.path.exists(order_file):
        with open(order_file, 'r') as f:
            for line in f:
                try: orders.append(json.loads(line))
                except: continue
    return pd.DataFrame(orders)

# --- Sidebar & Navigation ---

st.sidebar.title("Quant_firm")
st.sidebar.image("https://via.placeholder.com/150x50?text=QUANT+FIRM", use_column_width=True)

page = st.sidebar.radio("Navigation", [
    "🏠 Overview", 
    "📊 Portfolio & Positions", 
    "🛡️ Risk Management", 
    "🧠 Strategy Insights",
    "📜 Activity Log",
    "⚙️ System Settings",
    "🧪 Backtest Sandbox"
])

refresh_rate = st.sidebar.select_slider("Refresh Rate (s)", options=[10, 30, 60, 300], value=60)
st_autorefresh(interval=refresh_rate * 1000, key="data_refresh")

# --- Page Content ---

summary = _to_float(position_tracker.get_portfolio_summary())
reports_df = load_reports()
signals_df = load_signals()
orders_df = load_orders()
latest_report = get_latest_report()

if page == "🏠 Overview":
    st.title("Trading Overview")
    display_kpi_row(summary, reports_df)
    
    col1, col2 = st.columns([2, 1])
    with col1:
        display_performance_charts(reports_df)
    with col2:
        display_system_health(alpaca_gateway)
        st.divider()
        st.subheader("Asset Allocation")
        pos = _to_float(position_tracker.get_all_positions())
        if pos:
            df_pos = pd.DataFrame(pos)
            fig_pie = px.pie(df_pos, values='market_value', names='ticker', hole=0.4, template='plotly_dark')
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("No active positions.")

elif page == "📊 Portfolio & Positions":
    st.title("Portfolio & Positions")
    
    st.subheader("Open Positions")
    pos = _to_float(position_tracker.get_all_positions())
    if pos:
        df_pos = pd.DataFrame(pos)
        st.dataframe(
            df_pos.style.background_gradient(subset=['unrealized_pnl'], cmap='RdYlGn'),
            use_container_width=True
        )
        display_export_buttons(df_pos, "positions")
    else:
        st.info("No open positions.")
        
    st.divider()
    st.subheader("Historical Snapshots")
    if not reports_df.empty:
        st.dataframe(reports_df.sort_values('date', ascending=False), use_container_width=True)
    else:
        st.info("No historical data available.")

elif page == "🛡️ Risk Management":
    st.title("Risk Management Dashboard")
    display_risk_metrics(latest_report)
    
    st.divider()
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Sector Exposure")
        sector_data = latest_report.get('sector_analysis', {}).get('breakdown', {})
        if sector_data:
            df_sector = pd.DataFrame(list(sector_data.items()), columns=['Sector', 'Weight'])
            fig = px.bar(df_sector, x='Sector', y='Weight', template='plotly_dark')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No sector data available.")
            
    with col2:
        st.subheader("Concentration Risk")
        conc = latest_report.get('position_analysis', {}).get('concentration_risk', {})
        if conc:
            st.json(conc)
        else:
            st.info("No concentration data available.")

elif page == "🧠 Strategy Insights":
    st.title("Strategy Insights")
    display_strategy_heatmap(signals_df)
    
    st.divider()
    st.subheader("Signal Feed")
    if not signals_df.empty:
        st.dataframe(signals_df, use_container_width=True)
        display_export_buttons(signals_df, "signals")
    else:
        st.info("No signals found.")

elif page == "📜 Activity Log":
    st.title("Trading Activity Log")
    display_order_history(orders_df)
    
    if not orders_df.empty:
        display_export_buttons(orders_df, "orders")

elif page == "⚙️ System Settings":
    st.title("System Settings & Controls")
    display_config_viewer()

elif page == "🧪 Backtest Sandbox":
    st.title("Backtest Sandbox")
    with st.expander("Backtest Configuration", expanded=True):
        c1, c2, c3 = st.columns(3)
        ticker = c1.text_input("Ticker", "AAPL")
        start_date = c2.date_input("Start Date", value=date(2024, 1, 1))
        end_date = c3.date_input("End Date", value=date(2024, 12, 31))
        
        strat_list = strategy_engine.list_strategies()
        strat = st.selectbox("Select Strategy", strat_list)
        cap = st.number_input("Initial Capital", value=20000)
        run = st.button("🚀 Run Backtest", use_container_width=True)

    if run:
        from system.backtest_engine import BacktestEngine
        with st.spinner(f"Running {strat} on {ticker}..."):
            strategy = strategy_engine.strategies[strat]
            engine = BacktestEngine(strategy, initial_capital=cap)
            res = engine.run(ticker, str(start_date), str(end_date))
        
        if res:
            st.success("Backtest Completed!")
            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Total Return", f"{res['total_return']}%")
            b2.metric("Sharpe Ratio", f"{res['sharpe_ratio']}")
            b3.metric("Max Drawdown", f"{res['max_drawdown']}%")
            b4.metric("Total Trades", res['total_trades'])
            
            fig = px.line(y=res['daily_values'], title=f"Equity Curve: {strat} on {ticker}", template='plotly_dark')
            fig.update_layout(xaxis_title="Days", yaxis_title="Portfolio Value")
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("Trade Details")
            st.dataframe(pd.DataFrame(res['trades']), use_container_width=True)
        else:
            st.error("Backtest failed to produce results. Check logs for details.")
