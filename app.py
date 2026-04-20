import streamlit as st
import pandas as pd
import sys
import os
from datetime import datetime

from run_ic_screener import main as run_screener

# Set page config
st.set_page_config(
    page_title="Iron Condor Finder",
    page_icon="📈",
    layout="wide"
)

# Header
st.title("Iron Condor Finder")

# Sidebar
st.sidebar.header("Screener Inputs")

symbols = st.sidebar.text_input(
    "Tickers (comma-separated)", 
    value="TSLA,AMZN,GOOGL,AAPL,MSFT,WMT",
    help="Enter symbols separated by commas."
)

distances = st.sidebar.text_input(
    "Distances (% or fraction)", 
    value="3,5,8,10,15,20",
    help="Target distances for strikes."
)

wing_widths = st.sidebar.text_input(
    "Wing Widths ($)", 
    value="2.5, 5.0, 10.0",
    help="Comma-separated wing widths to scan simultaneously."
)

st.sidebar.markdown("---")
st.sidebar.subheader("Expiration Settings")

dte_range = st.sidebar.slider(
    "Days to Expiry (DTE) Range",
    min_value=0,
    max_value=120,
    value=(15, 45),
    step=1,
    help="Filter for options expiring within this many days."
)

monthly_only = st.sidebar.toggle(
    "Major Monthly Expiries Only",
    value=True,
    help="Only scan the 3rd Friday standard monthly expirations."
)

st.sidebar.markdown("---")

# Define output CSV in the same directory as this script
output_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ic_opportunities.csv")

# Main Execution Button on the Sidebar
if st.sidebar.button("🚀 Execute Screener", use_container_width=True):
    with st.spinner("Fetching data from API... Please wait."):
        # Build arguments for the screener
        screener_args = [
            "--symbols", symbols,
            "--distances", distances,
            "--wing-widths", wing_widths,
            "--min-dte", str(dte_range[0]),
            "--max-dte", str(dte_range[1]),
            "--output", output_csv
        ]
        
        if monthly_only:
            screener_args.append("--monthly-only")
            
        try:
            # Run the main function from run_ic_screener with our arguments
            exit_code = run_screener(screener_args)
            
            if exit_code == 0:
                st.sidebar.success("Screener execution completed!")
            else:
                st.sidebar.error(f"Screener finished with a non-zero exit code: {exit_code}")
                
        except Exception as e:
            st.sidebar.error(f"An error occurred during execution: {e}")

# Display Results
st.markdown("### Results")

if os.path.exists(output_csv) and os.path.getsize(output_csv) > 0:
    try:
        df = pd.read_csv(output_csv)
        if df.empty:
            st.warning("The screener ran successfully, but no opportunities were found matching your criteria.")
        else:
            # Display Last Updated timestamp
            last_modified_time = os.path.getmtime(output_csv)
            last_updated = datetime.fromtimestamp(last_modified_time).strftime('%Y-%m-%d %H:%M:%S')
            st.caption(f"Last Updated: {last_updated}")

            # --- Filters Section ---
            st.markdown("#### Filters")
            
            filtered_df = df.copy()

            # Organize layout: Left half for dropdowns, right half for sliders.
            # The third empty column ([2, 2, 1] ratio) acts as a spacer to limit the maximum width.
            filter_left, filter_right, _ = st.columns([2, 2, 1])

            with filter_left:
                if 'Stock' in filtered_df.columns:
                    stock_options = sorted(filtered_df['Stock'].dropna().unique().tolist())
                    selected_stocks = st.multiselect("Select Stock(s)", options=stock_options, default=stock_options)
                    filtered_df = filtered_df[filtered_df['Stock'].isin(selected_stocks)]
            
                if not filtered_df.empty and 'DTE' in filtered_df.columns:
                    dte_options = sorted(filtered_df['DTE'].dropna().unique().tolist())
                    selected_dtes = st.multiselect("Select DTE(s)", options=dte_options, default=dte_options)
                    filtered_df = filtered_df[filtered_df['DTE'].isin(selected_dtes)]
                else:
                    st.multiselect("Select DTE(s)", options=[], default=[], disabled=True)

            with filter_right:
                if not filtered_df.empty and '% Distance' in filtered_df.columns:
                    min_dist = float(filtered_df['% Distance'].min())
                    max_dist = float(filtered_df['% Distance'].max())
                    if min_dist >= max_dist:
                        dist_range = st.slider("% Distance Range", min_value=0.0, max_value=max_dist + 10.0, value=(min_dist, max_dist))
                    else:
                        dist_range = st.slider("% Distance Range", min_value=min_dist, max_value=max_dist, value=(min_dist, max_dist))
                    filtered_df = filtered_df[(filtered_df['% Distance'] >= dist_range[0]) & (filtered_df['% Distance'] <= dist_range[1])]
                else:
                    st.slider("% Distance Range", min_value=0.0, max_value=100.0, value=(0.0, 100.0), disabled=True)
                
                if not filtered_df.empty and 'Premium/Wing Ratio' in filtered_df.columns:
                    valid_ratios = filtered_df['Premium/Wing Ratio'].dropna()
                    if not valid_ratios.empty:
                        min_pw = float(valid_ratios.min())
                        max_pw = float(valid_ratios.max())
                        if min_pw >= max_pw:
                            pw_range = st.slider("Premium/Wing Ratio", min_value=0.0, max_value=max_pw + 0.1, value=(min_pw, max_pw))
                        else:
                            pw_range = st.slider("Premium/Wing Ratio", min_value=min_pw, max_value=max_pw, value=(min_pw, max_pw))
                        filtered_df = filtered_df[(filtered_df['Premium/Wing Ratio'] >= pw_range[0]) & (filtered_df['Premium/Wing Ratio'] <= pw_range[1])]
                    else:
                        st.slider("Premium/Wing Ratio", min_value=0.0, max_value=1.0, value=(0.0, 1.0), disabled=True)
                else:
                    st.slider("Premium/Wing Ratio", min_value=0.0, max_value=1.0, value=(0.0, 1.0), disabled=True)

            # --- Columns Display Toggle ---
            st.markdown("#### Display Options")
            show_prices = st.toggle("Show Prices (LP Mid, SP Mid, LC Mid, SC Mid)", value=False)
            
            columns_to_hide = ["LP Mid", "SP Mid", "LC Mid", "SC Mid"]
            if not show_prices:
                filtered_df = filtered_df.drop(columns=[col for col in columns_to_hide if col in filtered_df.columns])

            # Display as a dataframe
            st.dataframe(filtered_df, use_container_width=True)
            
            if filtered_df.empty:
                st.info("No matching results with the current filters.")
                
    except Exception as e:
        st.error(f"Error reading results file: {e}")
else:
    st.info("No results to display yet. Click 'Execute Screener' to generate data.")
