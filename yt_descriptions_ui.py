import streamlit as st
import subprocess
import sys
import os
import tempfile
import pandas as pd

# Path to the scripts
DISCOVER_SCRIPT = os.path.join(os.path.dirname(__file__), 'youtube_api_discovery', 'discover_channels_api.py')
EXTRACT_SCRIPT = os.path.join(os.path.dirname(__file__), 'channels_to_description.py')

st.title("YouTube Tools")

st.markdown("Discover channels and extract descriptions.")

tab1, tab2 = st.tabs(["Discover Channels", "Extract Descriptions"])

with tab1:
    st.header("Discover YouTube Channels")
    
    query = st.text_input("Search Query", value="", help="Leave blank to use default game-related queries")
    max_channels = st.slider("Max Channels", min_value=1, max_value=1000, value=100)
    include_recent_date = st.checkbox("Include recent video date (~100 units/channel)", value=False)
    include_avg_views = st.checkbox("Include avg views last month (~200-500 units/channel)", value=False)
    existing_csv = st.file_uploader("Existing Channels CSV (optional, to skip duplicates)", type=['csv'])
    output_path = st.text_input("Output CSV Path", value="outputs/yt_discover.csv")
    
    # Estimate costs
    num_queries = 11 if not query else 1  # Default queries count
    search_requests_per_query = (max_channels + 49) // 50  # Ceil division for requests needed
    base_cost = search_requests_per_query * 100 * num_queries  # Search costs
    channel_cost = max_channels * 1  # Channels list
    extra_cost = 0
    if include_recent_date:
        extra_cost += max_channels * 100  # 1 search request per channel
    if include_avg_views:
        extra_cost += max_channels * 300  # Estimate for multiple requests
    total_cost = base_cost + channel_cost + extra_cost
    
    st.write(f"Estimated API cost: {total_cost} units (Free tier: 10,000/day)")
    
    if st.button("Discover Channels"):
        with st.spinner("Discovering..."):
            cmd = [sys.executable, DISCOVER_SCRIPT, '--max-channels', str(max_channels), '--output', output_path]
            if query:
                cmd.extend(['--query', query])
            if include_recent_date:
                cmd.append('--include-recent-date')
            if include_avg_views:
                cmd.append('--include-avg-views')
            if existing_csv:
                # Save uploaded file to temp
                with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as tmp_existing:
                    tmp_existing.write(existing_csv.getvalue())
                    existing_path = tmp_existing.name
                cmd.extend(['--existing-csv', existing_path])
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(__file__))
            
            if result.returncode == 0:
                st.success("Discovery completed!")
                st.text("Output: " + output_path)
                try:
                    df = pd.read_csv(output_path)
                    st.dataframe(df.head())
                except Exception:
                    st.error("Failed to load output CSV")
            else:
                st.error("Error during discovery:")
                st.text(result.stderr)
                st.text(result.stdout)

with tab2:
    st.header("Extract Channel Descriptions")
    
    st.markdown("Upload a CSV with columns: video_url, video_title, channel_url, channel_name.")
    
    uploaded_file = st.file_uploader("Upload input CSV", type=['csv'])
    
    if uploaded_file is not None:
        # Display preview
        df = pd.read_csv(uploaded_file)
        st.write("Preview of uploaded CSV:")
        st.dataframe(df.head())
        
        if st.button("Extract Descriptions"):
            with st.spinner("Processing... This may take a while."):
                # Save uploaded file to temp
                with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as tmp_in:
                    tmp_in.write(uploaded_file.getvalue())
                    input_path = tmp_in.name
                
                # Output path
                output_path = os.path.join('outputs', 'channels_with_descriptions.csv')
                
                # Run the script
                cmd = [sys.executable, EXTRACT_SCRIPT, '--input', input_path, '--output', output_path]
                result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(__file__))
                
                if result.returncode == 0:
                    st.success("Extraction completed!")
                    # Load and display output
                    output_df = pd.read_csv(output_path)
                    st.write("Output CSV preview:")
                    st.dataframe(output_df.head())
                    
                    # Download button
                    with open(output_path, 'rb') as f:
                        st.download_button(
                            label="Download Output CSV",
                            data=f,
                            file_name="channels_with_descriptions.csv",
                            mime="text/csv"
                        )
                else:
                    st.error("Error during extraction:")
                    st.text(result.stderr)
                    st.text(result.stdout)