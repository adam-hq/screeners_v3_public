import streamlit as st
import pandas as pd
import sys
import os
from datetime import datetime

from run_ic_screener import main as run_ic_screener
from run_csp_screener import main as run_csp_screener

# Set page config
st.set_page_config(
    page_title="Options Screener",
    page_icon="📈",
    layout="wide"
)

# Header
st.title("Options Screener")

tab_ic, tab_csp = st.tabs(["Iron Condor Screener", "Cash Secured Put Screener"])

# Define output CSV in the same directory as this script
output_ic_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ic_opportunities.csv")
output_csp_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), "csp_opportunities.csv")

with tab_ic:
    st.header("Iron Condor Screener")
    
    with st.expander("Screener Inputs", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            ic_symbols = st.text_input(
                "Tickers (comma-separated)", 
                value="TSLA,AMZN,GOOGL,AAPL,MSFT,WMT",
                help="Enter symbols separated by commas.",
                key="ic_symbols_input"
            )
            ic_distances = st.text_input(
                "Distances (% or fraction)", 
                value="3,5,8,10,15,20",
                help="Target distances for strikes.",
                key="ic_distances_input"
            )
        with col2:
            ic_wing_widths = st.text_input(
                "Wing Widths ($)", 
                value="2.5, 5.0, 10.0",
                help="Comma-separated wing widths to scan simultaneously.",
                key="ic_wing_widths_input"
            )
            ic_dte_range = st.slider(
                "Days to Expiry (DTE) Range",
                min_value=0,
                max_value=120,
                value=(15, 45),
                step=1,
                help="Filter for options expiring within this many days.",
                key="ic_dte_range_input"
            )
        with col3:
            st.markdown("<br><br>", unsafe_allow_html=True)
            ic_monthly_only = st.toggle(
                "Major Monthly Expiries Only",
                value=False,
                help="Only scan the 3rd Friday standard monthly expirations.",
                key="ic_monthly_only_input"
            )

        if st.button("🚀 Execute IC Screener", use_container_width=True, key="ic_execute_btn"):
            with st.spinner("Fetching data from API and executing IC screener... Please wait."):
                ic_args = [
                    "--symbols", ic_symbols,
                    "--distances", ic_distances,
                    "--wing-widths", ic_wing_widths,
                    "--min-dte", str(ic_dte_range[0]),
                    "--max-dte", str(ic_dte_range[1]),
                    "--output", output_ic_csv
                ]
                if ic_monthly_only:
                    ic_args.append("--monthly-only")
                    
                try:
                    exit_code_ic = run_ic_screener(ic_args)
                    if exit_code_ic == 0:
                        st.success("IC Screener execution completed!")
                    else:
                        st.error(f"IC Screener finished with a non-zero exit code: {exit_code_ic}")
                except Exception as e:
                    st.error(f"An error occurred during execution: {e}")

    # Display Results
    st.markdown("### Results")
    if os.path.exists(output_ic_csv) and os.path.getsize(output_ic_csv) > 0:
        try:
            df = pd.read_csv(output_ic_csv)
            if df.empty:
                st.warning("The screener ran successfully, but no opportunities were found matching your criteria.")
            else:
                last_modified_time = os.path.getmtime(output_ic_csv)
                last_updated = datetime.fromtimestamp(last_modified_time).strftime('%Y-%m-%d %H:%M:%S')
                st.caption(f"Last Updated: {last_updated}")

                st.markdown("#### Filters")
                filtered_df = df.copy()
                filter_left, filter_right, _ = st.columns([2, 2, 1])

                with filter_left:
                    if 'Stock' in filtered_df.columns:
                        stock_options = sorted(filtered_df['Stock'].dropna().unique().tolist())
                        selected_stocks = st.multiselect("Select Stock(s)", options=stock_options, default=stock_options, key="ic_stocks")
                        filtered_df = filtered_df[filtered_df['Stock'].isin(selected_stocks)]
                
                    if not filtered_df.empty and 'DTE' in filtered_df.columns:
                        dte_options = sorted(filtered_df['DTE'].dropna().unique().tolist())
                        selected_dtes = st.multiselect("Select DTE(s)", options=dte_options, default=dte_options, key="ic_dtes")
                        filtered_df = filtered_df[filtered_df['DTE'].isin(selected_dtes)]

                with filter_right:
                    if not filtered_df.empty and '% Distance' in filtered_df.columns:
                        min_dist = float(filtered_df['% Distance'].min())
                        max_dist = float(filtered_df['% Distance'].max())
                        if min_dist >= max_dist:
                            dist_range = st.slider("% Distance Range", min_value=0.0, max_value=max_dist + 10.0, value=(min_dist, max_dist), key="ic_dist")
                        else:
                            dist_range = st.slider("% Distance Range", min_value=min_dist, max_value=max_dist, value=(min_dist, max_dist), key="ic_dist")
                        filtered_df = filtered_df[(filtered_df['% Distance'] >= dist_range[0]) & (filtered_df['% Distance'] <= dist_range[1])]
                    
                    if not filtered_df.empty and 'Premium/Wing Ratio' in filtered_df.columns:
                        valid_ratios = filtered_df['Premium/Wing Ratio'].dropna()
                        if not valid_ratios.empty:
                            min_pw = float(valid_ratios.min())
                            max_pw = float(valid_ratios.max())
                            if min_pw >= max_pw:
                                pw_range = st.slider("Premium/Wing Ratio", min_value=0.0, max_value=max_pw + 0.1, value=(min_pw, max_pw), key="ic_pw")
                            else:
                                pw_range = st.slider("Premium/Wing Ratio", min_value=min_pw, max_value=max_pw, value=(min_pw, max_pw), key="ic_pw")
                            filtered_df = filtered_df[(filtered_df['Premium/Wing Ratio'] >= pw_range[0]) & (filtered_df['Premium/Wing Ratio'] <= pw_range[1])]

                st.markdown("#### Display Options")
                show_more_information = st.toggle("Show more information", value=False, key="ic_more_info")
                columns_to_hide = ["LP Mid", "SP Mid", "LC Mid", "SC Mid", "ATR", "Support", "Resistance"]
                if not show_more_information:
                    filtered_df = filtered_df.drop(columns=[col for col in columns_to_hide if col in filtered_df.columns])

                st.dataframe(filtered_df, use_container_width=True)
                if filtered_df.empty:
                    st.info("No matching results with the current filters.")
        except Exception as e:
            st.error(f"Error reading results file: {e}")
    else:
        st.info("No IC results to display yet. Click 'Execute IC Screener' to generate data.")

with tab_csp:
    st.header("Cash Secured Put Screener")
    
    with st.expander("Screener Inputs", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            csp_symbols = st.text_input(
                "Tickers (comma-separated)", 
                value="TSLA,AMZN,GOOGL,AAPL,MSFT,WMT",
                help="Enter symbols separated by commas.",
                key="csp_symbols_input"
            )
            csp_distances = st.text_input(
                "Distances (% or fraction)", 
                value="3,5,8,10,15,20",
                help="Target distances for strikes.",
                key="csp_distances_input"
            )
        with col2:
            csp_dte_range = st.slider(
                "Days to Expiry (DTE) Range",
                min_value=0,
                max_value=120,
                value=(15, 45),
                step=1,
                help="Filter for options expiring within this many days.",
                key="csp_dte_range_input"
            )
        with col3:
            st.markdown("<br><br>", unsafe_allow_html=True)
            csp_monthly_only = st.toggle(
                "Major Monthly Expiries Only",
                value=False,
                help="Only scan the 3rd Friday standard monthly expirations.",
                key="csp_monthly_only_input"
            )

        if st.button("🚀 Execute CSP Screener", use_container_width=True, key="csp_execute_btn"):
            with st.spinner("Fetching data from API and executing CSP screener... Please wait."):
                csp_args = [
                    "--symbols", csp_symbols,
                    "--distances", csp_distances,
                    "--min-dte", str(csp_dte_range[0]),
                    "--max-dte", str(csp_dte_range[1]),
                    "--output", output_csp_csv
                ]
                if csp_monthly_only:
                    csp_args.append("--monthly-only")
                    
                try:
                    exit_code_csp = run_csp_screener(csp_args)
                    if exit_code_csp == 0:
                        st.success("CSP Screener execution completed!")
                    else:
                        st.error(f"CSP Screener finished with a non-zero exit code: {exit_code_csp}")
                except Exception as e:
                    st.error(f"An error occurred during execution: {e}")

    # Display Results
    st.markdown("### Results")
    if os.path.exists(output_csp_csv) and os.path.getsize(output_csp_csv) > 0:
        try:
            df_csp = pd.read_csv(output_csp_csv)
            if df_csp.empty:
                st.warning("The screener ran successfully, but no opportunities were found matching your criteria.")
            else:
                last_modified_time = os.path.getmtime(output_csp_csv)
                last_updated = datetime.fromtimestamp(last_modified_time).strftime('%Y-%m-%d %H:%M:%S')
                st.caption(f"Last Updated: {last_updated}")

                st.markdown("#### Filters")
                filtered_csp_df = df_csp.copy()
                filter_left, filter_right = st.columns(2)

                with filter_left:
                    if 'Stock' in filtered_csp_df.columns:
                        stock_options = sorted(filtered_csp_df['Stock'].dropna().unique().tolist())
                        selected_stocks = st.multiselect("Select Stock(s)", options=stock_options, default=stock_options, key="csp_stocks")
                        filtered_csp_df = filtered_csp_df[filtered_csp_df['Stock'].isin(selected_stocks)]
                
                    if not filtered_csp_df.empty and 'DTE' in filtered_csp_df.columns:
                        dte_options = sorted(filtered_csp_df['DTE'].dropna().unique().tolist())
                        selected_dtes = st.multiselect("Select DTE(s)", options=dte_options, default=dte_options, key="csp_dtes")
                        filtered_csp_df = filtered_csp_df[filtered_csp_df['DTE'].isin(selected_dtes)]

                    if not filtered_csp_df.empty and 'Delta' in filtered_csp_df.columns:
                        valid_deltas = filtered_csp_df['Delta'].dropna()
                        if not valid_deltas.empty:
                            min_delta = float(valid_deltas.min())
                            max_delta = float(valid_deltas.max())
                            if min_delta < max_delta:
                                delta_range = st.slider("Safety Level (Delta) Range", min_value=min_delta, max_value=max_delta, value=(min_delta, max_delta), key="csp_delta")
                                filtered_csp_df = filtered_csp_df[(filtered_csp_df['Delta'] >= delta_range[0]) & (filtered_csp_df['Delta'] <= delta_range[1])]

                with filter_right:
                    if not filtered_csp_df.empty and '% Distance' in filtered_csp_df.columns:
                        valid_dists = filtered_csp_df['% Distance'].dropna()
                        if not valid_dists.empty:
                            min_dist = float(valid_dists.min())
                            max_dist = float(valid_dists.max())
                            if min_dist < max_dist:
                                dist_range = st.slider("% Distance Range", min_value=min_dist, max_value=max_dist, value=(min_dist, max_dist), key="csp_dist")
                                filtered_csp_df = filtered_csp_df[(filtered_csp_df['% Distance'] >= dist_range[0]) & (filtered_csp_df['% Distance'] <= dist_range[1])]
                    
                    if not filtered_csp_df.empty and 'RSI 14' in filtered_csp_df.columns:
                        valid_rsis = filtered_csp_df['RSI 14'].dropna()
                        if not valid_rsis.empty:
                            min_rsi = float(valid_rsis.min())
                            max_rsi = float(valid_rsis.max())
                            if min_rsi < max_rsi:
                                rsi_range = st.slider("RSI 14 Range", min_value=min_rsi, max_value=max_rsi, value=(min_rsi, max_rsi), key="csp_rsi")
                                filtered_csp_df = filtered_csp_df[(filtered_csp_df['RSI 14'] >= rsi_range[0]) & (filtered_csp_df['RSI 14'] <= rsi_range[1])]

                st.markdown("#### Display Options")
                show_more_information = st.toggle("Show more information", value=False, key="csp_more_info")
                columns_to_hide = ["Lower BB", "SMA 200", "Stock Price"]
                if not show_more_information:
                    filtered_csp_df = filtered_csp_df.drop(columns=[col for col in columns_to_hide if col in filtered_csp_df.columns])

                st.dataframe(filtered_csp_df, use_container_width=True)
                if filtered_csp_df.empty:
                    st.info("No matching results with the current filters.")
        except Exception as e:
            st.error(f"Error reading results file: {e}")
    else:
        st.info("No CSP results to display yet. Click 'Execute CSP Screener' to generate data.")
