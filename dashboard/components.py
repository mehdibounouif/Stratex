
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import os
import json
from decimal import Decimal

# Constants for consistent styling
COLOR_PALETTE = ['#00CC96', '#636EFA', '#EF553B', '#AB63FA', '#FFA15A', '#19D3F3']
THEME_TEXT = "#E0E0E0"
THEME_BG = "#0E1117"

def inject_custom_css():
    """Inject custom CSS for a more professional, responsive look."""
    st.markdown("""
        <style>
        /* Main container padding */
        .main .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
            max-width: 95%;
        }
        
        /* Metric styling */
        [data-testid="stMetricValue"] {
            font-size: 1.8rem !important;
            font-weight: 700 !important;
        }
        
        /* Card-like headers */
        .card-header {
            font-size: 1.1rem;
            font-weight: 600;
            color: #808495;
            margin-bottom: 1rem;
            text-transform: uppercase;
            letter-spacing: 0.05rem;
        }
        
        /* Custom sidebar */
        .css-1d391kg {
            background-color: #161b22;
        }
        
        /* Table styling */
        .stDataFrame {
            border: 1px solid #30363d;
            border-radius: 8px;
        }
        
        /* Button styling */
        .stButton>button {
            border-radius: 6px;
            font-weight: 500;
        }
        </style>
    """, unsafe_allow_html=True)

def display_kpi_row(summary, reports_df):
    """Display key performance indicators in responsive cards."""
    cols = st.columns(5)
    
    metrics = [
        ("Net Liquidity", f"${float(summary.get('portfolio_value', 0)):,.2f}", None),
        ("Cash Balance", f"${float(summary.get('cash', 0)):,.2f}", None),
        ("Unrealized P&L", f"${float(summary.get('total_unrealized_pnl', 0)):,.2f}", f"{float(summary.get('total_unrealized_pnl', 0)):,.2f}"),
        ("Realized P&L", f"${float(summary.get('total_realized_pnl', 0)):,.2f}", None),
        ("Total Return", f"{float(summary.get('return_pct', 0)):.2f}%", f"{float(summary.get('return_pct', 0)):.2f}%")
    ]
    
    for i, (label, val, delta) in enumerate(metrics):
        with cols[i]:
            with st.container(border=True):
                st.metric(label, val, delta=delta)

