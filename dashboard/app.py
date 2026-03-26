
"""
Quant_firm Performance Dashboard.
Responsive, Aesthetic, and Professional Version.
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
    inject_custom_css, display_kpi_row, display_system_health, 
    display_risk_metrics, display_performance_charts, 
    display_strategy_heatmap, display_order_history, 
    display_config_viewer, display_export_buttons, COLOR_PALETTE
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

# Inject custom styling
inject_custom_css()

# --- Data Loading Helpers ---

def _to_float(val):
    if isinstance(val, Decimal): return float(val)
    if isinstance(val, dict): return {k: _to_float(v) for k, v in val.items()}
    if isinstance(val, list): return [_to_float(i) for i in val]
    return val

@st.cache_data(ttl=60)
def load_reports():
    reports = []
    dir_path = 'risk/reports'
    if os.path.exists(dir_path):
        files = sorted([f for f in os.listdir(dir_path) if f.startswith('risk_') and f.endswith('.json')])
        for f in files:
            try:
                with open(os.path.join(dir_path, f), 'r') as file:
                    data = json.load(file)
                    portfolio = data.get('portfolio', {})
                    reports.append({
                        'date': data.get('date', f.split('_')[1].split('.')[0]),
                        'portfolio_value': float(portfolio.get('portfolio_value', 0)),
                        'cash': float(portfolio.get('cash', 0)),
                        'return_pct': float(portfolio.get('return_pct', 0)),
                    })
            except: continue
    df = pd.DataFrame(reports)
    if not df.empty:
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

# --- Sidebar ---

with st.sidebar:
    st.markdown("# 📈 QUANT FIRM")
    st.markdown("---")
    page = st.radio("MAIN NAVIGATION", [
        "🏠 Overview", 
        "📊 Portfolio", 
        "🛡️ Risk Analytics", 
        "🧠 Strategy",
        "📜 Execution",
        "⚙️ Settings",
        "🧪 Sandbox"
    ])
    st.markdown("---")
    refresh_rate = st.select_slider("REFRESH (SEC)", options=[10, 30, 60, 300], value=60)
    st_autorefresh(interval=refresh_rate * 1000, key="data_refresh")
    st.markdown("---")
    st.caption(f"v1.2.0 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# --- Global Data ---

summary = _to_float(position_tracker.get_portfolio_summary())
reports_df = load_reports()
signals_df = load_signals()
orders_df = load_orders()
latest_report = get_latest_report()

# --- Main Views ---

if page == "🏠 Overview":
    st.title("Executive Dashboard")
    display_kpi_row(summary, reports_df)
    
    st.divider()
    
    col1, col2 = st.columns([2, 1])
    with col1:
        display_performance_charts(reports_df)
    with col2:
        display_system_health(alpaca_gateway)
        with st.container(border=True):
            st.markdown('<p class="card-header">Allocation by Asset</p>', unsafe_allow_html=True)
            pos = _to_float(position_tracker.get_all_positions())
            if pos:
                df_pos = pd.DataFrame(pos)
                fig_pie = px.pie(df_pos, values='market_value', names='ticker', 
                                 hole=0.6, template='plotly_dark',
                                 color_discrete_sequence=COLOR_PALETTE)
                fig_pie.update_layout(margin=dict(l=0, r=0, t=0, b=0), showlegend=True)
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("No active holdings.")

elif page == "📊 Portfolio":
    st.title("Portfolio Holdings")
    
    with st.container(border=True):
        st.markdown('<p class="card-header">Current Positions</p>', unsafe_allow_html=True)
        pos = _to_float(position_tracker.get_all_positions())
        if pos:
            df_pos = pd.DataFrame(pos)
            st.dataframe(
                df_pos.style.background_gradient(subset=['unrealized_pnl'], cmap='RdYlGn'),
                use_container_width=True, height=400
            )
            display_export_buttons(df_pos, "positions")
        else:
            st.info("Portfolio is currently empty.")
        
    st.divider()
    with st.expander("Show Historical Snapshots"):
        if not reports_df.empty:
            st.dataframe(reports_df.sort_values('date', ascending=False), use_container_width=True)
        else:
            st.info("No snapshots found.")

elif page == "🛡️ Risk Analytics":
    st.title("Risk Management Intelligence")
    display_risk_metrics(latest_report)
    
    st.divider()
    c1, c2 = st.columns(2)
    
    with c1:
        with st.container(border=True):
            st.markdown('<p class="card-header">Sector Concentration</p>', unsafe_allow_html=True)
            sector_data = latest_report.get('sector_analysis', {}).get('breakdown', {})
            if sector_data:
                df_sector = pd.DataFrame(list(sector_data.items()), columns=['Sector', 'Weight'])
                fig = px.bar(df_sector, x='Sector', y='Weight', template='plotly_dark', color='Weight', color_continuous_scale='Viridis')
                fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sector mapping unavailable.")
            
    with c2:
        with st.container(border=True):
            st.markdown('<p class="card-header">Diversification Stats</p>', unsafe_allow_html=True)
            conc = latest_report.get('position_analysis', {}).get('concentration_risk', {})
            if conc:
                st.json(conc)
            else:
                st.info("Concentration data missing.")

elif page == "🧠 Strategy":
    st.title("Strategy Performance & Signals")
    display_strategy_heatmap(signals_df)
    
    st.divider()
    with st.container(border=True):
        st.markdown('<p class="card-header">Recent Signals Feed</p>', unsafe_allow_html=True)
        if not signals_df.empty:
            st.dataframe(signals_df, use_container_width=True)
            display_export_buttons(signals_df, "signals")
        else:
            st.info("No signals generated.")

elif page == "📜 Execution":
    st.title("Trade Execution Audit")
    display_order_history(orders_df)
    if not orders_df.empty:
        display_export_buttons(orders_df, "orders")

elif page == "⚙️ Settings":
    st.title("System Configuration")
    display_config_viewer()
    
    st.divider()
    with st.container(border=True):
        st.markdown('<p class="card-header">Maintenance Controls</p>', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("🔴 EMERGENCY CLOSE ALL", type="primary", use_container_width=True):
                st.error("Operation not implemented in this demo.")
        with col2:
            if st.button("🔄 FORCE SYNC POSITIONS", use_container_width=True):
                st.info("Syncing...")
        with col3:
            if st.button("🧹 CLEAR CACHE", use_container_width=True):
                st.cache_data.clear()
                st.success("Cache cleared!")

elif page == "🧪 Sandbox":
    st.title("Strategy Backtesting Sandbox")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        ticker = c1.text_input("SYMBOL", "AAPL")
        start_date = c2.date_input("START", value=date(2024, 1, 1))
        end_date = c3.date_input("END", value=date(2024, 12, 31))
        
        strat_list = strategy_engine.list_strategies()
        strat = st.selectbox("STRATEGY MODEL", strat_list)
        cap = st.number_input("CAPITAL ($)", value=20000)
        run = st.button("🚀 EXECUTE SIMULATION", use_container_width=True, type="primary")

    if run:
        from system.backtest_engine import BacktestEngine
        with st.status(f"Simulating {strat} on {ticker}...", expanded=True) as status:
            strategy = strategy_engine.strategies[strat]
            engine = BacktestEngine(strategy, initial_capital=cap)
            res = engine.run(ticker, str(start_date), str(end_date))
            status.update(label="Simulation Complete!", state="complete")
        
        if res:
            with st.container(border=True):
                b1, b2, b3, b4 = st.columns(4)
                b1.metric("Return", f"{res['total_return']}%")
                b2.metric("Sharpe", f"{res['sharpe_ratio']}")
                b3.metric("Max DD", f"{res['max_drawdown']}%")
                b4.metric("Trades", res['total_trades'])
                
                fig = px.line(y=res['daily_values'], title=f"Equity Growth: {strat}", template='plotly_dark')
                fig.update_layout(margin=dict(l=0, r=0, t=30, b=0), xaxis_title="Time", yaxis_title="Equity")
                st.plotly_chart(fig, use_container_width=True)
            
            with st.expander("View Transaction Log"):
                st.dataframe(pd.DataFrame(res['trades']), use_container_width=True)
        else:
            st.error("Backtest engine returned no data. Check symbol validity.")
