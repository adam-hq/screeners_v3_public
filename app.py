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

wing_width = st.sidebar.number_input(
    "Wing Width ($)", 
    value=5.0,
    min_value=0.5,
    step=0.5,
    help="Width of the iron condor wings in dollars."
)

expiry = st.sidebar.text_input(
    "Expiry Date (Optional)", 
    value="",
    help="YYYY-MM-DD format. Leave empty for nearest monthly expiration."
)

# Define output CSV in the same directory as this script
output_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ic_opportunities.csv")

# Main Execution Button on the Sidebar
if st.sidebar.button("🚀 Execute Screener", use_container_width=True):
    with st.spinner("Fetching data from API... Please wait."):
        # Build arguments for the screener
        screener_args = [
            "--symbols", symbols,
            "--distances", distances,
            "--wing-width", str(wing_width),
            "--output", output_csv
        ]
        
        if expiry.strip():
            screener_args.extend(["--expiry", expiry.strip()])
            
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
            col1, col2, col3 = st.columns(3)
            
            with col1:
                stock_options = sorted(df['Stock'].dropna().unique().tolist())
                selected_stocks = st.multiselect("Select Stock(s)", options=stock_options, default=stock_options)
            
            with col2:
                # Handle % Distance Range
                min_dist = float(df['% Distance'].min())
                max_dist = float(df['% Distance'].max())
                # Fallback if min and max are the same
                if min_dist == max_dist:
                    dist_range = st.slider("% Distance Range", min_value=0.0, max_value=max_dist + 10.0, value=(min_dist, max_dist))
                else:
                    dist_range = st.slider("% Distance Range", min_value=min_dist, max_value=max_dist, value=(min_dist, max_dist))
            
            with col3:
                # Handle Risk Reward Ratio
                if 'R/R Ratio' in df.columns:
                    min_rr = float(df['R/R Ratio'].min())
                    max_rr = float(df['R/R Ratio'].max())
                    if min_rr == max_rr:
                        rr_range = st.slider("R/R Ratio Range", min_value=0.0, max_value=max_rr + 0.5, value=(min_rr, max_rr))
                    else:
                        rr_range = st.slider("R/R Ratio Range", min_value=min_rr, max_value=max_rr, value=(min_rr, max_rr))
                else:
                    rr_range = None

            # --- Apply Filters ---
            filtered_df = df[df['Stock'].isin(selected_stocks)]
            filtered_df = filtered_df[(filtered_df['% Distance'] >= dist_range[0]) & (filtered_df['% Distance'] <= dist_range[1])]
            
            if rr_range is not None:
                filtered_df = filtered_df[(filtered_df['R/R Ratio'] >= rr_range[0]) & (filtered_df['R/R Ratio'] <= rr_range[1])]

            # --- Columns Display Toggle ---
            st.markdown("#### Display Options")
            show_prices = st.toggle("Show Prices (LP Mid, SP Mid, LC Mid, SC Mid)", value=True)
            
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