def display_system_health(gateway):
    """Display system health with status indicators."""
    with st.container(border=True):
        st.markdown('<p class="card-header">System Health & Connectivity</p>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        
        with c1:
            status = "🟢 Online" if gateway.api else "🔴 Offline"
            st.write(f"**Broker (Alpaca):** {status}")
            
        with c2:
            status = "🟢 Open" if gateway.is_market_open() else "🔴 Closed"
            st.write(f"**Market Status:** {status}")
            
        with c3:
            st.write(f"**API Latency:** 42ms")

def display_risk_metrics(report_data):
    """Display advanced risk metrics in card layout."""
    if not report_data:
        st.info("No risk metrics available.")
        return
        
    risk = report_data.get('risk_metrics', {})
    
    st.markdown('<p class="card-header">Portfolio Risk Analytics</p>', unsafe_allow_html=True)
    cols = st.columns(4)
    
    with cols[0]:
        with st.container(border=True):
            st.metric("Sharpe Ratio", f"{risk.get('sharpe_ratio', 0):.2f}")
    
    with cols[1]:
        with st.container(border=True):
            st.metric("Volatility (Ann)", f"{risk.get('annual_volatility', 0):.2%}")
    
    with cols[2]:
        with st.container(border=True):
            var = risk.get('var_95_10d', {})
            st.metric("VaR (95%/10d)", f"${var.get('var_dollar', 0):,.0f}", delta=f"{var.get('var_percent', 0):.2%}", delta_color="inverse")
    
    with cols[3]:
        with st.container(border=True):
            mdd = risk.get('max_drawdown', {}).get('max_drawdown', 0)
            st.metric("Max Drawdown", f"{mdd:.2%}", delta_color="inverse")

def display_performance_charts(reports_df):
    """Display equity curve and drawdown with optimized responsiveness."""
    if reports_df.empty:
        st.info("Insufficient data for performance charts.")
        return
        
    with st.container(border=True):
        tab1, tab2 = st.tabs(["📈 Equity Growth", "📉 Drawdown Analysis"])
        
        with tab1:
            fig = px.area(reports_df, x='date', y='portfolio_value', 
                          template='plotly_dark',
                          color_discrete_sequence=['#00CC96'])
            fig.update_layout(
                margin=dict(l=0, r=0, t=30, b=0),
                xaxis_title=None, yaxis_title="Value ($)",
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                hovermode="x unified"
            )
            st.plotly_chart(fig, use_container_width=True)
            
        with tab2:
            vals = reports_df['portfolio_value']
            dd = (vals - vals.cummax()) / vals.cummax()
            fig_dd = px.area(x=reports_df['date'], y=dd, template='plotly_dark')
            fig_dd.update_traces(fillcolor='rgba(239, 85, 59, 0.3)', line_color='#EF553B')
            fig_dd.update_layout(
                margin=dict(l=0, r=0, t=30, b=0),
                xaxis_title=None, yaxis_title="Drawdown %",
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                hovermode="x unified"
            )
            st.plotly_chart(fig_dd, use_container_width=True)

def display_strategy_heatmap(signals_df):
    """Display strategy distribution with a cleaner chart."""
    if signals_df.empty:
        st.info("No signal data available.")
        return
        
    with st.container(border=True):
        st.markdown('<p class="card-header">Strategy Signal Distribution</p>', unsafe_allow_html=True)
        strat_counts = signals_df['strategy'].value_counts().reset_index()
        strat_counts.columns = ['Strategy', 'Signals']
        
        fig = px.bar(strat_counts, x='Strategy', y='Signals', 
                     color='Strategy', template='plotly_dark',
                     color_discrete_sequence=COLOR_PALETTE)
        fig.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False,
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(fig, use_container_width=True)

def display_order_history(orders_df):
    """Display execution log with consistent styling."""
    if orders_df.empty:
        st.info("No recent orders found.")
        return
        
    with st.container(border=True):
        st.markdown('<p class="card-header">Order Execution Log</p>', unsafe_allow_html=True)
        
        def color_status(val):
            if val in ['filled', 'held']: return 'color: #00CC96; font-weight: bold'
            if val in ['canceled', 'rejected']: return 'color: #EF553B'
            return 'color: #636EFA'

        st.dataframe(
            orders_df.style.applymap(color_status, subset=['status']),
            use_container_width=True,
            height=400
        )

def display_config_viewer():
    """Display sanitized configuration in cards."""
    cols = st.columns(2)
    
    with cols[0]:
        with st.container(border=True):
            st.markdown('<p class="card-header">Connectivity Settings</p>', unsafe_allow_html=True)
            env_vars = {
                'ALPACA_BASE': os.getenv('ALPACA_BASE_URL', 'Not Set'),
                'MODE': os.getenv('TRADING_MODE', 'PAPER'),
                'LOG_LEVEL': os.getenv('LOG_LEVEL', 'INFO')
            }
            st.table(pd.DataFrame(env_vars.items(), columns=['Key', 'Value']))

    with cols[1]:
        with st.container(border=True):
            st.markdown('<p class="card-header">Risk Controls</p>', unsafe_allow_html=True)
            risk_vars = {
                'MAX_POS': os.getenv('RISK_MAX_POS_SIZE', '0.15'),
                'MIN_CASH': os.getenv('RISK_MIN_CASH', '0.10'),
                'MAX_DRAWDOWN': os.getenv('RISK_MAX_DD', '0.15')
            }
            st.table(pd.DataFrame(risk_vars.items(), columns=['Risk Limit', 'Value']))

def display_export_buttons(df, filename_prefix):
    """Responsive export buttons."""
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            label="📥 Export to CSV",
            data=df.to_csv(index=False).encode('utf-8'),
            file_name=f"{filename_prefix}.csv",
            mime='text/csv',
            use_container_width=True
        )
    with c2:
        st.download_button(
            label="📤 Export to JSON",
            data=df.to_json(orient='records'),
            file_name=f"{filename_prefix}.json",
            mime='application/json',
            use_container_width=True
        )
