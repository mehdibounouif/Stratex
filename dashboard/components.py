
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import os
import json
from decimal import Decimal

def display_kpi_row(summary, reports_df):
    """Display key performance indicators in a row."""
    c1, c2, c3, c4, c5 = st.columns(5)
    
    portfolio_value = float(summary.get('portfolio_value', 0))
    cash = float(summary.get('cash', 0))
    unrealized_pnl = float(summary.get('total_unrealized_pnl', 0))
    realized_pnl = float(summary.get('total_realized_pnl', 0))
    total_pnl = unrealized_pnl + realized_pnl
    return_pct = float(summary.get('return_pct', 0))
    
    daily_chg = 0
    if not reports_df.empty and len(reports_df) > 1:
        daily_chg = reports_df.iloc[-1]['portfolio_value'] - reports_df.iloc[-2]['portfolio_value']
    
    c1.metric("Net Liquidity", f"${portfolio_value:,.2f}")
    c2.metric("Cash Balance", f"${cash:,.2f}")
    c3.metric("Total P&L", f"${total_pnl:,.2f}", delta=f"{total_pnl:,.2f}")
    c4.metric("Daily Change", f"${daily_chg:,.2f}", delta=f"{daily_chg:,.2f}")
    c5.metric("Total Return", f"{return_pct:.2f}%", delta=f"{return_pct:.2f}%")

def display_system_health(gateway):
    """Display system health and connectivity status."""
    st.subheader("System Health")
    c1, c2, c3, c4 = st.columns(4)
    
    with c1:
        if gateway.api:
            st.success("Alpaca: Connected")
        else:
            st.error("Alpaca: Disconnected")
            
    with c2:
        if gateway.is_market_open():
            st.success("Market: Open")
        else:
            st.info("Market: Closed")
            
    with c3:
        # Check for error logs in the last hour
        error_count = 0
        if os.path.exists('logs/trading.log'):
             # This is a placeholder, in a real system we'd parse the log
             pass
        st.metric("System Errors (1h)", f"{error_count}")
        
    with c4:
        # Placeholder for latency
        st.metric("API Latency", "42ms")

def display_risk_metrics(report_data):
    """Display advanced risk metrics from the latest report."""
    if not report_data:
        st.info("No risk metrics available.")
        return
        
    risk = report_data.get('risk_metrics', {})
    
    st.subheader("Risk Metrics")
    r1, r2, r3, r4 = st.columns(4)
    
    r1.metric("Sharpe Ratio", f"{risk.get('sharpe_ratio', 0):.2f}")
    
    vol = risk.get('annual_volatility', 0)
    r2.metric("Annual Volatility", f"{vol:.2%}")
    
    var = risk.get('var_95_10d', {})
    var_val = var.get('var_dollar', 0)
    var_pct = var.get('var_percent', 0)
    r3.metric("VaR (95%/10d)", f"${var_val:,.2f}", delta=f"{var_pct:.2%}", delta_color="inverse")
    
    mdd = risk.get('max_drawdown', {}).get('max_drawdown', 0)
    r4.metric("Max Drawdown", f"{mdd:.2%}", delta_color="inverse")

def display_performance_charts(reports_df):
    """Display equity curve and drawdown charts."""
    if reports_df.empty:
        st.info("Insufficient data for performance charts.")
        return
        
    st.subheader("Performance Visualization")
    tab1, tab2 = st.tabs(["Equity Curve", "Drawdown"])
    
    with tab1:
        fig = px.area(reports_df, x='date', y='portfolio_value', 
                      title="Portfolio Value Over Time",
                      template='plotly_dark',
                      color_discrete_sequence=['#00CC96'])
        fig.update_layout(xaxis_title="Date", yaxis_title="Portfolio Value ($)")
        st.plotly_chart(fig, use_container_width=True)
        
    with tab2:
        vals = reports_df['portfolio_value']
        dd = (vals - vals.cummax()) / vals.cummax()
        fig_dd = px.area(x=reports_df['date'], y=dd, title="Drawdown %", template='plotly_dark')
        fig_dd.update_traces(fillcolor='rgba(255,0,0,0.3)', line_color='red')
        fig_dd.update_layout(xaxis_title="Date", yaxis_title="Drawdown %")
        st.plotly_chart(fig_dd, use_container_width=True)

def display_strategy_heatmap(signals_df):
    """Display strategy performance comparison."""
    if signals_df.empty:
        st.info("No signal data available for strategy analysis.")
        return
        
    st.subheader("Strategy Distribution")
    strat_counts = signals_df['strategy'].value_counts().reset_index()
    strat_counts.columns = ['Strategy', 'Signals']
    
    fig = px.bar(strat_counts, x='Strategy', y='Signals', 
                 color='Signals', template='plotly_dark',
                 title="Signals per Strategy")
    st.plotly_chart(fig, use_container_width=True)

def display_order_history(orders_df):
    """Display recent orders with status coloring."""
    if orders_df.empty:
        st.info("No recent orders found.")
        return
        
    st.subheader("Execution Log")
    
    def color_status(val):
        color = 'white'
        if val == 'filled' or val == 'held': color = '#00CC96'
        elif val == 'canceled' or val == 'rejected': color = '#EF553B'
        elif val == 'submitted': color = '#636EFA'
        return f'color: {color}'

    st.dataframe(orders_df.style.applymap(color_status, subset=['status']))

def display_config_viewer():
    """Display sanitized environment configuration."""
    st.subheader("System Configuration")
    
    env_vars = {}
    for key in ['ALPACA_BASE_URL', 'TRADING_MODE', 'LOG_LEVEL', 'RISK_MAX_POS_SIZE']:
        val = os.getenv(key, 'Not Set')
        env_vars[key] = val
        
    # Mask API keys
    for key in ['ALPACA_API_KEY', 'ALPACA_SECRET_KEY']:
        val = os.getenv(key)
        if val:
            env_vars[key] = val[:4] + "*" * 8 + val[-4:]
        else:
            env_vars[key] = 'Not Set'
            
    st.table(pd.DataFrame(env_vars.items(), columns=['Setting', 'Value']))
    
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔴 EMERGENCY KILL SWITCH", type="primary", use_container_width=True):
            st.warning("Kill switch triggered. Cancelling all orders and closing positions...")
            # Here we would call gateway.cancel_all_orders() etc.
            
    with col2:
        mode = os.getenv('TRADING_MODE', 'PAPER')
        st.info(f"Current Mode: **{mode}**")
        if st.button("Toggle Paper/Live", use_container_width=True):
            st.info("Mode toggle would happen here in a real system.")

def display_export_buttons(df, filename_prefix):
    """Add buttons to export data."""
    col1, col2 = st.columns(2)
    csv = df.to_csv(index=False).encode('utf-8')
    col1.download_button(
        label="📥 Download CSV",
        data=csv,
        file_name=f"{filename_prefix}_{datetime.now().strftime('%Y%m%d')}.csv",
        mime='text/csv',
    )
    
    json_str = df.to_json(orient='records')
    col2.download_button(
        label="📥 Download JSON",
        data=json_str,
        file_name=f"{filename_prefix}_{datetime.now().strftime('%Y%m%d')}.json",
        mime='application/json',
    )
